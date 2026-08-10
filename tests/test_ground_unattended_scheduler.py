from __future__ import annotations

from types import SimpleNamespace

from netconsole.models.api.ground_unattended import GroundUnattendedTrainDTO
from netconsole.models.api.ground_unattended import GroundUnattendedProfileDTO
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.deep_scheduler import (
    DeepMrCollectionScheduler,
)
from netconsole.services.ground_unattended.supervisor import (
    GroundUnattendedSupervisor,
)


def test_daily_coverage_prioritizes_pinned_then_unseen_then_partial() -> None:
    trains = [
        _train("covered", priority=True, status="COVERED", attempts=1, rounds=1),
        _train("partial", status="PARTIAL", attempts=1),
        _train("unseen", attempts=0),
        _train("pinned", priority=True, attempts=0),
    ]
    ordered = DeepMrCollectionScheduler.ordered_candidates(
        trains,
        queue_order=["partial", "unseen", "pinned", "covered"],
        ping_loss_by_train={"covered": 99.0, "partial": 20.0},
    )
    assert [item.train_id for item in ordered] == ["pinned", "unseen", "partial"]
    assert "covered" not in {item.train_id for item in ordered}


def test_monitor_only_and_deep_disabled_do_not_cancel_depot_ping() -> None:
    for policy in (
        {"monitor_only": True},
        {"deep_collection_enabled": False},
    ):
        train = GroundUnattendedTrainDTO(
            train_id="train-depot",
            location_class="DEPOT",
            ping_eligible=True,
            deep_collection_eligible=False,
            ping_inclusion_reason="已启用车辆段长 Ping",
        )

        GroundUnattendedSupervisor._apply_train_policy(
            train, policy, priority=True
        )

        assert train.ping_eligible is True
        assert train.deep_collection_eligible is False
        assert train.priority is True


def test_disabled_train_cancels_all_unattended_eligibility() -> None:
    train = GroundUnattendedTrainDTO(
        train_id="train-depot",
        location_class="DEPOT",
        mainline_eligible=True,
        ping_eligible=True,
        deep_collection_eligible=True,
    )

    GroundUnattendedSupervisor._apply_train_policy(
        train, {"enabled": False}, priority=False
    )

    assert train.mainline_eligible is False
    assert train.ping_eligible is False
    assert train.deep_collection_eligible is False


def test_second_round_starts_only_after_every_eligible_train_is_covered() -> None:
    first_round = [
        _train("a", status="COVERED", attempts=1, rounds=1),
        _train("b", status="PARTIAL", attempts=1, rounds=0),
    ]
    assert [
        item.train_id
        for item in DeepMrCollectionScheduler.ordered_candidates(
            first_round, queue_order=["a", "b"]
        )
    ] == ["b"]
    second_round = [
        _train("a", status="COVERED", attempts=1, rounds=1),
        _train("b", priority=True, status="COVERED", attempts=1, rounds=1),
    ]
    assert [
        item.train_id
        for item in DeepMrCollectionScheduler.ordered_candidates(
            second_round, queue_order=["a", "b"]
        )
    ] == ["b", "a"]


def test_same_rank_uses_persisted_random_queue_order() -> None:
    trains = [_train("a"), _train("b"), _train("c")]
    first = DeepMrCollectionScheduler.ordered_candidates(
        trains, queue_order=["c", "a", "b"]
    )
    second = DeepMrCollectionScheduler.ordered_candidates(
        trains, queue_order=["c", "a", "b"]
    )
    assert [item.train_id for item in first] == ["c", "a", "b"]
    assert first == second


def test_daily_queue_reproducibly_appends_trains_seen_later(tmp_path) -> None:
    repository = GroundUnattendedRepository(tmp_path / "index.sqlite", site_id="site-a")
    run = repository.create_or_get_run(
        run_id="run-queue",
        run_date="2026-07-25",
        scheduled_start_at="2026-07-25T07:00:00+08:00",
        scheduled_end_at="2026-07-25T23:00:00+08:00",
    )
    scheduler = object.__new__(DeepMrCollectionScheduler)
    scheduler.site_id = "site-a"
    scheduler.repository = repository

    initial = scheduler._ensure_queue(run["run_id"], [_train("a"), _train("b")])
    expanded = scheduler._ensure_queue(
        run["run_id"], [_train("a"), _train("b"), _train("c"), _train("d")]
    )
    repeated = scheduler._ensure_queue(
        run["run_id"], [_train("a"), _train("b"), _train("c"), _train("d")]
    )

    assert expanded[:2] == initial
    assert set(expanded) == {"a", "b", "c", "d"}
    assert repeated == expanded
    assert repository.get_daily_queue(run["run_id"])["queue_order"] == expanded


