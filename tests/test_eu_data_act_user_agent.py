from __future__ import annotations

import json

from custom_components.vag_connect.cariad.auth import _eu_data_act


def test_user_agent_includes_manifest_version() -> None:
    manifest_path = _eu_data_act._MANIFEST_PATH
    version = json.loads(manifest_path.read_text(encoding="utf-8"))["version"]

    assert _eu_data_act._USER_AGENT == f"HA_vag_connect/{version}"


def test_manifest_read_failure_uses_fallback(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(_eu_data_act, "_MANIFEST_PATH", tmp_path / "missing.json")

    assert _eu_data_act._integration_version() == "unknown"


def test_invalid_manifest_version_uses_fallback(monkeypatch, tmp_path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"version": ""}', encoding="utf-8")
    monkeypatch.setattr(_eu_data_act, "_MANIFEST_PATH", manifest_path)

    assert _eu_data_act._integration_version() == "unknown"
