# Copyright 2026 Prash Balan (@its-me-prash) — GNU AGPL v3.0-or-later
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The h2 response shim must accept the calls the connector actually makes.

**The b3 regression this exists to prevent.** The first version of
``_H2Response.json()`` took no arguments, while the connector calls it the
aiohttp way — ``resp.json(content_type=None)``. That raised a ``TypeError``
inside ``_get_json``, which the enrichment paths swallow as "skipped
(TypeError)": the relations preflight and the platform probe died, MBB cars
fell back to the wrong gdc, every live read answered 412, and the whole
volkswagen.de channel went unavailable — while the LOGIN kept working, so the
transport looked healthy. Reported by @fschulte2812 on the pull request and by
@Joassens on #1659, both with the same one-line diagnosis.

The contract test that existed checked which *members* the connector uses
(``cookie_jar`` / ``get`` / ``post`` / ``close``) — not the *signatures* it
calls them with. That is exactly the gap, so this file closes it by binding
every real call site against the shim's own signature: a future call with a
new keyword fails here instead of in somebody's house.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import httpx
import pytest

from custom_components.vag_connect.cariad.auth import _website_authproxy as wap
from custom_components.vag_connect.cariad.auth._http2 import _H2Response

#: the shim reads ``resp.url``, which httpx only exposes on a response that
#: carries its request — so every fixture response gets one.
REQ = httpx.Request("GET", "https://www.volkswagen.de/app/authproxy/x")

CONNECTOR = pathlib.Path(inspect.getfile(wap))


def _response_calls() -> list[tuple[str, int, tuple[str, ...], int]]:
    """Every ``resp.<attr>(...)`` in the connector: (attr, #positional, kwargs, line)."""
    tree = ast.parse(CONNECTOR.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in ("resp", "r", "response")):
            out.append((node.func.attr, len(node.args),
                        tuple(k.arg or "" for k in node.keywords), node.lineno))
    return out


def test_the_connector_calls_something_we_can_check() -> None:
    """Guard the guard: if the scan finds nothing, the rest is vacuous."""
    calls = _response_calls()
    assert calls, "no resp.* calls found — the AST scan broke"
    assert any(c[0] == "json" for c in calls)
    assert any(c[0] == "text" for c in calls)


def test_every_real_call_site_binds_against_the_shim() -> None:
    """The actual regression test: bind each call the connector makes."""
    failures = []
    for attr, n_pos, kwargs, line in _response_calls():
        member = getattr(_H2Response, attr, None)
        if member is None:
            failures.append(f"line {line}: _H2Response has no '{attr}'")
            continue
        if not callable(member):
            continue  # a property; attribute access cannot fail on arguments
        sig = inspect.signature(member)
        try:
            sig.bind(None, *range(n_pos), **{k: None for k in kwargs if k})
        except TypeError as exc:
            failures.append(
                f"line {line}: resp.{attr}("
                f"{n_pos} positional, {list(kwargs)}) does not fit "
                f"{attr}{sig}: {exc}"
            )
    assert not failures, "\n".join(failures)


@pytest.mark.asyncio
async def test_json_accepts_content_type_like_aiohttp() -> None:
    """The exact call from ``_get_json``, which b3 raised a TypeError on."""
    resp = httpx.Response(200, json={"platform": "MBB"}, request=REQ)
    shim = _H2Response(resp, ())
    assert await shim.json(content_type=None) == {"platform": "MBB"}
    assert await shim.json() == {"platform": "MBB"}
    assert await shim.json(None) == {"platform": "MBB"}  # positional too


@pytest.mark.asyncio
async def test_an_empty_body_is_none_not_an_exception() -> None:
    """aiohttp returns None for an empty body; httpx raises JSONDecodeError and
    the caller has no handler for it (@fschulte2812's extra note)."""
    for content in (b"", b"   ", b"\n"):
        shim = _H2Response(httpx.Response(200, content=content, request=REQ), ())
        assert await shim.json(content_type=None) is None


@pytest.mark.asyncio
async def test_text_accepts_aiohttps_arguments() -> None:
    resp = httpx.Response(200, content="héllo".encode(), request=REQ)
    shim = _H2Response(resp, ())
    assert "llo" in await shim.text(errors="replace")
    assert "llo" in await shim.text("utf-8", "replace")
    assert "llo" in await shim.text(encoding="utf-8", errors="replace")


@pytest.mark.asyncio
async def test_undecodable_bytes_still_yield_a_string_when_tolerated() -> None:
    shim = _H2Response(
        httpx.Response(200, content=b"\xff\xfe\x00bad", request=REQ), ()
    )
    assert isinstance(await shim.text(errors="replace"), str)


def test_the_member_contract_also_still_holds() -> None:
    """The original contract check, kept: the session surface the connector
    reaches for must exist on the adapter."""
    import re

    from custom_components.vag_connect.cariad.auth._http2 import H2Session

    src = CONNECTOR.read_text(encoding="utf-8")
    for attr in sorted(set(re.findall(r"self\._session\.([a-z_]+)", src))):
        assert hasattr(H2Session, attr), attr