def test_collecting_train_starts_only_the_missing_endpoint() -> None:
    train = _train("train-a", status="COLLECTING")
    train.update(
        {
            "operations": {"CT": "operation-ct"},
            "endpoints": [
                {"endpoint": "CT", "device_id": 1, "management_ip": "10.0.0.1"},
                {"endpoint": "CW", "device_id": 2, "management_ip": "10.0.0.2"},
            ],
        }
    )

    selected = DeepMrCollectionScheduler._startable_endpoints(train, {"1"})

    assert [row["endpoint"] for row in selected] == ["CW"]


def test_deep_fping_is_forced_and_ct_cw_keep_independent_targets() -> None:
    profile = GroundUnattendedProfileDTO(site_id="site-a")
    profile.deep_fping.enabled = False

    ct = DeepMrCollectionScheduler._required_fping_config(profile, "10.0.0.1")
    cw = DeepMrCollectionScheduler._required_fping_config(profile, "10.0.0.2")

    assert ct.enabled is True
    assert cw.enabled is True
    assert ct.target == "10.0.0.1"
    assert cw.target == "10.0.0.2"
    assert ct.interval_ms == cw.interval_ms == profile.deep_fping.interval_ms


def test_train_coverage_waits_for_both_endpoints_and_is_counted_once(tmp_path) -> None:
    repository = GroundUnattendedRepository(tmp_path / "index.sqlite", site_id="site-a")
    run = repository.create_or_get_run(
        run_id="run-a",
        run_date="2026-07-25",
        scheduled_start_at="2026-07-25T07:00:00+08:00",
        scheduled_end_at="2026-07-25T23:00:00+08:00",
    )
    repository.upsert_train_state(
        run["run_id"],
        run["run_date"],
        {
            "train_id": "train-a",
            "deep_collection_eligible": True,
            "endpoints": [
                {"endpoint": "CT", "device_id": 1, "management_ip": "10.0.0.1"},
                {"endpoint": "CW", "device_id": 2, "management_ip": "10.0.0.2"},
            ],
        },
        ap_identity="ap-a",
        same_ap_since="2026-07-25T08:00:00+08:00",
    )
    repository.update_train_run(
        run["run_id"],
        "train-a",
        coverage_status="COLLECTING",
        attempt_count=1,
        operations_json={"CT": "operation-ct"},
    )
    _save_completed_operation(repository, run["run_id"], "operation-ct", "CT")
    scheduler = object.__new__(DeepMrCollectionScheduler)
    scheduler.site_id = "site-a"
    scheduler.repository = repository
    scheduler.application_service = _CompletedApplicationService()
    profile = SimpleNamespace(minimum_valid_collection_minutes=10)

    scheduler._update_train_coverage(run["run_id"], profile)
    assert (
        repository.get_train_run(run["run_id"], "train-a")["coverage_status"]
        == "COLLECTING"
    )

    repository.update_train_run(
        run["run_id"],
        "train-a",
        operations_json={"CT": "operation-ct", "CW": "operation-cw"},
    )
    _save_completed_operation(repository, run["run_id"], "operation-cw", "CW")
    scheduler._update_train_coverage(run["run_id"], profile)
    covered = repository.get_train_run(run["run_id"], "train-a")
    assert covered["coverage_status"] == "COVERED"
    assert covered["covered_rounds"] == 1
    assert covered["operations"] == {}

    scheduler._update_train_coverage(run["run_id"], profile)
    assert repository.get_train_run(run["run_id"], "train-a")["covered_rounds"] == 1


def _train(train_id: str, *, priority=False, status="NOT_SEEN", attempts=0, rounds=0):
    return {
        "train_id": train_id,
        "priority": priority,
        "coverage_status": status,
        "attempt_count": attempts,
        "covered_rounds": rounds,
        "deep_collection_eligible": True,
    }


def _save_completed_operation(
    repository, run_id: str, operation_id: str, endpoint: str
):
    repository.save_deep_operation(
        {
            "operation_id": operation_id,
            "site_id": "site-a",
            "run_id": run_id,
            "train_id": "train-a",
            "mr_id": f"mr-{endpoint.casefold()}",
            "mr_position_code": endpoint,
            "session_id": f"session-{endpoint.casefold()}",
            "state": "COMPLETED",
            "started_at": "2026-07-25T08:00:00+08:00",
            "ended_at": "2026-07-25T08:12:00+08:00",
            "stop_reason": "preferred_duration_reached",
            "error_summary": "",
            "finalization_complete": 1,
            "package_verified": 1,
            "updated_at": "2026-07-25T08:12:00+08:00",
        }
    )


class _CompletedApplicationService:
    @staticmethod
    def get_operation(*_args, **_kwargs):
        return SimpleNamespace(duration_minutes=12)
