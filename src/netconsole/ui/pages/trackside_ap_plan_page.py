from __future__ import annotations

from netconsole.ui.dialogs.message_service import MessageBox
from datetime import datetime
from pathlib import Path
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from netconsole.core import app_logger
from netconsole.core.i18n import I18n
from netconsole.repositories.ac_repository import AcRepository, TRACKSIDE_AP_PLAN_MODE
from netconsole.services.background_job import BackgroundJob
from netconsole.services.background_process_manager import BackgroundProcessManager
from netconsole.services.export.export_task_builders import repository_query_source, table_xlsx_source_spec, table_xlsx_spec
from netconsole.services.trackside_ap_business import parse_vlan_set
from netconsole.services.trackside_ap_plan_io import (
    MASK_ERROR_TEXT,
    TRACKSIDE_PLAN_COLUMN_WIDTHS,
    TRACKSIDE_PLAN_COLUMNS,
    TRACKSIDE_PLAN_HEADERS,
    _dedupe_station_rows,
    _dotted_netmask_to_prefix,
    _parse_mask_length,
    _valid_ipv4,
    _valid_ipv4_or_placeholder,
    export_trackside_plan_xlsx,
    read_trackside_plan_file,
)
from netconsole.ui.export_action_helper import submit_export_task
from netconsole.ui.render.table_render_engine import apply_table_style, set_table_column_fields
from netconsole.ui.shell.fluent_bridge import FIF
from netconsole.ui.table_utils import attach_table_context_menu, auto_fit_table_columns, configure_readable_table_columns


def _set_button_icon(button: QPushButton, icon: object | None) -> None:
    if icon is None:
        return
    icon_factory = getattr(icon, "icon", None)
    resolved_icon = icon_factory() if callable(icon_factory) else icon
    try:
        button.setIcon(resolved_icon)
    except TypeError:
        pass


