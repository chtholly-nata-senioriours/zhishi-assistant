# -*- coding: utf-8 -*-
"""交互对话框（统一玻璃拟态风格）

所有对话框继承 GlassDialog 基类，自动获得：
- 无边框 + 圆角毛玻璃卡片背景（可拖拽标题区）
- 统一的输入框/列表/滚动条样式（来自 glass_widgets 设计规范）
- 统一的间距与字体
"""
import subprocess
from pathlib import Path
from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QCheckBox, QFormLayout, QMessageBox, QInputDialog, QWidget,
    QDialogButtonBox, QTabWidget, QSizePolicy
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QColor, QMouseEvent

from tools.timer_tool import TomatoTimer
from tools.note_tool import NoteManager
from tools.quick_launch import QuickLaunch
from data.config_manager import config_manager
from data.log_manager import log_manager
from presentation.pet_model import model_manager
from presentation.glass_widgets import (
    GlassTheme, GlassButton, LiquidGlassButton, ToggleSwitch,
    SPACING, RADIUS, STATUS_COLOR, apply_dialog_style, paint_dialog_background,
)
from presentation.tray_icon import is_autostart_enabled, set_autostart


# ============================================================
# 统一对话框基类：圆角毛玻璃卡片 + 可拖拽
# ============================================================

class GlassDialog(QDialog):
    """所有交互对话框的统一基类"""

    def __init__(self, parent=None, dark: bool = False, title: str = ""):
        super().__init__(parent)
        self._theme = apply_dialog_style(self, dark=dark)
        self._drag_pos = None
        self._title = title
        self.setWindowTitle(title)

    def theme(self) -> GlassTheme:
        return self._theme

    def paintEvent(self, event):
        """绘制统一圆角毛玻璃背景"""
        paint_dialog_background(self, self._theme)

    # --- 无边框窗口的拖拽 ---
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 48:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_pos and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    # --- 供子类使用的统一组件 ---
    def make_title_bar(self, text: str) -> QWidget:
        """对话框标题栏：大标题 + 右侧关闭按钮（无边框窗口的退出入口）"""
        bar = QWidget(self)
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACING["sm"])

        lbl = QLabel(text)
        lbl.setFont(self._theme.font_bold)
        lbl.setStyleSheet(
            f"font-size: 16px; color: {self._theme.color('text').name()};"
        )
        row.addWidget(lbl)
        row.addStretch()

        btn_close = QPushButton("✕", bar)
        btn_close.setFixedSize(28, 28)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setToolTip("关闭")
        btn_close.setStyleSheet(f"""
            QPushButton {{
                border: none; border-radius: 14px;
                background: {self._theme.color('input_bg').name()};
                color: {self._theme.color('text_sec').name()};
                font-size: 13px;
            }}
            QPushButton:hover {{
                background: {STATUS_COLOR['offline']};
                color: #FFFFFF;
            }}
        """)
        btn_close.clicked.connect(self.reject)
        row.addWidget(btn_close)
        return bar

    def make_title_label(self, text: str) -> QLabel:
        """对话框大标题"""
        lbl = QLabel(text)
        lbl.setFont(self._theme.font_bold)
        lbl.setStyleSheet(
            f"font-size: 16px; color: {self._theme.color('text').name()};"
        )
        return lbl

    def make_section_label(self, text: str) -> QLabel:
        """分组小标题"""
        lbl = QLabel(text)
        lbl.setFont(self._theme.font_bold)
        lbl.setStyleSheet(f"color: {self._theme.color('text_sec').name()};")
        return lbl

    def make_status_label(self, text: str, color_key: str = "info") -> QLabel:
        """状态文字（带语义色圆点前缀）"""
        color = STATUS_COLOR.get(color_key, STATUS_COLOR["info"])
        lbl = QLabel(f'<span style="color:{color};">●</span> {text}')
        lbl.setFont(self._theme.font_bold)
        lbl.setTextFormat(Qt.TextFormat.RichText)
        return lbl


