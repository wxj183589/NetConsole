from __future__ import annotations

from netconsole.ui.dialogs.message_service import MessageBox
import ipaddress
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QRect, QSize, QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from netconsole.core.feature_flags import FeatureGate, default_feature_gate
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.services.export.export_task_builders import result_file_rows_source, table_csv_source_spec, table_xlsx_source_spec
from netconsole.services.network_tools.toolbox.fping_runner import discover_fping, scan_targets as scan_fping_targets
from netconsole.services.network_tools.toolbox.ip_calc import (
    TableResult,
    ipv4_calculate,
    ipv6_calculate,
    plan_vlsm,
    split_subnets,
    summarize_routes,
    wildcard_calculate,
)
from netconsole.services.network_tools.toolbox.ping_tools import run_batch_ping, run_single_ping, run_tcp_ping
from netconsole.services.external_tool_launcher import launch_ipop_as_admin
from netconsole.services.windows_network_manager import NetworkAdapterInfo, WindowsNetworkManager
from netconsole.ui.components.button_icons import apply_button_icon
from netconsole.ui.export_action_helper import submit_export_task
from netconsole.ui.table_utils import auto_fit_table_columns, configure_readable_table_columns, configure_readonly_table
from netconsole.ui.widgets.no_wheel import NoWheelSpinBox


DISPLAY_HEADERS = {
    "input": "输入",
    "network": "网络地址",
    "cidr": "CIDR",
    "broadcast": "广播地址",
    "netmask": "子网掩码",
    "prefix_length": "前缀长度",
    "prefix": "前缀长度",
    "wildcard": "反掩码",
    "total_addresses": "地址总数",
    "usable_hosts": "可用主机数",
    "first_usable": "首个可用地址",
    "last_usable": "最后可用地址",
    "ip_type": "地址类型",
    "class": "类别",
    "note": "说明",
    "compressed": "压缩格式",
    "exploded": "完整格式",
    "start": "起始地址",
    "end": "结束地址",
    "name": "名称",
    "requested_hosts": "需求主机数",
    "wasted_hosts": "剩余主机数",
    "index": "序号",
    "summary": "汇总网段",
    "range": "地址范围",
    "full_cover": "完整覆盖",
    "target": "目标",
    "resolved_ip": "解析地址",
    "status": "状态",
    "latency_ms": "延迟(ms)",
    "min_ms": "最小(ms)",
    "max_ms": "最大(ms)",
    "avg_ms": "平均(ms)",
    "packet_loss_percent": "丢包率(%)",
    "sent": "发送",
    "received": "接收",
    "timestamp": "时间",
    "error": "错误",
    "port": "端口",
    "order_index": "\u5e8f\u53f7",
    "destination_prefix": "\u76ee\u6807\u7f51\u7edc",
    "destination": "\u76ee\u6807\u7f51\u7edc",
    "next_hop": "\u4e0b\u4e00\u8df3/\u7f51\u5173",
    "interface_index": "接口索引",
    "interface_alias": "\u63a5\u53e3",
    "interface_ip": "接口地址",
    "metric": "\u8dc3\u70b9\u6570",
    "policy_store": "\u7b56\u7565\u5b58\u50a8",
    "source": "\u6765\u6e90",
    "on_link": "在链路上",
    "persistent": "\u6301\u4e45",
}

TOOLBOX_DIRECT_FILL_LIMIT = 200
TOOLBOX_FILL_BATCH_SIZE = 200
TOOLBOX_RESULT_DISPLAY_LIMIT = 2000
TOOLBOX_SYNC_CACHE_ROW_LIMIT = 200

STATUS_LABELS = {
    "ready": "就绪",
    "running": "执行中",
    "stopped": "已停止",
    "done": "完成",
    "failed": "失败",
    "online": "在线",
    "offline": "离线",
    "open": "端口开放",
    "closed": "端口关闭",
    "timeout": "超时",
    "unreachable": "不可达",
    "dns_failed": "DNS失败",
    "error": "错误",
    "unknown": "未知",
}

STATUS_COLORS = {
    "ready": "#94a3b8",
    "running": "#38bdf8",
    "stopped": "#f59e0b",
    "done": "#22c55e",
    "failed": "#ef4444",
}

STATUS_VALUE_COLORS = {
    "在线": "#22c55e",
    "端口开放": "#22c55e",
    "离线": "#ef4444",
    "端口关闭": "#ef4444",
    "失败": "#ef4444",
    "超时": "#f59e0b",
    "不可达": "#ef4444",
    "DNS失败": "#ef4444",
    "错误": "#ef4444",
    "执行中": "#38bdf8",
}


GRID_STATUS_LABELS = {
    "idle": "未测试",
    "scanning": "扫描中",
    "online": "在线",
    "offline": "离线",
    "timeout": "超时",
    "error": "失败",
    "disabled": "禁用",
}

GRID_STATUS_COLORS = {
    "idle": ("#111827", "#475569", "#cbd5e1"),
    "scanning": ("#0c4a6e", "#38bdf8", "#e0f2fe"),
    "online": ("#14532d", "#22c55e", "#dcfce7"),
    "offline": ("#7f1d1d", "#ef4444", "#fee2e2"),
    "timeout": ("#78350f", "#f59e0b", "#fffbeb"),
    "error": ("#7f1d1d", "#f43f5e", "#ffe4e6"),
    "disabled": ("#020617", "#1e293b", "#64748b"),
}


@dataclass
class NetworkPingHostResult:
    ip: str
    host_number: int
    in_range: bool = False
    status: str = "disabled"
    resolved_ip: str = ""
    latency_ms: object = None
    min_ms: object = None
    max_ms: object = None
    avg_ms: object = None
    packet_loss_percent: object = None
    sent: object = 0
    received: object = 0
    timestamp: str = ""
    error: str = ""


