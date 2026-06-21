from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QWidget

from netconsole.core.i18n import I18n
from netconsole.ui.pagination import PAGE_SIZE_OPTIONS, PaginationState


class PaginationWidget(QWidget):
    pageChanged = Signal(int)
    pageSizeChanged = Signal(int)

    def __init__(self, i18n: I18n, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.state = PaginationState()
        self.page_size_combo = QComboBox()
        self.first_button = QPushButton()
        self.prev_button = QPushButton()
        self.page_label = QLabel()
        self.next_button = QPushButton()
        self.last_button = QPushButton()
        self.total_label = QLabel()
        self.jump_label = QLabel()
        self.page_jump_spin = QSpinBox()
        self.page_unit_label = QLabel()
        self.page_jump_button = QPushButton()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(self.i18n.t("pagination.page_size")))
        layout.addWidget(self.page_size_combo)
        layout.addWidget(self.first_button)
        layout.addWidget(self.prev_button)
        layout.addWidget(self.page_label)
        layout.addWidget(self.next_button)
        layout.addWidget(self.last_button)
        layout.addWidget(self.total_label)
        layout.addWidget(self.jump_label)
        layout.addWidget(self.page_jump_spin)
        layout.addWidget(self.page_unit_label)
        layout.addWidget(self.page_jump_button)
        layout.addStretch(1)

        for size in PAGE_SIZE_OPTIONS:
            self.page_size_combo.addItem(str(size), size)
        self.page_size_combo.currentIndexChanged.connect(self._emit_page_size)
        self.first_button.clicked.connect(lambda: self.pageChanged.emit(1))
        self.prev_button.clicked.connect(lambda: self.pageChanged.emit(max(self.state.current_page - 1, 1)))
        self.next_button.clicked.connect(lambda: self.pageChanged.emit(min(self.state.current_page + 1, self.state.total_pages)))
        self.last_button.clicked.connect(lambda: self.pageChanged.emit(self.state.total_pages))
        self.page_jump_button.clicked.connect(self._emit_jump_page)
        self.page_jump_spin.lineEdit().returnPressed.connect(self._emit_jump_page)
        self.retranslate()
        self.set_state(self.state)

    def retranslate(self) -> None:
        self.first_button.setText(self.i18n.t("pagination.first"))
        self.prev_button.setText(self.i18n.t("pagination.prev"))
        self.next_button.setText(self.i18n.t("pagination.next"))
        self.last_button.setText(self.i18n.t("pagination.last"))
        self.jump_label.setText(self.i18n.t("pagination.jump_to"))
        self.page_unit_label.setText(self.i18n.t("pagination.page_unit"))
        self.page_jump_button.setText(self.i18n.t("pagination.jump"))
        self.set_state(self.state)

    def set_state(self, state: PaginationState) -> None:
        self.state = state
        index = self.page_size_combo.findData(state.page_size)
        if index >= 0 and self.page_size_combo.currentIndex() != index:
            self.page_size_combo.blockSignals(True)
            self.page_size_combo.setCurrentIndex(index)
            self.page_size_combo.blockSignals(False)
        self.page_label.setText(self.i18n.t("pagination.page_label", current=state.current_page, total=state.total_pages))
        self.total_label.setText(self.i18n.t("pagination.total", total=state.total_items))
        self.page_jump_spin.blockSignals(True)
        self.page_jump_spin.setMinimum(1)
        self.page_jump_spin.setMaximum(max(state.total_pages, 1))
        self.page_jump_spin.setValue(max(min(state.current_page, max(state.total_pages, 1)), 1))
        self.page_jump_spin.blockSignals(False)
        at_first = state.current_page <= 1
        at_last = state.current_page >= state.total_pages
        self.first_button.setEnabled(not at_first)
        self.prev_button.setEnabled(not at_first)
        self.next_button.setEnabled(not at_last)
        self.last_button.setEnabled(not at_last)

    def _emit_page_size(self) -> None:
        self.pageSizeChanged.emit(int(self.page_size_combo.currentData() or 200))

    def _emit_jump_page(self) -> None:
        page = max(1, min(int(self.page_jump_spin.value()), max(self.state.total_pages, 1)))
        if page != self.state.current_page:
            self.pageChanged.emit(page)
