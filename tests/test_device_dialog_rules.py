from PySide6.QtWidgets import QApplication

from netconsole.core.database import Database
from netconsole.core.i18n import I18n
from netconsole.models.device import Device
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.netmiko_connection import ConnectionTestResult
from netconsole.ui.dialogs.device_dialog import DeviceDialog
from netconsole.ui.dialogs.device_form_rules import format_auth_user, validate_device_form_data


def test_validate_device_form_requires_name_and_host():
    assert validate_device_form_data({"name": "", "primary_address": "10.0.0.1", "ssh_enabled": 1, "ssh_port": 22}) == "validation.name_required"
    assert validate_device_form_data({"name": "SW1", "primary_address": "", "ssh_enabled": 1, "ssh_port": 22}) == "validation.host_required"


def test_validate_device_form_requires_ssh_or_telnet():
    assert validate_device_form_data({"name": "SW1", "primary_address": "10.0.0.1", "ssh_enabled": 0, "telnet_enabled": 0}) == "validation.connection_required"


def test_validate_device_form_accepts_ssh_and_telnet_together():
    assert validate_device_form_data({"name": "SW1", "primary_address": "10.0.0.1", "ssh_enabled": 1, "ssh_port": 22, "telnet_enabled": 1, "telnet_port": 23}) is None


def test_credentials_allow_blank_usernames_and_passwords():
    assert validate_device_form_data(
        {
            "name": "SW1",
            "primary_address": "10.0.0.1",
            "ssh_enabled": 1,
            "ssh_port": 22,
            "ssh_username": "",
            "ssh_password": "",
            "telnet_username": "",
            "telnet_password": "",
        }
    ) is None


def test_auth_user_display_rules():
    assert format_auth_user("ssh", "") == "SSH:ssh / Telnet:-"
    assert format_auth_user("", "telnet") == "SSH:- / Telnet:telnet"
    assert format_auth_user("", "") == "SSH:- / Telnet:-"


def test_successful_connection_result_updates_dialog_system_name():
    QApplication.instance() or QApplication([])
    dialog = DeviceDialog(I18n("en_US"))

    sysname = dialog.apply_test_connection_system_name(
        ConnectionTestResult(True, "SSH", "10.0.0.51", 22, "ok", "<AC>", 1403)
    )

    assert sysname == "AC"
    assert dialog.form_data()["system_name"] == "AC"
    dialog.close()


def test_unparseable_connection_prompt_does_not_update_dialog_system_name():
    QApplication.instance() or QApplication([])
    dialog = DeviceDialog(I18n("en_US"))
    dialog.inputs["system_name"].setText("Existing")

    sysname = dialog.apply_test_connection_system_name(
        ConnectionTestResult(True, "SSH", "10.0.0.51", 22, "ok", "invalid", 1403)
    )

    assert sysname is None
    assert dialog.form_data()["system_name"] == "Existing"
    dialog.close()


def test_dialog_system_name_is_saved_to_repository_after_backfill(tmp_path):
    QApplication.instance() or QApplication([])
    database = Database(tmp_path / "devices.db")
    database.initialize()
    repository = DeviceRepository(database)
    dialog = DeviceDialog(I18n("en_US"))
    dialog.inputs["name"].setText("AC")
    dialog.inputs["primary_address"].setText("10.0.0.51")
    dialog.apply_test_connection_system_name(ConnectionTestResult(True, "SSH", "10.0.0.51", 22, "ok", "[AC]", 1403))

    created = repository.create(dialog.device())

    assert repository.get(created.id).system_name == "AC"
    dialog.close()


def test_dialog_system_name_overwrite_is_saved_to_repository_when_editing(tmp_path):
    QApplication.instance() or QApplication([])
    database = Database(tmp_path / "devices.db")
    database.initialize()
    repository = DeviceRepository(database)
    existing = repository.create(Device(name="SW", primary_address="10.0.0.52", system_name="OLD"))
    dialog = DeviceDialog(I18n("en_US"), device=existing)
    dialog.apply_test_connection_system_name(ConnectionTestResult(True, "SSH", "10.0.0.52", 22, "ok", "<SW01>", 1403))

    updated = repository.update(dialog.device())

    assert updated.system_name == "SW01"
    assert repository.get(existing.id).system_name == "SW01"
    dialog.close()


def test_dialog_form_contains_new_connection_and_tunnel_fields():
    QApplication.instance() or QApplication([])
    dialog = DeviceDialog(I18n("zh_CN"))

    assert "sysname" not in dialog.inputs
    assert "ip_address" not in dialog.inputs
    assert "tunnel1_local_port" not in dialog.inputs
    assert "tunnel2_local_port" not in dialog.inputs
    for field in ("system_name", "primary_address", "backup_address", "tunnel_enabled", "tunnel1_host", "tunnel2_host"):
        assert field in dialog.inputs
    assert dialog.labels["station"].text() == "归属站点"
    dialog.close()
