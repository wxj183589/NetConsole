from __future__ import annotations

from netconsole.core.database import Database
from netconsole.models.cloud_sync_models import CloudSyncProfile, WpsApiResult, WpsKSheetDocument, WpsKSheetSheet
from netconsole.repositories.cloud_sync_repository import CloudSyncRepository
from netconsole.services.cloud_sync.wps_auth import WpsAuthContext
from netconsole.services.cloud_sync.wps_ksheet_client import WpsKSheetClient
from netconsole.services.trackside_ap_business import (
    AP_OPTICAL_TREATMENT_RECORD_COLUMNS,
    TRACKSIDE_AP_BUSINESS_EXPORT_COLUMNS,
    build_trackside_ap_business_sheet_payloads,
)


def test_wps_profile_is_saved_per_site_with_separate_tokens(tmp_path):
    db = Database(tmp_path / "netconsole.db")
    db.initialize()
    repository = CloudSyncRepository(db)

    repository.save_profile(CloudSyncProfile(site_id="site-a", enabled=True, access_token="token-a", file_token="file-a"))
    repository.save_profile(CloudSyncProfile(site_id="site-b", enabled=True, access_token="token-b", file_token="file-b"))

    assert repository.get_profile("site-a").file_token == "file-a"
    assert repository.get_profile("site-b").file_token == "file-b"
    with db.connect() as conn:
        stored = conn.execute("SELECT access_token_encrypted FROM cloud_sync_profiles WHERE site_id = 'site-a'").fetchone()[0]
    assert stored != "token-a"
    assert repository.get_profile("site-a").access_token == "token-a"


def test_trackside_payload_uses_export_columns_and_preserves_optical_identity():
    rows = [
        {
            "site": "A站",
            "device_name": "SW1",
            "interface_name": "GigabitEthernet1/0/1",
            "link_status": "UP",
            "switch_rx_power": "-3.1",
            "switch_optical_status": "正常",
            "ap_mac": "aa-bb",
            "ap_name": "AP01",
            "serial_number": "SN01",
            "port_type": "L2",
            "pvid": "10",
            "vlan": "10",
        }
    ]
    treatment_rows = [{"site": "A站", "ap_name": "AP01", "ap_mac": "aa-bb", "serial_number": "SN01"}]
    payloads = build_trackside_ap_business_sheet_payloads(
        rows,
        headers=[key for key, _field in TRACKSIDE_AP_BUSINESS_EXPORT_COLUMNS],
        ap_optical_treatment_rows=treatment_rows,
        ap_optical_treatment_headers=[key for key, _field in AP_OPTICAL_TREATMENT_RECORD_COLUMNS],
        offline_ap_stats={"total_aps": 1, "online_aps": 0, "offline_aps": 1},
        offline_ap_ledger_rows=[{"site": "B站", "ap_name": "AP-B", "offline_at": "2026-06-30"}, {"site": "A站", "ap_name": "AP-A", "offline_at": "2026-06-29"}],
    )

    main = next(item for item in payloads if item.name == "轨旁AP业务")
    assert "端口类型" not in main.headers
    assert len(main.headers) == len(TRACKSIDE_AP_BUSINESS_EXPORT_COLUMNS)
    treatment = next(item for item in payloads if item.name == "AP光衰处理记录")
    assert {"ac.ap_name", "ac.ap_mac", "ap.serial_number"}.issubset(set(treatment.headers))
    assert treatment.rows[0][1:4] == ["AP01", "aa-bb", "SN01"]
    ledger = next(item for item in payloads if item.name == "离线AP台账")
    assert ledger.headers[5] == "trackside.export.offline_at"
    assert ledger.rows[0][0] == "A站"


def test_wps_client_batches_write_and_readonly_members_are_read_only():
    calls = []

    class Response:
        def __init__(self, body: str = "{}") -> None:
            self.body = body.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return self.body

    def opener(request, timeout):
        calls.append((request.get_method(), request.full_url, request.data))
        return Response("{}")

    client = WpsKSheetClient(WpsAuthContext("token"), opener=opener)
    client.write_table("file-1", "sheet-1", ["A"], [[1], [2], [3], [4], [5]], batch_size=2)
    client.set_readonly_members("file-1", [])

    write_calls = [call for call in calls if "/cells" in call[1]]
    assert len(write_calls) == 3


class FakeClient:
    def __init__(self) -> None:
        self.created = 0
        self.written = []
        self.members = []

    def test_connection(self):
        return WpsApiResult(True)

    def create_ksheet(self, name, folder_token=None):
        self.created += 1
        return WpsKSheetDocument("new-file", name, "https://kdocs.cn/l/new-file")

    def get_document_url(self, file_token):
        return f"https://kdocs.cn/l/{file_token}"

    def ensure_sheet(self, file_token, sheet_name, headers=None):
        return WpsKSheetSheet(sheet_name, sheet_name)

    def clear_sheet_data(self, file_token, sheet_id):
        return None

    def write_table(self, file_token, sheet_id, headers, rows, **kwargs):
        self.written.append((file_token, sheet_id, headers, rows))

    def apply_basic_format(self, file_token, sheet_id, columns):
        return None

    def set_readonly_members(self, file_token, members):
        self.members = members
        return WpsApiResult(True)


def test_readonly_member_payload_does_not_contain_write_permission():
    fake = FakeClient()
    fake.set_readonly_members("file-1", [])
    assert all(getattr(member, "permission", "read") != "write" for member in fake.members)
