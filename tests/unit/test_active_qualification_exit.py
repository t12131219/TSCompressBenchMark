from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "status,exit_code",
    [("SCOPED_QUALIFICATION_COMPLETE", 0), ("INCOMPLETE_OR_FAILED", 1)],
)
def test_qualification_command_reports_unsuccessful_acceptance_to_callers(
    tmp_path, monkeypatch, status, exit_code
):
    driver = Path(__file__).resolve().parents[2] / "tools/qualify_v32_active_entries.py"
    spec = importlib.util.spec_from_file_location("active_qualification_exit_driver", driver)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "plan.json").write_text(
        json.dumps({"cpu": 0, "model_cpus": [0, 2, 4], "selected_keys": ["deepzip"]})
    )
    monkeypatch.setattr(module, "validate_frozen", lambda *args: None)
    monkeypatch.setattr(module, "execute", lambda *args: {"status": status})
    monkeypatch.setattr(
        sys, "argv", [str(driver), "--output", str(tmp_path), "--cpu", "0", "--resume", "--execute"]
    )
    try:
        module.main()
    except SystemExit as error:
        observed = error.code
    else:
        observed = 0
    assert observed == exit_code
