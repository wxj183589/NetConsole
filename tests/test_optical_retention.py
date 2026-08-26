from __future__ import annotations

from netconsole.core.database import Database
from netconsole.repositories.ac_repository import AcRepository
from netconsole.services.optical_retention import (
    build_optical_projection,
    update_ap_optical_treatment,
    upsert_optical_current_and_history,
)
from netconsole.services.ap_business_optical import evaluate_ap_business_rx


def _optical_row(ap_uuid: str, rx: str, collected_at: str) -> dict[str, object]:
    return {
        "ap_uuid": ap_uuid,
        "ap_name": f"AP-{ap_uuid}",
        "ap_mac": "0011-2233-4455",
        "rx_power": rx,
        "tx_power": "-5.0",
        "status": "success",
        "collected_at": collected_at,
    }


def test_optical_current_deduplicates_identical_values_and_bounds_history(tmp_path) -> None:
    repository = AcRepository(Database(tmp_path / "devices.db"))
    repository.database.initialize()
    row = _optical_row("ap-1", "-10.00", "2026-08-01T00:00:00")
    for index in range(1000):
        repository.replace_fit_ap_optical(
            "ac-1",
            [{**row, "collected_at": f"2026-08-01T00:{index // 60:02d}:{index % 60:02d}"}],
        )
    with repository.database.connect_readonly() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM optical_current WHERE ap_identity='ap-1' AND side='AP'"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM optical_history WHERE ap_identity='ap-1' AND side='AP'"
        ).fetchone()[0] == 0

    for index in range(11):
        repository.replace_fit_ap_optical(
            "ac-1",
            [{**row, "rx_power": f"{-10.1 - index:.2f}", "collected_at": f"2026-08-02T00:00:{index:02d}"}],
        )
    with repository.database.connect_readonly() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM optical_history WHERE ap_identity='ap-1' AND side='AP'"
        ).fetchone()[0] == 10


def test_ap_optical_treatment_is_one_row_across_abnormal_recovery_and_recurrence(tmp_path) -> None:
    repository = AcRepository(Database(tmp_path / "devices.db"))
    repository.database.initialize()
    base = {"ap_uuid": "ap-1", "ap_name": "AP-1", "ap_mac": "0011-2233-4455"}
    for rx, timestamp in (
        ("-14.00", "2026-08-01T00:00:00"),
        ("-14.10", "2026-08-01T00:01:00"),
        ("-10.00", "2026-08-01T00:02:00"),
        ("-14.20", "2026-08-01T00:03:00"),
    ):
        repository.replace_fit_ap_optical("ac-1", [{**base, "rx_power": rx, "status": "success", "collected_at": timestamp}])

    treatment = repository.list_ap_optical_treatments()
    assert len(treatment) == 1
    assert treatment[0]["recurrence_count"] == 1
    assert treatment[0]["current_status"] == "ABNORMAL"
    assert treatment[0]["treatment_status"] == "RECURRENT"
    assert treatment[0]["first_detected_at"] == "2026-08-01T00:00:00"
    assert treatment[0]["first_resolved_at"] == "2026-08-01T00:02:00"

    for index in range(100):
        repository.replace_fit_ap_optical(
            "ac-1",
            [{**base, "rx_power": "-14.30", "status": "success", "collected_at": f"2026-08-02T00:01:{index:02d}"}],
        )
    assert len(repository.list_ap_optical_treatments()) == 1


def test_treatment_unique_key_scales_to_1500_aps(tmp_path) -> None:
    database = Database(tmp_path / "devices.db")
    database.initialize()
    with database.connect() as connection:
        for index in range(1500):
            row = _optical_row(f"ap-{index}", "-14.00", "2026-08-01T00:00:00")
            projection = upsert_optical_current_and_history(
                connection, row, site_id="scale-site", side="AP", now="2026-08-01T00:00:00"
            )
            update_ap_optical_treatment(
                connection,
                site_id="scale-site",
                ap_identity=str(projection["ap_identity"]),
                source_row=row,
                now="2026-08-01T00:00:00",
            )
        connection.commit()
        assert connection.execute(
            "SELECT COUNT(*) FROM ap_optical_treatment WHERE site_id='scale-site'"
        ).fetchone()[0] == 1500
        assert connection.execute(
            "SELECT COUNT(*) FROM ap_optical_treatment WHERE site_id='scale-site' GROUP BY site_id, ap_identity HAVING COUNT(*) > 1"
        ).fetchone() is None


def test_no_module_without_measurement_does_not_create_current_and_keeps_threshold() -> None:
    projection = build_optical_projection(
        {
            "ap_uuid": "ap-wa6522",
            "ap_name": "WA6522",
            "status": "no_module",
        },
        site_id="site-1",
        side="AP",
        now="2026-08-26T00:00:00",
    )

    assert projection is None
    assert evaluate_ap_business_rx("-13.90") == "normal"