# ============================================================
# 番茄钟对话框
# ============================================================

class TomatoDialog(GlassDialog):
    """番茄钟对话框"""

    def __init__(self, timer: TomatoTimer, parent=None):
        super().__init__(parent, title="番茄钟")
        self.timer = timer
        self.setFixedSize(340, 280)

        self._setup_ui()
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(self._refresh)
        self._update_timer.start(1000)
        self._refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING["xl"], SPACING["lg"], SPACING["xl"], SPACING["lg"])
        layout.setSpacing(SPACING["md"])

        # 标题行 + 关闭提示
        layout.addWidget(self.make_title_bar("番茄钟"))
        layout.addSpacing(SPACING["xs"])

        # 时间显示（大号等宽感数字）
        self._time_label = QLabel("25:00")
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._time_label.setStyleSheet(
            f"font-size: 52px; font-weight: 600;"
            f"color: {self._theme.color('text').name()};"
        )
        layout.addWidget(self._time_label)

        # 状态标签
        self._status_label = QLabel("就绪")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setStyleSheet(
            f"color: {self._theme.color('text_sec').name()};"
        )
        layout.addWidget(self._status_label)

        layout.addStretch()

        # 控制按钮（玻璃胶囊按钮）
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(SPACING["sm"])
        self._btn_start = LiquidGlassButton("开始工作", primary=True, theme=self._theme)
        self._btn_pause = LiquidGlassButton("暂停", theme=self._theme)
        self._btn_resume = LiquidGlassButton("继续", primary=True, theme=self._theme)
        self._btn_stop = LiquidGlassButton("停止", theme=self._theme)
        self._btn_stop.set_danger(True)

        self._btn_start.clicked.connect(self._on_start)
        self._btn_pause.clicked.connect(self._on_pause)
        self._btn_resume.clicked.connect(self._on_resume)
        self._btn_stop.clicked.connect(self._on_stop)

        btn_layout.addWidget(self._btn_start)
        btn_layout.addWidget(self._btn_pause)
        btn_layout.addWidget(self._btn_resume)
        btn_layout.addWidget(self._btn_stop)
        layout.addLayout(btn_layout)

    def _refresh(self):
        """刷新显示"""
        status = self.timer.get_status()
        self._time_label.setText(status["formatted"])

        state = status["state"]
        if state == "idle":
            self._status_label.setText(f"就绪 · 今日完成 {status['today_count']} 个 🍅")
            self._time_label.setStyleSheet(
                f"font-size: 52px; font-weight: 600; color: {self._theme.color('text').name()};")
        elif state == "running":
            if status["type"] == "work":
                self._status_label.setText("专注中，加油！")
                self._time_label.setStyleSheet("font-size: 52px; font-weight: 600; color: #3B82F6;")
            else:
                self._status_label.setText("休息中，放松一下~")
                self._time_label.setStyleSheet("font-size: 52px; font-weight: 600; color: #34C759;")
        elif state == "paused":
            self._status_label.setText("已暂停")
            self._time_label.setStyleSheet("font-size: 52px; font-weight: 600; color: #FF9F0A;")
        elif state == "finished":
            self._status_label.setText("已完成！")

        self._btn_start.setVisible(state == "idle" or state == "finished")
        self._btn_pause.setVisible(state == "running")
        self._btn_resume.setVisible(state == "paused")
        self._btn_stop.setVisible(state in ("running", "paused"))

    def _on_start(self):
        self.timer.start("work")

    def _on_pause(self):
        self.timer.pause()

    def _on_resume(self):
        self.timer.resume()

    def _on_stop(self):
        self.timer.stop()

    def closeEvent(self, event):
        self._update_timer.stop()
        super().closeEvent(event)


# ============================================================
# 便签对话框
# ============================================================

