# -*- coding: utf-8 -*-
"""AI 唤起面板 —— 产品的主交互面（L3）。

设计要点（对应执行框架 §8）
    - **预热常驻**：启动期构建控件树后隐藏待命，绝不每次重建。
      S3 spike 实测：冷构建 63ms vs 预热唤起 5.8ms，差 10 倍。
    - **双焦点模式**（ADR-3）：
        show_for_input()  需要键盘输入 → 激活窗口、抢焦点
        show_passive()    只展示结果 → WA_ShowWithoutActivating，不打断用户
    - **不碰业务**：面板只发信号（submitted / cancelled / delivery_requested），
      AI 调用、投递都由插件层负责。面板不知道 provider 的存在。
    - **投递只有一个按钮**：复制到剪贴板。曾有过「替换原文 / 粘贴到前台」，
      2026-10-12 移除 —— 它们依赖向外部应用注入 Ctrl+V，在受限会话 / 提权
      窗口下会**静默失败**，而代码无从察觉（见 `AGENTS.md` §4.6）。

样式
    面板不自己拼颜色 —— 它直接用应用样式表（`theme().qss()`），
    其中 `#aiCard` / `#aiTitle` / `#aiInput` / `#aiAction` 等规则已经定义好。
    于是「面板与对话框风格一致」是**结构上**保证的，而不是靠人工对齐数值。
    （早期版本在这里写死了一份深色 QSS，点 ⚙ 会弹出一张白卡片盖在深色面板上。）

窗口层级
    面板带 `WindowStaysOnTopHint`，与对话框同处「置顶层」；
    点击时经 `RaiseOnClickMixin` 提到该层最前，保证「点哪个哪个在上」。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .design import icons
from .design.theme import THEME_DARK, THEME_LIGHT, theme
from .design.tokens import SPACING
from .design.widgets import Button, IconButton
from .markdown_view import MarkdownView
from .window_behavior import RaiseOnClickMixin

MODE_TITLES = {
    "ask": "AI 问答",
    "translate": "划词翻译",
    "capture": "截图问答",
}

MODE_PLACEHOLDERS = {
    "ask": "问点什么…（Enter 发送，Esc 关闭）",
    "translate": "选中文本后按 Alt+T 直接翻译",
    "capture": "按 Alt+S 框选屏幕区域",
}

#: 标题行图标按钮的边长
_ICON_BTN = 24


class _ThemeToggleButton(IconButton):
    """昼夜切换：浅色时显示月亮，深色时显示太阳。"""

    def __init__(self, parent=None):
        super().__init__("moon", "切换浅色 / 深色主题", parent, size=_ICON_BTN)
        self._dark = theme().dark
        self.refresh_theme()

    def refresh_theme(self) -> None:
        self._dark = theme().dark
        self._icon_name = "sun" if self._dark else "moon"
        super().refresh_theme()


class AIPanel(RaiseOnClickMixin, QWidget):
    """唤起面板。"""

    submitted = Signal(str)              # 用户提交的文本
    cancelled = Signal()                 # Esc / 关闭
    delivery_requested = Signal(str)     # 目前只有 "copy"（见 §4.6）
    settings_requested = Signal()        # 点击齿轮：请求打开 AI 服务设置
    theme_changed = Signal(str)          # 面板内切换了明暗主题（主题名）

    def __init__(self, parent=None):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._theme = theme()
        self._mode = "ask"
        self._drag_pos: QPoint | None = None
        self._pinned = False
        self._streaming = False
        self._has_result = False

        self._build_ui()
        self.apply_theme()

    # ------------------------------------------------------------ 主题

    def apply_theme(self) -> None:
        """按当前应用主题重设样式表。

        自绘控件（图标按钮）订阅了 `theme().changed`，会自己重取图标；
        这里只需要把样式表换成新主题生成的那一份。
        """
        self._theme = theme()
        self.setStyleSheet(theme().qss())
        self.update()

    def _on_toggle_theme(self) -> None:
        """面板内的昼夜切换 —— 直接改 `appearance.theme` 并立即生效。

        对话框的颜色在构造时就烘焙进样式表了，所以**已打开的**对话框
        不会跟着变；下次打开即一致。面板是常驻的，所以必须当场重设样式。
        """
        from .design import set_theme

        new_name = THEME_LIGHT if theme().dark else THEME_DARK
        set_theme(new_name)
        self.apply_theme()
        self.theme_changed.emit(new_name)

    # ------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        card = QFrame(self)
        card.setObjectName("aiCard")
        root.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(SPACING["md"], SPACING["sm"], SPACING["md"], SPACING["md"])
        lay.setSpacing(SPACING["sm"])

        # --- 标题行 ---
        title_row = QHBoxLayout()
        title_row.setSpacing(SPACING["xs"])
        self._title = QLabel(MODE_TITLES["ask"], card)
        self._title.setObjectName("aiTitle")
        title_row.addWidget(self._title)

        self._hint = QLabel("", card)
        self._hint.setObjectName("aiHint")
        title_row.addWidget(self._hint)
        title_row.addStretch()

        self._btn_theme = _ThemeToggleButton(card)
        self._btn_theme.clicked.connect(self._on_toggle_theme)
        title_row.addWidget(self._btn_theme)

        self._btn_settings = IconButton("gear", "AI 服务设置：切换服务商 / 模型 / 填 API Key", card,
                                        size=_ICON_BTN)
        self._btn_settings.clicked.connect(self._on_settings)
        title_row.addWidget(self._btn_settings)

        self._btn_pin = IconButton("pin", "钉住：失焦不自动关闭", card, size=_ICON_BTN)
        self._btn_pin.setCheckable(True)
        self._btn_pin.toggled.connect(self._on_pin)
        title_row.addWidget(self._btn_pin)

        self._btn_close = IconButton("close", "关闭（Esc）", card, danger=True, size=_ICON_BTN)
        self._btn_close.clicked.connect(self._on_close)
        title_row.addWidget(self._btn_close)

        lay.addLayout(title_row)

        # --- 输出区 ---
        self._output = MarkdownView(card)
        self._output.setObjectName("aiOutput")
        lay.addWidget(self._output, 1)

        # --- 投递按钮行（有结果时才显示）---
        # 2026-10-12：只保留「复制」。「替换原文 / 粘贴到前台」已移除 —— 见 §4.6。
        self._actions = QWidget(card)
        act_row = QHBoxLayout(self._actions)
        act_row.setContentsMargins(0, 0, 0, 0)
        act_row.setSpacing(SPACING["sm"])
        btn = QPushButton("复制", self._actions)
        btn.setObjectName("aiAction")
        btn.setIcon(icons.themed("copy", "text_secondary", 14))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda _=False: self.delivery_requested.emit("copy"))
        act_row.addWidget(btn)
        act_row.addStretch()
        self._actions.hide()
        lay.addWidget(self._actions)

        # --- 输入区上方的一条发丝分隔线 ---
        self._sep = QFrame(card)
        self._sep.setObjectName("aiSep")
        self._sep.setFrameShape(QFrame.Shape.NoFrame)
        self._sep.setFixedHeight(1)
        lay.addWidget(self._sep)

        # --- 输入行 ---
        self._input = QLineEdit(card)
        self._input.setObjectName("aiInput")
        self._input.returnPressed.connect(self._on_submit)
        lay.addWidget(self._input)

        # --- 状态行 ---
        self._status = QLabel("", card)
        self._status.setObjectName("aiStatus")
        lay.addWidget(self._status)

    # ------------------------------------------------------------ 生命周期

    def warm_up(self) -> None:
        """启动期预热：完成样式、布局与**首次绘制**，随后隐藏待命。

        为什么必须真的画一次
            M1 端到端验证实测：若只 show()+hide()，首次绘制会被取消，
            真正的绘制推迟到第一次唤起时发生 —— 那一帧要 145ms，
            直接顶穿 150ms 的唤起延迟预算。
            这里在最终尺寸下强制走一遍布局 + 绘制，把成本挪到启动期。
        """
        from PySide6.QtWidgets import QApplication

        self.setWindowOpacity(0.0)
        self.move_to_cursor_screen()      # 先定尺寸，避免唤起时 resize 触发重排
        self.show()
        self.ensurePolished()
        self._output.setMarkdown("")
        QApplication.processEvents()      # 让布局与绘制真正发生
        self.repaint()
        QApplication.processEvents()
        self.hide()
        self.setWindowOpacity(1.0)

    def show_mode(self, mode: str, activating: bool = True) -> None:
        """切换模式并显示。"""
        self._mode = mode
        self._title.setText(MODE_TITLES.get(mode, mode))
        self._input.setPlaceholderText(MODE_PLACEHOLDERS.get(mode, ""))
        self._output.clear_content()
        self._actions.hide()
        self._has_result = False
        self._streaming = False
        self._status.setText("")

        if activating:
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
            self.show()
            self.raise_()
            self.activateWindow()
            self._input.setFocus()
        else:
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            self.show()
            self.raise_()

    def show_for_input(self, mode: str) -> None:
        self.show_mode(mode, activating=True)

    def show_passive(self, mode: str) -> None:
        self.show_mode(mode, activating=False)

    def activate_for_input(self) -> None:
        """从「被动展示」切换到「可输入」—— 抢焦点并聚焦输入框。

        唤起流程必须分两步：先 show_passive()（原应用保持焦点，才能取到选中文本），
        再 activate_for_input()。否则面板一出现就把焦点抢走，
        Ctrl+C 会复制到面板自己的输入框而不是原应用。
        """
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.raise_()
        self.activateWindow()
        self._input.setFocus()

    def move_to_cursor_screen(self) -> None:
        """把面板移到鼠标所在屏幕的中央偏上位置（多显示器友好）。"""
        from PySide6.QtGui import QCursor, QGuiApplication

        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        w = min(self.width(), int(geo.width() * 0.8))
        h = min(self.height(), int(geo.height() * 0.8))
        self.resize(w, h)
        self.move(geo.x() + (geo.width() - w) // 2,
                  geo.y() + int(geo.height() * 0.18))

    # ------------------------------------------------------------ 内容

    def set_context(self, text: str) -> None:
        if text:
            self._input.setText(text)
            self._input.selectAll()

    def begin_stream(self) -> None:
        self._streaming = True
        self._has_result = False
        self._actions.hide()
        self._output.clear_content()
        self.set_status("思考中…")

    def append_chunk(self, delta: str) -> None:
        self._output.append_chunk(delta)

    def set_result(self, markdown: str) -> None:
        self._streaming = False
        self._has_result = True
        self._output.set_content(markdown)
        self._actions.show()
        self.set_status("")

    def set_error(self, message: str) -> None:
        self._streaming = False
        self._has_result = False
        self._actions.hide()
        self._output.set_content(f"**出错了**\n\n{message}")
        self.set_status("点右上角 ⚙ 打开「AI 服务设置」，可测试连接并热切换模型")

    def load_history(self, messages, title: str = "") -> None:
        """把一条历史会话渲染进输出区（控制中心「继续对话」入口用）。

        只做**展示** —— 真正的上下文由调用方通过
        `SessionManager.ask(history=...)` 送进模型。这里显示出来是为了让用户
        看清「正在跟哪条会话继续」。

        刻意**不显示投递按钮**（`_has_result` 保持 False）：`_on_delivery()`
        的兜底就是「输出区内容」，若此刻允许投递，「替换原文」会把**整段历史**
        投到前台应用。等真的问出结果，`set_result()` 会再把它显示出来。
        """
        blocks = []
        for m in messages:
            who = "你" if m.role == "user" else "助手"
            body = m.content if isinstance(m.content, str) else "[图片]"
            blocks.append(f"**{who}**：{body}")
        self._output.set_content(
            "\n\n---\n\n".join(blocks) if blocks else "_（这条会话没有留下内容）_"
        )
        self._streaming = False
        self._has_result = False
        self._actions.hide()
        self.set_status(f"已载入历史会话{f'（{title}）' if title else ''}，接着问就好")

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def set_hint(self, text: str) -> None:
        self._hint.setText(text)

    def input_text(self) -> str:
        return self._input.text().strip()

    # ------------------------------------------------------------ 事件

    def _on_submit(self) -> None:
        text = self.input_text()
        if text and not self._streaming:
            self.submitted.emit(text)

    def _on_close(self) -> None:
        self.hide()
        self.cancelled.emit()

    def _on_settings(self) -> None:
        """打开设置前先钉住自己。

        设置是独立对话框，弹出后本面板会失去焦点；若此时已有结果，
        `focusOutEvent` 会把它自动关掉，用户改完配置回来发现面板没了。
        钉住后 `focusOutEvent` 不再自动关闭，改完配置可以接着用。
        """
        if not self._pinned:
            self._btn_pin.setChecked(True)
        self.settings_requested.emit()

    def _on_pin(self, checked: bool) -> None:
        self._pinned = checked

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._on_close()
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        # 钉住时不自动关闭
        if not self._pinned and self._has_result and not self._streaming:
            self.hide()
            self.cancelled.emit()
        super().focusOutEvent(event)

    # --- 拖拽（标题区）+ 点击置顶 ---

    def mousePressEvent(self, event):
        # 先置顶：面板与设置对话框同处「置顶层」，点谁谁在前
        self.raise_to_front()
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 40:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)