class IpStatusGridWidget(QWidget):
    hostClicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.hosts: dict[int, NetworkPingHostResult] = {}
        self.rects: dict[int, QRect] = {}
        self.selected_ip = ""
        self.hover_host: int | None = None
        self.message = "请输入 /24 或更小的 IPv4 网段。"
        self.setMouseTracking(True)
        self.setMinimumHeight(220)

    def set_hosts(self, hosts: list[NetworkPingHostResult], message: str = "") -> None:
        self.hosts = {item.host_number: item for item in hosts}
        self.selected_ip = ""
        self.message = message
        self.updateGeometry()
        self.update()

    def clear(self) -> None:
        self.hosts = {}
        self.rects = {}
        self.selected_ip = ""
        self.message = "请输入 /24 或更小的 IPv4 网段。"
        self.update()

    def update_host_status(self, ip: str, result: NetworkPingHostResult) -> None:
        host = result.host_number
        if host in self.hosts:
            self.hosts[host] = result
            self.update(self.rects.get(host, self.rect()))

    def select_ip(self, ip: str) -> None:
        self.selected_ip = ip
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(900, 260)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#0f172a"))
        if not self.hosts:
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(self.rect(), Qt.AlignCenter, self.message)
            return

        margin = 8
        gap = 4
        columns = max(16, min(32, (self.width() - margin * 2) // 30))
        cell_w = max(24, (self.width() - margin * 2 - gap * (columns - 1)) // columns)
        cell_h = 24
        self.rects = {}
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        for host in range(1, 256):
            row = (host - 1) // columns
            col = (host - 1) % columns
            rect = QRect(margin + col * (cell_w + gap), margin + row * (cell_h + gap), cell_w, cell_h)
            self.rects[host] = rect
            item = self.hosts.get(host)
            status = item.status if item else "disabled"
            fill, border, text = GRID_STATUS_COLORS.get(status, GRID_STATUS_COLORS["idle"])
            if self.hover_host == host and status != "disabled":
                border = "#e2e8f0"
            if item and item.ip == self.selected_ip:
                painter.setPen(QPen(QColor("#facc15"), 3))
                painter.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), 4, 4)
            painter.setPen(QPen(QColor(border), 1))
            painter.setBrush(QColor(fill))
            painter.drawRoundedRect(rect, 4, 4)
            painter.setPen(QColor(text))
            painter.drawText(rect, Qt.AlignCenter, str(host))

    def mouseMoveEvent(self, event) -> None:
        host = self._host_at(event.position().toPoint())
        if host != self.hover_host:
            self.hover_host = host
            self.update()
        if host and host in self.hosts:
            QToolTip.showText(event.globalPosition().toPoint(), self._tooltip(self.hosts[host]), self)
        else:
            QToolTip.hideText()

    def leaveEvent(self, _event) -> None:
        self.hover_host = None
        QToolTip.hideText()
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        host = self._host_at(event.position().toPoint())
        item = self.hosts.get(host or -1)
        if item and item.in_range:
            self.select_ip(item.ip)
            self.hostClicked.emit(item.ip)

    def _host_at(self, point) -> int | None:
        for host, rect in self.rects.items():
            if rect.contains(point):
                return host
        return None

    @staticmethod
    def _tooltip(item: NetworkPingHostResult) -> str:
        lines = [
            f"IP：{item.ip}",
            f"状态：{GRID_STATUS_LABELS.get(item.status, item.status)}",
        ]
        if item.latency_ms not in (None, ""):
            lines.append(f"延迟：{item.latency_ms} ms")
        if item.packet_loss_percent not in (None, ""):
            lines.append(f"丢包率：{item.packet_loss_percent}%")
        if item.timestamp:
            lines.append(f"时间：{item.timestamp}")
        if item.error:
            lines.append(f"错误：{item.error}")
        return "\n".join(lines)


class _Worker(QObject):
    finished = Signal(object, str, str)

    def __init__(self, fn: Callable[[], object], prefix: str) -> None:
        super().__init__()
        self.fn = fn
        self.prefix = prefix

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self.fn(), "", self.prefix)
        except Exception as exc:
            self.finished.emit(None, str(exc), self.prefix)


