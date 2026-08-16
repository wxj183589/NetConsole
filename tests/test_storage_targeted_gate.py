from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts.quality.run_storage_targeted_gate import (
    TARGETS,
    run_storage_targeted_gate,
)


def test_targeted_gate_binds_head_and_cleans_isolated_root(tmp_path: Path) -> None:
    calls: list[tuple[tuple[str, ...], Path, dict[str, str]]] = []

    def runner(command, *, cwd, env, check):
        assert check is False
        calls.append((tuple(command), Path(cwd), dict(env)))
        return SimpleNamespace(returncode=0)

    output = tmp_path / "reports" / "targeted.json"
    report = run_storage_targeted_gate(
        run_id="targeted-test",
        output_path=output,
        development_root=tmp_path.parent.parent,
        test_base_root=tmp_path / "test-data",
        runner=runner,
    )

    assert report["result"] == "PASS"
    assert report["passed"] == ["storage-targeted"]
    assert len(report["head_sha"]) == 40
    assert report["targets"] == list(TARGETS)
    assert report["isolation"]["test_root_removed"] is True
    assert not Path(report["isolation"]["test_root"]).exists()
    assert calls[0][2]["NETCONSOLE_RUNTIME_MODE"] == "test"
    assert json.loads(output.read_text(encoding="utf-8"))["result"] == "PASS"
