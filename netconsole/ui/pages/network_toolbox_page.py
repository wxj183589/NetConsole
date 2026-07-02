from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from netconsole.core.admin import is_admin
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.services.network_tools.toolbox.export import export_rows_csv, export_rows_xlsx
from netconsole.services.network_tools.toolbox.ip_calc import (
    ipv4_calculate,
    ipv6_calculate,
    plan_vlsm,
    split_subnets,
    summarize_routes,
    wildcard_calculate,
)
from netconsole.services.network_tools.toolbox.ping_tools import run_batch_ping, run_single_ping, run_tcp_ping
from netconsole.services.network_tools.toolbox.route_tools import (
    build_add_route_command,
    build_delete_route_command,
    execute_powershell,
    list_local_routes,
)
from netconsole.ui.table_utils import configure_readonly_table
from netconsole.ui.widgets.no_wheel import NoWheelSpinBox


class _Worker(QObject):
    finished = Signal(object, str)

    def __init__(self, fn, *args, **kwargs) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def run(self) -> None:
        try:
            self.finished.emit(self.fn(*self.args, **self.kwargs), "")
        except Exception as exc:
            self.finished.emit(None, str(exc))


class NetworkToolboxPage(QWidget):
    def __init__(self, i18n: I18n, site_name: str, paths: PathResolver) -> None:
        super().__init__()
        self.i18n = i18n
        self.site_name = site_name
        self.paths = paths
        self.thread: QThread | None = None
        self.worker: _Worker | None = None
        self.current_rows: list[dict[str, object]] = []
        self.current_headers: list[str] = []
        self.current_export_prefix = "toolbox"

        self.tabs = QTabWidget()
        self.ip_tabs = QTabWidget()
        self.ping_tabs = QTabWidget()
        self.result_table = QTableWidget()
        configure_readonly_table(self.result_table)
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.status_label = QLabel("就绪")
        self.export_csv_button = QPushButton("导出 CSV")
        self.export_xlsx_button = QPushButton("导出 XLSX")
        self.clear_button = QPushButton("清空结果")

        self._build_ui()
        self._connect()

    def set_site(self, site_name: str) -> None:
        self.site_name = site_name

    def retranslate(self) -> None:
        pass

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.addWidget(self.tabs)
        self.tabs.addTab(self._ip_page(), "IP计算")
        self.tabs.addTab(self._connectivity_page(), "连通性检测")
        self.tabs.addTab(self._routes_page(), "本机路由")

        result_box = QGroupBox("结果")
        result_layout = QVBoxLayout(result_box)
        actions = QHBoxLayout()
        actions.addWidget(self.status_label, 1)
        actions.addWidget(self.export_csv_button)
        actions.addWidget(self.export_xlsx_button)
        actions.addWidget(self.clear_button)
        result_layout.addLayout(actions)
        result_layout.addWidget(self.result_table, 4)
        result_layout.addWidget(self.summary_text, 1)
        root.addWidget(result_box, 1)

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

    def _ipv4_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.ipv4_edit = QLineEdit("192.168.1.1/24")
        button = QPushButton("计算")
        button.clicked.connect(self.calculate_ipv4)
        form.addRow("网络地址", self.ipv4_edit)
        form.addRow(button)
        return page

    def _ipv6_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.ipv6_edit = QLineEdit("2408::1/64")
        button = QPushButton("计算")
        button.clicked.connect(self.calculate_ipv6)
        form.addRow("IPv6地址/前缀", self.ipv6_edit)
        form.addRow(button)
        return page

    def _vlsm_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.vlsm_parent_edit = QLineEdit("192.168.1.0/24")
        self.vlsm_requests_edit = QTextEdit("部门A,50\n部门B,30\n部门C,20\n部门D,10")
        button = QPushButton("规划 VLSM")
        button.clicked.connect(self.calculate_vlsm)
        form.addRow("主网络", self.vlsm_parent_edit)
        form.addRow("子网需求", self.vlsm_requests_edit)
        layout.addLayout(form)
        layout.addWidget(button)
        return page

    def _subnet_split_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.subnet_parent_edit = QLineEdit("192.168.0.0/22")
        self.subnet_prefix_spin = self._spin(1, 32, 24)
        self.subnet_page_size_spin = self._spin(1, 500, 50)
        button = QPushButton("划分")
        button.clicked.connect(self.calculate_subnets)
        form.addRow("主网络", self.subnet_parent_edit)
        form.addRow("目标前缀", self.subnet_prefix_spin)
        form.addRow("每页数量", self.subnet_page_size_spin)
        form.addRow(button)
        return page

    def _route_summary_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.summary_input = QTextEdit("192.168.0.0/24\n192.168.1.0/24\n192.168.2.0/24\n192.168.3.0/24")
        button = QPushButton("汇总")
        button.clicked.connect(self.calculate_route_summary)
        layout.addWidget(QLabel("每行一个网段"))
        layout.addWidget(self.summary_input)
        layout.addWidget(button)
        return page

    def _wildcard_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.wildcard_input = QTextEdit("/24\n255.255.0.0\n192.168.0.0 255.255.0.0")
        button = QPushButton("计算反掩码")
        button.clicked.connect(self.calculate_wildcard)
        layout.addWidget(QLabel("支持单行或多行输入"))
        layout.addWidget(self.wildcard_input)
        layout.addWidget(button)
        return page

    def _single_ping_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.single_ping_target = QLineEdit()
        self.single_ping_count = self._spin(1, 100, 4)
        self.single_ping_size = self._spin(1, 65500, 32)
        self.single_ping_timeout = self._spin(100, 60000, 1500)
        button = QPushButton("开始 Ping")
        button.clicked.connect(self.run_single_ping)
        for size in (32, 1024, 4096, 8192):
            quick = QPushButton(f"{size}B")
            quick.clicked.connect(lambda _checked=False, value=size: self.single_ping_size.setValue(value))
            form.addRow(quick)
        form.addRow("目标主机", self.single_ping_target)
        form.addRow("测试次数", self.single_ping_count)
        form.addRow("包大小", self.single_ping_size)
        form.addRow("超时(ms)", self.single_ping_timeout)
        form.addRow(button)
        return page

    def _continuous_ping_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.continuous_ping_target = QLineEdit()
        self.continuous_ping_interval = self._spin(1, 3600, 1)
        self.continuous_ping_size = self._spin(1, 65500, 32)
        self.continuous_ping_timeout = self._spin(100, 60000, 1500)
        self.continuous_button = QPushButton("执行一次持续 Ping 采样")
        self.continuous_button.clicked.connect(self.run_continuous_sample)
        form.addRow("目标主机", self.continuous_ping_target)
        form.addRow("间隔(秒)", self.continuous_ping_interval)
        form.addRow("包大小", self.continuous_ping_size)
        form.addRow("超时(ms)", self.continuous_ping_timeout)
        form.addRow(self.continuous_button)
        return page

    def _batch_ping_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.batch_ping_targets = QTextEdit()
        self.batch_ping_timeout = self._spin(100, 60000, 1500)
        self.batch_ping_concurrency = self._spin(1, 500, 100)
        self.batch_ping_mode = QComboBox()
        self.batch_ping_mode.addItems(["快速扫描", "稳定检测"])
        button = QPushButton("开始批量 Ping")
        button.clicked.connect(self.run_batch_ping)
        form.addRow("主机列表", self.batch_ping_targets)
        form.addRow("超时(ms)", self.batch_ping_timeout)
        form.addRow("并发数", self.batch_ping_concurrency)
        form.addRow("模式", self.batch_ping_mode)
        layout.addLayout(form)
        layout.addWidget(button)
        return page

    def _network_ping_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.network_ping_cidr = QLineEdit("192.168.1.0/24")
        self.network_ping_threads = self._spin(1, 500, 50)
        self.network_ping_usable_only = QCheckBox("只扫描可用主机")
        self.network_ping_usable_only.setChecked(True)
        button = QPushButton("扫描网段")
        button.clicked.connect(self.run_network_ping)
        form.addRow("网段", self.network_ping_cidr)
        form.addRow("线程数", self.network_ping_threads)
        form.addRow(self.network_ping_usable_only)
        form.addRow(button)
        return page

    def _tcp_ping_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.tcp_target = QLineEdit()
        self.tcp_port = self._spin(1, 65535, 443)
        self.tcp_count = self._spin(1, 1000, 10)
        self.tcp_timeout = self._spin(1, 60, 3)
        quick_row = QHBoxLayout()
        for label, port in (("HTTP:80", 80), ("HTTPS:443", 443), ("SSH:22", 22), ("RDP:3389", 3389), ("MySQL:3306", 3306), ("Redis:6379", 6379)):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, value=port: self.tcp_port.setValue(value))
            quick_row.addWidget(button)
        start = QPushButton("开始 TCP Ping")
        start.clicked.connect(self.run_tcp_ping)
        form.addRow("目标主机", self.tcp_target)
        form.addRow("端口", self.tcp_port)
        form.addRow("测试次数", self.tcp_count)
        form.addRow("超时(秒)", self.tcp_timeout)
        form.addRow(quick_row)
        form.addRow(start)
        return page

    def _routes_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        top = QHBoxLayout()
        self.route_status = QLabel()
        self.refresh_routes_button = QPushButton("刷新路由表")
        self.refresh_routes_button.clicked.connect(self.refresh_routes)
        top.addWidget(self.route_status, 1)
        top.addWidget(self.refresh_routes_button)
        layout.addLayout(top)
        form = QFormLayout()
        self.route_destination = QLineEdit()
        self.route_gateway = QLineEdit()
        self.route_interface_index = self._spin(0, 99999, 0)
        self.route_metric = self._spin(0, 99999, 10)
        self.route_persistent = QCheckBox("持久路由")
        preview_add = QPushButton("生成添加命令")
        preview_add.clicked.connect(self.preview_add_route)
        preview_delete = QPushButton("生成删除命令")
        preview_delete.clicked.connect(self.preview_delete_route)
        execute_add = QPushButton("执行添加")
        execute_add.clicked.connect(self.execute_add_route)
        execute_delete = QPushButton("执行删除")
        execute_delete.clicked.connect(self.execute_delete_route)
        for button in (execute_add, execute_delete):
            button.setEnabled(is_admin())
        form.addRow("目标网络", self.route_destination)
        form.addRow("网关", self.route_gateway)
        form.addRow("接口索引", self.route_interface_index)
        form.addRow("跃点数 Metric", self.route_metric)
        form.addRow(self.route_persistent)
        buttons = QHBoxLayout()
        for button in (preview_add, preview_delete, execute_add, execute_delete):
            buttons.addWidget(button)
        form.addRow(buttons)
        layout.addLayout(form)
        self.route_status.setText("管理员权限：是" if is_admin() else "管理员权限：否，仅可查看路由和生成命令预览")
        return page

    def _connect(self) -> None:
        self.export_csv_button.clicked.connect(lambda: self.export_current("csv"))
        self.export_xlsx_button.clicked.connect(lambda: self.export_current("xlsx"))
        self.clear_button.clicked.connect(self.clear_results)

    def calculate_ipv4(self) -> None:
        self._show_rows([ipv4_calculate(self.ipv4_edit.text())], "ipv4_calc", summary_title="IPv4 计算")

    def calculate_ipv6(self) -> None:
        self._show_rows([ipv6_calculate(self.ipv6_edit.text())], "ipv6_calc", summary_title="IPv6 计算")

    def calculate_vlsm(self) -> None:
        result = plan_vlsm(self.vlsm_parent_edit.text(), self.vlsm_requests_edit.toPlainText())
        self._show_table_result(result, "vlsm")

    def calculate_subnets(self) -> None:
        result = split_subnets(self.subnet_parent_edit.text(), self.subnet_prefix_spin.value(), page_size=self.subnet_page_size_spin.value())
        self._show_table_result(result, "subnet_split")

    def calculate_route_summary(self) -> None:
        self._show_table_result(summarize_routes(self.summary_input.toPlainText()), "route_summary")

    def calculate_wildcard(self) -> None:
        self._show_table_result(wildcard_calculate(self.wildcard_input.toPlainText()), "wildcard")

    def run_single_ping(self) -> None:
        self._run_async(
            lambda: [asdict(run_single_ping(self.single_ping_target.text(), count=self.single_ping_count.value(), size=self.single_ping_size.value(), timeout_ms=self.single_ping_timeout.value()))],
            "ping_result",
        )

    def run_continuous_sample(self) -> None:
        self._run_async(
            lambda: [asdict(run_single_ping(self.continuous_ping_target.text(), count=1, size=self.continuous_ping_size.value(), timeout_ms=self.continuous_ping_timeout.value()))],
            "ping_result",
        )

    def run_batch_ping(self) -> None:
        count = 1 if self.batch_ping_mode.currentIndex() == 0 else 4
        targets = self.batch_ping_targets.toPlainText().splitlines()
        self._run_async(lambda: [asdict(row) for row in run_batch_ping(targets, count=count, timeout_ms=self.batch_ping_timeout.value(), concurrency=self.batch_ping_concurrency.value())], "ping_result")

    def run_network_ping(self) -> None:
        import ipaddress

        network = ipaddress.ip_network(self.network_ping_cidr.text(), strict=False)
        hosts = list(network.hosts()) if self.network_ping_usable_only.isChecked() else list(network)
        if len(hosts) > 4096:
            QMessageBox.warning(self, "网段 Ping", "单次扫描最大地址数为 4096，请缩小范围。")
            return
        targets = [str(host) for host in hosts]
        self._run_async(lambda: [asdict(row) for row in run_batch_ping(targets, count=1, concurrency=self.network_ping_threads.value())], "network_ping")

    def run_tcp_ping(self) -> None:
        def task() -> list[dict[str, object]]:
            rows = [run_tcp_ping(self.tcp_target.text(), self.tcp_port.value(), timeout_seconds=self.tcp_timeout.value()) for _ in range(self.tcp_count.value())]
            return [asdict(row) for row in rows]

        self._run_async(task, "tcp_ping")

    def refresh_routes(self) -> None:
        self._run_async(lambda: [asdict(row) for row in list_local_routes()], "local_routes")

    def preview_add_route(self) -> None:
        command = build_add_route_command(
            self.route_destination.text(),
            self.route_gateway.text(),
            interface_index=self.route_interface_index.value() or None,
            metric=self.route_metric.value() or None,
            persistent=self.route_persistent.isChecked(),
        )
        self.summary_text.setPlainText(command)

    def preview_delete_route(self) -> None:
        command = build_delete_route_command(self.route_destination.text(), self.route_gateway.text(), interface_index=self.route_interface_index.value() or None)
        self.summary_text.setPlainText(command)

    def execute_add_route(self) -> None:
        self.preview_add_route()
        self._execute_route_command(self.summary_text.toPlainText())

    def execute_delete_route(self) -> None:
        self.preview_delete_route()
        self._execute_route_command(self.summary_text.toPlainText())

    def _execute_route_command(self, command: str) -> None:
        if not is_admin():
            QMessageBox.warning(self, "本机路由", "需要以管理员身份运行才能修改路由。")
            return
        if QMessageBox.question(self, "本机路由", f"确认执行？\n{command}") != QMessageBox.Yes:
            return
        result = execute_powershell(command)
        self.status_label.setText("执行完成" if result.returncode == 0 else "执行失败")
        self.summary_text.setPlainText(result.stdout or result.stderr)
        self.refresh_routes()

    def _show_table_result(self, result, prefix: str) -> None:
        if result.errors:
            self.status_label.setText("计算失败")
            self.summary_text.setPlainText("\n".join(result.errors))
            self._show_rows([], prefix)
            return
        self._show_rows(result.rows, prefix, result.summary)

    def _run_async(self, fn, prefix: str) -> None:
        if self.thread is not None:
            QMessageBox.information(self, "小工具", "已有任务正在执行，请等待完成。")
            return
        self.status_label.setText("执行中...")
        self.thread = QThread(self)
        self.worker = _Worker(fn)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(lambda payload, error, p=prefix: self._async_finished(payload, error, p))
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self._thread_finished)
        self.thread.start()

    def _async_finished(self, payload, error: str, prefix: str) -> None:
        if error:
            self.status_label.setText("执行失败")
            self.summary_text.setPlainText(error)
            return
        self._show_rows(payload or [], prefix)

    def _thread_finished(self) -> None:
        self.thread = None
        self.worker = None

    def _show_rows(self, rows: list[dict[str, object]], prefix: str, summary: dict[str, object] | None = None, *, summary_title: str = "") -> None:
        normalized = [_normalize_row(row) for row in rows]
        self.current_rows = normalized
        self.current_export_prefix = prefix
        headers: list[str] = []
        for row in normalized:
            for key in row:
                if key not in headers:
                    headers.append(key)
        self.current_headers = headers
        self.result_table.setColumnCount(len(headers))
        self.result_table.setHorizontalHeaderLabels(headers)
        self.result_table.setRowCount(len(normalized))
        for row_index, row in enumerate(normalized):
            for column, header in enumerate(headers):
                self.result_table.setItem(row_index, column, QTableWidgetItem(str(row.get(header, ""))))
        self.result_table.resizeColumnsToContents()
        summary_lines = [summary_title] if summary_title else []
        if summary:
            summary_lines.extend(f"{key}: {value}" for key, value in summary.items())
        self.summary_text.setPlainText("\n".join(summary_lines))
        self.status_label.setText(f"结果 {len(normalized)} 条")

    def export_current(self, suffix: str) -> None:
        if not self.current_headers:
            QMessageBox.information(self, "导出", "没有可导出的结果。")
            return
        export_dir = self.paths.toolbox_outputs_dir(self.site_name)
        default = export_dir / f"{self.current_export_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{suffix}"
        filter_text = "Excel (*.xlsx)" if suffix == "xlsx" else "CSV (*.csv)"
        selected, _filter = QFileDialog.getSaveFileName(self, "导出结果", str(default), filter_text)
        if not selected:
            return
        path = Path(selected)
        if suffix == "xlsx":
            export_rows_xlsx(path, self.current_headers, self.current_rows)
        else:
            export_rows_csv(path, self.current_headers, self.current_rows)
        QMessageBox.information(self, "导出", f"已导出：{path}")

    def clear_results(self) -> None:
        self.current_rows = []
        self.current_headers = []
        self.result_table.setRowCount(0)
        self.result_table.setColumnCount(0)
        self.summary_text.clear()
        self.status_label.setText("已清空")

    @staticmethod
    def _spin(minimum: int, maximum: int, value: int) -> QSpinBox:
        spin = NoWheelSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        return spin


def _normalize_row(row: object) -> dict[str, object]:
    if is_dataclass(row):
        return asdict(row)
    if isinstance(row, dict):
        return row
    return {"value": row}
