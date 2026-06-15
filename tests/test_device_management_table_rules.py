import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton

from netconsole.core.database import Database
from netconsole.core.i18n import I18n
from netconsole.models.device import Device
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.ui.dialogs.device_detail_dialog import DeviceDetailDialog, INTERFACE_COLUMNS, LLDP_COLUMNS, OPTICAL_MODULE_COLUMNS, OVERVIEW_FIELDS, _column_min_widths
from netconsole.ui.pages.device_management_page import DeviceManagementPage, choose_devices_for_export, delete_device_ids, select_device_id_for_connection
from netconsole.ui.widgets.device_table import CHECK_COLUMN, COLUMNS, DeviceTable, protocol_label


def app():
    return QApplication.instance() or QApplication([])


def test_protocol_display_rules():
    assert protocol_label(1, 0) == "SSH"
    assert protocol_label(0, 1) == "Telnet"
    assert protocol_label(1, 1) == "SSH/Telnet"
    assert protocol_label(0, 0) == "-"


def test_main_table_columns_only_include_core_fields():
    assert [field for field, _key in COLUMNS] == [
        "select",
        "status",
        "name",
        "station",
        "ip_address",
        "protocols",
        "updated_at",
        "actions",
    ]


def test_delete_device_ids_deletes_multiple_devices():
    class Repository:
        def __init__(self):
            self.deleted = []

        def delete(self, device_id):
            self.deleted.append(device_id)

    repository = Repository()

    delete_device_ids(repository, [1, 3, 5])

    assert repository.deleted == [1, 3, 5]


def test_choose_devices_for_export_uses_all_when_selection_is_empty():
    all_devices = [Device(id=1, name="A"), Device(id=2, name="B")]

    assert choose_devices_for_export(all_devices, []) == all_devices


def test_choose_devices_for_export_uses_selected_when_available():
    all_devices = [Device(id=1, name="A"), Device(id=2, name="B")]
    selected = [all_devices[1]]

    assert choose_devices_for_export(all_devices, selected) == selected


def test_test_connection_selection_requires_a_device():
    assert select_device_id_for_connection([], None) == (None, "devices.select_first_test")


def test_test_connection_selection_rejects_multiple_checked_devices():
    assert select_device_id_for_connection([1, 2], 1) == (None, "devices.select_one_for_test")


def test_test_connection_selection_uses_single_checked_or_current_device():
    assert select_device_id_for_connection([2], 1) == (2, None)
    assert select_device_id_for_connection([], 1) == (1, None)


def make_table():
    app()
    table = DeviceTable(I18n("en_US"))
    table.set_devices([Device(id=1, name="A"), Device(id=2, name="B")])
    return table


def test_double_click_row_does_not_call_edit_callback():
    table = make_table()
    edited = []
    table.edit_requested.connect(lambda device_id: edited.append(device_id))

    table.doubleClicked.emit(table.model().index(0, 2))

    assert edited == []


def test_row_edit_button_calls_edit_callback():
    table = make_table()
    edited = []
    table.edit_requested.connect(lambda device_id: edited.append(device_id))

    action_widget = table.cellWidget(0, 7)
    buttons = action_widget.findChildren(QPushButton)
    buttons[1].click()

    assert edited == [1]


def test_row_action_buttons_include_detail_edit_and_delete():
    table = make_table()
    action_widget = table.cellWidget(0, 7)
    buttons = action_widget.findChildren(QPushButton)

    assert [button.text() for button in buttons] == ["Details", "Edit", "Delete"]


def test_row_action_buttons_include_chinese_detail_text():
    app()
    table = DeviceTable(I18n("zh_CN"))
    table.set_devices([Device(id=1, name="A")])
    action_widget = table.cellWidget(0, 7)
    buttons = action_widget.findChildren(QPushButton)

    assert buttons[0].text() == "详情"