class TracksideApPlanPage(QWidget):
    plan_saved = Signal()

    def __init__(self, repository: AcRepository, i18n: I18n, site_name: str) -> None:
        super().__init__()
        self.repository = repository
        self.i18n = i18n
        self.site_name = site_name
        self.table = QTableWidget()
        self.add_button = QPushButton()
        self.delete_button = QPushButton()
        self.save_button = QPushButton()
        self.import_button = QPushButton()
        self.export_button = QPushButton()
        self.template_button = QPushButton()
        self.refresh_button = QPushButton()
        self.background_manager = BackgroundProcessManager(self)
        self.background_manager.finished.connect(self._background_finished)
        self.background_manager.failed.connect(self._background_failed)
        self._jobs: dict[str, str] = {}
        self._busy = False
        self._dirty = False
        self._build_ui()
        self.retranslate()
        self.refresh()

    def _build_ui(self) -> None:
        actions = QHBoxLayout()
        for button in (self.add_button, self.delete_button, self.save_button, self.import_button, self.export_button, self.template_button, self.refresh_button):
            actions.addWidget(button)
        actions.addStretch(1)

        self.table.setColumnCount(len(TRACKSIDE_PLAN_COLUMNS))
        set_table_column_fields(self.table, [field for _key, field in TRACKSIDE_PLAN_COLUMNS])
        apply_table_style(self.table)
        configure_readable_table_columns(self.table)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        attach_table_context_menu(self.table, self.i18n.language, include_history=False)
        self._apply_column_layout()

        layout = QVBoxLayout(self)
        layout.addLayout(actions)
        layout.addWidget(self.table, 1)

        self.add_button.clicked.connect(self.add_row)
        self.delete_button.clicked.connect(self.delete_selected)
        self.save_button.clicked.connect(self.save_plan)
        self.import_button.clicked.connect(self.import_plan)
        self.export_button.clicked.connect(self.export_plan)
        self.template_button.clicked.connect(self.download_template)
        self.refresh_button.clicked.connect(self.refresh)
        self.table.itemChanged.connect(self._mark_dirty)

    def retranslate(self) -> None:
        self.add_button.setText(self.i18n.t("ac.trackside_plan.add_row"))
        self.delete_button.setText(self.i18n.t("ac.trackside_plan.delete_selected"))
        self.save_button.setText(self.i18n.t("ac.trackside_plan.save"))
        self.import_button.setText(self.i18n.t("ac.trackside_plan.import"))
        self.export_button.setText(self.i18n.t("ac.trackside_plan.export"))
        self.template_button.setText(self.i18n.t("ac.trackside_plan.template"))
        self.refresh_button.setText(self.i18n.t("details.refresh"))
        self._apply_button_icons()
        self.table.setHorizontalHeaderLabels([self.i18n.t(key) for key, _field in TRACKSIDE_PLAN_COLUMNS])

    def _apply_button_icons(self) -> None:
        button_icons = (
            (self.add_button, FIF.ADD),
            (self.delete_button, FIF.DELETE),
            (self.save_button, FIF.SAVE),
            (self.import_button, FIF.DOWNLOAD),
            (self.export_button, FIF.SHARE),
            (self.template_button, FIF.CLOUD_DOWNLOAD),
            (self.refresh_button, FIF.SYNC),
        )
        for button, icon in button_icons:
            _set_button_icon(button, icon)

    def refresh(self) -> None:
        if self._busy:
            return
        if not self._confirm_discard_or_save_changes():
            return
        self.reload_plan_table()

    def add_row(self) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        for column in range(len(TRACKSIDE_PLAN_COLUMNS)):
            self.table.setItem(row, column, self._make_item(""))
        self._apply_column_layout()
        self._dirty = True

    def delete_selected(self) -> None:
        for row in sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)
            self._dirty = True

    def save_plan(self) -> bool:
        if self._busy:
            return False
        try:
            rows = self._read_table_rows()
        except ValueError as exc:
            MessageBox.warning(self, self.i18n.t("ac.trackside_plan.validation_failed"), str(exc))
            return False
        for row in rows:
            app_logger.log_info(
                "TRACKSIDE_AP_PLAN_SAVED",
                f"保存轨旁AP规划：station={row.get('station_name')}, ap_count={row.get('ap_count')}, vlan={row.get('ap_management_vlans')}",
            )
        self._start_job("trackside_ap_plan_save", {"rows": rows})
        return True

    def import_plan(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.i18n.t("ac.trackside_plan.import"), "", "Excel/CSV (*.xlsx *.csv)")
        if not path:
            return
        self._start_job("trackside_ap_plan_import", {"path": path})

    def _start_job(self, task_type: str, params: dict[str, object] | None = None) -> None:
        if self._busy:
            return
        self._set_busy(True)
        job_id = self.background_manager.start_job(
            BackgroundJob(
                task_type=task_type,
                params={
                    "db_path": str(self.repository.database.path),
                    "site_name": self.site_name,
                    "mode": TRACKSIDE_AP_PLAN_MODE,
                    **dict(params or {}),
                },
            )
        )
        self._jobs[job_id] = task_type

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for button in (self.add_button, self.delete_button, self.save_button, self.import_button, self.refresh_button):
            button.setEnabled(not busy)

    def _background_finished(self, event: dict) -> None:
        task_type = self._jobs.pop(str(event.get("job_id") or ""), "")
        self._set_busy(False)
        result = dict(event.get("result") or {})
        if task_type == "trackside_ap_plan_refresh":
            self._set_rows([dict(row) for row in result.get("rows") or [] if isinstance(row, dict)])
            self._dirty = False
            return
        if task_type in {"trackside_ap_plan_import", "trackside_ap_plan_save"}:
            app_logger.log_info("TRACKSIDE_AP_PLAN_SAVED", f"task={task_type}, count={result.get('count', 0)}")
            self._dirty = False
            self.plan_saved.emit()
            self.reload_plan_table()

    def _background_failed(self, event: dict) -> None:
        self._jobs.pop(str(event.get("job_id") or ""), None)
        self._set_busy(False)
        MessageBox.warning(self, self.i18n.t("ac.trackside_plan.validation_failed"), str(event.get("message") or event.get("error") or "后台任务失败"))

    def export_plan(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, self.i18n.t("ac.trackside_plan.export"), self._default_export_name(), "Excel (*.xlsx)")
        if not path:
            return
        submit_export_task(
            self,
            table_xlsx_source_spec(
                Path(path),
                columns=[{"key": field, "title": TRACKSIDE_PLAN_HEADERS[index], "width": TRACKSIDE_PLAN_COLUMN_WIDTHS.get(field)} for index, (_key, field) in enumerate(TRACKSIDE_PLAN_COLUMNS)],
                source=repository_query_source(
                    db_path=self.repository.database.path,
                    repository="ac_repository",
                    method="list_trackside_ap_plan",
                    filters={"mode": TRACKSIDE_AP_PLAN_MODE},
                ),
                sheet_name="轨旁AP规划",
                title=self.i18n.t("ac.trackside_plan.export"),
            ),
            success_title=self.i18n.t("ac.trackside_plan.export"),
        )

    def download_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, self.i18n.t("ac.trackside_plan.template"), self._default_export_name(template=True), "Excel (*.xlsx)")
        if not path:
            return
        submit_export_task(
            self,
            table_xlsx_spec(
                Path(path),
                columns=[{"key": field, "title": TRACKSIDE_PLAN_HEADERS[index], "width": TRACKSIDE_PLAN_COLUMN_WIDTHS.get(field)} for index, (_key, field) in enumerate(TRACKSIDE_PLAN_COLUMNS)],
                rows=[],
                sheet_name="轨旁AP规划",
                title=self.i18n.t("ac.trackside_plan.template"),
                allow_inline_rows=True,
                inline_reason="轨旁 AP 规划下载空白静态模板",
            ),
            success_title=self.i18n.t("ac.trackside_plan.template"),
        )

    def reload_plan_table(self) -> None:
        self._start_job("trackside_ap_plan_refresh")

    def _set_rows(self, rows: list[dict[str, object | None]]) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, (_key, field) in enumerate(TRACKSIDE_PLAN_COLUMNS):
                self.table.setItem(row_index, column_index, self._make_item(str(row.get(field) or "")))
            app_logger.log_info(
                "TRACKSIDE_AP_PLAN_LOADED",
                f"加载轨旁AP规划：station={row.get('station_name')}, ap_count={row.get('ap_count')}, vlan={row.get('ap_management_vlans')}",
            )
        self.table.blockSignals(False)
        auto_fit_table_columns(
            self.table,
            min_widths={index: min(120, width) for index, width in enumerate(TRACKSIDE_PLAN_COLUMN_WIDTHS.values())},
            max_widths={index: max(220, width) for index, width in enumerate(TRACKSIDE_PLAN_COLUMN_WIDTHS.values())},
        )

    def _apply_column_layout(self) -> None:
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.Interactive)
        fields = [field for _key, field in TRACKSIDE_PLAN_COLUMNS]
        for column, field in enumerate(fields):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
            self.table.setColumnWidth(column, TRACKSIDE_PLAN_COLUMN_WIDTHS[field])

    def _read_table_rows(self) -> list[dict[str, object | None]]:
        rows = []
        for row_index in range(self.table.rowCount()):
            row = {field: (self.table.item(row_index, column_index).text() if self.table.item(row_index, column_index) else "") for column_index, (_key, field) in enumerate(TRACKSIDE_PLAN_COLUMNS)}
            if not any(str(value or "").strip() for value in row.values()):
                continue
            row["sort_order"] = len(rows)
            rows.append(row)
        self._validate_rows(rows)
        return _dedupe_station_rows(rows)

    def _validate_rows(self, rows: list[dict[str, object | None]]) -> None:
        seen: set[str] = set()
        for index, row in enumerate(rows, start=2):
            station = str(row.get("station_name") or "").strip()
            if not station:
                raise ValueError(f"第{index}行 车站名称：必填")
            if station.casefold() in seen:
                continue
            seen.add(station.casefold())
            try:
                row["ap_count"] = int(str(row.get("ap_count") or "0").strip())
            except ValueError:
                raise ValueError(f"第{index}行 AP数量：必须是整数") from None
            if int(row["ap_count"]) < 0:
                raise ValueError(f"第{index}行 AP数量：必须是非负整数")
            mask_length = _parse_mask_length(row.get("mask_length"))
            if mask_length is None and str(row.get("mask_length") or "").strip():
                raise ValueError(f"第{index}行 掩码：{MASK_ERROR_TEXT}")
            row["mask_length"] = mask_length
            vlans = parse_vlan_set(row.get("ap_management_vlans"))
            if not vlans:
                raise ValueError(f"第{index}行 AP管理VLAN：必填")
            row["station_name"] = station
            row["ap_management_vlans"] = ",".join(str(vlan) for vlan in sorted(vlans))
            start = str(row.get("ap_start_address") or "").strip()
            gateway = str(row.get("ap_gateway") or "").strip()
            if start and not _valid_ipv4_or_placeholder(start):
                raise ValueError(f"第{index}行 AP起始地址：格式无效")
            if gateway and not _valid_ipv4(gateway):
                raise ValueError(f"第{index}行 AP网关：必须是IPv4")

    def _default_export_name(self, template: bool = False) -> str:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = "轨旁AP规划模板" if template else "轨旁AP规划"
        safe_site = re.sub(r'[\\/:*?"<>|]+', "_", str(self.site_name or "").strip()) or "site"
        return f"{safe_site}_{suffix}_{stamp}.xlsx"

    def _make_item(self, value: str) -> QTableWidgetItem:
        item = QTableWidgetItem(value)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        return item

    def _mark_dirty(self, _item: QTableWidgetItem) -> None:
        self._dirty = True

    def _confirm_discard_or_save_changes(self) -> bool:
        if not self._dirty:
            return True
        result = MessageBox.question(
            self,
            "轨旁AP规划",
            "当前轨旁AP规划有未保存修改，是否先保存？",
            MessageBox.StandardButton.Save | MessageBox.StandardButton.Discard | MessageBox.StandardButton.Cancel,
        )
        if result == MessageBox.StandardButton.Save:
            self.save_plan()
            return False
        if result == MessageBox.StandardButton.Cancel:
            return False
        return result == MessageBox.StandardButton.Discard
