from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from scripts.quality.local_gate import remove_owned_test_root


ROOT = Path(__file__).resolve().parents[2]
TEST_BASE_ROOT = Path(r"D:\study\NetConsole-Workspace\test-data\NetConsole")
MAIN_CONTRACT_TESTS = (
    "tests/test_electron_runtime.py::test_electron_runtime_accepts_only_loopback_configuration",
    "tests/test_sites.py::test_site_manager_creates_demo_and_chinese_site",
    "tests/test_device_management_web_api.py::test_list_supports_filter_sort_pagination_and_never_returns_credentials",
    "tests/test_ac_management_web_api.py::test_ac_management_get_api_is_read_only_and_redacts_serial_number",
    "tests/test_rail_transit_base_data_web_api.py::test_base_data_api_defaults_to_locked_and_redacts_credentials",
    "tests/test_trackside_ap_business_snapshot.py::test_business_revision_and_content_hash_are_idempotent",
    "tests/test_mesh_analysis_web_api.py::test_mesh_analysis_queries_keep_analysis_files_unchanged",
    "tests/test_online_mr_application_service.py::test_application_start_places_task_in_explicit_site_with_device_metadata",
    "tests/test_ground_unattended_api.py::test_ground_unattended_empty_pages_are_stable",
    "tests/test_job_center_web_api.py::test_job_center_get_api_is_read_only_and_returns_associations",
    "tests/test_export_process_framework.py::test_generic_table_csv_handler_writes_utf8_sig_and_replaces_tmp",
    "tests/test_system_settings_web_api.py::test_default_desktop_profile_reaches_settings_and_round_trips",
)


def _owned_test_root(run_id: str) -> Path:
    target = (TEST_BASE_ROOT / run_id).resolve()
    base = TEST_BASE_ROOT.resolve()
    if target == base or not target.is_relative_to(base):
        raise ValueError(r"main smoke test root must be inside D:\study\NetConsole-Workspace\test-data\NetConsole\<run-id>")
    return target


def run_main_contract_smoke(*, run_id: str | None = None) -> int:
    run_root = _owned_test_root(run_id or f"main-contract-{uuid4().hex}")
    run_root.mkdir(parents=True, exist_ok=False)
    environment = os.environ.copy()
    environment.update(
        {
            "NETCONSOLE_RUNTIME_MODE": "test",
            "NETCONSOLE_STORAGE_MODE": "persistent",
            "NETCONSOLE_DATA_ROOT": str(run_root / "session"),
        }
    )
    command = [
        sys.executable,
        "-m",
        "pytest",
        *MAIN_CONTRACT_TESTS,
        "-q",
        "--tb=short",
        "--basetemp",
        str(run_root / "pytest"),
    ]
    try:
        return subprocess.run(command, cwd=ROOT, env=environment, check=False).returncode
    finally:
        remove_owned_test_root(run_root, base_root=TEST_BASE_ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the stable 12-entry NetConsole main contract smoke suite.")
    parser.add_argument("--run-id")
    args = parser.parse_args()
    return run_main_contract_smoke(run_id=args.run_id)


if __name__ == "__main__":
    raise SystemExit(main())