def test_checkbox_click_adds_and_removes_selected_device_id():
    table = make_table()
    item = table.item(0, CHECK_COLUMN)

    item.setCheckState(Qt.Checked)
    assert table.checked_device_ids() == [1]
    assert table.selected_device_ids == {1}

    item.setCheckState(Qt.Unchecked)
    assert table.checked_device_ids() == []
    assert table.selected_device_ids == set()


def test_header_checkbox_selects_and_clears_current_devices():
    table = make_table()

    table._header_clicked(CHECK_COLUMN)
    assert table.checked_device_ids() == [1, 2]
    assert table.horizontalHeaderItem(CHECK_COLUMN).checkState() == Qt.Checked

    table._header_clicked(CHECK_COLUMN)
    assert table.checked_device_ids() == []
    assert table.horizontalHeaderItem(CHECK_COLUMN).checkState() == Qt.Unchecked


class PageRepository:
    def __init__(self):
        self.database = Database(":memory:")
        self.devices = [Device(id=1, name="A", ip_address="10.0.0.1"), Device(id=2, name="B", ip_address="10.0.0.2")]

    def list(self, **_kwargs):
        return list(self.devices)

    def get(self, device_id):
        return next(device for device in self.devices if device.id == device_id)

    def delete(self, device_id):
        self.devices = [device for device in self.devices if device.id != device_id]


def test_batch_delete_button_tracks_selected_device_ids():
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))

    assert page.batch_delete_button.isEnabled() is False

    page.table.item(0, CHECK_COLUMN).setCheckState(Qt.Checked)
    assert page.batch_delete_button.isEnabled() is True

    page.table.item(0, CHECK_COLUMN).setCheckState(Qt.Unchecked)
    assert page.batch_delete_button.isEnabled() is False


def test_toolbar_contains_device_details_button():
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))

    assert page.detail_button.text() == "Device Details"


def test_toolbar_contains_test_connection_button():
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))

    assert page.test_connection_button.text() == "Test Connection"


def test_toolbar_test_connection_without_selection_shows_select_first(monkeypatch):
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda _parent, _title, text: messages.append(text))

    page.test_selected_device_connection()

    assert messages == ["Select a device first."]


def test_toolbar_test_connection_with_multiple_devices_uses_batch(monkeypatch):
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))
    captured = []
    monkeypatch.setattr(page, "batch_test_connections", lambda devices: captured.extend(devices))

    page.table._set_all_checked(True)
    page.test_selected_device_connection()

    assert [device.name for device in captured] == ["A", "B"]


def test_top_toolbar_omits_edit_delete_and_contains_batch_refresh_details():
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))
    top_buttons = [button.text() for button in page.findChildren(QPushButton) if button.parent() is page]

    assert "Edit" not in top_buttons
    assert "Delete" not in top_buttons
    assert page.batch_refresh_details_button.text() == "Batch Refresh Details"


def test_same_device_detail_window_is_created_once(monkeypatch):
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))
    created = []

    class FakeDetail:
        def __init__(self, *args):
            created.append(self)

        def show(self):
            pass

        def raise_(self):
            pass

        def activateWindow(self):
            pass

        @property
        def destroyed(self):
            class Signal:
                def connect(self, _callback):
                    pass

            return Signal()

    monkeypatch.setattr("netconsole.ui.pages.device_management_page.DeviceDetailDialog", FakeDetail)
    monkeypatch.setattr("netconsole.ui.pages.device_management_page.window_manager.register_child_window", lambda *_args, **_kwargs: None)

    page.show_device_detail(1)
    page.show_device_detail(1)

    assert len(created) == 1


def test_detail_window_removed_after_close_allows_recreate(monkeypatch):
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))
    removed = []
    monkeypatch.setattr("netconsole.ui.pages.device_management_page.window_manager.unregister_child_window", lambda window: removed.append(window))
    dialog = object()
    page.detail_dialogs["device-1"] = dialog

    page._remove_detail_dialog("device-1", dialog)

    assert page.detail_dialogs == {}
    assert removed == [dialog]