class NoteDialog(GlassDialog):
    """便签对话框"""

    def __init__(self, note_manager: NoteManager, parent=None):
        super().__init__(parent, title="便签")
        self.note_manager = note_manager
        self.setFixedSize(440, 400)

        self._setup_ui()
        self._refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING["xl"], SPACING["lg"], SPACING["xl"], SPACING["lg"])
        layout.setSpacing(SPACING["md"])

        layout.addWidget(self.make_title_bar("便签"))
        layout.addSpacing(SPACING["xs"])

        # 便签列表
        self._list = QListWidget()
        self._list.setAlternatingRowColors(False)
        self._list.itemDoubleClicked.connect(self._on_edit_note)
        layout.addWidget(self._list, stretch=1)

        # 按钮（玻璃胶囊）
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(SPACING["sm"])
        btn_new = GlassButton("新建便签", primary=True, theme=self._theme)
        btn_delete = LiquidGlassButton("删除选中", theme=self._theme)
        btn_delete.set_danger(True)
        btn_refresh = GlassButton("刷新", theme=self._theme)

        btn_new.clicked.connect(self._on_new_note)
        btn_delete.clicked.connect(self._on_delete_note)
        btn_refresh.clicked.connect(self._refresh)

        btn_layout.addWidget(btn_new)
        btn_layout.addWidget(btn_delete)
        btn_layout.addWidget(btn_refresh)
        layout.addLayout(btn_layout)

    def _refresh(self):
        """刷新便签列表"""
        self._list.clear()
        theme_c = self._theme.color("text_sec").name()
        for note in self.note_manager.get_all_notes():
            prefix = "[完成] " if note.completed else "[待办] "
            text = f"{prefix}{note.title}  ({note.created_at[:10]})"
            item = QListWidgetItem(text)
            if note.completed:
                item.setForeground(QColor("#8A99B0"))
            item.setData(Qt.ItemDataRole.UserRole, note.id)
            item.setToolTip(note.content or "无内容")
            self._list.addItem(item)

    def _on_new_note(self):
        """新建便签"""
        title, ok = QInputDialog.getText(self, "新建便签", "标题:")
        if ok and title.strip():
            content, ok2 = QInputDialog.getMultiLineText(self, "新建便签", "内容:")
            if ok2:
                self.note_manager.create_note(title.strip(), content)
                self._refresh()

    def _on_edit_note(self, item):
        """编辑便签"""
        note_id = item.data(Qt.ItemDataRole.UserRole)
        note = self.note_manager.get_note(note_id)
        if note:
            title, ok = QInputDialog.getText(self, "编辑便签", "标题:", text=note.title)
            if ok and title.strip():
                content, ok2 = QInputDialog.getMultiLineText(self, "编辑便签", "内容:", text=note.content)
                if ok2:
                    self.note_manager.update_note(note_id, title=title.strip(), content=content)
                    if not note.completed:
                        self.note_manager.complete_note(note_id)
                    self._refresh()

    def _on_delete_note(self):
        """删除选中便签"""
        item = self._list.currentItem()
        if item:
            note_id = item.data(Qt.ItemDataRole.UserRole)
            reply = QMessageBox.question(self, "确认删除", "确定删除此便签吗？",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.note_manager.delete_note(note_id)
                self._refresh()


# ============================================================
# 快捷启动对话框
# ============================================================

class LaunchDialog(GlassDialog):
    """快捷启动对话框"""

    def __init__(self, launcher: QuickLaunch, parent=None):
        super().__init__(parent, title="快捷启动")
        self.launcher = launcher
        self.setFixedSize(420, 380)

        self._setup_ui()
        self._refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING["xl"], SPACING["lg"], SPACING["xl"], SPACING["lg"])
        layout.setSpacing(SPACING["md"])

        layout.addWidget(self.make_title_bar("快捷启动"))
        layout.addSpacing(SPACING["xs"])

        # 分类选择
        self._category_combo = QComboBox()
        self._category_combo.currentTextChanged.connect(self._refresh)
        layout.addWidget(self._category_combo)

        # 启动项列表（双击直接启动）
        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._on_launch)
        layout.addWidget(self._list, stretch=1)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(SPACING["sm"])
        btn_launch = GlassButton("启动选中", primary=True, theme=self._theme)
        btn_refresh = GlassButton("刷新", theme=self._theme)

        btn_launch.clicked.connect(self._on_launch_selected)
        btn_refresh.clicked.connect(self._refresh)

        btn_layout.addWidget(btn_launch)
        btn_layout.addWidget(btn_refresh)
        layout.addLayout(btn_layout)

    def _refresh(self):
        """刷新列表"""
        # 更新分类下拉（临时断开信号，避免 setCurrentIndex 触发递归）
        self._category_combo.currentTextChanged.disconnect(self._refresh)
        current_cat = self._category_combo.currentText()
        self._category_combo.clear()
        self._category_combo.addItem("全部")
        for cat in self.launcher.get_categories():
            self._category_combo.addItem(cat)
        idx = self._category_combo.findText(current_cat)
        if idx >= 0:
            self._category_combo.setCurrentIndex(idx)
        self._category_combo.currentTextChanged.connect(self._refresh)

        # 刷新列表
        self._list.clear()
        items = self.launcher.get_all_items()
        selected_cat = self._category_combo.currentText()
        if selected_cat != "全部":
            items = [i for i in items if i.category == selected_cat]

        for item in items:
            text = f"{item.name}  [{item.category}]" if item.category else item.name
            list_item = QListWidgetItem(text)
            list_item.setData(Qt.ItemDataRole.UserRole, item.id)
            list_item.setToolTip(f"命令: {item.command}")
            self._list.addItem(list_item)

    def _on_launch(self, item):
        """双击启动"""
        item_id = item.data(Qt.ItemDataRole.UserRole)
        self.launcher.launch(item_id)

    def _on_launch_selected(self):
        """按钮启动"""
        item = self._list.currentItem()
        if item:
            self._on_launch(item)


