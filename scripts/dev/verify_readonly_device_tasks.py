"""Run explicitly selected lab devices through the real API and task workers."""
from __future__ import annotations

import argparse
import json
import os
import socket
import time
from pathlib import Path
from uuid import uuid4


def main() -> int:
    parser = argparse.ArgumentParser(description="隔离 TEST 根内验收真实设备只读任务")
    parser.add_argument("--ssh-target", action="append", required=True, help="name,role,address")
    parser.add_argument("--telnet-probe", help="仅检查 TCP 23 可达性")
    parser.add_argument("--ac-collections", action="store_true", help="增加 AC 无线与 MESH 只读采集验收")
    parser.add_argument("--only-kind", choices=("custom", "lldp", "wireless", "mesh"), help="仅执行指定的已启用采集类型")
    args = parser.parse_args()
    username = os.environ.get("NETCONSOLE_LAB_USERNAME")
    password = os.environ.get("NETCONSOLE_LAB_PASSWORD")
    if not username or not password:
        parser.error("请通过 NETCONSOLE_LAB_USERNAME/NETCONSOLE_LAB_PASSWORD 提供实验凭据")
    repository = Path(__file__).resolve().parents[2]
    os.environ["NETCONSOLE_RUNTIME_MODE"] = "test"
    os.environ["NETCONSOLE_PROJECT_ROOT"] = str(repository)
    os.environ["NETCONSOLE_STORAGE_MODE"] = "persistent"
    from netconsole.core.runtime_environment import test_data_root_base

    root = test_data_root_base(repository_root=repository) / f"phase7-readonly-lab-{uuid4().hex[:10]}"
    root.mkdir(parents=True, exist_ok=False)
    os.environ["NETCONSOLE_DATA_ROOT"] = str(root)

    from fastapi.testclient import TestClient
    from netconsole.backend.api.main import create_app
    from netconsole.core.database import Database
    from netconsole.core.paths import PathResolver
    from netconsole.core.runtime_mode import RuntimeMode
    from netconsole.models.device import Device
    from netconsole.models.task_state import TERMINAL_TASK_STATES
    from netconsole.repositories.device_repository import DeviceRepository
    from netconsole.services.site_manager import SiteManager

    paths = PathResolver(app_root=repository, data_root=root)
    site = "phase7-lab"
    SiteManager(paths).create_site(site)
    devices = DeviceRepository(Database(paths.site_db_path(site)))
    targets = []
    for value in args.ssh_target:
        name, role, address = value.split(",", 2)
        device = devices.create(Device(
            name=name, device_type=role, primary_address=address, device_vendor="H3C",
            protocol="ssh", port=22, username=username, password=password,
            ssh_enabled=1, ssh_port=22, ssh_username=username, ssh_password=password,
            telnet_enabled=0,
        ))
        targets.append({"name": name, "address": address, "role": role, "device_uuid": device.device_uuid})
    app = create_app(RuntimeMode.TEST, paths=paths)
    tasks = app.state.task_service
    report = {"root": str(root), "runtime_mode": "test", "site": site, "targets": targets, "runs": [],
              "PRODUCTION_DATA_MODIFIED": 0, "DEV_REAL_DATA_MODIFIED": 0, "DATABASES_REMOVED": 0}

    def terminal(task_id: str):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            snapshot = tasks.repository(site).get(task_id)
            if snapshot is not None and snapshot.status in TERMINAL_TASK_STATES:
                return snapshot
            time.sleep(0.2)
        raise TimeoutError(f"Task did not finish: {task_id}")

    with TestClient(app) as client:
        def post(path: str, payload=None):
            response = client.post("/api/device-operations" + path, json=payload)
            response.raise_for_status()
            return response.json()

        definition = {"name": "Phase7 版本只读验收", "category": "实验室验收",
                      "source": "display version", "schema_fields": {},
                      "command_type": "read_only", "vendor": "h3c", "platform": "comware"}
        saved = post("/templates", definition)
        updated = client.put(
            f"/api/device-operations/templates/{saved['template_id']}?expected_version=1",
            json={**definition, "source": "{# Phase7 v2 #}\ndisplay version"},
        )
        updated.raise_for_status()
        version = updated.json()
        report["template"] = {"template_id": version["template_id"], "version": version["version"]}
        selection = {"template_id": version["template_id"], "version": version["version"], "values": {}}
        preview = post("/templates/saved-preview", selection)
        requests = [
            {"kind": "custom", "device_uuids": [target["device_uuid"] for target in targets],
             "concurrency": 3, "command_timeout": 30,
             "saved_template": {**selection, "preview_digest": preview["preview_digest"]}},
        ]
        switches = [target["device_uuid"] for target in targets if target["role"] == "SW"]
        if switches:
            requests.append({"kind": "lldp", "device_uuids": switches, "concurrency": 1, "command_timeout": 30})
        controllers = [target["device_uuid"] for target in targets if target["role"] == "AC"]
        if args.ac_collections and controllers:
            for kind in ("wireless", "mesh"):
                requests.append({"kind": kind, "device_uuids": controllers, "concurrency": 2, "command_timeout": 30})
        if args.only_kind:
            requests = [request for request in requests if request["kind"] == args.only_kind]
        if not requests:
            raise ValueError("所选设备和采集选项未产生可运行任务")
        for request in requests:
            reference = post("/tasks", request)
            snapshot = terminal(reference["task_id"])
            response = client.get(f"/api/device-operations/tasks/{reference['task_id']}/result")
            response.raise_for_status()
            result = response.json()
            run = {"task_id": reference["task_id"], "kind": request["kind"], "state": snapshot.status.value,
                   "business_status": result.get("business_status"), "template": result.get("template"),
                   "items": []}
            for item in result.get("items", []):
                run["items"].append({
                    "device_uuid": item["device_uuid"], "device_name": item.get("device_name"),
                    "status": item["status"], "elapsed_ms": item.get("elapsed_ms"),
                    "record_count": item.get("record_count"), "message": item.get("message", ""),
                    "wireless_summary": item.get("wireless_summary"), "executed_commands": item.get("commands"),
                    "commands": [{"command": row["command"], "status": row["status"],
                                  "output_characters": len(row.get("output", ""))}
                                 for row in item.get("command_results", [])],
                })
            export = post(f"/tasks/{reference['task_id']}/exports")
            terminal(export["task_id"])
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                exported = tasks.repository(site).get(export["task_id"])
                if exported.result.get("sha256"):
                    break
                time.sleep(0.1)
            artifact_id = exported.result["artifact_id"]
            artifact = client.get(f"/api/job-center/artifacts/{artifact_id}")
            artifact.raise_for_status()
            run["export"] = {"task_id": export["task_id"], "state": exported.status.value,
                             "artifact_id": artifact_id, "bytes": len(artifact.content),
                             "sha256": exported.result.get("sha256")}
            report["runs"].append(run)
        if args.telnet_probe:
            try:
                with socket.create_connection((args.telnet_probe, 23), timeout=5):
                    report["fit_ap_telnet"] = {"address": args.telnet_probe, "status": "PARTIAL",
                                               "reason": "TCP 23 可达，FIT-AP 独立任务角色尚未适配"}
            except OSError:
                report["fit_ap_telnet"] = {"address": args.telnet_probe, "status": "BLOCKED",
                                           "reason": "TCP 23 无法连接，需现有远程登录服务"}
    (root / "sanitized-result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(run["business_status"] == "SUCCESS" for run in report["runs"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