def test_toolbar_detail_without_selection_shows_select_first(monkeypatch):
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda _parent, _title, text: messages.append(text))

    page.show_selected_device_detail()

    assert messages == ["Select a device first."]


def test_batch_refresh_details_without_selection_shows_select_first(monkeypatch):
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda _parent, _title, text: messages.append(text))

    page.batch_refresh_details()

    assert messages == ["Select a device first."]


def test_device_detail_dialog_title_includes_device_name_and_empty_hint(tmp_path):
    app()
    database = Database(tmp_path / "devices.db")
    database.initialize()
    dialog = DeviceDetailDialog(
        I18n("en_US"),
        DeviceFactRepository(database),
        Device(name="Core", device_uuid="device-1"),
    )

    labels = [label.text() for label in dialog.findChildren(QLabel)]
    assert dialog.windowTitle() == "Device Details - Core"
    assert [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())] == [
        "Overview",
        "Interfaces",
        "Optical Modules",
        "LLDP Neighbors",
    ]
    assert any("Demo data is generated only when the demo database is first created" in text for text in labels)


def test_device_detail_dialog_has_refresh_button(tmp_path):
    app()
    database = Database(tmp_path / "devices.db")
    database.initialize()
    dialog = DeviceDetailDialog(
        I18n("en_US"),
        DeviceFactRepository(database),
        Device(name="Core", device_uuid="device-1"),
    )

    assert dialog.refresh_button.text() == "Refresh"


def test_device_detail_overview_fields_are_complete():
    assert [field for _label_key, field in OVERVIEW_FIELDS] == [
        "sysname",
        "model",
        "serial_number",
        "software_version",
        "bootrom_version",
        "vendor",
        "uptime",
        "collected_at",
        "raw_log_path",
    ]


def test_device_detail_interface_columns_are_complete():
    assert [field for _label_key, field in INTERFACE_COLUMNS] == [
        "interface_name",
        "link_status",
        "protocol_status",
        "speed",
        "duplex",
        "interface_type",
        "port_status",
        "pvid",
        "description",
        "ip_address",
        "mac_address",
        "vlan",
        "collected_at",
    ]


def test_device_detail_optical_module_columns_are_complete():
    assert [field for _label_key, field in OPTICAL_MODULE_COLUMNS] == [
        "interface_name",
        "status",
        "rx_power",
        "tx_power",
        "temperature",
        "voltage",
        "bias_current",
        "rx_low_alarm",
        "rx_high_alarm",
        "tx_low_alarm",
        "tx_high_alarm",
        "rx_low_warning",
        "rx_high_warning",
        "tx_low_warning",
        "tx_high_warning",
        "module_model",
        "module_serial_number",
        "module_vendor",
        "wavelength",
        "transmission_distance",
        "connector_type",
        "collected_at",
    ]


def test_device_detail_lldp_columns_are_complete():
    assert [field for _label_key, field in LLDP_COLUMNS] == [
        "local_interface",
        "neighbor_sysname",
        "neighbor_mac",
        "neighbor_interface",
        "collected_at",
    ]


def test_device_detail_long_interface_columns_have_minimum_widths():
    interface_widths = _column_min_widths(INTERFACE_COLUMNS)
    optical_widths = _column_min_widths(OPTICAL_MODULE_COLUMNS)
    lldp_widths = _column_min_widths(LLDP_COLUMNS)

    assert interface_widths[0] >= 180
    assert optical_widths[0] >= 180
    assert lldp_widths[0] >= 180
    assert lldp_widths[3] >= 180


def test_toolbar_edit_without_selection_shows_select_first(monkeypatch):
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda _parent, _title, text: messages.append(text))

    page.edit_device()

    assert messages == ["Select a device first."]


def test_toolbar_edit_with_multiple_checked_devices_shows_single_edit_message(monkeypatch):
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda _parent, _title, text: messages.append(text))

    page.table._set_all_checked(True)
    page.edit_device()

    assert messages == ["Select one device to edit."]
