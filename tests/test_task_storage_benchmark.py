from __future__ import annotations

from pathlib import Path

from scripts.maintenance.benchmark_tasks_db_governance import run_benchmark


def test_task_storage_benchmark_compares_all_result_layouts(tmp_path: Path) -> None:
    report = run_benchmark(
        tmp_path / "benchmark",
        task_counts=(2,),
        result_sample_counts={"small": 2, "medium": 1, "large": 1},
        progress_events=4,
    )

    assert report["phase"] == "B3_COMPATIBILITY_PHASE"
    comparisons = report["terminal_result_storage"]["task_count_scale"]
    assert len(comparisons) == 1
    layouts = comparisons[0]["layouts"]
    assert set(layouts) == {
        "legacy_dual_full",
        "b3_dual_write",
        "future_ref_only",
    }
    assert layouts["legacy_dual_full"]["results"] == 0
    assert layouts["b3_dual_write"]["results"] == 2
    assert layouts["future_ref_only"]["results"] == 2
    assert layouts["future_ref_only"]["read_path"] == "task_results_read_through"

    size_samples = report["terminal_result_storage"]["result_size_samples"]
    large = next(item for item in size_samples if item["result_profile"] == "large")
    assert 4_000_000 <= large["result_canonical_bytes"] <= 5_000_000
    assert "potential" in report["terminal_result_storage"]["space_claim"].lower()
    assert report["retention"] == "PREVIEW_ONLY_USER_POLICY_REQUIRED"
    assert report["destructive_operations"] == {
        "DELETE": "NO",
        "DROP": "NO",
        "VACUUM": "NO",
    }
    assert (tmp_path / "benchmark" / "TASKS_DB_GOVERNANCE_BENCHMARK.json").is_file()
