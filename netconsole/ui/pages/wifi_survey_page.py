from __future__ import annotations

from netconsole.ui.dialogs.message_service import MessageBox
from netconsole.ui.dialogs.input_dialog_service import InputDialog
import csv
import shutil
from pathlib import Path

from PySide6.QtCore import QPointF, Qt, QThread, Signal
from PySide6.QtGui import QBrush, QColor, QCursor, QImageReader, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from netconsole.core import app_logger
from netconsole.core.database import Database
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.repositories.wifi_survey_repository import WifiSurveyRepository
from netconsole.services.wifi_survey.heatmap import build_heatmap_samples, clean_rssi, generate_idw_heatmap, render_heatmap_png, rssi_to_color
from netconsole.ui.table_utils import configure_readable_table_columns
from netconsole.services.wifi_survey.scanner import WifiObservation, scan_wifi
from netconsole.services.wifi_survey.signal_query import SignalAtPoint, nearest_point_for_position, query_signal_at_position


class WifiScanThread(QThread):
    finished_ok = Signal(list)
    failed = Signal(str)

    def run(self) -> None:
        try:
            self.finished_ok.emit(scan_wifi())
        except Exception as exc:
            self.failed.emit(str(exc))


class FloorPlanView(QGraphicsView):
    floor_clicked = Signal(QPointF)

    def __init__(self) -> None:
        super().__init__()
        self.setRenderHints(self.renderHints())
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setMouseTracking(True)
        self.sampling_enabled = False
        self._press_pos = None

    def set_sampling_enabled(self, enabled: bool) -> None:
        self.sampling_enabled = enabled
        self.setDragMode(QGraphicsView.NoDrag if enabled else QGraphicsView.ScrollHandDrag)
        self.setCursor(QCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor))

    def wheelEvent(self, event) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:
        if self.sampling_enabled and event.button() == Qt.LeftButton:
            self.floor_clicked.emit(self.mapToScene(event.position().toPoint()))
            return
        if event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if not self.sampling_enabled and event.button() == Qt.LeftButton and self._press_pos is not None:
            release_pos = event.position().toPoint()
            if (release_pos - self._press_pos).manhattanLength() <= 3:
                self.floor_clicked.emit(self.mapToScene(release_pos))
        self._press_pos = None
        super().mouseReleaseEvent(event)


class SurveyPointItem(QGraphicsEllipseItem):
    def __init__(self, point: dict[str, object], color: QColor) -> None:
        x = float(point["x_px"])
        y = float(point["y_px"])
        super().__init__(x - 6, y - 6, 12, 12)
        self.point = point
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor("#1d4ed8"), 2))
        self.setZValue(30)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)


