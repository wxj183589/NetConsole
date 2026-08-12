from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "quality-gate.yml",
    ROOT / ".github" / "workflows" / "python-full-regression.yml",
)


def _workflow(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_windows_runner_selection_is_consistent_and_safe_for_public_prs() -> None:
    for path in WORKFLOWS:
        raw = path.read_text(encoding="utf-8")
        workflow = _workflow(path)
        jobs = workflow["jobs"]
        selector = jobs["runner-preflight"]["runs-on"]

        assert workflow["permissions"] == {"contents": "read"}
        assert "pull_request_target" not in raw
        assert "continue-on-error" not in raw
        assert "github.event_name == 'pull_request' && 'windows-latest'" in selector
        assert "vars.NETCONSOLE_CI_RUNNER_MODE == 'self-hosted'" in selector
        assert "netconsole-ci-windows-x64" in selector
        assert jobs["runner-preflight"]["timeout-minutes"] == 5
        assert "Public pull_request runs must never use the self-hosted runner." in raw
        assert "D:\\NetConsoleTestData" in raw

        for job_name, job in jobs.items():
            assert job["runs-on"] == selector, (path, job_name)


def test_manual_runner_choice_and_setup_documentation_are_present() -> None:
    for path in WORKFLOWS:
        workflow = _workflow(path)
        runner_mode = workflow[True]["workflow_dispatch"]["inputs"]["runner_mode"]
        assert runner_mode["type"] == "choice"
        assert runner_mode["default"] == "auto"
        assert runner_mode["options"] == ["auto", "hosted", "self-hosted"]

    documentation = (ROOT / "docs" / "development" / "SELF_HOSTED_CI.md").read_text(
        encoding="utf-8"
    )
    for expected in (
        "NETCONSOLE_CI_RUNNER_MODE",
        "netconsole-ci-windows-x64",
        "Settings → Actions → Runners → New self-hosted runner",
        "D:\\GitHubActions\\NetConsoleRunner",
        "D:\\NetConsoleTestData\\<run-id>",
        "pull_request",
    ):
        assert expected in documentation