# ============================================================
# 设置对话框
# ============================================================

class SettingsDialog(GlassDialog):
    """设置对话框"""

    def __init__(self, parent=None):
        super().__init__(parent, title="设置")
        self.setFixedSize(420, 380)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING["xl"], SPACING["lg"], SPACING["xl"], SPACING["lg"])
        layout.setSpacing(SPACING["md"])

        layout.addWidget(self.make_title_bar("设置"))
        layout.addSpacing(SPACING["xs"])

        tabs = QTabWidget()
        tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {self._theme.color('input_border').name()};
                border-radius: {RADIUS['md']}px;
                background: {self._theme.color('surface_hover').name()};
            }}
            QTabBar::tab {{
                padding: 6px 16px;
                border-radius: {RADIUS['sm']}px;
                color: {self._theme.color('text_sec').name()};
            }}
            QTabBar::tab:selected {{
                background: {self._theme.color('primary').name()};
                color: #FFFFFF;
            }}
        """)

        # 行为设置
        behavior_tab = QWidget()
        b_layout = QFormLayout(behavior_tab)
        b_layout.setSpacing(SPACING["sm"])

        self._idle_spin = QSpinBox()
        self._idle_spin.setRange(5, 600)
        self._idle_spin.setValue(config_manager.get("behavior.idle_threshold", 30))
        b_layout.addRow("进入放松（秒）:", self._idle_spin)

        self._sleep_spin = QSpinBox()
        self._sleep_spin.setRange(30, 3600)
        self._sleep_spin.setValue(config_manager.get("behavior.sleep_threshold", 300))
        b_layout.addRow("进入休眠（秒）:", self._sleep_spin)

        self._focus_spin = QSpinBox()
        self._focus_spin.setRange(10, 300)
        self._focus_spin.setValue(config_manager.get("behavior.focus_threshold", 60))
        b_layout.addRow("专注阈值 (次/30秒):", self._focus_spin)

        self._sound_check = QCheckBox("启用音效")
        self._sound_check.setChecked(config_manager.get("behavior.sound_enabled", True))
        b_layout.addRow(self._sound_check)

        # 开机自启开关（勾选态读注册表实况）
        self._sw_autostart = ToggleSwitch("开机自启动（静默启动到托盘）", theme=self._theme)
        self._sw_autostart.setChecked(is_autostart_enabled())
        b_layout.addRow(self._sw_autostart)

        tabs.addTab(behavior_tab, "行为")

        # 番茄钟设置
        tomato_tab = QWidget()
        t_layout = QFormLayout(tomato_tab)
        t_layout.setSpacing(SPACING["sm"])

        self._work_spin = QSpinBox()
        self._work_spin.setRange(1, 120)
        self._work_spin.setValue(config_manager.get("tomato.work_duration", 25))
        t_layout.addRow("工作时长（分）:", self._work_spin)

        self._break_spin = QSpinBox()
        self._break_spin.setRange(1, 60)
        self._break_spin.setValue(config_manager.get("tomato.break_duration", 5))
        t_layout.addRow("休息时长（分）:", self._break_spin)

        tabs.addTab(tomato_tab, "番茄钟")

        # 外观设置
        appear_tab = QWidget()
        a_layout = QFormLayout(appear_tab)
        a_layout.setSpacing(SPACING["sm"])

        self._pet_name_edit = QLineEdit(config_manager.get("appearance.pet_name", "小宠"))
        a_layout.addRow("宠物名字:", self._pet_name_edit)

        # 宠物模型选择
        self._model_combo = QComboBox()
        self._model_combo.addItem("默认", "")
        for m in model_manager.get_available_models():
            self._model_combo.addItem(m["name"], m["id"])
        current_model = config_manager.get("appearance.pet_model", "")
        idx = self._model_combo.findData(current_model)
        if idx >= 0:
            self._model_combo.setCurrentIndex(idx)
        a_layout.addRow("宠物模型:", self._model_combo)

        self._opacity_spin = QDoubleSpinBox()
        self._opacity_spin.setRange(0.3, 1.0)
        self._opacity_spin.setSingleStep(0.05)
        self._opacity_spin.setValue(max(0.3, config_manager.get("window.opacity", 0.9)))
        a_layout.addRow("透明度:", self._opacity_spin)

        tabs.addTab(appear_tab, "外观")

        layout.addWidget(tabs, stretch=1)

        # 保存/取消按钮（玻璃胶囊，替代系统默认按钮盒）
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(SPACING["sm"])
        btn_layout.addStretch()
        btn_cancel = GlassButton("取消", theme=self._theme)
        btn_save = GlassButton("保存", primary=True, theme=self._theme)
        btn_cancel.clicked.connect(self.reject)
        btn_save.clicked.connect(self._save)
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)

    def _save(self):
        """保存设置"""
        config_manager.set("behavior.idle_threshold", self._idle_spin.value())
        config_manager.set("behavior.sleep_threshold", self._sleep_spin.value())
        config_manager.set("behavior.focus_threshold", self._focus_spin.value())
        config_manager.set("behavior.sound_enabled", self._sound_check.isChecked())
        config_manager.set("tomato.work_duration", self._work_spin.value())
        config_manager.set("tomato.break_duration", self._break_spin.value())
        config_manager.set("appearance.pet_name", self._pet_name_edit.text())
        config_manager.set("window.opacity", self._opacity_spin.value())

        # 开机自启（注册表即时生效）
        set_autostart(self._sw_autostart.isChecked())

        # 宠物模型切换
        new_model = self._model_combo.currentData() or ""
        old_model = config_manager.get("appearance.pet_model", "")
        config_manager.set("appearance.pet_model", new_model)
        config_manager.save()

        # 如果模型变了，立即应用
        if new_model != old_model:
            parent = self.parent()
            if hasattr(parent, '_ui_manager') and parent._ui_manager:
                parent._ui_manager.apply_pet_model(new_model)
            elif hasattr(parent, 'apply_pet_model'):
                parent.apply_pet_model(new_model)

        QMessageBox.information(self, "设置", "设置已保存")
        self.accept()
