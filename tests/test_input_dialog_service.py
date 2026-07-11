from __future__ import annotations

import shiboken6
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QLineEdit

from netconsole.ui.dialogs.input_dialog_service import InputDialog


def app() -> QApplication:
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication([])
    return instance


def test_get_item_caches_value_before_dialog_children_are_deleted(monkeypatch):
    app()
    saw_delete_on_close = []

    def fake_exec(dialog: QDialog):
        combo = dialog.findChild(QComboBox)
        buttons = dialog.findChild(QDialogButtonBox)
        assert combo is not None
        assert buttons is not None
        combo.setCurrentIndex(1)
        saw_delete_on_close.append(dialog.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose))
        buttons.accepted.emit()
        shiboken6.delete(combo)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)

    value, accepted = InputDialog.getItem(None, "切换局点", "请选择局点", ["A", "B"], 0, False)

    assert value == "B"
    assert accepted is True
    assert saw_delete_on_close == [False]


def test_get_text_caches_value_before_dialog_children_are_deleted(monkeypatch):
    app()

    def fake_exec(dialog: QDialog):
        edit = dialog.findChild(QLineEdit)
        buttons = dialog.findChild(QDialogButtonBox)
        assert edit is not None
        assert buttons is not None
        edit.setText("新名称")
        buttons.accepted.emit()
        shiboken6.delete(edit)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)

    value, accepted = InputDialog.getText(None, "新建局点", "局点名称", text="旧名称")

    assert value == "新名称"
    assert accepted is True


def test_get_double_caches_value_before_dialog_children_are_deleted(monkeypatch):
    app()

    def fake_exec(dialog: QDialog):
        spin = dialog.findChild(QDoubleSpinBox)
        buttons = dialog.findChild(QDialogButtonBox)
        assert spin is not None
        assert buttons is not None
        spin.setValue(12.5)
        buttons.accepted.emit()
        shiboken6.delete(spin)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)

    value, accepted = InputDialog.getDouble(None, "设置比例尺", "距离", 1.0, 0.0, 100.0, 1)

    assert value == 12.5
    assert accepted is True