class ResultCacheWriteWorker(QThread):
    completed = Signal(int, object, int)
    failed = Signal(int, str)

    def __init__(self, generation: int, cache_dir: Path, prefix: str, rows: list[dict[str, object]], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.generation = generation
        self.cache_dir = Path(cache_dir)
        self.prefix = prefix
        self.rows = rows

    def run(self) -> None:
        try:
            path = write_result_cache_file(self.cache_dir, self.prefix, self.rows)
            self.completed.emit(self.generation, path, len(self.rows))
        except Exception as exc:
            self.failed.emit(self.generation, str(exc))


def write_result_cache_file(cache_dir: Path, prefix: str, rows: list[dict[str, object]]) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.jsonl"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str))
            handle.write("\n")
    return path


class ToolResultPanel(QGroupBox):
    def __init__(self, paths: PathResolver, site_name: str, export_prefix: str, parent: QWidget | None = None) -> None:
        super().__init__("结果", parent)
        self.paths = paths
        self.site_name = site_name
        self.export_prefix = export_prefix
        self.current_rows: list[dict[str, object]] = []
        self.current_headers: list[str] = []
        self.current_result_file: Path | None = None
        self._fill_generation = 0
        self._cache_generation = 0
        self._cache_worker: ResultCacheWriteWorker | None = None
        self._cache_pending = False
        self._cache_error = ""
        self._summary_base_lines: list[str] = []
        self._result_total_count = 0
        self._result_display_count = 0
        self._table_fill_pending = False

        self.status_label = QLabel()
        self.result_table = QTableWidget()
        configure_readonly_table(self.result_table)
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setMaximumHeight(96)
        self.export_csv_button = QPushButton("导出 CSV")
        self.export_xlsx_button = QPushButton("导出 XLSX")
        self.clear_button = QPushButton("清空")
        apply_button_icon(self.export_csv_button, "SHARE")
        apply_button_icon(self.export_xlsx_button, "SHARE")
        apply_button_icon(self.clear_button, "DELETE")

        for button in (self.export_csv_button, self.export_xlsx_button, self.clear_button):
            button.setMinimumWidth(92)
            button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        actions = QHBoxLayout()
        actions.addWidget(self.status_label, 1)
        actions.addWidget(self.export_csv_button)
        actions.addWidget(self.export_xlsx_button)
        actions.addWidget(self.clear_button)
        layout.addLayout(actions)
        layout.addWidget(self.result_table, 1)
        layout.addWidget(self.summary_text)

        self.export_csv_button.clicked.connect(lambda: self.export_current("csv"))
        self.export_xlsx_button.clicked.connect(lambda: self.export_current("xlsx"))
        self.clear_button.clicked.connect(self.clear_results)
        self.set_status("ready")
        self._sync_export_buttons()

    def set_site(self, site_name: str) -> None:
        self.site_name = site_name

    def set_status(self, status: str, message: str = "") -> None:
        label = STATUS_LABELS.get(status, status)
        self.status_label.setText(f"{label}：{message}" if message else label)
        color = STATUS_COLORS.get(status, STATUS_COLORS["ready"])
        self.status_label.setStyleSheet(f"color: {color}; font-weight: 600;")

    def show_error(self, message: str) -> None:
        self.set_status("failed", message)
        self.summary_text.setPlainText(message)

    def show_table_result(self, result: TableResult, prefix: str) -> None:
        if result.errors:
            self.export_prefix = prefix
            self.show_rows([], prefix, {"错误": "\n".join(result.errors)})
            self.show_error("\n".join(result.errors))
            return
        self.show_rows(result.rows, prefix, result.summary)

    def show_rows(self, rows: list[object], prefix: str, summary: dict[str, object] | None = None, *, summary_title: str = "") -> None:
        self.export_prefix = prefix
        normalized = [_display_row(row) for row in rows]
        self.current_rows = normalized
        self._result_total_count = len(normalized)
        headers: list[str] = []
        for row in normalized:
            for key in row:
                if key not in headers:
                    headers.append(key)
        self.current_headers = headers
        self.current_result_file = None
        self._prepare_result_cache(prefix, normalized) if headers else self._reset_result_cache_state()
        display_rows = normalized[:TOOLBOX_RESULT_DISPLAY_LIMIT]
        self._result_display_count = len(display_rows)
        hidden_count = max(0, len(normalized) - len(display_rows))
        self._fill_generation += 1
        generation = self._fill_generation

        self.result_table.setUpdatesEnabled(False)
        try:
            self.result_table.clearContents()
            self.result_table.setColumnCount(len(headers))
            # UI 表格只承载硬上限内的可见结果；完整运行结果写入 JSONL 缓存供导出进程读取。
            self.result_table.setRowCount(len(display_rows))
            self.result_table.setHorizontalHeaderLabels(headers)
        finally:
            self.result_table.setUpdatesEnabled(True)

        summary_lines = [summary_title] if summary_title else []
        if summary:
            summary_lines.extend(f"{key}: {_stringify(value)}" for key, value in summary.items())
        if hidden_count:
            summary_lines.append(f"表格仅显示前 {len(display_rows)} 条，导出将读取缓存文件中的 {len(normalized)} 条完整结果。")
        self._summary_base_lines = summary_lines
        self._update_summary_cache_status()
        self.result_table.setToolTip(
            f"当前表格仅显示前 {len(display_rows)} 条；如需完整数据，请直接导出。"
            if hidden_count
            else ""
        )
        if len(display_rows) <= TOOLBOX_DIRECT_FILL_LIMIT:
            self._fill_table_rows(display_rows, headers, 0, len(display_rows))
            auto_fit_table_columns(self.result_table, max_rows=200)
            self._table_fill_pending = False
            self._sync_result_status()
            return

        self._table_fill_pending = True
        self.set_status("loading", f"正在填充 0/{len(display_rows)} 行")

        def fill_next(start: int = 0) -> None:
            if generation != self._fill_generation:
                return
            end = min(start + TOOLBOX_FILL_BATCH_SIZE, len(display_rows))
            self._fill_table_rows(display_rows, headers, start, end)
            self.set_status("loading", f"正在填充 {end}/{len(display_rows)} 行")
            if end < len(display_rows):
                QTimer.singleShot(0, lambda: fill_next(end))
                return
            auto_fit_table_columns(self.result_table, max_rows=200)
            self._table_fill_pending = False
            self._sync_result_status()

        QTimer.singleShot(0, fill_next)

    def _fill_table_rows(self, rows: list[dict[str, object]], headers: list[str], start: int, end: int) -> None:
        self.result_table.setUpdatesEnabled(False)
        try:
            for row_index in range(start, end):
                row = rows[row_index]
                row_color = STATUS_VALUE_COLORS.get(str(row.get("状态", "")))
                for column, header in enumerate(headers):
                    item = QTableWidgetItem(_stringify(row.get(header, "")))
                    if row_color:
                        item.setForeground(QColor(row_color))
                    self.result_table.setItem(row_index, column, item)
        finally:
            self.result_table.setUpdatesEnabled(True)

    def _prepare_result_cache(self, prefix: str, rows: list[dict[str, object]]) -> None:
        self._cache_generation += 1
        generation = self._cache_generation
        self._cache_pending = False
        self._cache_error = ""
        self.current_result_file = None
        self._sync_export_buttons()
        if len(rows) <= TOOLBOX_SYNC_CACHE_ROW_LIMIT:
            try:
                self.current_result_file = write_result_cache_file(self.paths.runtime_cache_dir / "toolbox_results", prefix, rows)
            except Exception as exc:
                self._cache_error = str(exc)
            self._sync_export_buttons()
            return
        self._cache_pending = True
        worker = ResultCacheWriteWorker(generation, self.paths.runtime_cache_dir / "toolbox_results", prefix, rows, self)
        self._cache_worker = worker
        worker.completed.connect(self._result_cache_written)
        worker.failed.connect(self._result_cache_failed)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(lambda worker=worker: self._cache_worker_finished(worker))
        worker.start()
        self._sync_export_buttons()

    def _reset_result_cache_state(self) -> None:
        self._cache_generation += 1
        self._cache_pending = False
        self._cache_error = ""
        self.current_result_file = None
        self._sync_export_buttons()

    def _result_cache_written(self, generation: int, path: object, _row_count: int) -> None:
        if generation != self._cache_generation:
            return
        self.current_result_file = Path(path)
        self._cache_pending = False
        self._cache_error = ""
        self._sync_export_buttons()
        self._update_summary_cache_status()
        self._sync_result_status()

    def _result_cache_failed(self, generation: int, message: str) -> None:
        if generation != self._cache_generation:
            return
        self.current_result_file = None
        self._cache_pending = False
        self._cache_error = message or "未知错误"
        self._sync_export_buttons()
        self._update_summary_cache_status()
        self._sync_result_status()

    def _cache_worker_finished(self, worker: ResultCacheWriteWorker) -> None:
        if self._cache_worker is worker:
            self._cache_worker = None

    def _sync_export_buttons(self) -> None:
        enabled = bool(self.current_headers) and not self._cache_pending and self.current_result_file is not None and self.current_result_file.is_file()
        self.export_csv_button.setEnabled(enabled)
        self.export_xlsx_button.setEnabled(enabled)

    def _update_summary_cache_status(self) -> None:
        lines = list(self._summary_base_lines)
        if self._cache_pending:
            lines.append("导出缓存正在后台写入，完成前导出按钮不可用。")
        elif self._cache_error:
            lines.append(f"缓存写入失败，无法导出完整结果：{self._cache_error}")
        elif self.current_headers and self.current_result_file is not None:
            lines.append(f"导出缓存已就绪：{len(self.current_rows)} 条。")
        self.summary_text.setPlainText("\n".join(lines))

    def _sync_result_status(self) -> None:
        if self._table_fill_pending:
            return
        message = self._result_status_text(self._result_total_count, self._result_display_count)
        if self._cache_pending:
            self.set_status("loading", f"{message}，正在写入导出缓存")
        elif self._cache_error:
            self.set_status("failed", "缓存写入失败，无法导出完整结果")
        else:
            self.set_status("done", message)

    @staticmethod
    def _result_status_text(total_count: int, display_count: int) -> str:
        if total_count > display_count:
            return f"显示 {display_count}/{total_count} 条，导出读取完整缓存"
        return f"{total_count} 条"

    def export_current(self, suffix: str) -> None:
        if not self.current_headers:
            MessageBox.information(self, "导出", "没有可导出的结果。")
            return
        if self._cache_pending:
            MessageBox.warning(self, "导出", "结果缓存仍在写入，请稍后导出。")
            return
        if self._cache_error:
            MessageBox.warning(self, "导出", "缓存写入失败，无法导出完整结果。")
            return
        if self.current_result_file is None or not self.current_result_file.is_file():
            MessageBox.warning(self, "导出", "未找到运行结果缓存文件，请重新生成结果后再导出。")
            return
        export_dir = self.paths.toolbox_outputs_dir(self.site_name)
        default = export_dir / f"{self.export_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{suffix}"
        filter_text = "Excel (*.xlsx)" if suffix == "xlsx" else "CSV (*.csv)"
        selected, _filter = QFileDialog.getSaveFileName(self, "导出结果", str(default), filter_text)
        if not selected:
            return
        path = Path(selected)
        columns = [{"key": header, "title": header, "text": True} for header in self.current_headers]
        source = result_file_rows_source(self.current_result_file)
        if suffix == "xlsx":
            spec = table_xlsx_source_spec(
                path,
                columns=columns,
                source=source,
                sheet_name="结果",
                title="导出结果",
                open_dir_on_success=True,
            )
        else:
            spec = table_csv_source_spec(
                path,
                columns=columns,
                source=source,
                title="导出结果",
                open_dir_on_success=True,
            )
        submit_export_task(self, spec, success_title="导出结果", paths=self.paths)

    def clear_results(self) -> None:
        self.current_rows = []
        self.current_headers = []
        self.current_result_file = None
        self._fill_generation += 1
        self._reset_result_cache_state()
        self._summary_base_lines = []
        self._result_total_count = 0
        self._result_display_count = 0
        self._table_fill_pending = False
        self.result_table.setUpdatesEnabled(False)
        try:
            self.result_table.clearContents()
            self.result_table.setRowCount(0)
            self.result_table.setColumnCount(0)
        finally:
            self.result_table.setUpdatesEnabled(True)
        self.summary_text.clear()
        self.set_status("ready")

    def select_row_by_value(self, header: str, value: str) -> bool:
        if header not in self.current_headers:
            return False
        column = self.current_headers.index(header)
        for row in range(self.result_table.rowCount()):
            item = self.result_table.item(row, column)
            if item and item.text() == value:
                self.result_table.selectRow(row)
                self.result_table.scrollToItem(item)
                return True
        return False

    def select_row_containing(self, value: str) -> bool:
        for row in range(self.result_table.rowCount()):
            for column in range(self.result_table.columnCount()):
                item = self.result_table.item(row, column)
                if item and item.text() == value:
                    self.result_table.selectRow(row)
                    self.result_table.scrollToItem(item)
                    return True
        return False


class NetworkToolboxPage(QWidget):
    async_result_ready = Signal(object, str, str)
    network_ping_progress_ready = Signal(dict)

    def __init__(
        self,
        i18n: I18n,
        site_name: str,
        paths: PathResolver,
        network_manager: WindowsNetworkManager | None = None,
        feature_gate: FeatureGate | None = None,
    ) -> None:
        super().__init__()
        self.i18n = i18n
        self.site_name = site_name
        self.paths = paths
        self.feature_gate = feature_gate or default_feature_gate()
        self.network_manager = network_manager or WindowsNetworkManager()
        self.thread: QThread | None = None
        self.worker: _Worker | None = None
        self.active_panel: ToolResultPanel | None = None
        self.result_panels: list[ToolResultPanel] = []
        self.adapters: list[NetworkAdapterInfo] = []
        self.current_network_ping_results: dict[str, NetworkPingHostResult] = {}
        self.network_ping_stop_requested = False
        self._destroyed = False

        self.tabs = QTabWidget()
        self.ip_tabs = QTabWidget()
        self.ping_tabs = QTabWidget()

        self._build_ui()
        self.async_result_ready.connect(self._async_finished, Qt.QueuedConnection)
        self.network_ping_progress_ready.connect(self._network_ping_progress, Qt.QueuedConnection)
        self.destroyed.connect(self._on_destroyed)

    def set_site(self, site_name: str) -> None:
        self.site_name = site_name
        for panel in self.result_panels:
            panel.set_site(site_name)

    def retranslate(self) -> None:
        pass

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        self.ipop_button = QPushButton("管理员启动 IPOP v4.1")
        self.ipop_button.setVisible(self.feature_gate.is_visible("network_tools.ipop"))
        self.ipop_button.setEnabled(self.feature_gate.is_enabled("network_tools.ipop"))
        self.ipop_button.clicked.connect(self.launch_ipop)
        apply_button_icon(self.ipop_button, "PLAY")
        root.addWidget(self.ipop_button, 0, Qt.AlignmentFlag.AlignLeft)
        root.addWidget(self.tabs)
        self.tabs.addTab(self._ip_page(), "IP 计算")
        self.tabs.addTab(self._connectivity_page(), "连通性检测")

    def launch_ipop(self) -> None:
        result = launch_ipop_as_admin(self.paths)
        if result.success:
            MessageBox.information(self, "IPOP v4.1", result.message)
        else:
            MessageBox.warning(self, "IPOP v4.1", result.message)

    def _ip_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self.ip_tabs)
        self.ip_tabs.addTab(self._ipv4_tab(), "IPv4")
        self.ip_tabs.addTab(self._ipv6_tab(), "IPv6")
        self.ip_tabs.addTab(self._vlsm_tab(), "VLSM")
        self.ip_tabs.addTab(self._subnet_split_tab(), "子网划分")
        self.ip_tabs.addTab(self._route_summary_tab(), "路由汇总")
        self.ip_tabs.addTab(self._wildcard_tab(), "反掩码")
        return page

    def _connectivity_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(self.ping_tabs)
        self.ping_tabs.addTab(self._single_ping_tab(), "单个 Ping")
        self.ping_tabs.addTab(self._continuous_ping_tab(), "持续 Ping")
        self.ping_tabs.addTab(self._batch_ping_tab(), "批量 Ping")
        self.ping_tabs.addTab(self._network_ping_tab(), "网段 Ping")
        self.ping_tabs.addTab(self._tcp_ping_tab(), "TCP Ping")
        return page

    def _tool_page(self, prefix: str) -> tuple[QWidget, QGridLayout, QHBoxLayout, ToolResultPanel]:
        page = self._scrollable_tab()
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 24, 10)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignTop)
        page.setWidget(content)

        params_box = QGroupBox("\u53c2\u6570")
        params = QGridLayout(params_box)
        params.setContentsMargins(12, 16, 12, 12)
        params.setSpacing(8)
        params.setColumnStretch(1, 1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)

        panel = ToolResultPanel(self.paths, self.site_name, prefix)
        panel.setMinimumHeight(360)
        panel.result_table.setMinimumHeight(240)
        self.result_panels.append(panel)

        layout.addWidget(params_box)
        layout.addLayout(actions)
        layout.addWidget(panel)
        layout.addStretch(1)
        return page, params, actions, panel

    def _scrollable_tab(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet(
            """
            QScrollArea { background: transparent; border: none; }
            QScrollArea > QWidget > QWidget { background: transparent; }
            """
        )
        return scroll

    def _add_row(self, grid: QGridLayout, row: int, label: str, widget: QWidget) -> None:
        grid.addWidget(QLabel(label), row, 0)
        grid.addWidget(widget, row, 1)

    def _action_button(self, text: str, slot, icon_name: str | None = None) -> QPushButton:
        button = QPushButton(text)
        button.setMinimumSize(104, 32)
        button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        apply_button_icon(button, icon_name)
        button.clicked.connect(slot)
        return button

    def _network_action_button(self, text: str, slot, icon_name: str | None = None) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("networkPingActionButton")
        button.setMinimumSize(100, 34)
        button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        apply_button_icon(button, icon_name)
        button.clicked.connect(slot)
        return button

    def _network_card(self, title: str) -> tuple[QWidget, QVBoxLayout]:
        card = QWidget()
        card.setObjectName("ncCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)
        title_label = QLabel(title)
        title_label.setObjectName("networkPingCardTitle")
        layout.addWidget(title_label)
        return card, layout

    def _apply_network_form_control(self, widget: QWidget, *, spin: bool = False) -> None:
        widget.setMinimumHeight(34)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if spin and isinstance(widget, QAbstractSpinBox):
            widget.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            widget.setMinimumWidth(136)
            widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def _ipv4_tab(self) -> QWidget:
        page, grid, actions, panel = self._tool_page("ipv4_calc")
        self.ipv4_panel = panel
        self.ipv4_edit = QLineEdit("192.168.1.1/24")
        self._add_row(grid, 0, "网络地址", self.ipv4_edit)
        actions.addWidget(self._action_button("计算", self.calculate_ipv4, "SEARCH"))
        return page

    def _ipv6_tab(self) -> QWidget:
        page, grid, actions, panel = self._tool_page("ipv6_calc")
        self.ipv6_panel = panel
        self.ipv6_edit = QLineEdit("2408::1/64")
        self._add_row(grid, 0, "IPv6 地址/前缀", self.ipv6_edit)
        actions.addWidget(self._action_button("计算", self.calculate_ipv6, "SEARCH"))
        return page

    def _vlsm_tab(self) -> QWidget:
        page, grid, actions, panel = self._tool_page("vlsm")
        self.vlsm_panel = panel
        self.vlsm_parent_edit = QLineEdit("192.168.1.0/24")
        self.vlsm_requests_edit = QTextEdit()
        self.vlsm_requests_edit.setAcceptRichText(False)
        self.vlsm_requests_edit.setPlainText("\n".join(["部门A,50", "部门B,30", "部门C,20", "部门D,10"]))
        self.vlsm_requests_edit.setMaximumHeight(112)
        self._add_row(grid, 0, "主网络", self.vlsm_parent_edit)
        self._add_row(grid, 1, "子网需求", self.vlsm_requests_edit)
        actions.addWidget(self._action_button("规划 VLSM", self.calculate_vlsm, "EDIT"))
        return page

    def _subnet_split_tab(self) -> QWidget:
        page, grid, actions, panel = self._tool_page("subnet_split")
        self.subnet_panel = panel
        self.subnet_parent_edit = QLineEdit("192.168.0.0/22")
        self.subnet_prefix_spin = self._spin(1, 32, 24)
        self.subnet_page_size_spin = self._spin(1, 500, 50)
        self._add_row(grid, 0, "主网络", self.subnet_parent_edit)
        self._add_row(grid, 1, "目标前缀", self.subnet_prefix_spin)
        self._add_row(grid, 2, "每页数量", self.subnet_page_size_spin)
        actions.addWidget(self._action_button("划分", self.calculate_subnets, "EDIT"))
        return page

    def _route_summary_tab(self) -> QWidget:
        page, grid, actions, panel = self._tool_page("route_summary")
        self.route_summary_panel = panel
        self.summary_input = QTextEdit()
        self.summary_input.setAcceptRichText(False)
        self.summary_input.setPlainText("\n".join(["192.168.0.0/24", "192.168.1.0/24", "192.168.2.0/24", "192.168.3.0/24"]))
        self.summary_input.setMaximumHeight(112)
        self._add_row(grid, 0, "每行一个网段", self.summary_input)
        actions.addWidget(self._action_button("汇总", self.calculate_route_summary, "ACCEPT"))
        return page

    def _wildcard_tab(self) -> QWidget:
        page, grid, actions, panel = self._tool_page("wildcard")
        self.wildcard_panel = panel
        self.wildcard_input = QTextEdit()
        self.wildcard_input.setAcceptRichText(False)
        self.wildcard_input.setPlainText("\n".join(["/24", "255.255.0.0", "192.168.0.0 255.255.0.0"]))
        self.wildcard_input.setMaximumHeight(112)
        self._add_row(grid, 0, "输入", self.wildcard_input)
        actions.addWidget(self._action_button("计算反掩码", self.calculate_wildcard, "SEARCH"))
        return page

    def _single_ping_tab(self) -> QWidget:
        page, grid, actions, panel = self._tool_page("single_ping")
        self.single_ping_panel = panel
        self.single_ping_target = QLineEdit()
        self.single_ping_count = self._spin(1, 100, 4)
        self.single_ping_size = self._spin(1, 65500, 32)
        self.single_ping_timeout = self._spin(100, 60000, 1500)
        quick_row = QHBoxLayout()
        for size in (32, 1024, 4096, 8192):
            quick = QPushButton(f"{size}B")
            quick.setMinimumWidth(76)
            quick.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            quick.clicked.connect(lambda _checked=False, value=size: self.single_ping_size.setValue(value))
            quick_row.addWidget(quick)
        quick_row.addStretch(1)
        self._add_row(grid, 0, "目标主机", self.single_ping_target)
        self._add_row(grid, 1, "测试次数", self.single_ping_count)
        self._add_row(grid, 2, "包大小", self.single_ping_size)
        grid.addLayout(quick_row, 2, 2)
        self._add_row(grid, 3, "超时(ms)", self.single_ping_timeout)
        actions.addWidget(self._action_button("开始 Ping", self.run_single_ping, "PLAY"))
        return page

    def _continuous_ping_tab(self) -> QWidget:
        page, grid, actions, panel = self._tool_page("continuous_ping")
        self.continuous_ping_panel = panel
        self.continuous_ping_target = QLineEdit()
        self.continuous_ping_interval = self._spin(1, 3600, 1)
        self.continuous_ping_size = self._spin(1, 65500, 32)
        self.continuous_ping_timeout = self._spin(100, 60000, 1500)
        self._add_row(grid, 0, "目标主机", self.continuous_ping_target)
        self._add_row(grid, 1, "间隔(秒)", self.continuous_ping_interval)
        self._add_row(grid, 2, "包大小", self.continuous_ping_size)
        self._add_row(grid, 3, "超时(ms)", self.continuous_ping_timeout)
        actions.addWidget(self._action_button("采样一次", self.run_continuous_sample, "PLAY"))
        return page

    def _batch_ping_tab(self) -> QWidget:
        page, grid, actions, panel = self._tool_page("batch_ping")
        self.batch_ping_panel = panel
        self.batch_ping_targets = QTextEdit()
        self.batch_ping_targets.setAcceptRichText(False)
        self.batch_ping_targets.setMaximumHeight(112)
        self.batch_ping_timeout = self._spin(100, 60000, 1500)
        self.batch_ping_concurrency = self._spin(1, 500, 100)
        self.batch_ping_mode = QComboBox()
        self.batch_ping_mode.addItems(["快速扫描", "稳定检测"])
        self._add_row(grid, 0, "主机列表", self.batch_ping_targets)
        self._add_row(grid, 1, "超时(ms)", self.batch_ping_timeout)
        self._add_row(grid, 2, "并发数", self.batch_ping_concurrency)
        self._add_row(grid, 3, "模式", self.batch_ping_mode)
        actions.addWidget(self._action_button("批量 Ping", self.run_batch_ping, "PLAY"))
        return page

    def _network_ping_tab(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)

        scroll = self._scrollable_tab()
        content = QWidget()
        content.setObjectName("networkPingScrollContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 12, 24, 12)
        content_layout.setSpacing(10)
        content_layout.setAlignment(Qt.AlignTop)
        scroll.setWidget(content)
        page_layout.addWidget(scroll)

        params_card, params_layout = self._network_card("参数")
        grid = QGridLayout()
        grid.setContentsMargins(14, 18, 14, 16)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(14)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(3, 1)
        grid.setColumnStretch(5, 1)
        grid.setColumnStretch(6, 0)
        params_layout.addLayout(grid)

        self.network_adapter_combo = QComboBox()
        self.network_ping_cidr = QLineEdit("192.168.1.0/24")
        self.network_ping_timeout = self._spin(100, 60000, 1500)
        self.network_ping_size = self._spin(1, 65500, 32)
        self.network_ping_threads = self._spin(1, 500, 50)
        self._apply_network_form_control(self.network_adapter_combo)
        self._apply_network_form_control(self.network_ping_cidr)
        for spin in (self.network_ping_timeout, self.network_ping_size, self.network_ping_threads):
            self._apply_network_form_control(spin, spin=True)
        self.network_ping_usable_only = QCheckBox("只扫描可用主机")
        self.network_ping_usable_only.setChecked(True)

        refresh = QPushButton("刷新网卡")
        refresh.setMinimumSize(112, 34)
        refresh.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        apply_button_icon(refresh, "SYNC")
        refresh.clicked.connect(self.refresh_network_adapters)
        self.network_adapter_combo.currentIndexChanged.connect(self._network_adapter_changed)

        grid.addWidget(QLabel("网卡"), 0, 0)
        grid.addWidget(self.network_adapter_combo, 0, 1, 1, 4)
        grid.addWidget(refresh, 0, 6)
        grid.addWidget(QLabel("网段"), 1, 0)
        grid.addWidget(self.network_ping_cidr, 1, 1, 1, 6)
        grid.addWidget(QLabel("超时(ms)"), 2, 0)
        grid.addWidget(self.network_ping_timeout, 2, 1)
        grid.addWidget(QLabel("包大小"), 2, 2)
        grid.addWidget(self.network_ping_size, 2, 3)
        grid.addWidget(QLabel("线程数"), 2, 4)
        grid.addWidget(self.network_ping_threads, 2, 5)
        grid.addWidget(self.network_ping_usable_only, 3, 1, 1, 3)
        params_card.setMinimumHeight(210)
        content_layout.addWidget(params_card)

        panel = ToolResultPanel(self.paths, self.site_name, "network_ping")
        self.network_ping_panel = panel
        self.result_panels.append(panel)
        panel.export_csv_button.hide()
        panel.export_xlsx_button.hide()
        panel.clear_button.hide()
        panel.result_table.setMinimumHeight(320)
        panel.summary_text.setMinimumHeight(120)
        panel.summary_text.setMaximumHeight(16777215)
        panel.setMinimumHeight(500)

        actions_card, actions_layout = self._network_card("操作")
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions_layout.addLayout(actions)
        for button in (
            self._network_action_button("扫描网段", self.run_network_ping, "PLAY"),
            self._network_action_button("停止", self.stop_network_ping, "CANCEL"),
            self._network_action_button("导出 CSV", lambda: panel.export_current("csv"), "SHARE"),
            self._network_action_button("导出 XLSX", lambda: panel.export_current("xlsx"), "SHARE"),
            self._network_action_button("清空", self.clear_network_ping_results, "DELETE"),
        ):
            actions.addWidget(button)
        actions.addStretch(1)
        actions_card.setMinimumHeight(82)
        content_layout.addWidget(actions_card)

        stats_card, stats_layout = self._network_card("状态统计")
        stats_row = QHBoxLayout()
        stats_row.setContentsMargins(0, 0, 0, 0)
        stats_row.setSpacing(8)
        self.network_ping_engine_label = QLabel("当前引擎：检测中")
        stats_row.addWidget(self.network_ping_engine_label)
        self.network_ping_stats_label = QLabel("就绪 | 总计: 0 | 已扫: 0 | 在线: 0 | 离线: 0 | 在线率: 0.00%")
        stats_row.addWidget(self.network_ping_stats_label, 1)
        legend_row = QHBoxLayout()
        legend_row.setContentsMargins(0, 0, 0, 0)
        legend_row.setSpacing(8)
        for text, color in (("未测试", "#475569"), ("扫描中", "#38bdf8"), ("在线", "#22c55e"), ("离线", "#ef4444"), ("超时", "#f59e0b")):
            dot = QLabel(f"● {text}")
            dot.setStyleSheet(f"color: {color}; font-weight: 600;")
            legend_row.addWidget(dot)
        legend_row.addStretch(1)
        stats_layout.addLayout(stats_row)
        stats_layout.addLayout(legend_row)
        stats_card.setMinimumHeight(86)
        content_layout.addWidget(stats_card)

        grid_card, grid_layout = self._network_card("IP地址状态网格（1-255）")
        self.network_ping_grid = IpStatusGridWidget()
        self.network_ping_grid.setMinimumHeight(320)
        self.network_ping_grid.hostClicked.connect(self._network_grid_host_clicked)
        grid_layout.addWidget(self.network_ping_grid)
        grid_card.setMinimumHeight(370)
        content_layout.addWidget(grid_card)

        panel.setTitle("详细结果表格")
        content_layout.addWidget(panel)

        log_card, log_layout = self._network_card("日志/详情")
        self.network_ping_detail_text = QTextEdit()
        self.network_ping_detail_text.setReadOnly(True)
        self.network_ping_detail_text.setMinimumHeight(120)
        log_layout.addWidget(self.network_ping_detail_text)
        log_card.setMinimumHeight(168)
        content_layout.addWidget(log_card)

        panel.result_table.itemSelectionChanged.connect(self._network_table_selection_changed)
        self.refresh_network_adapters()
        return page

    def _tcp_ping_tab(self) -> QWidget:
        page, grid, actions, panel = self._tool_page("tcp_ping")
        self.tcp_ping_panel = panel
        self.tcp_target = QLineEdit()
        self.tcp_port = self._spin(1, 65535, 443)
        self.tcp_count = self._spin(1, 1000, 10)
        self.tcp_timeout = self._spin(1, 60, 3)
        quick_row = QHBoxLayout()
        for label, port in (("HTTP:80", 80), ("HTTPS:443", 443), ("SSH:22", 22), ("RDP:3389", 3389), ("MySQL:3306", 3306), ("Redis:6379", 6379)):
            button = QPushButton(label)
            button.setMinimumWidth(92)
            button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            button.clicked.connect(lambda _checked=False, value=port: self.tcp_port.setValue(value))
            quick_row.addWidget(button)
        quick_row.addStretch(1)
        self._add_row(grid, 0, "目标主机", self.tcp_target)
        self._add_row(grid, 1, "端口", self.tcp_port)
        grid.addLayout(quick_row, 1, 2)
        self._add_row(grid, 2, "测试次数", self.tcp_count)
        self._add_row(grid, 3, "超时(秒)", self.tcp_timeout)
        actions.addWidget(self._action_button("TCP Ping", self.run_tcp_ping, "PLAY"))
        return page

    def calculate_ipv4(self) -> None:
        self.ipv4_panel.show_rows([ipv4_calculate(self.ipv4_edit.text())], "ipv4_calc", summary_title="IPv4 计算")

    def calculate_ipv6(self) -> None:
        self.ipv6_panel.show_rows([ipv6_calculate(self.ipv6_edit.text())], "ipv6_calc", summary_title="IPv6 计算")

    def calculate_vlsm(self) -> None:
        parent_text = self.vlsm_parent_edit.text()
        requests_text = self.vlsm_requests_edit.toPlainText()
        self._run_async(self.vlsm_panel, lambda: plan_vlsm(parent_text, requests_text), "vlsm")

    def calculate_subnets(self) -> None:
        parent_text = self.subnet_parent_edit.text()
        target_prefix = self.subnet_prefix_spin.value()
        page_size = self.subnet_page_size_spin.value()
        self._run_async(self.subnet_panel, lambda: split_subnets(parent_text, target_prefix, page_size=page_size), "subnet_split")

    def calculate_route_summary(self) -> None:
        text = self.summary_input.toPlainText()
        self._run_async(self.route_summary_panel, lambda: summarize_routes(text), "route_summary")

    def calculate_wildcard(self) -> None:
        text = self.wildcard_input.toPlainText()
        self._run_async(self.wildcard_panel, lambda: wildcard_calculate(text), "wildcard")

    def run_single_ping(self) -> None:
        self._run_async(
            self.single_ping_panel,
            lambda: [asdict(run_single_ping(self.single_ping_target.text(), count=self.single_ping_count.value(), size=self.single_ping_size.value(), timeout_ms=self.single_ping_timeout.value()))],
            "single_ping",
        )

    def run_continuous_sample(self) -> None:
        self._run_async(
            self.continuous_ping_panel,
            lambda: [asdict(run_single_ping(self.continuous_ping_target.text(), count=1, size=self.continuous_ping_size.value(), timeout_ms=self.continuous_ping_timeout.value()))],
            "continuous_ping",
        )

    def run_batch_ping(self) -> None:
        count = 1 if self.batch_ping_mode.currentIndex() == 0 else 4
        targets = self.batch_ping_targets.toPlainText().splitlines()
        self._run_async(
            self.batch_ping_panel,
            lambda: self._run_fping_or_system_batch(
                targets,
                count=count,
                size=32,
                timeout_ms=self.batch_ping_timeout.value(),
                concurrency=self.batch_ping_concurrency.value(),
                source_ip="",
            )[0],
            "batch_ping",
        )

    def run_network_ping(self) -> None:
        network = ipaddress.ip_network(self.network_ping_cidr.text(), strict=False)
        hosts = list(network.hosts()) if self.network_ping_usable_only.isChecked() else list(network)
        if len(hosts) > 4096:
            MessageBox.warning(self, "网段 Ping", "单次扫描最大地址数为 4096，请缩小范围。")
            return
        targets = [str(host) for host in hosts]
        self.network_ping_stop_requested = False
        self._init_network_ping_grid(network, targets)
        source_ip = self._selected_source_ip()
        size = self.network_ping_size.value()
        timeout_ms = self.network_ping_timeout.value()
        concurrency = self.network_ping_threads.value()
        self._run_async(self.network_ping_panel, lambda: self._run_network_ping_task(targets, source_ip, size, timeout_ms, concurrency), "network_ping")

    def _run_network_ping_task(self, targets: list[str], source_ip: str, size: int, timeout_ms: int, concurrency: int) -> list[dict[str, object]]:
        rows, engine = self._run_fping_or_system_batch(
            targets,
            count=1,
            size=size,
            timeout_ms=timeout_ms,
            concurrency=concurrency,
            source_ip=source_ip,
            progress=lambda row: self.network_ping_progress_ready.emit(row),
            should_stop=lambda: self.network_ping_stop_requested,
        )
        self.network_ping_progress_ready.emit({"engine": engine})
        return rows

    def _run_fping_or_system_batch(
        self,
        targets: list[str],
        *,
        count: int,
        size: int,
        timeout_ms: int,
        concurrency: int,
        source_ip: str,
        progress: Callable[[dict[str, object]], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> tuple[list[dict[str, object]], str]:
        root = Path(self.paths.app_root)
        availability = discover_fping(root)
        if availability.available:
            if progress:
                for target in targets:
                    progress({"target": target, "status": "scanning"})
            results, run_availability = scan_fping_targets(
                targets,
                root=root,
                count=count,
                size=size,
                timeout_ms=timeout_ms,
                source_ip=source_ip,
                progress=lambda result: progress(asdict(result)) if progress else None,
                should_stop=should_stop,
            )
            if run_availability.available and results:
                engine = f"当前引擎：fping 5.5 ({run_availability.path})"
                if source_ip.strip() and not run_availability.supports_source_ip:
                    engine += "；当前 fping 不支持绑定源地址，已按系统路由扫描"
                return [asdict(row) for row in results], engine
            availability = run_availability
        engine = f"当前引擎：系统 ping（fping 不可用：{availability.error or '未知原因'}）"
        rows = self._run_system_ping_batch(targets, count=count, size=size, timeout_ms=timeout_ms, concurrency=concurrency, source_ip=source_ip, progress=progress, should_stop=should_stop)
        return rows, engine

    def _run_system_ping_batch(
        self,
        targets: list[str],
        *,
        count: int,
        size: int,
        timeout_ms: int,
        concurrency: int,
        source_ip: str,
        progress: Callable[[dict[str, object]], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> list[dict[str, object]]:
        results: list[dict[str, object]] = []
        with ThreadPoolExecutor(max_workers=max(1, min(concurrency, 500))) as executor:
            futures = {}
            for target in targets:
                if should_stop and should_stop():
                    break
                if progress:
                    progress({"target": target, "status": "scanning"})
                future = executor.submit(
                    run_single_ping,
                    target,
                    count=1,
                    size=size,
                    timeout_ms=timeout_ms,
                    source_ip=source_ip,
                )
                futures[future] = target
            for future in as_completed(futures):
                if should_stop and should_stop():
                    continue
                row = asdict(future.result())
                results.append(row)
                if progress:
                    progress(row)
        order = {target: index for index, target in enumerate(targets)}
        return sorted(results, key=lambda item: order.get(str(item.get("target")), 0))

    def stop_network_ping(self) -> None:
        self.network_ping_stop_requested = True
        self.network_ping_panel.set_status("stopped")
        self._refresh_network_ping_stats("已停止")

    def clear_network_ping_results(self) -> None:
        self.network_ping_stop_requested = False
        self.current_network_ping_results = {}
        self.network_ping_panel.clear_results()
        if hasattr(self, "network_ping_grid"):
            self.network_ping_grid.clear()
        if hasattr(self, "network_ping_detail_text"):
            self.network_ping_detail_text.clear()
        if hasattr(self, "network_ping_engine_label"):
            self.network_ping_engine_label.setText("当前引擎：检测中")
        self._refresh_network_ping_stats("就绪")

    def run_tcp_ping(self) -> None:
        def task() -> list[dict[str, object]]:
            rows = [run_tcp_ping(self.tcp_target.text(), self.tcp_port.value(), timeout_seconds=self.tcp_timeout.value()) for _ in range(self.tcp_count.value())]
            return [asdict(row) for row in rows]

        self._run_async(self.tcp_ping_panel, task, "tcp_ping")

    def refresh_network_adapters(self) -> None:
        try:
            self.adapters = self.network_manager.list_adapters()
        except Exception as exc:
            self.adapters = []
            self.network_ping_panel.show_error(f"读取网卡失败：{exc}")
        self.network_adapter_combo.blockSignals(True)
        try:
            self.network_adapter_combo.clear()
            self.network_adapter_combo.addItem("自动选择")
            for adapter in self.adapters:
                self.network_adapter_combo.addItem(self._adapter_label(adapter))
        finally:
            self.network_adapter_combo.blockSignals(False)

    def _run_async(self, panel: ToolResultPanel, fn: Callable[[], object], prefix: str) -> None:
        if self.thread is not None:
            panel.show_error("已有任务正在执行，请等待完成。")
            return
        panel.set_status("running")
        self.active_panel = panel
        self.thread = QThread(self)
        self.worker = _Worker(fn, prefix)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._forward_worker_result, Qt.QueuedConnection)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self._thread_finished)
        self.thread.start()

    @Slot(object, str, str)
    def _forward_worker_result(self, payload: object, error: str, prefix: str) -> None:
        self.async_result_ready.emit(payload, error, prefix)

    @Slot(object, str, str)
    def _async_finished(self, payload: object, error: str, prefix: str) -> None:
        if self._destroyed or self.active_panel is None:
            return
        panel = self.active_panel
        if error:
            panel.show_error(error)
            return
        if prefix == "network_ping" and self.network_ping_stop_requested:
            panel.set_status("stopped")
            self._refresh_network_ping_stats("已停止")
            return
        if isinstance(payload, TableResult):
            panel.show_table_result(payload, prefix)
            return
        rows = list(payload or [])
        panel.show_rows(rows, prefix)
        if prefix == "network_ping":
            self._refresh_network_ping_stats()

    @Slot()
    def _thread_finished(self) -> None:
        self.thread = None
        self.worker = None
        self.active_panel = None

    def _init_network_ping_grid(self, network: ipaddress.IPv4Network, targets: list[str]) -> None:
        target_set = set(targets)
        self.current_network_ping_results = {}
        if network.version != 4 or network.prefixlen < 24:
            self.network_ping_grid.set_hosts([], "当前仅对 /24 及更小范围提供单页网格可视化；更大网段请缩小范围或查看表格结果。")
            self._refresh_network_ping_stats("就绪")
            return
        visual_network = network if network.prefixlen == 24 else network.supernet(new_prefix=24)
        rows: list[NetworkPingHostResult] = []
        for host_number in range(1, 256):
            ip = str(visual_network.network_address + host_number)
            in_range = ip in target_set
            result = NetworkPingHostResult(ip=ip, host_number=host_number, in_range=in_range, status="idle" if in_range else "disabled")
            rows.append(result)
            if in_range:
                self.current_network_ping_results[ip] = result
        self.network_ping_grid.set_hosts(rows)
        self._refresh_network_ping_stats("就绪")

    @Slot(dict)
    def _network_ping_progress(self, row: dict) -> None:
        if self._destroyed or self.network_ping_stop_requested:
            return
        if "engine" in row:
            self.network_ping_engine_label.setText(str(row.get("engine") or ""))
            return
        target = str(row.get("target") or "")
        if not target or target not in self.current_network_ping_results:
            return
        current = self.current_network_ping_results[target]
        updated = self._network_host_result_from_row(row, current)
        self.current_network_ping_results[target] = updated
        self.network_ping_grid.update_host_status(target, updated)
        self._refresh_network_ping_stats("执行中")

    def _network_host_result_from_row(self, row: dict, current: NetworkPingHostResult) -> NetworkPingHostResult:
        status = str(row.get("status") or "")
        if status == "scanning":
            grid_status = "scanning"
        elif status == "online":
            grid_status = "online"
        elif status == "offline":
            grid_status = "timeout" if row.get("packet_loss_percent") == 100 else "offline"
        elif status in {"timeout", "failed", "unreachable", "dns_failed", "error"}:
            grid_status = "timeout" if status == "timeout" else "error"
        else:
            grid_status = current.status
        return NetworkPingHostResult(
            ip=current.ip,
            host_number=current.host_number,
            in_range=current.in_range,
            status=grid_status,
            resolved_ip=str(row.get("resolved_ip") or ""),
            latency_ms=row.get("latency_ms"),
            min_ms=row.get("min_ms"),
            max_ms=row.get("max_ms"),
            avg_ms=row.get("avg_ms"),
            packet_loss_percent=row.get("packet_loss_percent"),
            sent=row.get("sent") or 0,
            received=row.get("received") or 0,
            timestamp=str(row.get("timestamp") or ""),
            error=str(row.get("error") or ""),
        )

    def _refresh_network_ping_stats(self, state: str = "完成") -> None:
        rows = [item for item in self.current_network_ping_results.values() if item.in_range]
        total = len(rows)
        scanned = sum(1 for item in rows if item.status in {"online", "offline", "timeout", "error"})
        online = sum(1 for item in rows if item.status == "online")
        offline = sum(1 for item in rows if item.status in {"offline", "timeout", "error"})
        rate = (online / scanned * 100) if scanned else 0
        if hasattr(self, "network_ping_stats_label"):
            self.network_ping_stats_label.setText(f"{state} | 总计: {total} | 已扫: {scanned} | 在线: {online} | 离线: {offline} | 在线率(在线/已扫): {rate:.2f}%")

    def _network_grid_host_clicked(self, ip: str) -> None:
        self.network_ping_grid.select_ip(ip)
        self.network_ping_panel.select_row_containing(ip)
        self._show_network_ping_detail(ip)

    def _network_table_selection_changed(self) -> None:
        table = self.network_ping_panel.result_table
        selected = table.selectedItems()
        for item in selected:
            text = item.text()
            if text in self.current_network_ping_results:
                self.network_ping_grid.select_ip(text)
                self._show_network_ping_detail(text)
                return

    def _show_network_ping_detail(self, ip: str) -> None:
        if not hasattr(self, "network_ping_detail_text"):
            return
        item = self.current_network_ping_results.get(ip)
        if item is None:
            self.network_ping_detail_text.clear()
            return
        lines = [
            f"IP：{item.ip}",
            f"状态：{GRID_STATUS_LABELS.get(item.status, item.status)}",
            f"解析IP：{item.resolved_ip or '-'}",
            f"延迟：{item.latency_ms if item.latency_ms not in (None, '') else '-'} ms",
            f"最小/平均/最大：{item.min_ms or '-'} / {item.avg_ms or '-'} / {item.max_ms or '-'} ms",
            f"发送/接收：{item.sent} / {item.received}",
            f"丢包率：{item.packet_loss_percent if item.packet_loss_percent is not None else '-'}%",
            f"时间：{item.timestamp or '-'}",
        ]
        if item.error:
            lines.append(f"错误：{item.error}")
        self.network_ping_detail_text.setPlainText("\n".join(lines))

    @Slot(object)
    def _on_destroyed(self, _obj: object = None) -> None:
        self._destroyed = True

    def _network_adapter_changed(self) -> None:
        adapter = self._selected_adapter()
        if not adapter or not adapter.ipv4_addresses:
            return
        try:
            network = ipaddress.IPv4Interface(adapter.ipv4_addresses[0]).network
        except ValueError:
            return
        self.network_ping_cidr.setText(str(network))

    def _selected_adapter(self) -> NetworkAdapterInfo | None:
        index = self.network_adapter_combo.currentIndex() - 1
        if 0 <= index < len(self.adapters):
            return self.adapters[index]
        return None

    def _selected_source_ip(self) -> str:
        adapter = self._selected_adapter()
        if not adapter or not adapter.ipv4_addresses:
            return ""
        return adapter.ipv4_addresses[0].split("/", 1)[0].strip()

    @staticmethod
    def _adapter_label(adapter: NetworkAdapterInfo) -> str:
        ip_text = ", ".join(adapter.ipv4_addresses) if adapter.ipv4_addresses else "无 IPv4"
        status = adapter.status or "-"
        return f"{adapter.name} / {ip_text} / {status}"

    @staticmethod
    def _spin(minimum: int, maximum: int, value: int) -> NoWheelSpinBox:
        spin = NoWheelSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        return spin


def _display_row(row: object) -> dict[str, object]:
    if is_dataclass(row):
        raw = asdict(row)
    elif isinstance(row, dict):
        raw = row
    else:
        raw = {"value": row}
    result: dict[str, object] = {}
    for key, value in raw.items():
        if key == "raw_output" or str(key).startswith("_"):
            continue
        label = DISPLAY_HEADERS.get(str(key), str(key))
        result[label] = _translate_value(key, value)
    return result


def _translate_value(key: object, value: object) -> object:
    if key == "status" and isinstance(value, str):
        return STATUS_LABELS.get(value, value)
    if isinstance(value, bool):
        return "\u662f" if value else "\u5426"
    return value


def _stringify(value: object) -> str:
    if value is None:
        return ""
    return str(value)
