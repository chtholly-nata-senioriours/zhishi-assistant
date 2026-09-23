"""UI渲染器模块

负责创建和管理桌宠的UI窗口，包括：
- 半透明显示窗口
- 桌宠静态图片/GIF显示
- 右键菜单
- 气泡提示
- 位置控制

使用 PySide6 实现跨平台窗口渲染。

注意：
    - 窗口使用 Qt.WA_TranslucentBackground 实现透明背景
    - 窗口无标题栏，支持拖拽移动
    - 支持 DPI 适配
"""

import sys
import os
from pathlib import Path
from typing import Optional, Tuple, List, Callable

from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QMenu, QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QMessageBox
)
from PySide6.QtCore import Qt, QTimer, QPoint, QPropertyAnimation, QEasingCurve, Signal, QObject
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QCursor, QAction

from event_bus import event_bus
from data.config_manager import config_manager
from data.log_manager import log_manager
from presentation.pet_model import model_manager


class PetWindow(QWidget):
    """桌宠主窗口 - 无标题栏、半透明、可拖拽"""

    # 信号
    clicked = Signal(QPoint)
    dragged = Signal(QPoint)
    rightClicked = Signal(QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)

        # 窗口属性
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |       # 无边框
            Qt.WindowType.WindowStaysOnTopHint |     # 置顶
            Qt.WindowType.Tool                         # 工具窗口（不在任务栏显示）
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        # 窗口大小和位置（从配置读取，拖动结束保存，下次启动恢复）
        self._size = config_manager.get("window.size", [200, 200])[0] if config_manager.get("window.size") else 200
        self.setFixedSize(self._size, self._size)
        position = config_manager.get("window.position", [100, 200])
        if isinstance(position, (list, tuple)) and len(position) == 2:
            self.move(int(position[0]), int(position[1]))
        else:
            self.move(100, 200)

        # 拖拽支持
        self._drag_pos = None

        # 动画组件
        self._anim_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._anim_effect)

        # 透明度（从配置读取，限制在可见范围 0.3~1.0，防止配置过低导致看不见）
        self._opacity = max(0.3, min(1.0, float(config_manager.get("window.opacity", 0.9))))
        self.setWindowOpacity(self._opacity)

        # 气泡提示
        self._bubble = None

        # 初始化UI
        self._setup_ui()

        # 加载默认图片
        self._load_default_image()

    def _setup_ui(self):
        """初始化UI组件"""
        # 主布局
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 10, 10, 10)
        self._layout.setSpacing(0)

        # 图片显示
        self._image_label = QLabel(self)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setScaledContents(True)
        self._layout.addWidget(self._image_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # 提示文字（浮在图片上层，不参与布局，避免挤压精灵图）
        self._text_label = QLabel(self)
        self._text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text_label.setStyleSheet("""
            color: #333;
            font-size: 12px;
            background: rgba(255, 255, 255, 180);
            border-radius: 8px;
            padding: 4px 8px;
        """)
        self._text_label.hide()
        self._text_label.setFixedWidth(160)
        self._text_label.setWordWrap(False)

    def _load_default_image(self, model_name: str = None):
        """加载默认图片（按当前宠物模型）"""
        img_path = model_manager.find_default_image(model_name)
        if img_path:
            self.set_image(img_path)
            # 缓存当前默认图路径
            self._default_image_path = img_path
        else:
            self._show_placeholder()
            self._default_image_path = None

    def _show_placeholder(self):
        """占位不再需要，直接使用待机精灵图"""
        pass

    def set_image(self, image_path: str):
        """
        设置桌宠显示的图片

        Args:
            image_path: 图片路径
        """
        if not os.path.exists(image_path):
            print(f"图片不存在: {image_path}")
            return

        self._current_image = image_path
        pixmap = QPixmap(image_path)

        # 缩放以适应窗口
        scaled = pixmap.scaled(
            self._size - 20, self._size - 20,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self._image_label.setPixmap(scaled)
        self._text_label.hide()

    def show_text(self, text: str, duration: int = 3000):
        """
        显示文字气泡（浮动在精灵图上层，不参与布局）

        Args:
            text: 要显示的文本
            duration: 显示时长（毫秒）
        """
        self._text_label.setText(text)
        # 定位到窗口顶部居中
        text_w = self._text_label.width()
        x = (self.width() - text_w) // 2
        self._text_label.move(x, 5)
        self._text_label.show()

        # 定时隐藏
        QTimer.singleShot(duration, self._text_label.hide)

    # ----- 鼠标事件 -----

    def mousePressEvent(self, event):
        """鼠标按下"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.clicked.emit(event.globalPosition().toPoint())
            event_bus.publish("PET_CLICKED", {"x": event.globalPosition().x(), "y": event.globalPosition().y()})

        elif event.button() == Qt.MouseButton.RightButton:
            self.rightClicked.emit(event.globalPosition().toPoint())
            self._show_context_menu(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event):
        """鼠标拖动"""
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos:
            new_pos = event.globalPosition().toPoint() - self._drag_pos
            self.move(new_pos)
            self.dragged.emit(new_pos)
            event_bus.publish("PET_DRAGGED", {"x": new_pos.x(), "y": new_pos.y()})

    def mouseReleaseEvent(self, event):
        """鼠标释放"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = None
            self._image_label.setStyleSheet("")
            # 拖动结束保存位置，下次启动恢复
            pos = self.pos()
            config_manager.set("window.position", [pos.x(), pos.y()])
            config_manager.save()

    def _show_context_menu(self, pos: QPoint):
        """显示右键菜单（菜单项来自插件系统）"""
        menu = QMenu(self)

        ui_mgr = self._get_ui_manager()
        if ui_mgr and ui_mgr.plugin_manager:
            actions = ui_mgr.plugin_manager.get_menu_actions()
            # 按 category 分组，不同组之间加分隔线
            last_cat = None
            for act in actions:
                if last_cat and act.category != last_cat:
                    menu.addSeparator()
                qact = QAction(act.name, self)
                # 包一层异常捕获+日志：windowed exe（console=False）下
                # 未捕获异常会被静默吞掉，表现为"点了没反应"
                qact.triggered.connect(
                    lambda checked=False, cb=act.callback, name=act.name: self._run_menu_action(name, cb)
                )
                menu.addAction(qact)
                last_cat = act.category
        else:
            # 后备：至少保留退出
            qact = QAction("退出", self)
            qact.triggered.connect(self._quit_app)
            menu.addAction(qact)

        menu.popup(QCursor.pos())

    def _run_menu_action(self, name: str, callback):
        """执行插件菜单回调，异常记录日志而非静默吞掉"""
        try:
            callback()
        except Exception as e:
            import traceback
            log_manager.error(f"菜单项 [{name}] 执行失败: {e}\n{traceback.format_exc()}")
            QMessageBox.warning(self, "插件错误", f"菜单项 [{name}] 打开失败：\n{e}")

    def _quit_app(self):
        """退出应用"""
        QApplication.instance().quit()

    def closeEvent(self, event):
        """关闭拦截：默认最小化到托盘（配置 window.close_to_tray 控制）

        真正退出走托盘菜单/右键菜单的「退出」（app.stop → app.quit，
        quit 不会触发 closeEvent，不会递归）。
        """
        if config_manager.get("window.close_to_tray", True):
            event.ignore()
            self.hide()
            # 首次隐藏时气泡提示（托盘图标可能尚未就绪，容错）
            tray = getattr(self, "_tray_icon", None)
            if tray:
                tray.show_message("小小桌宠", "我藏到系统托盘里啦，双击托盘图标唤出我~")
        else:
            super().closeEvent(event)

    def _get_ui_manager(self):
        """获取UIManager实例"""
        return getattr(self, '_ui_manager', None)

    def set_window_opacity(self, opacity: float):
        """
        设置窗口透明度

        Args:
            opacity: 0.0 - 1.0
        """
        self._opacity = max(0.3, min(1.0, opacity))
        self.setWindowOpacity(self._opacity)


class UIManager(QObject):
    """UI管理器 - 管理整个表现层的UI"""

    # 跨线程安全信号：状态回调在事件发布者线程执行，UI 操作必须转回主线程
    _text_requested = Signal(str, int)

    def __init__(self):
        super().__init__()
        self.app = None
        self.window = None
        self._initialized = False
        self.anim_controller = None
        self.plugin_manager = None  # 由 PluginManager 注入
        self._text_requested.connect(self._show_text_on_window)

    def set_plugin_manager(self, pm):
        """注入插件管理器"""
        self.plugin_manager = pm

    def set_anim_controller(self, controller):
        """注入动画控制器"""
        self.anim_controller = controller
        # 连接 AnimController 的文字请求信号到 PetWindow.show_text()
        if controller and self.window:
            controller.text_requested.connect(
                lambda text, sec: self.window.show_text(text, int(sec * 1000))
            )
            # 连接窗口作为数值动画的目标控件
            controller.set_target_widget(self.window)

    def apply_pet_model(self, model_name: str = None):
        """
        切换宠物模型，重载所有资源

        Args:
            model_name: 模型名，None 或 "" 使用默认
        """
        if model_name is None:
            model_name = config_manager.get("appearance.pet_model", "")

        model_manager.current_model = model_name

        # 1. 重载窗口默认图
        if self.window:
            self.window._load_default_image(model_name)

        # 2. 重载动画资源
        if self.anim_controller:
            asset_dir = model_manager.get_current_asset_dir()
            default_img = model_manager.get_current_default_image()
            self.anim_controller.reload_assets(str(asset_dir), default_img)

        print(f"  宠物模型切换: {'默认' if not model_name else model_name}")

    def initialize(self):
        """初始化UI（必须在主线程中调用）"""
        if self._initialized:
            return

        # DPI 适配必须在 QApplication 创建之前设置才生效
        if QApplication.instance() is None:
            QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling)
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.app.setApplicationName("PetDemo")
        self.app.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

        self.window = PetWindow()
        self.window._ui_manager = self  # 让PetWindow能找到UIManager

        # 加载当前配置的宠物模型
        self.apply_pet_model()

        # 注册事件监听
        self._setup_event_listeners()

        self._initialized = True

    def _setup_event_listeners(self):
        """设置事件监听器"""
        # 动画播放由 AnimController 通过事件总线独立处理，UIManager 只负责UI反馈
        event_bus.subscribe("REQUEST_SOUND", self._on_request_sound)
        event_bus.subscribe("STATE_CHANGE", self._on_state_change)

    def _on_state_change(self, event):
        """状态变更 → 显示气泡文字"""
        data = event.get("data", {})
        to_state = data.get("to", "")
        state_texts = {
            "focus":    "加油！我在陪你~",
            "relax":    "休息一下吧~",
            "sleep":    "我先睡会儿...",
            "interact": "嘿嘿！",
            "idle":     "我在看着你哦",
        }
        text = state_texts.get(to_state, "")
        if text:
            # 状态回调可能在非主线程执行，通过信号转回主线程操作 UI
            self._text_requested.emit(text, 2500)

    def _show_text_on_window(self, text: str, duration_ms: int):
        """在主线程显示气泡文字"""
        if self.window:
            self.window.show_text(text, duration_ms)

    def show(self):
        """显示窗口"""
        if self.window:
            self.window.show()

    def run(self):
        """进入事件循环"""
        if self.app:
            self.app.exec()

    def _on_request_sound(self, event):
        """处理音效请求"""
        data = event.get("data", {})
        sound_type = data.get("type", "")
        print(f"播放音效: {sound_type}")


