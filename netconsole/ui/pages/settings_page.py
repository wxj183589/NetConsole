from __future__ import annotations

import traceback
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QWheelEvent
from PySide6.QtWidgets import QFileDialog, QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget

from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore, normalize_external_terminal_type
from netconsole.core.sites import Site
from netconsole.ui.shell.fluent_bridge import ComboBox, InfoBar, InfoBarPosition, SpinBox, SwitchButton


THEME_LABELS = {
    "浅色": "light",
    "深色": "dark",
    "跟随系统": "auto",
}

LANGUAGE_LABELS = {
    "中文": "zh_CN",
    "English": "en_US",
}

THEME_COLOR_LABELS = {
    "Windows 蓝 #0078D4": "#0078D4",
    "工程蓝 #2563EB": "#2563EB",
    "青色 #0891B2": "#0891B2",
    "绿色 #16A34A": "#16A34A",
}

EXTERNAL_TERMINAL_LABELS = {
    "PuTTY": "putty",
    "SecureCRT": "securecrt",
    "Xshell": "xshell",
}


class NoWheelSettingsComboBox(ComboBox if ComboBox is not None else QComboBox):
    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt override
        view = self.view() if hasattr(self, "view") else None
        if view is not None and view.isVisible():
            super().wheelEvent(event)
            return
        event.ignore()


class NoWheelSettingsSpinBox(SpinBox if SpinBox is not None else QSpinBox):
    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt override
        event.ignore()


class NoWheelSettingsDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt override
        event.ignore()