class WifiSurveyPage(QWidget):
    def __init__(self, i18n: I18n, site_name: str, paths: PathResolver) -> None:
        super().__init__()
        self.i18n = i18n
        self.site_name = site_name
        self.paths = paths
        self.repository = WifiSurveyRepository(Database(paths.site_db_path(site_name)))
        self.current_floor_plan: dict[str, object] | None = None
        self.current_session: dict[str, object] | None = None
        self.current_filter: tuple[str, str] | None = None
        self.floor_pixmap: QPixmap | None = None
        self.floor_item: QGraphicsPixmapItem | None = None
        self.heatmap_item: QGraphicsPixmapItem | None = None
        self.heatmap_pixmap: QPixmap | None = None
        self.point_items: list[QGraphicsItem] = []
        self.scale_points: list[QPointF] = []
        self.scale_mode = False
        self.interaction_mode = "query"
        self.scale_items: list[QGraphicsItem] = []
        self.scan_thread: WifiScanThread | None = None
        self.pending_sample_pos: QPointF | None = None
        self.last_heatmap_valid_count = 0

        self.scene = QGraphicsScene(self)
        self.view = FloorPlanView()
        self.view.setScene(self.scene)
        self.view.floor_clicked.connect(self.on_floor_clicked)
        self.legend_label = QLabel(self.view.viewport())
        self.legend_label.setObjectName("wifiSurveyLegend")
        self.legend_label.setStyleSheet(
            "QLabel#wifiSurveyLegend { background: rgba(17, 24, 39, 210); color: white; "
            "border-radius: 6px; padding: 8px; font-size: 12px; }"
        )
        self.legend_label.setTextFormat(Qt.RichText)
        self.legend_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.signal_popup = QFrame(self.view.viewport())
        self.signal_popup.setObjectName("wifiSignalPopup")
        self.signal_popup.setStyleSheet(
            "QFrame#wifiSignalPopup { background: rgba(15, 23, 42, 235); color: white; "
            "border: 1px solid rgba(255, 255, 255, 80); border-radius: 6px; }"
            "QLabel { color: white; } QTableWidget { background: white; color: #111827; }"
        )
        self.signal_popup.hide()
        self.signal_title = QLabel()
        self.signal_empty_label = QLabel("该位置暂无可用无线数据")
        self.signal_table = QTableWidget(0, 6)
        self.signal_table.setHorizontalHeaderLabels(["SSID/AP名称", "BSSID/AP_MAC", "频段", "信道", "RSSI", "类型"])
        configure_readable_table_columns(self.signal_table)
        self.signal_table.setColumnWidth(0, 180)
        self.signal_table.setColumnWidth(1, 150)
        self.signal_table.setMaximumHeight(260)
        self.signal_close_button = QPushButton("关闭")
        popup_layout = QVBoxLayout(self.signal_popup)
        title_row = QHBoxLayout()
        title_row.addWidget(self.signal_title, 1)
        title_row.addWidget(self.signal_close_button)
        popup_layout.addLayout(title_row)
        popup_layout.addWidget(self.signal_empty_label)
        popup_layout.addWidget(self.signal_table)
        self.signal_close_button.clicked.connect(self.signal_popup.hide)

        self.title_label = QLabel("无线测试 / WiFi Survey")
        self.title_label.setObjectName("pageTitle")
        self.floor_combo = QComboBox()
        self.session_combo = QComboBox()
        self.floor_info_label = QLabel("当前图纸：-")
        self.session_info_label = QLabel("当前会话：-")
        self.point_count_label = QLabel("采样点：0 个")
        self.heatmap_count_label = QLabel("当前热力图有效点：0")
        self.heatmap_mode_label = QLabel("当前模式：最强信号")
        self.filter_label = QLabel("当前筛选：-")
        self.scan_status_label = QLabel("扫描状态：空闲")
        self.scale_status_label = QLabel("比例尺设置：空闲")
        self.hint_label = QLabel("请先导入 PNG/JPG 图纸")
        self.hint_label.setAlignment(Qt.AlignCenter)

        self.import_button = QPushButton("导入图纸")
        self.session_button = QPushButton("新建会话")
        self.scale_button = QPushButton("设置比例尺")
        self.sample_button = QPushButton("开始采样")
        self.heatmap_button = QPushButton("生成热力图")
        self.clear_heatmap_button = QPushButton("清除热力图")
        self.export_image_button = QPushButton("导出图片")
        self.export_csv_button = QPushButton("导出CSV")
        self.network_tree = QTreeWidget()
        self.network_tree.setHeaderLabels(["SSID / BSSID", "信道", "最近RSSI"])
        self.detail_table = QTableWidget(0, 8)
        self.detail_table.setHorizontalHeaderLabels(["SSID", "BSSID", "RSSI(dBm估算)", "信道", "频率", "频段", "加密", "扫描时间"])
        configure_readable_table_columns(self.detail_table)
        for column, width in enumerate((180, 150, 130, 80, 90, 80, 120, 170)):
            self.detail_table.setColumnWidth(column, width)

        self._build_layout()
        self._connect_signals()
        self.reload_floor_plans()

    def set_site(self, site_name: str) -> None:
        self.site_name = site_name
        self.repository = WifiSurveyRepository(Database(self.paths.site_db_path(site_name)))
        self.current_floor_plan = None
        self.current_session = None
        self.current_filter = None
        self.clear_scene()
        self.reload_floor_plans()

    def retranslate(self) -> None:
        return

    def _build_layout(self) -> None:
        controls = QWidget()
        controls.setMinimumWidth(340)
        controls.setMaximumWidth(380)
        left = QVBoxLayout(controls)
        left.addWidget(self.title_label)
        left.addWidget(QLabel("图纸"))
        left.addWidget(self.floor_combo)
        left.addWidget(QLabel("会话"))
        left.addWidget(self.session_combo)
        for widget in (
            self.floor_info_label,
            self.session_info_label,
            self.point_count_label,
            self.heatmap_count_label,
            self.heatmap_mode_label,
            self.filter_label,
            self.scan_status_label,
            self.scale_status_label,
        ):
            left.addWidget(widget)
        for button in (
            self.import_button,
            self.session_button,
            self.scale_button,
            self.sample_button,
            self.heatmap_button,
            self.clear_heatmap_button,
            self.export_image_button,
            self.export_csv_button,
        ):
            button.setMinimumHeight(30)
            left.addWidget(button)
        left.addWidget(QLabel("SSID/BSSID 筛选"))
        left.addWidget(self.network_tree, 1)

        canvas = QWidget()
        canvas_layout = QVBoxLayout(canvas)
        canvas_layout.addWidget(self.hint_label)
        canvas_layout.addWidget(self.view, 1)
        canvas_layout.addWidget(QLabel("当前采样点详情"))
        canvas_layout.addWidget(self.detail_table)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(360)
        scroll.setMaximumWidth(400)
        scroll.setWidget(controls)

        splitter = QSplitter()
        splitter.addWidget(scroll)
        splitter.addWidget(canvas)
        splitter.setStretchFactor(1, 1)
        layout = QHBoxLayout(self)
        layout.addWidget(splitter)

    def _connect_signals(self) -> None:
        self.import_button.clicked.connect(self.import_floor_plan)
        self.session_button.clicked.connect(self.create_session)
        self.scale_button.clicked.connect(self.start_scale_mode)
        self.sample_button.clicked.connect(self.start_sample_mode)
        self.heatmap_button.clicked.connect(self.generate_heatmap)
        self.clear_heatmap_button.clicked.connect(self.clear_heatmap)
        self.export_image_button.clicked.connect(self.export_image)
        self.export_csv_button.clicked.connect(self.export_csv)
        self.floor_combo.currentIndexChanged.connect(self.on_floor_combo_changed)
        self.session_combo.currentIndexChanged.connect(self.on_session_combo_changed)
        self.network_tree.itemChanged.connect(self.on_network_tree_changed)

    def reload_floor_plans(self) -> None:
        self.floor_combo.blockSignals(True)
        self.floor_combo.clear()
        for plan in self.repository.list_floor_plans():
            self.floor_combo.addItem(str(plan["name"]), plan)
        self.floor_combo.blockSignals(False)
        if self.floor_combo.count():
            self.floor_combo.setCurrentIndex(0)
            self.load_floor_plan(self.floor_combo.currentData())
        else:
            self.update_status()

    def on_floor_combo_changed(self, index: int) -> None:
        if index >= 0:
            self.load_floor_plan(self.floor_combo.itemData(index))

    def load_floor_plan(self, plan: dict[str, object]) -> None:
        self.current_floor_plan = plan
        path = Path(str(plan["image_path"]))
        if not path.exists():
            MessageBox.warning(self, "无线测试", "图纸文件不存在，请重新导入图纸")
            self.clear_scene()
            return
        self.clear_scene(keep_floor=False)
        self.floor_pixmap = QPixmap(str(path))
        self.floor_item = self.scene.addPixmap(self.floor_pixmap)
        self.floor_item.setZValue(0)
        self.scene.setSceneRect(self.floor_pixmap.rect())
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        self.hint_label.setText("请先新建测试会话" if not self.repository.list_sessions(int(plan["id"])) else "")
        self.load_sessions()
        self.update_status()

    def load_sessions(self) -> None:
        self.session_combo.blockSignals(True)
        self.session_combo.clear()
        self.current_session = None
        if self.current_floor_plan is not None:
            for session in self.repository.list_sessions(int(self.current_floor_plan["id"])):
                self.session_combo.addItem(str(session["name"]), session)
        self.session_combo.blockSignals(False)
        if self.session_combo.count():
            self.session_combo.setCurrentIndex(0)
            self.load_session(self.session_combo.currentData())
        else:
            self.load_points()
            self.update_status()

    def on_session_combo_changed(self, index: int) -> None:
        if index >= 0:
            self.load_session(self.session_combo.itemData(index))

    def load_session(self, session: dict[str, object]) -> None:
        self.current_session = session
        self.current_filter = None
        self.clear_heatmap()
        self.load_points()
        self.load_network_tree()
        self.update_status()

    def import_floor_plan(self) -> None:
        path_text, _ = QFileDialog.getOpenFileName(self, "导入图纸", "", "Images (*.png *.jpg *.jpeg)")
        if not path_text:
            return
        source = Path(path_text)
        image_reader = QImageReader(str(source))
        size = image_reader.size()
        if not size.isValid():
            MessageBox.warning(self, "无线测试", "无法读取图纸文件")
            return
        target_dir = self.paths.wireless_scan_projects_dir(self.site_name) / "wifi_survey" / "floorplans"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / source.name
        counter = 1
        while target.exists():
            target = target_dir / f"{source.stem}_{counter}{source.suffix}"
            counter += 1
        shutil.copy2(source, target)
        plan = self.repository.create_floor_plan(source.stem, str(target), size.width(), size.height())
        self.reload_floor_plans()
        index = self.floor_combo.findData(plan)
        if index >= 0:
            self.floor_combo.setCurrentIndex(index)

    def create_session(self) -> None:
        if self.current_floor_plan is None:
            MessageBox.information(self, "无线测试", "请先导入图纸")
            return
        name, accepted = InputDialog.getText(self, "新建测试会话", "会话名称", QLineEdit.Normal, "WiFi Survey")
        if not accepted or not name.strip():
            return
        session = self.repository.create_session(int(self.current_floor_plan["id"]), name.strip())
        self.load_sessions()
        index = self.session_combo.findData(session)
        if index >= 0:
            self.session_combo.setCurrentIndex(index)

    def start_scale_mode(self) -> None:
        if self.current_floor_plan is None:
            MessageBox.information(self, "无线测试", "请先导入图纸")
            return
        self.set_interaction_mode("scale")
        self.clear_scale_items()
        self.scale_points = []
        self.scale_mode = True
        self.view.set_sampling_enabled(True)
        self.scale_button.setText("正在设置比例尺...")
        self.scale_status_label.setText("比例尺设置：请在图纸上点击第 1 个参考点")
        self.hint_label.setText("比例尺设置：请在图纸上点击第 1 个参考点")

    def start_sample_mode(self) -> None:
        if self.interaction_mode == "sample":
            self.set_interaction_mode("query")
            return
        if self.current_floor_plan is None:
            MessageBox.information(self, "无线测试", "请先导入图纸")
            return
        if self.current_session is None:
            MessageBox.information(self, "无线测试", "请先新建测试会话")
            return
        self.set_interaction_mode("sample")

    def set_interaction_mode(self, mode: str) -> None:
        self.interaction_mode = mode
        self.scale_mode = mode == "scale"
        self.view.set_sampling_enabled(mode in {"sample", "scale"})
        if mode == "sample":
            self.sample_button.setText("停止采样")
            self.hint_label.setText("采样模式：点击图纸新增采样点")
            self.scan_status_label.setText("采样模式：点击图纸新增采样点")
        elif mode == "scale":
            self.sample_button.setText("开始采样")
        else:
            self.sample_button.setText("开始采样")
            self.scale_button.setText("设置比例尺")
            self.scale_mode = False
            self.hint_label.setText("浏览/查询模式：点击图纸查看 AP/RSSI")

    def on_floor_clicked(self, pos: QPointF) -> None:
        if self.current_floor_plan is None or self.floor_pixmap is None:
            return
        if not self.floor_pixmap.rect().contains(int(pos.x()), int(pos.y())):
            return
        if self.interaction_mode == "scale":
            self.collect_scale_point(pos)
            return
        if self.current_session is None:
            MessageBox.information(self, "无线测试", "请先新建测试会话")
            return
        if self.interaction_mode == "sample":
            self.sample_at(pos)
        else:
            self.show_signal_popup(pos)

    def collect_scale_point(self, pos: QPointF) -> None:
        self.scale_points.append(pos)
        if len(self.scale_points) < 2:
            self.draw_scale_endpoint(pos)
            self.scale_status_label.setText("比例尺设置：请点击第 2 个参考点")
            self.hint_label.setText("比例尺设置：请点击第 2 个参考点")
            return
        p1, p2 = self.scale_points[:2]
        pixel_distance = ((p1.x() - p2.x()) ** 2 + (p1.y() - p2.y()) ** 2) ** 0.5
        if pixel_distance < 5:
            MessageBox.information(self, "设置比例尺", "两个参考点距离太近，请重新选择")
            self.clear_scale_items()
            self.scale_points = []
            self.scale_status_label.setText("比例尺设置：请在图纸上点击第 1 个参考点")
            self.hint_label.setText("比例尺设置：请在图纸上点击第 1 个参考点")
            return
        line_item = self.draw_scale_line(p1, p2)
        distance, accepted = InputDialog.getDouble(self, "设置比例尺", "请输入两点之间的实际距离（米）", 1.0, 0.01, 100000.0, 2)
        if not accepted:
            self.finish_scale_mode("比例尺设置已取消", clear_items=True)
            return
        meter_per_px = float(distance) / pixel_distance
        self.draw_scale_distance_label(p1, p2, distance)
        if line_item is not None:
            line_item.setToolTip(f"{distance:.2f} m / {pixel_distance:.1f} px")
        self.repository.update_floor_plan_scale(int(self.current_floor_plan["id"]), meter_per_px)
        self.current_floor_plan = self.repository.get_floor_plan(int(self.current_floor_plan["id"]))
        self.finish_scale_mode("比例尺设置完成", clear_items=False)
        self.update_status()

    def finish_scale_mode(self, status: str, *, clear_items: bool) -> None:
        self.scale_points = []
        self.scale_mode = False
        self.set_interaction_mode("query")
        self.scale_status_label.setText(status)
        self.hint_label.setText(status)
        if clear_items:
            self.clear_scale_items()

    def clear_scale_items(self) -> None:
        for item in self.scale_items:
            if item.scene() is self.scene:
                self.scene.removeItem(item)
        self.scale_items = []

    def draw_scale_endpoint(self, pos: QPointF) -> QGraphicsItem:
        item = self.scene.addEllipse(pos.x() - 7, pos.y() - 7, 14, 14, QPen(QColor("#facc15"), 3), QBrush(QColor("#2563eb")))
        item.setZValue(90)
        self.scale_items.append(item)
        return item

    def draw_scale_line(self, p1: QPointF, p2: QPointF) -> QGraphicsItem | None:
        self.clear_scale_items()
        self.draw_scale_endpoint(p1)
        self.draw_scale_endpoint(p2)
        line = self.scene.addLine(p1.x(), p1.y(), p2.x(), p2.y(), QPen(QColor("#facc15"), 3))
        line.setZValue(89)
        self.scale_items.append(line)
        return line

    def draw_scale_distance_label(self, p1: QPointF, p2: QPointF, distance: float) -> None:
        label = self.scene.addSimpleText(f"{distance:.2f} m")
        label.setBrush(QBrush(QColor("#facc15")))
        label.setPos((p1.x() + p2.x()) / 2 + 8, (p1.y() + p2.y()) / 2 + 8)
        label.setZValue(91)
        self.scale_items.append(label)

    def sample_at(self, pos: QPointF) -> None:
        if self.scan_thread is not None and self.scan_thread.isRunning():
            return
        points = self.repository.list_points(int(self.current_session["id"]))
        next_index = len(points) + 1
        self.pending_sample_pos = pos
        self.hint_label.setText(f"正在采集第 {next_index} 个点...")
        self.scan_status_label.setText("扫描状态：扫描中")
        self.sample_button.setEnabled(False)
        self.scan_thread = WifiScanThread()
        self.scan_thread.finished_ok.connect(self.on_scan_finished)
        self.scan_thread.failed.connect(self.on_scan_failed)
        self.scan_thread.start()

    def on_scan_finished(self, observations: list[WifiObservation]) -> None:
        self.sample_button.setEnabled(True)
        self.view.set_sampling_enabled(self.interaction_mode == "sample")
        if self.pending_sample_pos is None or self.current_session is None:
            return
        points = self.repository.list_points(int(self.current_session["id"]))
        plan_scale = self.current_floor_plan.get("meter_per_px") if self.current_floor_plan else None
        point = self.repository.create_point(
            int(self.current_session["id"]),
            len(points) + 1,
            float(self.pending_sample_pos.x()),
            float(self.pending_sample_pos.y()),
            float(plan_scale) if plan_scale else None,
        )
        self.repository.save_observations(int(point["id"]), observations)
        self.pending_sample_pos = None
        self.scan_status_label.setText("扫描状态：完成" if observations else "扫描状态：完成，未扫描到无线网络")
        self.load_points()
        self.load_network_tree()
        self.show_point_detail(point)
        self.update_status()

    def on_scan_failed(self, error: str) -> None:
        self.sample_button.setEnabled(True)
        self.view.set_sampling_enabled(self.interaction_mode == "sample")
        self.pending_sample_pos = None
        self.scan_status_label.setText("扫描状态：失败")
        MessageBox.warning(self, "无线测试", f"无线扫描失败，请确认 Windows WLAN 服务和无线网卡状态\n{error}")

    def load_points(self) -> None:
        for item in self.point_items:
            self.scene.removeItem(item)
        self.point_items = []
        if self.current_session is None:
            self.update_status()
            return
        points = self.repository.list_points(int(self.current_session["id"]))
        for point in points:
            color = self.point_color(point)
            item = SurveyPointItem(point, color)
            item.setToolTip(self.point_tooltip(point))
            item.mousePressEvent = lambda event, p=point: self.show_point_clicked(p)
            self.scene.addItem(item)
            text = QGraphicsSimpleTextItem(str(point["point_index"]))
            text.setBrush(QBrush(QColor("#0f172a")))
            text.setPos(float(point["x_px"]) + 8, float(point["y_px"]) - 8)
            text.setZValue(31)
            self.scene.addItem(text)
            self.point_items.extend([item, text])
        self.update_status()

    def point_color(self, point: dict[str, object]) -> QColor:
        if self.heatmap_pixmap is None and self.current_filter is None:
            return QColor("#2563eb")
        rssi = self.rssi_for_point(int(point["id"]))
        return rssi_to_color(rssi, 220)

    def point_tooltip(self, point: dict[str, object]) -> str:
        observations = self.repository.list_observations_by_point(int(point["id"]))
        rssi = self.rssi_for_point(int(point["id"]))
        strongest = self.strongest_rssi_for_point(int(point["id"]))
        scan_time = max((str(obs.get("scan_time") or "") for obs in observations), default="-") or "-"
        return (
            f"采样点 #{point['point_index']}\n"
            f"坐标：{float(point['x_px']):.1f}, {float(point['y_px']):.1f}\n"
            f"采样时间：{scan_time}\n"
            f"扫描到的 AP 数量：{len(observations)}\n"
            f"当前筛选 RSSI：{self.format_rssi(rssi)}\n"
            f"最强 RSSI：{self.format_rssi(strongest)}"
        )

    def strongest_rssi_for_point(self, point_id: int) -> float | None:
        values = [
            clean_rssi(obs.get("rssi_dbm"), obs.get("signal_quality"))
            for obs in self.repository.list_observations_by_point(point_id)
        ]
        numeric = [float(value) for value in values if value is not None]
        return max(numeric) if numeric else None

    def show_point_clicked(self, point: dict[str, object]) -> None:
        self.show_point_detail(point)
        self.show_signal_popup(QPointF(float(point["x_px"]), float(point["y_px"])))

    def show_point_detail(self, point: dict[str, object]) -> None:
        observations = self.repository.list_observations_by_point(int(point["id"]))
        self.detail_table.setRowCount(0)
        for obs in observations:
            row = self.detail_table.rowCount()
            self.detail_table.insertRow(row)
            values = [
                obs.get("ssid"),
                obs.get("bssid"),
                obs.get("rssi_dbm"),
                obs.get("channel"),
                obs.get("frequency_mhz"),
                obs.get("band"),
                obs.get("security"),
                obs.get("scan_time"),
            ]
            for column, value in enumerate(values):
                self.detail_table.setItem(row, column, QTableWidgetItem("" if value is None else str(value)))

    def show_signal_popup(self, pos: QPointF) -> None:
        if self.current_session is None:
            return
        points = self.repository.list_points(int(self.current_session["id"]))
        observations = self.repository.list_observations_by_session(int(self.current_session["id"]))
        _, selected_ssids, selected_bssids, _ = self.current_heatmap_selection()
        if self.current_filter is None:
            selected_ssids = set()
            selected_bssids = set()
        signals = query_signal_at_position(
            float(pos.x()),
            float(pos.y()),
            points,
            observations,
            selected_ssids=selected_ssids,
            selected_bssids=selected_bssids,
        )
        nearest = nearest_point_for_position(float(pos.x()), float(pos.y()), points)
        if nearest is not None:
            self.signal_title.setText(f"采样点 #{nearest['point_index']} - 实测信号")
        else:
            self.signal_title.setText("当前位置 - 估算信号")
        self.populate_signal_table(signals)
        viewport_pos = self.view.mapFromScene(pos)
        self.place_signal_popup(viewport_pos.x() + 14, viewport_pos.y() + 14)

    def populate_signal_table(self, signals: list[SignalAtPoint]) -> None:
        self.signal_table.setRowCount(0)
        self.signal_empty_label.setVisible(not signals)
        self.signal_table.setVisible(bool(signals))
        for signal in signals[:20]:
            row = self.signal_table.rowCount()
            self.signal_table.insertRow(row)
            values = [
                signal.ssid,
                signal.bssid,
                signal.band,
                "" if signal.channel is None else str(signal.channel),
                self.format_rssi(signal.rssi_dbm),
                signal.data_type,
            ]
            for column, value in enumerate(values):
                self.signal_table.setItem(row, column, QTableWidgetItem(value))

    def place_signal_popup(self, x: int, y: int) -> None:
        self.signal_popup.adjustSize()
        width = min(max(self.signal_popup.sizeHint().width(), 560), max(360, self.view.viewport().width() - 20))
        height = min(max(self.signal_popup.sizeHint().height(), 160), max(160, self.view.viewport().height() - 20))
        self.signal_popup.resize(width, height)
        x = max(8, min(x, self.view.viewport().width() - width - 8))
        y = max(8, min(y, self.view.viewport().height() - height - 8))
        self.signal_popup.move(x, y)
        self.signal_popup.show()
        self.signal_popup.raise_()

    @staticmethod
    def format_rssi(value: float | None) -> str:
        if value is None:
            return "-"
        if float(value).is_integer():
            return f"{int(value)} dBm"
        return f"{value:.1f} dBm"

    def load_network_tree(self) -> None:
        self.network_tree.blockSignals(True)
        self.network_tree.clear()
        if self.current_session is None:
            self.network_tree.blockSignals(False)
            return
        by_ssid: dict[str, list[dict[str, object]]] = {}
        for row in self.repository.list_network_tree(int(self.current_session["id"])):
            by_ssid.setdefault(str(row["ssid"]), []).append(row)
        for ssid, rows in by_ssid.items():
            parent = QTreeWidgetItem([ssid, "", ""])
            parent.setCheckState(0, Qt.Unchecked)
            parent.setData(0, Qt.UserRole, ("ssid", ssid))
            self.network_tree.addTopLevelItem(parent)
            for row in rows:
                child = QTreeWidgetItem([str(row["bssid"]), str(row.get("channel") or ""), str(row.get("latest_rssi") or "")])
                child.setCheckState(0, Qt.Unchecked)
                child.setData(0, Qt.UserRole, ("bssid", str(row["bssid"])))
                parent.addChild(child)
            parent.setExpanded(True)
        self.network_tree.blockSignals(False)

    def on_network_tree_changed(self, changed: QTreeWidgetItem, column: int) -> None:
        if column != 0:
            return
        if changed.checkState(0) != Qt.Checked:
            self.current_filter = None
            self.load_points()
            self.update_status()
            return
        self.network_tree.blockSignals(True)
        for index in range(self.network_tree.topLevelItemCount()):
            parent = self.network_tree.topLevelItem(index)
            if parent is not changed:
                parent.setCheckState(0, Qt.Unchecked)
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                if child is not changed:
                    child.setCheckState(0, Qt.Unchecked)
        self.network_tree.blockSignals(False)
        data = changed.data(0, Qt.UserRole)
        self.current_filter = tuple(data) if data else None
        self.load_points()
        self.update_status()

    def rssi_for_point(self, point_id: int) -> float | None:
        observations = self.repository.list_observations_by_point(point_id)
        if not observations:
            return None
        mode, selected_ssids, selected_bssids, _ = self.current_heatmap_selection()
        candidates = []
        for obs in observations:
            if mode == "strongest":
                candidates.append(clean_rssi(obs.get("rssi_dbm"), obs.get("signal_quality")))
            elif mode == "ssid" and str(obs.get("ssid") or "<hidden>") in selected_ssids:
                candidates.append(clean_rssi(obs.get("rssi_dbm"), obs.get("signal_quality")))
            elif mode == "bssid" and str(obs.get("bssid") or "").casefold() in selected_bssids:
                candidates.append(clean_rssi(obs.get("rssi_dbm"), obs.get("signal_quality")))
        numeric = [float(item) for item in candidates if item is not None]
        return max(numeric) if numeric else None

    def current_heatmap_selection(self) -> tuple[str, set[str], set[str], str]:
        if self.current_filter is None:
            return "strongest", set(), set(), "最强信号"
        mode, value = self.current_filter
        if mode == "ssid":
            return "ssid", {value}, set(), f"SSID {value}"
        if mode == "bssid":
            return "bssid", set(), {value}, f"BSSID {value}"
        return "strongest", set(), set(), "最强信号"

    def generate_heatmap(self) -> None:
        if self.floor_pixmap is None or self.current_session is None:
            return
        points = self.repository.list_points(int(self.current_session["id"]))
        observations = self.repository.list_observations_by_session(int(self.current_session["id"]))
        mode, selected_ssids, selected_bssids, mode_label = self.current_heatmap_selection()
        samples = build_heatmap_samples(points, observations, mode, selected_ssids, selected_bssids)
        app_logger.log_info(
            "WIFI_SURVEY_HEATMAP_SAMPLES",
            (
                f"session_id={self.current_session['id']} "
                f"floor_plan_id={self.current_floor_plan['id'] if self.current_floor_plan else '-'} "
                f"total_points={len(points)} selected_mode={mode} "
                f"selected_ssid={','.join(sorted(selected_ssids)) or '-'} "
                f"selected_bssid={','.join(sorted(selected_bssids)) or '-'} "
                f"valid_heatmap_points={len(samples)} "
                f"samples={[{'point_id': sample.point_id, 'rssi': sample.rssi_dbm} for sample in samples]}"
            ),
        )
        if len(samples) < 3:
            self.load_points()
            if mode == "ssid":
                message = "当前 SSID 有效采样点不足 3 个，无法生成该 SSID 热力图。可取消筛选生成最强信号热力图。"
            elif mode == "bssid":
                message = "当前 BSSID 有效采样点不足 3 个，无法生成该 AP 热力图。"
            else:
                message = "当前会话有效采样点不足 3 个，无法生成最强信号热力图。"
            MessageBox.information(self, "无线测试", message)
            self.update_status()
            return
        self.heatmap_pixmap = generate_idw_heatmap(
            self.floor_pixmap.width(),
            self.floor_pixmap.height(),
            [(sample.x_px, sample.y_px, sample.rssi_dbm) for sample in samples],
        )
        if self.heatmap_pixmap is None:
            return
        if self.heatmap_item is not None:
            self.scene.removeItem(self.heatmap_item)
        self.heatmap_item = self.scene.addPixmap(self.heatmap_pixmap)
        self.heatmap_item.setOpacity(0.72)
        self.heatmap_item.setZValue(10)
        self.last_heatmap_valid_count = len(samples)
        self.load_points()
        self.heatmap_mode_label.setText(f"当前模式：{mode_label}")
        self.heatmap_count_label.setText(f"当前热力图有效点：{len(samples)}")
        self.update_legend()

    def clear_heatmap(self) -> None:
        if self.heatmap_item is not None:
            self.scene.removeItem(self.heatmap_item)
            self.heatmap_item = None
        self.heatmap_pixmap = None
        self.last_heatmap_valid_count = 0
        self.load_points()
        self.update_legend()

    def export_image(self) -> None:
        if self.floor_pixmap is None:
            MessageBox.information(self, "无线测试", "请先导入图纸")
            return
        default = self._export_dir() / "wifi_survey_heatmap.png"
        path_text, _ = QFileDialog.getSaveFileName(self, "导出图片", str(default), "PNG (*.png)")
        if not path_text:
            return
        render_heatmap_png(self.floor_pixmap, self.heatmap_pixmap).save(path_text, "PNG")

    def export_csv(self) -> None:
        if self.current_session is None:
            MessageBox.information(self, "无线测试", "请先新建测试会话")
            return
        default = self._export_dir() / "wifi_survey_samples.csv"
        path_text, _ = QFileDialog.getSaveFileName(self, "导出CSV", str(default), "CSV (*.csv)")
        if not path_text:
            return
        rows = self.repository.list_observations_by_session(int(self.current_session["id"]))
        fields = [
            "session_name",
            "point_index",
            "x_px",
            "y_px",
            "x_meter",
            "y_meter",
            "scan_time",
            "ssid",
            "bssid",
            "rssi_dbm",
            "signal_quality",
            "channel",
            "frequency_mhz",
            "band",
            "security",
        ]
        with Path(path_text).open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: (self.current_session["name"] if field == "session_name" else row.get(field)) for field in fields})

    def _export_dir(self) -> Path:
        path = self.paths.wireless_scan_export_dir(self.site_name) / "wifi_survey"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def clear_scene(self, keep_floor: bool = False) -> None:
        self.scene.clear()
        self.floor_item = None
        self.heatmap_item = None
        self.heatmap_pixmap = None
        self.last_heatmap_valid_count = 0
        self.point_items = []
        self.scale_items = []
        self.scale_points = []
        self.scale_mode = False
        self.scale_button.setText("设置比例尺")
        if not keep_floor:
            self.floor_pixmap = None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.update_overlay_positions()

    def update_overlay_positions(self) -> None:
        if self.legend_label.isVisible():
            self.legend_label.adjustSize()
            self.legend_label.move(12, max(12, self.view.viewport().height() - self.legend_label.height() - 12))
            self.legend_label.raise_()
        if self.signal_popup.isVisible():
            self.place_signal_popup(self.signal_popup.x(), self.signal_popup.y())

    def update_legend(self) -> None:
        _, _, _, mode_label = self.current_heatmap_selection()
        filter_text = f"{self.current_filter[0].upper()} {self.current_filter[1]}" if self.current_filter else "最强信号"
        if self.heatmap_pixmap is None:
            title = "当前显示：采样点位置"
            detail = "蓝色圆点：已采集点位"
        else:
            title = f"当前热力图模式：{mode_label}"
            detail = f"当前筛选对象：{filter_text}<br>有效热力图采样点：{self.last_heatmap_valid_count}"
        self.legend_label.setText(
            f"<b>{title}</b><br>"
            f"{detail}<br>"
            f"<span style='color:#60a5fa'>●</span> 蓝色圆点：采样点<br>"
            f"<span style='color:#9ca3af'>●</span> 灰色圆点：当前筛选网络无数据<br>"
            f"<span style='color:#0a783c'>■</span> 绿色：信号强，&gt;= -55 dBm<br>"
            f"<span style='color:#3ab45a'>■</span> 黄绿色：良好，-56 ~ -67 dBm<br>"
            f"<span style='color:#eba52d'>■</span> 黄色/橙色：较弱，-68 ~ -78 dBm<br>"
            f"<span style='color:#dc5a37'>■</span> 红色：弱覆盖，&lt;= -80 dBm"
        )
        self.legend_label.show()
        self.update_overlay_positions()

    def update_status(self) -> None:
        floor_name = self.current_floor_plan["name"] if self.current_floor_plan else "-"
        session_name = self.current_session["name"] if self.current_session else "-"
        points = self.repository.list_points(int(self.current_session["id"])) if self.current_session else []
        point_count = len(points)
        mode, selected_ssids, selected_bssids, mode_label = self.current_heatmap_selection()
        observations = self.repository.list_observations_by_session(int(self.current_session["id"])) if self.current_session else []
        valid_count = len(build_heatmap_samples(points, observations, mode, selected_ssids, selected_bssids))
        filter_text = f"{self.current_filter[0].upper()} {self.current_filter[1]}" if self.current_filter else "最强信号"
        scale = self.current_floor_plan.get("meter_per_px") if self.current_floor_plan else None
        scale_text = f"（比例尺：{float(scale):.4f} m/px，1 px = {float(scale):.4f} m）" if scale else ""
        self.floor_info_label.setText(f"当前图纸：{floor_name}{scale_text}")
        self.session_info_label.setText(f"当前会话：{session_name}")
        self.point_count_label.setText(f"总采样点：{point_count}")
        self.heatmap_count_label.setText(f"当前热力图有效点：{valid_count}")
        self.heatmap_mode_label.setText(f"当前模式：{mode_label}")
        self.filter_label.setText(f"当前筛选：{filter_text}")
        if self.scale_mode:
            self.update_legend()
            return
        if self.current_floor_plan is None:
            self.hint_label.setText("请先导入 PNG/JPG 图纸")
        elif self.current_session is None:
            self.hint_label.setText("请先新建测试会话")
        self.update_legend()
