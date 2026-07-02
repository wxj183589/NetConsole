from __future__ import annotations

import difflib
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from netconsole.core.i18n import I18n
from netconsole.services.config_lifecycle_service import clean_config_for_diff
from netconsole.ui.render.table_render_engine import apply_table_style


@dataclass(frozen=True)
class SideBySideDiffRow:
    left_line: int | None
    left_text: str
    status: str
    right_line: int | None
    right_text: str


class ConfigDiffViewer(QWidget):
    def __init__(self, i18n: I18n, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.raw_diff_text = ""
        self.summary_label = QLabel()
        self.table = QTableWidget(0, 5)
        self.table.setWordWrap(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        self.table.setVerticalScrollMode(QTableWidget.ScrollPerPixel)
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.table, 1)
        self.retranslate()

    def retranslate(self) -> None:
        self.table.setHorizontalHeaderLabels(
            [
                self.i18n.t("config_center.diff.left_line"),
                self.i18n.t("config_center.diff.left_text"),
                self.i18n.t("config_center.diff.status"),
                self.i18n.t("config_center.diff.right_line"),
                self.i18n.t("config_center.diff.right_text"),
            ]
        )

    def set_message(self, message: str) -> None:
        self.raw_diff_text = message
        self.summary_label.setText("")
        self.table.setRowCount(1)
        self.table.setSpan(0, 0, 1, 5)
        item = QTableWidgetItem(message)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        self.table.setItem(0, 0, item)
        apply_table_style(self.table)

    def set_diff(self, left_title: str, right_title: str, left_text: str, right_text: str, raw_diff: str = "") -> None:
        self.table.clearSpans()
        left_lines = clean_config_for_diff(left_text).splitlines()
        right_lines = clean_config_for_diff(right_text).splitlines()
        rows, added, deleted, modified_blocks = build_side_by_side_rows(left_lines, right_lines)
        self.raw_diff_text = raw_diff or "\n".join(
            difflib.unified_diff(left_lines, right_lines, fromfile=left_title, tofile=right_title, lineterm="")
        )
        self.summary_label.setText(
            self.i18n.t(
                "config_center.diff.summary",
                left=left_title,
                right=right_title,
                added=added,
                deleted=deleted,
                modified=modified_blocks,
            )
        )
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (
                "" if row.left_line is None else str(row.left_line),
                row.left_text,
                row.status,
                "" if row.right_line is None else str(row.right_line),
                row.right_text,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                item.setToolTip(value)
                if column in {0, 2, 3}:
                    item.setTextAlignment(Qt.AlignCenter)
                item.setBackground(_status_color(row.status))
                self.table.setItem(row_index, column, item)
        self.table.resizeColumnsToContents()
        apply_table_style(self.table)


def build_side_by_side_rows(left_lines: list[str], right_lines: list[str]) -> tuple[list[SideBySideDiffRow], int, int, int]:
    rows: list[SideBySideDiffRow] = []
    added = 0
    deleted = 0
    modified_blocks = 0
    matcher = difflib.SequenceMatcher(a=left_lines, b=right_lines)
    for tag, left_start, left_end, right_start, right_end in matcher.get_opcodes():
        left_block = left_lines[left_start:left_end]
        right_block = right_lines[right_start:right_end]
        if tag == "equal":
            for offset, (left, right) in enumerate(zip(left_block, right_block)):
                rows.append(SideBySideDiffRow(left_start + offset + 1, left, "=", right_start + offset + 1, right))
        elif tag == "delete":
            deleted += len(left_block)
            for offset, left in enumerate(left_block):
                rows.append(SideBySideDiffRow(left_start + offset + 1, left, "-", None, ""))
        elif tag == "insert":
            added += len(right_block)
            for offset, right in enumerate(right_block):
                rows.append(SideBySideDiffRow(None, "", "+", right_start + offset + 1, right))
        elif tag == "replace":
            modified_blocks += 1
            max_len = max(len(left_block), len(right_block))
            for offset in range(max_len):
                left_exists = offset < len(left_block)
                right_exists = offset < len(right_block)
                if left_exists and right_exists:
                    rows.append(SideBySideDiffRow(left_start + offset + 1, left_block[offset], "~", right_start + offset + 1, right_block[offset]))
                elif left_exists:
                    deleted += 1
                    rows.append(SideBySideDiffRow(left_start + offset + 1, left_block[offset], "-", None, ""))
                else:
                    added += 1
                    rows.append(SideBySideDiffRow(None, "", "+", right_start + offset + 1, right_block[offset]))
    return rows, added, deleted, modified_blocks


def _status_color(status: str) -> QColor:
    if status == "+":
        return QColor(225, 245, 232)
    if status == "-":
        return QColor(252, 228, 228)
    if status == "~":
        return QColor(255, 246, 204)
    return QColor(0, 0, 0, 0)