class SettingsPage(QWidget):
    def __init__(
        self,
        settings: SettingsStore,
        site: Site,
        paths: PathResolver,
        *,
        apply_theme_callback=None,
        apply_language_callback=None,
        create_site_callback=None,
        switch_site_callback=None,
        disk_cleanup_callback=None,
        changelog_callback=None,
        open_source_callback=None,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.site = site
        self.paths = paths
        self.apply_theme_callback = apply_theme_callback
        self.apply_language_callback = apply_language_callback
        self.create_site_callback = create_site_callback
        self.switch_site_callback = switch_site_callback
        self.disk_cleanup_callback = disk_cleanup_callback
        self.changelog_callback = changelog_callback
        self.open_source_callback = open_source_callback
        self.dirty = False
        self.setObjectName("settingsPage")

        self.theme_combo = self._combo()
        self.theme_combo.addItems(list(THEME_LABELS))
        self.language_combo = self._combo()
        self.language_combo.addItems(list(LANGUAGE_LABELS))
        self.theme_color_combo = self._combo()
        self.theme_color_combo.addItems(list(THEME_COLOR_LABELS))
        self.mica_switch = self._switch()
        self.compact_table_switch = self._switch()
        self.default_concurrency_spin = self._spin(1, 500, self.settings.int_value("default_concurrency", 10, 1, 500))
        self.command_timeout_spin = self._spin(1, 600, self.settings.int_value("command_timeout", 30, 1, 600))
        self.log_retention_spin = self._spin(1, 3650, self.settings.int_value("log_retention_days", 30, 1, 3650))
        self.raw_echo_log_switch = self._switch()
        self.download_dir_edit = QLineEdit(str(self.settings.get_value("download_dir", "")))
        self.backup_dir_edit = QLineEdit(str(self.settings.get_value("backup_dir", "")))
        self.report_dir_edit = QLineEdit(str(self.settings.get_value("report_dir", "")))
        self.iperf3_path_edit = QLineEdit(str(self.settings.get_value("network_tools/iperf_path", "")))
        self.fping_path_edit = QLineEdit(str(self.settings.get_value("online_mr.fping_path", "")))
        self.mib_dir_edit = QLineEdit(str(self.settings.get_value("mib_dir", "")))
        self.external_terminal_type_combo = self._combo()
        self.external_terminal_type_combo.addItems(list(EXTERNAL_TERMINAL_LABELS))
        self.external_terminal_path_edit = QLineEdit()
        self.crt_session_dir_edit = QLineEdit(str(self.settings.get_value("external_terminal/securecrt_sessions_root", "")))
        self.ssh_port_spin = self._spin(1, 65535, self.settings.int_value("external_terminal/default_ssh_port", 22, 1, 65535))
        self.telnet_port_spin = self._spin(1, 65535, self.settings.int_value("external_terminal/default_telnet_port", 23, 1, 65535))
        self.crt_encoding_combo = self._combo()
        self.crt_encoding_combo.addItems(["UTF-8", "GBK"])
        self.site_name_label = QLabel(site.name)
        self.site_dir_label = QLabel(str(paths.site_dir(site.name)))

        self._build_ui()
        self._load_values()
        self._connect_signals()

    def update_site(self, site: Site) -> None:
        self.site = site
        self.site_name_label.setText(site.name)
        self.site_dir_label.setText(str(self.paths.site_dir(site.name)))

    def save_settings(self) -> None:
        try:
            self.settings.set_theme(THEME_LABELS.get(self.theme_combo.currentText(), "light"))
            language = LANGUAGE_LABELS.get(self.language_combo.currentText(), "zh_CN")
            self.settings.set_language(language)
            self.settings.set_theme_color(THEME_COLOR_LABELS.get(self.theme_color_combo.currentText(), "#0078D4"))
            self.settings.set_mica_enabled(self._is_checked(self.mica_switch))
            self.settings.set_compact_table(self._is_checked(self.compact_table_switch))
            self.settings.set_int_value("default_concurrency", self.default_concurrency_spin.value(), 1, 500)
            self.settings.set_int_value("command_timeout", self.command_timeout_spin.value(), 1, 600)
            self.settings.set_int_value("log_retention_days", self.log_retention_spin.value(), 1, 3650)
            self.settings.set_value("raw_echo_log", self._is_checked(self.raw_echo_log_switch))
            self.settings.set_value("download_dir", self.download_dir_edit.text().strip())
            self.settings.set_value("backup_dir", self.backup_dir_edit.text().strip())
            self.settings.set_value("report_dir", self.report_dir_edit.text().strip())
            self.settings.set_value("network_tools/iperf_path", self.iperf3_path_edit.text().strip())
            self.settings.set_value("online_mr.fping_path", self.fping_path_edit.text().strip())
            self.settings.set_value("mib_dir", self.mib_dir_edit.text().strip())
            terminal_type = self._external_terminal_type()
            terminal_path = self.external_terminal_path_edit.text().strip()
            self.settings.set_value("external_terminal/type", terminal_type)
            if terminal_type == "putty":
                self.settings.set_value("external_terminal/putty_path", terminal_path)
            elif terminal_type == "xshell":
                self.settings.set_value("external_terminal/xshell_path", terminal_path)
            elif terminal_type == "securecrt":
                self.settings.set_value("external_terminal/securecrt_path", terminal_path)
            self.settings.set_value("external_terminal/securecrt_sessions_root", self.crt_session_dir_edit.text().strip())
            self.settings.set_int_value("external_terminal/default_ssh_port", self.ssh_port_spin.value(), 1, 65535)
            self.settings.set_int_value("external_terminal/default_telnet_port", self.telnet_port_spin.value(), 1, 65535)
            self.settings.set_value("external_terminal/crt_encoding", self.crt_encoding_combo.currentText())
            if self.apply_language_callback is not None:
                QTimer.singleShot(0, lambda selected_language=language: self.apply_language_callback(selected_language))
            self.dirty = False
            self._show_success("设置已保存", f"配置已写入：{self.settings.path}")
        except Exception as exc:
            detail = traceback.format_exc()
            app_logger.log_error("SETTINGS_SAVE_FAILED", detail)
            self._show_error("设置保存失败", str(exc))

    def reload_settings(self) -> None:
        self.settings.values = {**self.settings.values, **self.settings._read()}
        self._load_values()
        self.dirty = False

    def reset_defaults(self) -> None:
        self.theme_combo.setCurrentText("浅色")
        self.language_combo.setCurrentText("中文")
        self.theme_color_combo.setCurrentText("Windows 蓝 #0078D4")
        self._set_checked(self.mica_switch, False)
        self._set_checked(self.compact_table_switch, False)
        self.default_concurrency_spin.setValue(10)
        self.command_timeout_spin.setValue(30)
        self.log_retention_spin.setValue(30)
        self._set_checked(self.raw_echo_log_switch, True)
        for edit in (self.download_dir_edit, self.backup_dir_edit, self.report_dir_edit, self.iperf3_path_edit, self.fping_path_edit, self.mib_dir_edit):
            edit.clear()
        self.external_terminal_type_combo.setCurrentText("SecureCRT")
        self.external_terminal_path_edit.clear()
        self._mark_dirty()

    def open_config_dir(self) -> None:
        self.settings.path.parent.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.settings.path.parent)))

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 0, 10, 10)
        layout.setSpacing(12)

        layout.addWidget(self._section("外观", [
            ("主题", "浅色 / 深色 / 跟随系统", self.theme_combo),
            ("语言", "中文 / English，部分界面重启后生效", self.language_combo),
            ("主题色", "Fluent 强调色", self.theme_color_combo),
            ("Mica 效果", "默认关闭，不支持时自动降级", self.mica_switch),
            ("紧凑表格模式", "降低表格行高，适合大数据浏览", self.compact_table_switch),
        ]))
        layout.addWidget(self._site_section())
        layout.addWidget(self._section("采集", [
            ("默认并发数", "后续接入现有采集参数", self.default_concurrency_spin),
            ("命令超时(秒)", "SSH/Telnet 命令读取超时", self.command_timeout_spin),
            ("日志保留天数", "历史日志清理策略", self.log_retention_spin),
            ("原始回显日志", "保存设备原始回显，便于排障", self.raw_echo_log_switch),
        ]))
        layout.addWidget(self._section("文件", [
            ("默认下载目录", "文件管理下载默认位置", self._path_row(self.download_dir_edit, directory=True)),
            ("配置备份目录", "配置采集备份目录", self._path_row(self.backup_dir_edit, directory=True)),
            ("报告导出目录", "分析报告导出目录", self._path_row(self.report_dir_edit, directory=True)),
        ]))
        layout.addWidget(self._section("工具路径 / 外部终端", [
            ("iperf3.exe", "iperf 带宽测试工具路径", self._path_row(self.iperf3_path_edit, directory=False)),
            ("Fping_v3.exe", "高频 Ping 工具路径", self._path_row(self.fping_path_edit, directory=False)),
            ("MIB 目录", "SNMP MIB 资源目录", self._path_row(self.mib_dir_edit, directory=True)),
            ("外部终端类型", "设备外部登录工具", self.external_terminal_type_combo),
            ("外部终端程序路径", "PuTTY / SecureCRT / Xshell 程序路径", self._path_row(self.external_terminal_path_edit, directory=False)),
            ("CRT 会话目录", "生成 SecureCRT 会话文件的根目录", self._path_row(self.crt_session_dir_edit, directory=True)),
            ("默认 SSH 端口", "新设备外部终端默认 SSH 端口", self.ssh_port_spin),
            ("默认 Telnet 端口", "新设备外部终端默认 Telnet 端口", self.telnet_port_spin),
            ("生成 CRT 会话编码", "SecureCRT 会话配置编码", self.crt_encoding_combo),
        ]))
        layout.addWidget(self._maintenance_section())
        layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _section(self, title: str, rows: list[tuple[str, str, QWidget]]) -> QWidget:
        section = QWidget()
        section.setObjectName("ncCard")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)
        label = QLabel(title)
        label.setObjectName("fluentPageTitle")
        layout.addWidget(label)
        for row_label, description, widget in rows:
            layout.addWidget(self._setting_row(row_label, description, widget))
        return section

    def _site_section(self) -> QWidget:
        section = QWidget()
        section.setObjectName("ncCard")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)
        label = QLabel("局点")
        label.setObjectName("fluentPageTitle")
        layout.addWidget(label)
        buttons = QHBoxLayout()
        for text, callback in (("新建局点", self.create_site_callback), ("切换局点", self.switch_site_callback), ("打开局点目录", self._open_site_dir)):
            button = QPushButton(text)
            button.setMinimumWidth(96)
            if callback is not None:
                button.clicked.connect(callback)
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addWidget(self._setting_row("当前局点", "当前数据目录绑定的局点", self.site_name_label))
        layout.addWidget(self._setting_row("局点目录", "当前局点本地数据路径", self.site_dir_label))
        button_row = QWidget()
        button_row.setLayout(buttons)
        layout.addWidget(self._setting_row("局点操作", "新建、切换或打开当前局点目录", button_row))
        return section

    def _maintenance_section(self) -> QWidget:
        section = QWidget()
        section.setObjectName("ncCard")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)
        label = QLabel("维护与关于")
        label.setObjectName("fluentPageTitle")
        layout.addWidget(label)
        layout.addWidget(
            self._setting_row(
                "磁盘清理",
                "清理软件运行缓存、临时文件和过期运行日志，不删除采集数据",
                self._button_row(("打开磁盘清理", self.disk_cleanup_callback)),
            )
        )
        layout.addWidget(
            self._setting_row(
                "版本更新日志",
                "查看 NetConsole 各版本新增、优化和修复内容",
                self._button_row(("查看更新日志", self.changelog_callback)),
            )
        )
        layout.addWidget(
            self._setting_row(
                "开源许可",
                "查看第三方开源组件、版本和许可证信息",
                self._button_row(("查看开源许可", self.open_source_callback)),
            )
        )
        return section

    def _button_row(self, *buttons: tuple[str, object]) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for text, callback in buttons:
            button = QPushButton(text)
            button.setMinimumWidth(128)
            button.setEnabled(callable(callback))
            if callable(callback):
                button.clicked.connect(callback)
            layout.addWidget(button)
        layout.addStretch(1)
        return row

    def _setting_row(self, title: str, description: str, control: QWidget) -> QWidget:
        row = QWidget()
        row.setObjectName("settingRow")
        row.setMinimumHeight(70)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(16)
        text_area = QWidget()
        text_layout = QVBoxLayout(text_area)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)
        title_label = QLabel(title)
        title_label.setObjectName("settingRowTitle")
        description_label = QLabel(description)
        description_label.setObjectName("settingRowDescription")
        description_label.setWordWrap(True)
        text_layout.addWidget(title_label)
        text_layout.addWidget(description_label)
        text_area.setMinimumWidth(220)
        text_area.setMaximumWidth(360)
        control.setMinimumWidth(260)
        control.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(text_area)
        layout.addWidget(control, 1)
        return row

    def _path_row(self, edit: QLineEdit, *, directory: bool) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        browse = QPushButton("浏览")
        browse.setFixedWidth(72)
        edit.setMinimumWidth(480)
        browse.clicked.connect(lambda: self._browse_path(edit, directory=directory))
        layout.addWidget(edit, 1)
        layout.addWidget(browse)
        return row

    def _connect_signals(self) -> None:
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        self.theme_color_combo.currentTextChanged.connect(self._on_theme_color_changed)
        for widget in (
            self.mica_switch,
            self.compact_table_switch,
            self.language_combo,
            self.default_concurrency_spin,
            self.command_timeout_spin,
            self.log_retention_spin,
            self.raw_echo_log_switch,
            self.download_dir_edit,
            self.backup_dir_edit,
            self.report_dir_edit,
            self.iperf3_path_edit,
            self.fping_path_edit,
            self.mib_dir_edit,
            self.external_terminal_type_combo,
            self.external_terminal_path_edit,
            self.crt_session_dir_edit,
            self.ssh_port_spin,
            self.telnet_port_spin,
            self.crt_encoding_combo,
        ):
            signal = (
                getattr(widget, "textChanged", None)
                or getattr(widget, "currentTextChanged", None)
                or getattr(widget, "valueChanged", None)
                or getattr(widget, "checkedChanged", None)
                or getattr(widget, "toggled", None)
            )
            if signal is not None:
                signal.connect(self._mark_dirty)

    def _load_values(self) -> None:
        reverse_theme = {value: label for label, value in THEME_LABELS.items()}
        self.theme_combo.setCurrentText(reverse_theme.get(self.settings.theme, "浅色"))
        reverse_language = {value: label for label, value in LANGUAGE_LABELS.items()}
        self.language_combo.setCurrentText(reverse_language.get(self.settings.language, "中文"))
        reverse_color = {value: label for label, value in THEME_COLOR_LABELS.items()}
        self.theme_color_combo.setCurrentText(reverse_color.get(self.settings.theme_color, "Windows 蓝 #0078D4"))
        self._set_checked(self.mica_switch, self.settings.mica_enabled)
        self._set_checked(self.compact_table_switch, self.settings.compact_table)
        self._set_checked(self.raw_echo_log_switch, bool(self.settings.get_value("raw_echo_log", True)))
        self.external_terminal_type_combo.setCurrentText(self._external_terminal_label())
        self.external_terminal_path_edit.setText(self._external_terminal_path())
        self.crt_session_dir_edit.setText(str(self.settings.get_value("external_terminal/securecrt_sessions_root", "") or ""))
        self.ssh_port_spin.setValue(self.settings.int_value("external_terminal/default_ssh_port", 22, 1, 65535))
        self.telnet_port_spin.setValue(self.settings.int_value("external_terminal/default_telnet_port", 23, 1, 65535))
        self.crt_encoding_combo.setCurrentText(str(self.settings.get_value("external_terminal/crt_encoding", "UTF-8") or "UTF-8"))

    def _on_theme_changed(self, text: str) -> None:
        theme = THEME_LABELS.get(text, "light")
        if self.apply_theme_callback is not None:
            QTimer.singleShot(0, lambda: self.apply_theme_callback(theme))
        self._mark_dirty(True)

    def _on_theme_color_changed(self, text: str) -> None:
        self.settings.set_theme_color(THEME_COLOR_LABELS.get(text, "#0078D4"))
        if self.apply_theme_callback is not None:
            QTimer.singleShot(0, lambda: self.apply_theme_callback(self.settings.theme))
        self._mark_dirty(True)

    def _browse_path(self, edit: QLineEdit, *, directory: bool) -> None:
        if directory:
            value = QFileDialog.getExistingDirectory(self, "选择目录", edit.text() or str(Path.cwd()))
        else:
            value, _ = QFileDialog.getOpenFileName(self, "选择文件", edit.text() or str(Path.cwd()))
        if value:
            edit.setText(value)

    def _open_site_dir(self) -> None:
        path = self.paths.site_dir(self.site.name)
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _combo(self):
        return NoWheelSettingsComboBox()

    def _switch(self):
        return SwitchButton() if SwitchButton is not None else QCheckBox()

    def _spin(self, minimum: int, maximum: int, value: int):
        spin = NoWheelSettingsSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        if hasattr(spin, "setButtonSymbols"):
            spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        spin.setMinimumWidth(100)
        return spin

    def _external_terminal_type(self) -> str:
        return normalize_external_terminal_type(EXTERNAL_TERMINAL_LABELS.get(self.external_terminal_type_combo.currentText(), "securecrt"))

    def _external_terminal_label(self) -> str:
        mapping = {
            "putty": "PuTTY",
            "securecrt": "SecureCRT",
            "xshell": "Xshell",
        }
        terminal_type = normalize_external_terminal_type(self.settings.get_value("external_terminal/type", "securecrt"))
        return mapping.get(terminal_type, "SecureCRT")

    def _external_terminal_path(self) -> str:
        terminal_type = normalize_external_terminal_type(self.settings.get_value("external_terminal/type", "securecrt"))
        key = {
            "putty": "external_terminal/putty_path",
            "securecrt": "external_terminal/securecrt_path",
            "xshell": "external_terminal/xshell_path",
        }.get(terminal_type, "external_terminal/securecrt_path")
        return str(self.settings.get_value(key, "") or "")

    def _is_checked(self, widget) -> bool:
        return bool(widget.isChecked()) if hasattr(widget, "isChecked") else False

    def _set_checked(self, widget, checked: bool) -> None:
        if hasattr(widget, "setChecked"):
            widget.setChecked(bool(checked))

    def _mark_dirty(self, dirty: bool = True) -> None:
        self.dirty = dirty

    def _show_success(self, title: str, content: str) -> None:
        if InfoBar is not None:
            InfoBar.success(title=title, content=content, duration=2500, position=InfoBarPosition.TOP_RIGHT, parent=self.window())

    def _show_error(self, title: str, content: str) -> None:
        if InfoBar is not None:
            InfoBar.error(title=title, content=content, duration=4000, position=InfoBarPosition.TOP_RIGHT, parent=self.window())
