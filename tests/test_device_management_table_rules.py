import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from netconsole.core.i18n import I18n
from netconsole.models.device import Device
from netconsole.ui.pages.device_management_page import DeviceManagementPage, choose_devices_for_export, delete_device_ids
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
        "tags",
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

    action_widget = table.cellWidget(0, 8)
    buttons = action_widget.findChildren(QPushButton)
    buttons[1].click()

    assert edited == [1]


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
