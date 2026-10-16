# -*- coding: utf-8 -*-
"""控制中心 —— 应用的**主窗口**。

布局（规格要求）
    ┌──────────────────────────────────────────────┐
    │ QToolBar   iconOnly + tooltip，四态齐全        │
    ├──────────┬───────────────────────────────────┤
    │ 左侧导航  │  QStackedWidget 工作区             │
    │ 200-240px│                                   │
    ├──────────┴───────────────────────────────────┤
    │ QStatusBar  主题 / 模型 / 插件数 / 忙碌反馈     │
    └──────────────────────────────────────────────┘

设计约定
    · 窗口是**普通窗口**（不进置顶层）—— 悬浮球与 AI 面板才是常驻置顶的。
    · 关闭 = 隐藏。`quitOnLastWindowClosed` 已是 False，退出只走托盘菜单。
    · 每个页面实现 `reload()` / `save()`，工具栏的「刷新 / 保存」直接转发，
      于是新增页面不需要改工具栏代码。
"""
from __future__ import annotations

import math
import sys
import time
from datetime import datetime
from pathlib import Path

from data.paths import pet_home

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QDesktopServices, QFontMetrics, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from data.config_manager import DEFAULT_CONFIG, config_manager
from data.log_manager import log_manager
from data.privacy import clear_entry, entries, export_data, human_size, total_size
from engine.activity import (
    ACTION_ADOPT,
    ACTION_IGNORE,
    CATEGORIES,
    CATEGORY_RULES,
    HOURS_PER_DAY,
    MAX_ADVICES,
    busiest_hour,
    category_totals,
    compare_periods,
    daily_totals,
    focus_seconds,
    format_context,
    hour_label,
    hour_switches,
    human_duration,
    is_structured,
    merge_segments,
    parse_report,
    switch_count,
    today_range,
    top_apps,
    total_seconds,
)
from engine.ai.prompt import BUILTIN_PRESETS
from presentation.ai_config_form import AIConfigForm
from presentation.design import set_theme
from presentation.design.advice_card import AdviceCard, AdviceSummary
from presentation.design.charts import (
    AxisLabels,
    BarChart,
    OverviewBoard,
    RankBar,
    StatTile,
    TimelineBar,
)
from presentation.design.focus_card import (
    FOCUS_ENTRY_ID,
    FocusCard,
    apply_phase,
    focus_label,
)
from presentation.design.theme import THEME_DARK, THEME_LIGHT, theme
from presentation.design.tokens import ICON_SIZE, SPACING
from presentation.design.widgets import (
    BusyIndicator,
    Button,
    Card,
    EmptyState,
    LogView,
    NavList,
    PageHint,
    PageTitle,
    SectionLabel,
    SegmentedControl,
    ToggleSwitch,
    ToolButton,
    busy_cursor,
    configure_list,
    configure_table,
)
from presentation.dialogs import ask_preset, delivery_label
from presentation.tray_icon import is_autostart_enabled, set_autostart

APP_NAME = "知时助手"
CONFIG_DIR = pet_home()
LOG_DIR = CONFIG_DIR / "logs"


# ================================================================
# 通用构件
# ================================================================

class FormCard(Card):
    """带标题的分组表单卡片（两列表单，标签右对齐）。"""

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        if title:
            lbl = QLabel(title, self)
            lbl.setObjectName("sectionLabel")
            self.layout_().addWidget(lbl)
        self._form = QFormLayout()
        self._form.setSpacing(SPACING["sm"])
        self._form.setContentsMargins(0, 0, 0, 0)
        self._form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.layout_().addLayout(self._form)

    def add(self, label: str, widget: QWidget, hint: str = "") -> QWidget:
        if hint:
            holder = QWidget(self)
            col = QVBoxLayout(holder)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(2)
            col.addWidget(widget)
            h = QLabel(hint, holder)
            h.setObjectName("pageHint")
            col.addWidget(h)
            self._form.addRow(label, holder)
        else:
            self._form.addRow(label, widget)
        return widget

    def add_widget(self, widget: QWidget) -> QWidget:
        self.layout_().addWidget(widget)
        return widget


def open_path(path: Path) -> None:
    """用系统文件管理器打开目录（不存在就先建）。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    except OSError as e:  # noqa: BLE001
        log_manager.error(f"打开目录失败 {path}: {e}")


class Page(QWidget):
    """页面基类。子类实现 `_build_body(layout)` / `reload()` / `save()`。"""

    title = "页面"
    hint = ""

    def __init__(self, center, parent=None):
        super().__init__(parent)
        self.center = center
        self.app = getattr(center, "app", None)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACING["xl"], SPACING["lg"], SPACING["xl"], SPACING["lg"])
        outer.setSpacing(SPACING["xs"])
        outer.addWidget(PageTitle(self.title, self))
        if self.hint:
            outer.addWidget(PageHint(self.hint, self))
        outer.addSpacing(SPACING["sm"])

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget(scroll)
        self.body_layout = QVBoxLayout(body)
        self.body_layout.setContentsMargins(0, 0, SPACING["sm"], 0)
        self.body_layout.setSpacing(SPACING["md"])
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self._build_body(self.body_layout)
        self.body_layout.addStretch()
        self.reload()

    # ----- 子类钩子 -----

    def _build_body(self, layout: QVBoxLayout) -> None:
        pass

    def reload(self) -> None:
        pass

    def save(self) -> bool:
        return True


# ================================================================
# 页面：外观
# ================================================================

class AppearancePage(Page):
    title = "外观"
    hint = ""

    def _build_body(self, layout):
        # --- 主题 ---
        card = FormCard("主题", self)
        self._seg_theme = SegmentedControl(["浅色", "深色"], 0, card)
        self._seg_theme.changed.connect(self._on_theme)
        card.add("配色", self._seg_theme)
        layout.addWidget(card)

        # --- 窗口 ---
        card2 = FormCard("窗口", self)
        self._slider_opacity = QSlider(Qt.Orientation.Horizontal, card2)
        self._slider_opacity.setRange(30, 100)
        self._lbl_opacity = QLabel("", card2)
        self._lbl_opacity.setObjectName("monoValue")
        self._lbl_opacity.setFixedWidth(44)
        row = QWidget(card2)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(SPACING["sm"])
        rl.addWidget(self._slider_opacity, 1)
        rl.addWidget(self._lbl_opacity)
        self._slider_opacity.valueChanged.connect(
            lambda v: self._lbl_opacity.setText(f"{v}%"))
        card2.add("悬浮球透明度", row)
        layout.addWidget(card2)

        # --- 启动与关闭 ---
        card3 = FormCard("启动与关闭", self)
        self._chk_autostart = ToggleSwitch("开机自启动（静默启动到托盘）", parent=card3)
        card3.add_widget(self._chk_autostart)
        self._chk_tray = ToggleSwitch("关闭悬浮球窗口时最小化到托盘", parent=card3)
        card3.add_widget(self._chk_tray)
        layout.addWidget(card3)

    def _on_theme(self, index: int) -> None:
        set_theme(THEME_DARK if index == 1 else THEME_LIGHT)
        self.center.refresh_status()

    def reload(self):
        c = config_manager
        self._seg_theme.set_index(1 if theme().dark else 0)
        op = int(round(max(0.3, float(c.get("window.opacity", 0.9))) * 100))
        self._slider_opacity.setValue(op)
        self._lbl_opacity.setText(f"{op}%")
        self._chk_autostart.setChecked(is_autostart_enabled())
        self._chk_tray.setChecked(bool(c.get("window.close_to_tray", True)))

    def save(self) -> bool:
        c = config_manager
        c.set("window.opacity", self._slider_opacity.value() / 100.0)
        c.set("window.close_to_tray", self._chk_tray.isChecked())
        c.save()
        set_autostart(self._chk_autostart.isChecked())
        return True


# ================================================================
# 页面：行为
# ================================================================

class BehaviorPage(Page):
    title = "行为"
    hint = "悬浮球的状态切换阈值与音效。数值越大，它越「迟钝」。"

    def _build_body(self, layout):
        card = FormCard("状态阈值", self)
        self._idle = QSpinBox(card)
        self._idle.setRange(5, 600)
        self._idle.setSuffix(" 秒")
        card.add("进入放松", self._idle, "无操作超过该时长 → 放松状态")

        self._sleep = QSpinBox(card)
        self._sleep.setRange(30, 3600)
        self._sleep.setSuffix(" 秒")
        card.add("进入休眠", self._sleep, "无操作超过该时长 → 休眠状态")

        self._focus = QSpinBox(card)
        self._focus.setRange(10, 300)
        card.add("专注阈值", self._focus, "30 秒内输入次数达到该值 → 专注状态")

        self._debounce = QSpinBox(card)
        self._debounce.setRange(1, 120)
        self._debounce.setSuffix(" 秒")
        card.add("专注去抖", self._debounce, "进入专注后需保持该时长才确认")

        self._cooldown = QSpinBox(card)
        self._cooldown.setRange(0, 60)
        self._cooldown.setSuffix(" 秒")
        card.add("状态切换冷却", self._cooldown, "两次状态切换之间的最短间隔")
        layout.addWidget(card)

        card2 = FormCard("音效", self)
        self._chk_sound = ToggleSwitch("启用音效", parent=card2)
        card2.add_widget(self._chk_sound)

        self._slider_volume = QSlider(Qt.Orientation.Horizontal, card2)
        self._slider_volume.setRange(0, 100)
        self._lbl_volume = QLabel("", card2)
        self._lbl_volume.setObjectName("monoValue")
        self._lbl_volume.setFixedWidth(44)
        row = QWidget(card2)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(SPACING["sm"])
        rl.addWidget(self._slider_volume, 1)
        rl.addWidget(self._lbl_volume)
        self._slider_volume.valueChanged.connect(lambda v: self._lbl_volume.setText(f"{v}%"))
        card2.add("音量", row)
        layout.addWidget(card2)

    def reload(self):
        c = config_manager
        self._idle.setValue(int(c.get("behavior.idle_threshold", 30)))
        self._sleep.setValue(int(c.get("behavior.sleep_threshold", 300)))
        self._focus.setValue(int(c.get("behavior.focus_threshold", 60)))
        self._debounce.setValue(int(c.get("behavior.focus_debounce", 15)))
        self._cooldown.setValue(int(c.get("behavior.state_switch_cooldown", 1)))
        self._chk_sound.setChecked(bool(c.get("behavior.sound_enabled", True)))
        vol = int(round(float(c.get("behavior.volume", 0.5)) * 100))
        self._slider_volume.setValue(vol)
        self._lbl_volume.setText(f"{vol}%")

    def save(self) -> bool:
        c = config_manager
        c.set("behavior.idle_threshold", self._idle.value())
        c.set("behavior.sleep_threshold", self._sleep.value())
        c.set("behavior.focus_threshold", self._focus.value())
        c.set("behavior.focus_debounce", self._debounce.value())
        c.set("behavior.state_switch_cooldown", self._cooldown.value())
        c.set("behavior.sound_enabled", self._chk_sound.isChecked())
        c.set("behavior.volume", self._slider_volume.value() / 100.0)
        c.save()

        # 同步到运行中的状态机 / 输入监听器（否则要重启才生效）
        sm = getattr(self.app, "state_machine", None) if self.app else None
        if sm is not None:
            sm.idle_threshold = self._idle.value()
            sm.sleep_threshold = self._sleep.value()
            sm.focus_debounce = self._debounce.value()
            sm.state_cooldown = self._cooldown.value()
        im = getattr(self.app, "input_monitor", None) if self.app else None
        if im is not None:
            im._focus_threshold = self._focus.value()
        return True


# ================================================================
# 页面：番茄钟
# ================================================================

class TomatoPage(Page):
    title = "番茄钟"
    hint = "时长设置与当前进度。改动在下次开始计时时生效。"

    #: 状态轮询间隔 —— 与专注卡一致（1 秒），倒计时要看得出在走。
    #: 原来这一页的状态只在切页 / 点按钮时刷一次，点完「开始」那行字就定住了，
    #: 看起来像卡死。
    _TICK_MS = 1_000

    #: 状态 → 中文。原来直接把 `running` / `paused` 这种英文枚举印给用户看。
    _STATE_TEXT = {
        "idle": "未开始",
        "running": "进行中",
        "paused": "已暂停",
        "finished": "已完成",
    }

    def _build_body(self, layout):
        card = FormCard("时长", self)
        self._work = QSpinBox(card)
        self._work.setRange(1, 120)
        self._work.setSuffix(" 分钟")
        card.add("工作时长", self._work)

        self._break = QSpinBox(card)
        self._break.setRange(1, 60)
        self._break.setSuffix(" 分钟")
        card.add("休息时长", self._break)

        self._long = QSpinBox(card)
        self._long.setRange(1, 120)
        self._long.setSuffix(" 分钟")
        card.add("长休息时长", self._long)

        self._interval = QSpinBox(card)
        self._interval.setRange(1, 12)
        self._interval.setSuffix(" 个")
        card.add("长休息间隔", self._interval, "每完成这么多个番茄后进入长休息")

        self._chk_auto = ToggleSwitch("工作结束后自动开始休息", parent=card)
        card.add_widget(self._chk_auto)
        layout.addWidget(card)

        card2 = FormCard("当前状态", self)
        self._lbl_status = QLabel("", card2)
        self._lbl_status.setObjectName("monoValue")
        card2.add_widget(self._lbl_status)
        self._btn_start = Button("开始一个番茄", "accent", card2)
        self._btn_start.clicked.connect(self._on_start)
        card2.add_widget(self._btn_start)
        layout.addWidget(card2)

        # 页面可见时才轮询（见 showEvent / hideEvent）—— 控制中心常年开着，
        # 为一个看不见的倒计时每秒读一次状态是白烧电。
        self._tick = QTimer(self)
        self._tick.setInterval(self._TICK_MS)
        self._tick.timeout.connect(self._refresh_status)
        # 改了工作时长，按钮上写的时长要立刻跟上（否则按钮说 25、实际跑 45）
        self._work.valueChanged.connect(lambda _=0: self._refresh_status())

    def showEvent(self, event):
        super().showEvent(event)
        self._tick.start()
        self._refresh_status()

    def hideEvent(self, event):
        self._tick.stop()
        super().hideEvent(event)

    def reload(self):
        c = config_manager
        self._work.setValue(int(c.get("tomato.work_duration", 25)))
        self._break.setValue(int(c.get("tomato.break_duration", 5)))
        self._long.setValue(int(c.get("tomato.long_break_duration", 15)))
        self._interval.setValue(int(c.get("tomato.long_break_interval", 4)))
        self._chk_auto.setChecked(bool(c.get("tomato.auto_start_break", False)))
        self._refresh_status()

    def _timer(self):
        return getattr(self.app, "timer", None) if self.app else None

    def _refresh_status(self):
        timer = self._timer()
        if timer is None:
            self._lbl_status.setText("番茄钟插件未加载")
            self._btn_start.setEnabled(False)
            return
        try:
            st = timer.get_status()
            state = str(st.get("state") or "idle")
            kind = str(st.get("type") or "work")
            # 取值也在 try 里：计时器插件是可选的外部实现，字段缺一个
            # 不该把整页打崩（`reload()` 期间 `_work.setValue` 就会触发到这里）。
            self._lbl_status.setText(
                f"{st.get('formatted', '00:00')} · {self._STATE_TEXT.get(state, state)}"
                f" · 今日完成 {st.get('today_count', 0)} 个"
            )
        except Exception:  # noqa: BLE001
            self._lbl_status.setText("状态不可用")
            return
        # 按钮**自己**也要跟着变（P2.19）—— 原来只有旁边那行小字变，
        # 按钮一直写着「开始一个番茄」、还能反复点。
        self._btn_start.setEnabled(state not in ("running", "paused"))
        self._btn_start.setText(focus_label(state, self._work.value(), kind))

    def _on_start(self):
        timer = self._timer()
        if timer is not None:
            timer.start("work")
            self._refresh_status()

    def save(self) -> bool:
        c = config_manager
        c.set("tomato.work_duration", self._work.value())
        c.set("tomato.break_duration", self._break.value())
        c.set("tomato.long_break_duration", self._long.value())
        c.set("tomato.long_break_interval", self._interval.value())
        c.set("tomato.auto_start_break", self._chk_auto.isChecked())
        c.save()
        return True


# ================================================================
# 页面：AI 服务
# ================================================================

class AIServicePage(Page):
    title = "AI 服务"
    hint = "切换服务商 / 模型 / Key。「测试连接」会发起真实网络请求，不阻塞界面。"

    def _build_body(self, layout):
        card = Card(self)
        self._form = AIConfigForm(card, config=config_manager,
                                  busy_check=self._is_streaming)
        self._form.busy_changed.connect(self._on_busy)
        card.layout_().addWidget(self._form)
        # 不给 stretch：让卡片按内容高度收缩。否则卡片占满整页，
        # 里面的输出区被拉成一大块空白。
        layout.addWidget(card)

        self._btn_test = Button("测试连接", parent=self)
        self._btn_test.clicked.connect(self._form.test)
        self._btn_save = Button("保存并生效", "accent", self)
        self._btn_save.clicked.connect(self._save_clicked)

        row = QWidget(self)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(SPACING["sm"])
        rl.addWidget(self._btn_test)
        rl.addWidget(self._btn_save)
        rl.addStretch()
        layout.addWidget(row)

        # 快捷键一览（只读）
        card2 = FormCard("快捷键", self)
        self._lbl_hotkeys = QLabel("", card2)
        self._lbl_hotkeys.setObjectName("monoValue")
        self._lbl_hotkeys.setTextFormat(Qt.TextFormat.RichText)
        card2.add_widget(self._lbl_hotkeys)
        layout.addWidget(card2)

    def _is_streaming(self) -> bool:
        pm = getattr(self.app, "plugin_manager", None) if self.app else None
        plugin = pm.get_plugin("ai_assistant") if pm else None
        return bool(plugin and plugin._is_streaming())

    def _on_busy(self, busy: bool) -> None:
        self._btn_test.setEnabled(not busy)
        self._btn_save.setEnabled(not busy)
        self.center.set_busy(busy, "正在测试 AI 连接…")

    def _save_clicked(self):
        ok, title, text = self._form.validate()
        if not ok:
            self.center.warn(title, text)
            return
        if not self._form.collect()["vision_model"]:
            if not self.center.confirm("视觉模型为空",
                                       "截图问答（Alt+S）需要一个能看图的模型。\n\n仍要保存吗？"):
                return
        if self._form.save():
            self.center.info("AI 服务", "配置已保存并生效，无需重启。")

    def reload(self):
        self._form.load_from_config()
        c = config_manager
        rows = [
            ("AI 问答", c.get("ai.hotkey_ask", "")),
            ("划词翻译", c.get("ai.hotkey_translate", "")),
            ("截图问答", c.get("ai.hotkey_capture", "")),
        ]
        html = "<br>".join(
            f'<b>{(combo or "未绑定").upper()}</b>&nbsp;&nbsp;{name}' for name, combo in rows
        )
        self._lbl_hotkeys.setText(html)

    def save(self) -> bool:
        ok, title, text = self._form.validate()
        if not ok:
            self.center.warn(title, text)
            return False
        return self._form.save()


# ================================================================
# 页面：会话历史
# ================================================================

def _fmt_time(ts) -> str:
    """时间戳 → 本地「月-日 时:分」。脏数据返回破折号，绝不抛异常。"""
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%m-%d %H:%M")
    except (OSError, ValueError, TypeError, OverflowError):
        return "—"


class SessionsPage(Page):
    title = "会话历史"
    hint = "AI 问答 / 翻译在本机的记录。数据只存在 ~/.pet_demo/ai.db，不会上传。"

    def _build_body(self, layout):
        split = QWidget(self)
        row = QHBoxLayout(split)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACING["md"])

        # ---- 左：会话列表 ----
        left = QWidget(split)
        left.setFixedWidth(292)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(SPACING["sm"])

        self._search = QLineEdit(left)
        self._search.setPlaceholderText("搜索标题或预设…")
        self._search.textChanged.connect(lambda _t: self._apply_filter())
        lv.addWidget(self._search)

        self._list = QListWidget(left)
        configure_list(self._list)
        self._list.currentItemChanged.connect(self._on_select)
        lv.addWidget(self._list, 1)

        self._empty_list = EmptyState(
            "history", "还没有会话记录",
            "按 Alt+Q 问一句，或 Alt+T 划词翻译，记录会出现在这里。", left)
        lv.addWidget(self._empty_list, 1)
        row.addWidget(left)

        # ---- 右：详情 ----
        right = Card(split)
        self._detail_head = QLabel("", right)
        self._detail_head.setObjectName("sectionLabel")
        right.layout_().addWidget(self._detail_head)

        self._detail = QPlainTextEdit(right)
        self._detail.setObjectName("sessionDetail")
        self._detail.setReadOnly(True)
        self._detail.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        right.layout_().addWidget(self._detail, 1)

        self._empty_detail = EmptyState(
            "history", "选择左侧的一条会话",
            "这里会显示完整的对话内容。", right)
        right.layout_().addWidget(self._empty_detail, 1)
        row.addWidget(right, 1)

        layout.addWidget(split, 1)

        # ---- 底部动作 ----
        bar = QWidget(self)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(SPACING["sm"])
        self._btn_continue = Button("继续对话", "accent", parent=bar, icon_name="send")
        self._btn_continue.setToolTip("把这条会话载入 AI 面板，接着往下问")
        self._btn_continue.clicked.connect(self._on_continue)
        self._btn_continue.setEnabled(False)
        self._btn_delete = Button("删除选中", "danger", parent=bar, icon_name="trash")
        self._btn_delete.clicked.connect(self._on_delete)
        self._btn_delete.setEnabled(False)
        btn_clear = Button("清空全部", "danger", parent=bar, icon_name="trash")
        btn_clear.clicked.connect(self._on_clear)
        btn_open = Button("打开数据目录", parent=bar, icon_name="folder")
        btn_open.clicked.connect(lambda: open_path(CONFIG_DIR))
        bl.addWidget(self._btn_continue)
        bl.addWidget(self._btn_delete)
        bl.addWidget(btn_clear)
        bl.addStretch()
        bl.addWidget(btn_open)
        layout.addWidget(bar)

        self._sessions: list[dict] = []
        self._show_detail(False)

    # ----- 数据 -----

    def reload(self):
        store = self.center.store()
        try:
            self._sessions = store.list_sessions(limit=200) if store else []
        except Exception as e:  # noqa: BLE001 —— 读不出来就显示空状态，不能崩页面
            log_manager.error(f"读取会话历史失败: {e}")
            self._sessions = []
        self._apply_filter()

    def _apply_filter(self):
        keyword = self._search.text().strip().lower()
        rows = [
            s for s in self._sessions
            if not keyword
            or keyword in (s.get("title") or "").lower()
            or keyword in (s.get("preset_id") or "").lower()
        ]
        self._list.clear()
        for s in rows:
            title = (s.get("title") or "").strip() or "（无标题）"
            item = QListWidgetItem(
                f"{title}\n{_fmt_time(s.get('updated_at'))} · {s.get('preset_id') or 'ask'}"
            )
            item.setData(Qt.ItemDataRole.UserRole, s.get("id"))
            item.setToolTip(title)
            self._list.addItem(item)

        has = bool(rows)
        self._list.setVisible(has)
        self._empty_list.setVisible(not has)
        if not has:
            self._show_detail(False)
        has_sel = self._list.currentItem() is not None
        self._btn_delete.setEnabled(has_sel)
        self._btn_continue.setEnabled(has_sel)

    def _on_select(self, current, _previous=None):
        if current is None:
            self._show_detail(False)
            self._btn_delete.setEnabled(False)
            self._btn_continue.setEnabled(False)
            return
        sid = current.data(Qt.ItemDataRole.UserRole)
        store = self.center.store()
        try:
            msgs = store.get_messages(sid) if store else []
        except Exception as e:  # noqa: BLE001
            log_manager.error(f"读取会话内容失败: {e}")
            msgs = []

        rec = next((s for s in self._sessions if s.get("id") == sid), {})
        self._detail_head.setText(
            f"{rec.get('preset_id') or 'ask'} · {_fmt_time(rec.get('updated_at'))}"
            f" · {len(msgs)} 条消息"
        )
        blocks = []
        for m in msgs:
            who = {"user": "用户", "assistant": "助手"}.get(m.role, m.role)
            blocks.append(f"[{who}] {m.content}")
        self._detail.setPlainText(
            "\n\n".join(blocks) if blocks else "（这条会话没有留下消息内容）"
        )
        self._show_detail(True)
        self._btn_delete.setEnabled(True)
        self._btn_continue.setEnabled(True)

    def _show_detail(self, on: bool) -> None:
        self._detail.setVisible(on)
        self._detail_head.setVisible(on)
        self._empty_detail.setVisible(not on)

    # ----- 动作 -----

    def _on_continue(self):
        """把选中的会话载入 AI 面板继续对话。"""
        item = self._list.currentItem()
        if item is None:
            return
        sid = item.data(Qt.ItemDataRole.UserRole)
        store = self.center.store()
        try:
            msgs = store.get_messages(sid) if store else []
        except Exception as e:  # noqa: BLE001
            log_manager.error(f"读取会话内容失败: {e}")
            msgs = []
        if not msgs:
            self.center.warn(
                "继续对话",
                "这条会话没有可用的对话内容 —— 可能只落库了标题。",
            )
            return
        self.center.continue_session(sid, msgs)

    def _on_delete(self):
        item = self._list.currentItem()
        if item is None:
            return
        sid = item.data(Qt.ItemDataRole.UserRole)
        if not self.center.confirm("删除会话", "确定删除这条会话记录吗？此操作不可撤销。"):
            return
        self._delete_one(sid)
        self.reload()

    def _on_clear(self):
        if not self._sessions:
            self.center.info("会话历史", "目前没有可清空的记录。")
            return
        if not self.center.confirm(
            "清空全部会话",
            f"将删除全部 {len(self._sessions)} 条会话记录，此操作不可撤销。\n\n继续吗？",
        ):
            return
        for s in list(self._sessions):
            self._delete_one(s.get("id"))
        self.reload()
        self.center.statusMessage("会话历史已清空")

    def _delete_one(self, sid) -> None:
        store = self.center.store()
        if store is None or not sid:
            return
        try:
            store.delete_session(sid)
        except Exception as e:  # noqa: BLE001
            log_manager.error(f"删除会话失败: {e}")


# ================================================================
# 页面：预设
# ================================================================

class PresetsPage(Page):
    title = "预设"
    hint = "预设决定「怎么问」—— 系统提示词 + 默认投递方式。内置预设固定，自定义预设存在本机。"

    COLUMNS = ["名称", "标识", "来源", "默认投递", "说明"]

    def _build_body(self, layout):
        #: [(Preset, builtin), ...] —— 表格行序与此一一对应。
        #: 必须**先**定义：下面的信号连接可能在构建过程中就被触发。
        self._rows: list[tuple] = []

        self._table = QTableWidget(0, len(self.COLUMNS), self)
        self._table.setHorizontalHeaderLabels(self.COLUMNS)
        configure_table(self._table)
        hh = self._table.horizontalHeader()
        for col in range(len(self.COLUMNS) - 1):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(len(self.COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)
        self._table.setMinimumHeight(220)
        self._table.itemSelectionChanged.connect(self._sync_buttons)
        self._table.itemDoubleClicked.connect(lambda _item: self._on_edit())
        layout.addWidget(self._table, 1)

        self._empty = EmptyState("wrench", "还没有任何预设",
                                 "点「新建预设」创建第一个自定义预设。", self)
        layout.addWidget(self._empty, 1)

        bar = QWidget(self)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(SPACING["sm"])
        self._btn_new = Button("新建预设", "accent", parent=bar, icon_name="plus")
        self._btn_new.clicked.connect(self._on_new)
        self._btn_edit = Button("编辑", parent=bar, icon_name="pencil")
        self._btn_edit.clicked.connect(self._on_edit)
        self._btn_del = Button("删除", "danger", parent=bar, icon_name="trash")
        self._btn_del.clicked.connect(self._on_delete)
        btn_refresh = Button("刷新", parent=bar, icon_name="refresh")
        btn_refresh.clicked.connect(self.reload)
        bl.addWidget(self._btn_new)
        bl.addWidget(self._btn_edit)
        bl.addWidget(self._btn_del)
        bl.addStretch()
        bl.addWidget(btn_refresh)
        layout.addWidget(bar)

    # ----- 数据 -----

    def reload(self):
        rows = [(p, True) for p in BUILTIN_PRESETS.values()]
        store = self.center.store()
        if store is not None:
            try:
                rows += [(p, False) for p in store.list_presets()]
            except Exception as e:  # noqa: BLE001
                log_manager.error(f"读取自定义预设失败: {e}")
        self._rows = rows

        self._table.setRowCount(0)
        for preset, builtin in rows:
            r = self._table.rowCount()
            self._table.insertRow(r)
            cells = (
                preset.name,
                preset.id,
                "内置" if builtin else "自定义",
                delivery_label(preset.default_delivery),
                preset.description,
            )
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self._table.setItem(r, c, item)

        has = bool(rows)
        self._table.setVisible(has)
        self._empty.setVisible(not has)
        self._sync_buttons()

    def _selected(self):
        r = self._table.currentRow()
        if r < 0 or r >= len(self._rows):
            return None
        return self._rows[r]

    def _sync_buttons(self):
        sel = self._selected()
        custom = sel is not None and not sel[1]
        self._btn_edit.setEnabled(custom)
        self._btn_del.setEnabled(custom)

    # ----- 动作 -----

    def _on_new(self):
        preset = ask_preset(self, taken_ids=[p.id for p, _ in self._rows])
        if preset is None:
            return
        if self._persist(preset):
            self.reload()
            self.center.statusMessage(f"已新建预设「{preset.name}」")

    def _on_edit(self):
        sel = self._selected()
        if sel is None or sel[1]:
            return
        preset, _ = sel
        updated = ask_preset(
            self, preset=preset,
            taken_ids=[p.id for p, _ in self._rows if p.id != preset.id],
        )
        if updated is None:
            return
        if self._persist(updated):
            self.reload()
            self.center.statusMessage(f"已更新预设「{updated.name}」")

    def _on_delete(self):
        sel = self._selected()
        if sel is None or sel[1]:
            return
        preset, _ = sel
        if not self.center.confirm("删除预设", f"确定删除自定义预设「{preset.name}」吗？"):
            return
        store = self.center.store()
        if store is None:
            self.center.warn("删除失败", "会话数据库不可用。")
            return
        try:
            store.delete_preset(preset.id)
        except Exception as e:  # noqa: BLE001
            self.center.warn("删除失败", f"{type(e).__name__}: {e}")
            return
        self.reload()
        self.center.statusMessage(f"已删除预设「{preset.name}」")

    def _persist(self, preset) -> bool:
        store = self.center.store()
        if store is None:
            self.center.warn("保存失败", "会话数据库不可用。")
            return False
        try:
            store.save_preset(preset)
            return True
        except Exception as e:  # noqa: BLE001
            self.center.warn("保存失败", f"{type(e).__name__}: {e}")
            return False


# ================================================================
# 页面：插件
# ================================================================

class PluginsPage(Page):
    title = "插件"
    hint = "系统内置与用户安装的插件。菜单入口在托盘 / 右键菜单中。"

    #: 放按钮的行要比普通行高一点（按钮本身 28px，四周留白）
    _ACTION_ROW_HEIGHT = 36

    def _build_body(self, layout):
        self._table = QTableWidget(0, 5, self)
        self._table.setHorizontalHeaderLabels(["名称", "版本", "作者", "说明", ""])
        configure_table(self._table)
        hh = self._table.horizontalHeader()
        # 操作列在最后，但**不该被拉伸** —— 让它按内容收窄，
        # 把多余宽度全给「说明」。`configure_table` 默认拉伸最后一列。
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.verticalHeader().setDefaultSectionSize(self._ACTION_ROW_HEIGHT)
        self._table.setMinimumHeight(220)
        layout.addWidget(self._table, 1)

        self._empty = EmptyState("puzzle", "还没有加载任何插件",
                                 "把插件目录放进 extensions/user/ 后点「刷新」。", self)
        layout.addWidget(self._empty, 1)

        # --- 已卸载 ---
        self._removed_label = SectionLabel("已卸载", self)
        layout.addWidget(self._removed_label)
        self._removed_hint = PageHint(
            "这些插件下次启动不会再加载。系统内置插件点「恢复」即可找回；"
            "用户插件的目录在卸载时已删除，需要重新放入插件目录。", self)
        layout.addWidget(self._removed_hint)

        self._removed_table = QTableWidget(0, 3, self)
        self._removed_table.setHorizontalHeaderLabels(["名称", "来源", ""])
        configure_table(self._removed_table)
        rhh = self._removed_table.horizontalHeader()
        rhh.setStretchLastSection(False)
        rhh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        rhh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        rhh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._removed_table.verticalHeader().setDefaultSectionSize(self._ACTION_ROW_HEIGHT)
        self._removed_table.setMinimumHeight(110)
        layout.addWidget(self._removed_table)

        btn = Button("刷新插件列表", parent=self, icon_name="refresh")
        btn.clicked.connect(self.reload)
        layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignLeft)

    # ----- 数据 -----

    def _pm(self):
        return getattr(self.app, "plugin_manager", None) if self.app else None

    def reload(self):
        pm = self._pm()
        plugins = pm.get_all_plugins() if pm else {}
        self._table.setRowCount(0)
        has = bool(plugins)
        self._table.setVisible(has)
        self._empty.setVisible(not has)

        for name, plugin in sorted(plugins.items()):
            m = plugin.manifest
            row = self._table.rowCount()
            self._table.insertRow(row)
            for col, text in enumerate((name, m.version, m.author, m.description)):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self._table.setItem(row, col, item)
            self._table.setCellWidget(row, 4, self._row_button(
                self._table, "卸载", "trash", lambda n=name: self._on_uninstall(n)))

        self._reload_removed(pm)

    def _reload_removed(self, pm) -> None:
        """刷新「已卸载」区。没有已卸载插件时整段收掉，不留空表格。"""
        names = self._disabled_names(pm)
        self._removed_table.setRowCount(0)
        for name in sorted(names):
            row = self._removed_table.rowCount()
            self._removed_table.insertRow(row)
            item = QTableWidgetItem(name)
            item.setToolTip(name)
            self._removed_table.setItem(row, 0, item)
            origin = {"system": "系统内置", "user": "用户安装", "dev": "开发"}.get(
                self._layer_of(pm, name), "未知")
            self._removed_table.setItem(row, 1, QTableWidgetItem(origin))
            self._removed_table.setCellWidget(row, 2, self._row_button(
                self._removed_table, "恢复", "refresh", lambda n=name: self._on_restore(n)))

        visible = bool(names)
        for w in (self._removed_label, self._removed_hint, self._removed_table):
            w.setVisible(visible)

    # 插件管理器是**鸭子类型**的（预览脚本会塞普通对象进来，见 spikes/s13），
    # 所以这两个新接口要探一下再用 —— 拿不到就当「没有已卸载插件」，
    # 页面照常显示已加载列表，而不是整个崩掉。

    @staticmethod
    def _disabled_names(pm) -> list:
        getter = getattr(pm, "disabled_names", None)
        if not callable(getter):
            return []
        try:
            return [str(n) for n in getter()]
        except Exception:  # noqa: BLE001 —— 读名单失败不该让页面起不来
            return []

    @staticmethod
    def _layer_of(pm, name: str):
        getter = getattr(pm, "layer_of", None)
        if not callable(getter):
            return None
        try:
            return getter(name)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _row_button(table, text: str, icon_name: str, callback) -> QWidget:
        """表格单元格里的按钮。

        按钮不能直接塞进单元格 —— `QTableWidget` 会把控件拉伸到整格，
        所以垫一层带边距的容器，按钮才会保持正常尺寸并居中。
        """
        holder = QWidget(table)
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(SPACING["xs"], 0, SPACING["xs"], 0)
        lay.setSpacing(0)
        btn = Button(text, parent=holder, icon_name=icon_name)
        btn.clicked.connect(callback)
        lay.addWidget(btn)
        return holder

    # ----- 动作 -----

    def _on_uninstall(self, name: str) -> None:
        pm = self._pm()
        action = getattr(pm, "uninstall", None) if pm is not None else None
        if not callable(action):
            self.center.warn("无法卸载", "当前插件管理器不支持卸载。")
            return
        layer = self._layer_of(pm, name)
        if layer == "user":
            text = (f"「{name}」是你自己安装的插件。\n\n"
                    "卸载会删除它的插件目录，之后要重新放回插件目录才能恢复。\n"
                    "确定卸载吗？")
        elif layer == "system":
            text = (f"「{name}」是系统内置插件。\n\n"
                    "卸载只是停用它（程序自带的文件保持不动），下次启动不再加载，"
                    "随时可以在下面点「恢复」找回来。\n确定卸载吗？")
        else:
            text = f"确定卸载「{name}」吗？"
        if not self.center.confirm("卸载插件", text):
            return

        ok, message = action(name)
        self.reload()
        self.center.refresh_status()
        if ok:
            self.center.info("已卸载", message)
        else:
            self.center.warn("卸载失败", message)

    def _on_restore(self, name: str) -> None:
        pm = self._pm()
        action = getattr(pm, "restore", None) if pm is not None else None
        if not callable(action):
            self.center.warn("无法恢复", "当前插件管理器不支持恢复。")
            return
        ok, message = action(name)
        self.reload()
        self.center.refresh_status()
        if ok:
            self.center.info("已恢复", message)
        else:
            self.center.warn("恢复失败", message)


# ================================================================
# 页面：隐私与数据
# ================================================================

#: 隐私承诺。**每一句都要能被代码兑现** —— 写进这里的话都是用户在审我们的账，
#: 所以只陈述结构性事实：字段级不采集、只进本机库、出网内容是什么。
#: 采集开关的边界说明见 `_privacy_text`（「今日」页开启开关的同一张卡里）。
_PRIVACY_PROMISE = (
    "知时助手把所有数据都保存在这一台电脑上。\n"
    "\n"
    "会保存在本机的：\n"
    "· 设置与偏好（含 AI 服务地址、模型和 API 密钥）\n"
    "· 你与 AI 的提问与回答、自建的预设\n"
    "· 活动记录：前台应用名、类别、停留时长、键盘敲击次数\n"
    "\n"
    "不会采集的：窗口标题、按键内容、剪贴板内容、截图。\n"
    "活动记录不记录你用过什么软件做了什么，只记录「在某个应用上待了多久」。\n"
    "\n"
    "会送出这台电脑的：只有你主动发起的 AI 提问，"
    "发送到你自己在「AI 服务」页填写的地址（默认 DeepSeek）。"
    "API 密钥只保存在本机，不随请求发往任何第三方。\n"
    "\n"
    "你随时可以做三件事：在下面看清每类数据、把它打包带走、把它删掉。"
)


class PrivacyPage(Page):
    title = "隐私与数据"
    hint = "你的数据存在哪、含什么，以及怎么带走或删掉。"

    #: 放按钮的行要比普通行高一点（与「插件」页同一约定）
    _ACTION_ROW_HEIGHT = 36

    def _build_body(self, layout):
        # --- 承诺 ---
        card = FormCard("我们怎么对待你的数据", self)
        lbl = QLabel(_PRIVACY_PROMISE, card)
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.TextFormat.PlainText)
        card.add_widget(lbl)
        layout.addWidget(card)

        # --- 清单 ---
        layout.addWidget(SectionLabel("本机数据", self))
        self._lbl_total = PageHint("", self)
        layout.addWidget(self._lbl_total)

        self._table = QTableWidget(0, 4, self)
        self._table.setHorizontalHeaderLabels(["数据", "大小", "说明", ""])
        configure_table(self._table)
        hh = self._table.horizontalHeader()
        # 操作列放两个按钮，**不该被拉伸** —— 把宽度全给「说明」
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.verticalHeader().setDefaultSectionSize(self._ACTION_ROW_HEIGHT)
        layout.addWidget(self._table)

        # --- 动作 ---
        bar = QWidget(self)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(SPACING["sm"])
        btn_export = Button("导出全部数据…", "accent", parent=bar, icon_name="save")
        btn_export.clicked.connect(self._on_export_all)
        btn_open = Button("打开数据目录", parent=bar, icon_name="folder")
        btn_open.clicked.connect(lambda: open_path(pet_home()))
        btn_refresh = Button("刷新", parent=bar, icon_name="refresh")
        btn_refresh.clicked.connect(self.reload)
        bl.addWidget(btn_export)
        bl.addWidget(btn_open)
        bl.addWidget(btn_refresh)
        bl.addStretch()
        layout.addWidget(bar)

    # ----- 数据 -----

    def reload(self):
        items = entries()
        self._table.setRowCount(0)
        for entry in items:
            row = self._table.rowCount()
            self._table.insertRow(row)

            name = QTableWidgetItem(entry.label)
            self._table.setItem(row, 0, name)

            size = entry.size()
            size_item = QTableWidgetItem(human_size(size) if size else "—")
            self._table.setItem(row, 1, size_item)

            # 说明列**不设 tooltip**：列已经把这句话完整显示出来了，
            # 再挂一份一模一样的是冗余，离屏目检时还会浮出一个假提示框。
            detail = QTableWidgetItem(entry.detail)
            self._table.setItem(row, 2, detail)

            self._table.setCellWidget(
                row, 3, self._row_actions(entry, size))

        total = total_size()
        self._lbl_total.setText(
            f"共 {len(items)} 类，合计 {human_size(total)}，都在这个目录里：{pet_home()}")

    def _row_actions(self, entry, size: int) -> QWidget:
        holder = QWidget(self._table)
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(SPACING["xs"], 0, SPACING["xs"], 0)
        lay.setSpacing(SPACING["xs"])

        btn_export = Button("导出", parent=holder, icon_name="save")
        btn_export.setEnabled(size > 0)
        btn_export.setToolTip("这一类还没有数据" if size == 0 else "只导出这一类")
        btn_export.clicked.connect(lambda: self._on_export(entry.key))
        lay.addWidget(btn_export)

        btn_clear = Button("清空", "danger", parent=holder, icon_name="trash")
        btn_clear.setEnabled(size > 0)
        btn_clear.setToolTip("这一类还没有数据" if size == 0 else "")
        btn_clear.clicked.connect(lambda: self._on_clear(entry))
        lay.addWidget(btn_clear)
        return holder

    # ----- 动作 -----

    def _on_export(self, key: str) -> None:
        dest = QFileDialog.getExistingDirectory(self, "选择导出位置")
        if not dest:
            return
        with busy_cursor():
            ok, message, path = export_data(Path(dest), (key,))
        self._report_export(ok, message, path)

    def _on_export_all(self) -> None:
        dest = QFileDialog.getExistingDirectory(self, "选择导出位置")
        if not dest:
            return
        with busy_cursor():
            ok, message, path = export_data(Path(dest))
        self._report_export(ok, message, path)

    def _report_export(self, ok: bool, message: str, path) -> None:
        self.reload()
        if ok:
            self.center.info("导出完成", f"{message}\n\n{path}")
        else:
            self.center.warn("导出失败", message)

    def _on_clear(self, entry) -> None:
        warn = "\n\n这个操作不能撤销，删掉的数据只能从你此前的导出备份里找回。"
        if entry.sensitive:
            warn += f"\n「{entry.label}」含有敏感内容。"
        if not self.center.confirm(f"清空{entry.label}", entry.detail + warn):
            return
        with busy_cursor():
            ok, message = clear_entry(entry.key, self.app)
        self.reload()
        self.center.refresh_status()
        if ok:
            self.center.info("已清空", message)
        else:
            self.center.warn("没能清空", message)


# ================================================================
# 页面：日志
# ================================================================

_LOG_KINDS = [("app", "运行日志"), ("behavior", "行为日志"), ("migration", "配置迁移")]
_LINE_CHOICES = [100, 300, 1000, 3000]


class LogsPage(Page):
    title = "日志"
    hint = "只有级别标签着色，正文保持常规灰 —— 便于扫读定位问题行。"

    def _build_body(self, layout):
        bar = QWidget(self)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(SPACING["sm"])

        self._combo_kind = QComboBox(bar)
        for key, label in _LOG_KINDS:
            self._combo_kind.addItem(label, key)
        bl.addWidget(QLabel("类型", bar))
        bl.addWidget(self._combo_kind)

        self._combo_lines = QComboBox(bar)
        for n in _LINE_CHOICES:
            self._combo_lines.addItem(f"最近 {n} 行", n)
        self._combo_lines.setCurrentIndex(1)
        bl.addWidget(self._combo_lines)
        bl.addStretch()

        btn_refresh = Button("刷新", parent=bar, icon_name="refresh")
        btn_refresh.clicked.connect(self.reload)
        bl.addWidget(btn_refresh)
        btn_clear = Button("清空", "danger", parent=bar, icon_name="trash")
        btn_clear.clicked.connect(self._on_clear)
        bl.addWidget(btn_clear)
        btn_open = Button("打开目录", parent=bar, icon_name="folder")
        btn_open.clicked.connect(lambda: open_path(LOG_DIR))
        bl.addWidget(btn_open)
        layout.addWidget(bar)

        self._view = LogView(self)
        layout.addWidget(self._view, 1)

        self._empty = EmptyState("scroll", "还没有日志",
                                 "启动一段时间后回来看看，或点「刷新」重试。", self)
        layout.addWidget(self._empty, 1)

        # 信号必须**在全部控件建好之后**再接：`addItem` 会触发
        # `currentIndexChanged`，那时 `self._view` 还不存在。
        self._combo_kind.currentIndexChanged.connect(self.reload)
        self._combo_lines.currentIndexChanged.connect(self.reload)

    def reload(self):
        kind = self._combo_kind.currentData() or "app"
        lines = int(self._combo_lines.currentData() or 300)
        rows = log_manager.get_recent_logs(kind, lines=lines)
        has = bool(rows)
        self._view.setVisible(has)
        self._empty.setVisible(not has)
        if has:
            self._view.set_lines(rows)

    def _on_clear(self):
        kind = self._combo_kind.currentData() or "app"
        if self.center.confirm("清空日志", f"确定清空「{self._combo_kind.currentText()}」吗？"):
            log_manager.clear_logs(kind)
            self.reload()


# ================================================================
# 页面：关于
# ================================================================

class AboutPage(Page):
    title = "关于"
    hint = "版本、技术栈与文件位置。"

    def _build_body(self, layout):
        card = FormCard("", self)
        title = QLabel(f"<b>{APP_NAME}</b>", card)
        title.setTextFormat(Qt.TextFormat.RichText)
        card.add_widget(title)
        self._lbl_version = QLabel("", card)
        self._lbl_version.setObjectName("monoValue")
        card.add_widget(self._lbl_version)
        self._lbl_stack = QLabel("", card)
        self._lbl_stack.setObjectName("monoValue")
        self._lbl_stack.setWordWrap(True)
        card.add_widget(self._lbl_stack)
        layout.addWidget(card)

        card2 = FormCard("文件位置", self)
        self._lbl_paths = QLabel("", card2)
        self._lbl_paths.setObjectName("monoValue")
        self._lbl_paths.setWordWrap(True)
        self._lbl_paths.setTextFormat(Qt.TextFormat.RichText)
        card2.add_widget(self._lbl_paths)

        row = QWidget(card2)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(SPACING["sm"])
        b1 = Button("打开配置目录", parent=row, icon_name="folder")
        b1.clicked.connect(lambda: open_path(CONFIG_DIR))
        b2 = Button("打开日志目录", parent=row, icon_name="folder")
        b2.clicked.connect(lambda: open_path(LOG_DIR))
        rl.addWidget(b1)
        rl.addWidget(b2)
        rl.addStretch()
        card2.add_widget(row)
        layout.addWidget(card2)

    def reload(self):
        from PySide6 import __version__ as pyside_version

        version = DEFAULT_CONFIG.get("version", "unknown")
        self._lbl_version.setText(f"版本 {version}")
        self._lbl_stack.setText(
            f"Python {sys.version.split()[0]} · PySide6 {pyside_version} · Qt Widgets"
        )
        cfg = CONFIG_DIR / "user_config.json"
        self._lbl_paths.setText(
            f"配置：{cfg}<br>日志：{LOG_DIR}"
        )


# ================================================================
# 页面：今日
# ================================================================

#: 「今日」页固定看今天。多天口径在「趋势」页 —— 一页只回答一个问题。
_TODAY_DAYS = 1

#: 采集边界说明。必须写在**开启开关的同一张卡里** ——
#: 用户点开关之前就该看到「会记什么、不会记什么、发到哪」。
#:
#: 保留天数由调用方**从配置读进来**，不写死：写死的话用户改了配置，
#: 页面就在说假话（这正是「结构性保证」要避免的那类事）。
def _privacy_text(retention_days: int = 0) -> str:
    keep = (f"记录只留在本机，保留最近 {int(retention_days)} 天后自动清理。\n"
            if retention_days else "")
    return (
        "会记录：应用名（如 code.exe）、类别（工作 / 娱乐 / 其他）、停留时长、"
        "键盘敲击次数。你离开电脑的那段时间会自动从时长里扣除。\n"
        "不会记录：窗口标题、按键内容、剪贴板、截图。\n"
        + keep
        + "生成建议时，只把上面那份「本机概览」摘要发送到 AI 服务。"
    )


_ACTIVITY_NO_PLUGIN = (
    "活动建议插件未加载。\n"
    "可在「插件」页确认它是否被禁用。"
)


def _activity_plugin(app):
    """按鸭子类型取活动插件；取不到返回 `None`。

    为什么用鸭子类型而不是 import 插件类
        控制中心不该硬依赖某个插件 —— 插件可以被禁用或整个移除。
        取不到就明确告诉用户「不是坏了，是插件没开」，比静默失败好得多。
        （副作用：预览脚本塞一个普通对象就能当插件用，见 `spikes/s13`。）
    """
    pm = getattr(app, "plugin_manager", None) if app is not None else None
    plugin = pm.get_plugin("activity_advisor") if pm is not None else None
    if plugin is None or not hasattr(plugin, "set_enabled"):
        return None
    return plugin

#: 时间轴刻度。**必须有刻度** —— 没有刻度时看不出这条带子代表多长时间，
#: 会把「一天里只有 8:00–17:00 有记录」误读成「图被截断了」（P2.14 目检踩过）。
_TIMELINE_TICKS = ((0.0, "0:00"), (0.25, "6:00"), (0.5, "12:00"),
                   (0.75, "18:00"), (1.0, "24:00"))

_EMPTY_DISABLED = (
    "采集已关闭",
    # 显式换行：CJK 允许在任意字之间断行，不给换行点的话会断在
    # 「…会显示今 / 天的时间分布」这种词中间（目检时真的出现了）。
    "打开上面的开关，正常用一会儿电脑。\n这里会显示今天的时间分布。",
)
_EMPTY_NO_DATA = (
    "今天还没有记录",
    "正常用一会儿电脑，这里会显示今天的时间分布。\n"
    "只想看大致节奏的话，五分钟的记录就够画出来了。",
)
_EMPTY_NO_PLUGIN = ("活动建议插件未加载", _ACTIVITY_NO_PLUGIN)


class TodayPage(Page):
    """今日 —— 今天的时间去哪了：概览 / 时间轴 / 排行 / 建议卡。

    为什么这页是主窗口的默认页（P2.14）
        「活动建议」原来只是 10 个平级设置页里的一项 —— 等于把时间洞察
        藏进了设置里。现在它和 AI 命令层面板并列成两个核心：
        面板管「我现在想问点什么」，这一页管「我今天是怎么过的」。

    为什么第一张卡是「本机记录」而不是概览
        采集开关与它的边界说明必须在**同一屏、且先于数据**出现 ——
        P2.12 定的规矩：用户点开关之前就该看到「会记什么、不会记什么、发到哪」。
        折进设置里、或只在首次运行时弹一次，都不算数。

    为什么「忽略」要落库、而不只在页面里过滤
        「忽略」是要长期生效的状态。只在页面里过滤的话，换个视图
        （插件对话框）同一条建议又会冒出来。过滤放在
        `plugin.filter_ignored()`，页面只管画。

    为什么建议既画卡片又留一个纯文本区
        卡片要求模型按 JSON 回答。模型偶尔会回一段大白话 ——
        那时硬塞进「结论 / 证据 / 动作」的壳里读起来很怪，
        所以**原样显示**（`is_structured()` 判据在 `engine.activity.advice`）。
    """

    title = "今日"
    hint = "今天的时间去哪了。数据在本机统计，只有你点「生成建议」时摘要才出网。"

    # ---------------- 构建 ----------------

    def _build_body(self, layout):
        self._advice_buffer = ""
        self._analyzing = False

        layout.addWidget(self._build_record_card())
        layout.addWidget(self._build_dashboard())

        self._empty = EmptyState("monitor", *_EMPTY_DISABLED, parent=self)
        self._empty.hide()
        layout.addWidget(self._empty)

    def _build_record_card(self) -> QWidget:
        card = FormCard("本机记录", self)
        self._chk_enabled = ToggleSwitch("开启活动采集", parent=card)
        self._chk_enabled.toggled.connect(self._on_toggle)
        card.add_widget(self._chk_enabled)
        # 保留天数在 reload() 里按配置回填（这里先给不带保留天数的版本）
        self._privacy = PageHint(_privacy_text(), card)
        card.add_widget(self._privacy)

        row = QWidget(card)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(SPACING["sm"])
        self._btn_clear = Button("清空行为数据", "danger", row, icon_name="trash")
        self._btn_clear.clicked.connect(self._on_clear)
        rl.addWidget(self._btn_clear)
        rl.addStretch()
        card.add_widget(row)
        return card

    def _build_dashboard(self) -> QWidget:
        box = QWidget(self)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACING["md"])

        # --- 概览仪表盘 ---
        # 四个指标不是同等重要：「今日总时长」是这一页的头条数字，
        # 所以给它 primary 变体（accent 软底 + 更大字号）和更多宽度，
        # 其余三个是它的分解。全部一样大等于没有重点。
        self._overview = OverviewBoard("今日概览", box)
        self._tiles = {
            "total": StatTile("今日总时长", icon_name="clock", primary=True),
            "focus": StatTile("深度工作", icon_name="rocket"),
            "top": StatTile("最长应用", icon_name="monitor"),
            "switch": StatTile("切换打断", icon_name="refresh"),
        }
        for key, tile in self._tiles.items():
            self._overview.add_tile(key, tile, stretch=2 if key == "total" else 1)
        lay.addWidget(self._overview)

        # --- 时间轴（整天 0:00–24:00，带刻度）---
        lay.addWidget(SectionLabel("今天的时间去哪了", box))
        self._timeline = TimelineBar()
        lay.addWidget(self._timeline)
        self._axis = AxisLabels()
        self._axis.set_labels(_TIMELINE_TICKS)
        lay.addWidget(self._axis)

        # --- 排行 + 建议 ---
        bottom = QHBoxLayout()
        bottom.setSpacing(SPACING["lg"])
        bottom.addLayout(self._build_rank_column(box), 1)
        bottom.addLayout(self._build_advice_column(box), 1)
        lay.addLayout(bottom, 1)

        self._dashboard = box
        return box

    def _build_rank_column(self, parent) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(SPACING["sm"])
        col.addWidget(SectionLabel("应用排行", parent))
        self._rank = RankBar(limit=5)
        col.addWidget(self._rank)
        col.addStretch(1)
        return col

    def _build_advice_column(self, parent) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(SPACING["sm"])

        # 专注倒计时卡（P2.18）—— 只在专注进行中展开。
        # 放在这一列最上面：它是「此刻正在发生的事」，比下面的历史结论更急。
        self._focus_card = FocusCard(parent)
        self._focus_card.pause_requested.connect(self._on_focus_pause)
        self._focus_card.resume_requested.connect(self._on_focus_resume)
        self._focus_card.stop_requested.connect(self._on_focus_stop)
        self._focus_card.state_changed.connect(self._on_focus_state)
        col.addWidget(self._focus_card)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(SPACING["sm"])
        head.addWidget(SectionLabel("AI 建议", parent))
        head.addStretch(1)
        self._btn_focus = Button(self._focus_button_text("idle"), "default", parent,
                                 icon_name="play")
        # 与建议卡上的按钮共用同一个 id 与同一套 QSS（见 `apply_phase`）
        self._btn_focus.setObjectName(FOCUS_ENTRY_ID)
        self._btn_focus.clicked.connect(self._on_focus)
        head.addWidget(self._btn_focus)
        self._btn_analyze = Button("生成建议", "accent", parent, icon_name="send")
        self._btn_analyze.clicked.connect(self._on_analyze)
        head.addWidget(self._btn_analyze)
        col.addLayout(head)

        # 总结（P2.18）—— 模型给的「今天整体怎么样」，放在卡片上方当锚点
        self._summary = AdviceSummary(parent)
        col.addWidget(self._summary)

        # 建议卡按上限一次性建好，之后只切显隐 —— 每次刷新重建控件树会让
        # 焦点和滚动位置跳掉（RankBar 同款理由）。
        self._cards: list = []
        for _ in range(MAX_ADVICES):
            card = AdviceCard(parent)
            card.decided.connect(self._on_card_decided)
            card.hide()
            self._cards.append(card)
            col.addWidget(card)

        # 模型没按 JSON 回答时的兜底区（原样显示，不硬塞进卡片）
        self._raw = QPlainTextEdit(parent)
        self._raw.setReadOnly(True)
        self._raw.setMinimumHeight(120)
        self._raw.setPlaceholderText(
            "点「生成建议」，AI 读完本机概览后会给出今天的节奏建议。"
        )
        col.addWidget(self._raw)

        self._status = PageHint("", parent)
        col.addWidget(self._status)
        col.addStretch(1)
        return col

    # ---------------- 视图协议（插件按鸭子类型回调这几个）----------------

    def set_status(self, text: str) -> None:
        self._status.setText(text or "")

    def set_advice(self, text: str) -> None:
        """整段替换建议文本（生成结束时插件会发一次完整结果）。"""
        self._advice_buffer = str(text or "")
        self._render_advice()

    def append_advice(self, delta: str) -> None:
        self._advice_buffer += str(delta or "")
        self._render_advice()

    def set_analyzing(self, running: bool) -> None:
        self._analyzing = bool(running)
        self._btn_analyze.setEnabled(not running)
        self._btn_analyze.setText("分析中…" if running else "生成建议")
        self._render_advice()

    # ---------------- 页面钩子 ----------------

    def selected_days(self) -> int:
        return _TODAY_DAYS

    def showEvent(self, event) -> None:
        """页面可见时才轮询番茄钟。

        控制中心常年开着，为一个看不见的倒计时卡每秒读一次状态是白烧电；
        页面被切走就停掉（见 `hideEvent`）。
        """
        super().showEvent(event)
        self._focus_card.set_status_provider(self._focus_status)

    def hideEvent(self, event) -> None:
        self._focus_card.set_status_provider(None)
        super().hideEvent(event)

    def reload(self):
        plugin = _activity_plugin(self.app)
        if plugin is None:
            self._chk_enabled.blockSignals(True)
            self._chk_enabled.setChecked(False)
            self._chk_enabled.blockSignals(False)
            self._chk_enabled.setEnabled(False)
            self._btn_analyze.setEnabled(False)
            self._btn_focus.setEnabled(False)
            self._btn_clear.setEnabled(False)
            self._privacy.setText(_privacy_text())
        else:
            self._chk_enabled.setEnabled(True)
            self._btn_analyze.setEnabled(True)
            # 专注进行中时这些按钮必须是禁用的 —— 重新 enable 会让界面
            # 出现「卡里写着专注中、按钮却写着开始」的自相矛盾状态。
            # 顶部按钮 + 建议卡按钮一起同步（`_focus_card.state()` 在页面
            # 没 show 过时还是 idle，所以这里直接读计时器实况）。
            self._sync_focus_entries()
            self._btn_clear.setEnabled(True)
            self._privacy.setText(_privacy_text(plugin.retention_days()))
            # 阻断信号：回填开关状态不该触发一次「保存」
            self._chk_enabled.blockSignals(True)
            self._chk_enabled.setChecked(bool(plugin.is_enabled()))
            self._chk_enabled.blockSignals(False)
            plugin.attach_view(self)
        self._refresh()

    def save(self) -> bool:
        # 开关是「点一下立即生效」的，没有需要工具栏「保存」的东西。
        return True

    # ---------------- 内部 ----------------

    def _plugin(self):
        return _activity_plugin(self.app)

    def _refresh(self) -> None:
        plugin = self._plugin()
        if plugin is None:
            self._set_empty(_EMPTY_NO_PLUGIN)
            return

        segments = plugin.segments_for(_TODAY_DAYS) or []
        if not segments:
            # 关了采集但还有旧记录时不该走这里 —— 关采集不等于删数据。
            self._set_empty(
                _EMPTY_NO_DATA if plugin.is_enabled() else _EMPTY_DISABLED
            )
            return

        self._empty.hide()
        self._dashboard.show()
        self._fill(segments)
        self._advice_buffer = plugin.cached_advice(_TODAY_DAYS)
        self._render_advice()
        self._update_status(plugin)

    def _set_empty(self, text) -> None:
        self._dashboard.hide()
        self._empty.set_text(*text)
        self._empty.show()
        self._advice_buffer = ""
        self._summary.set_summary("")
        self._show_cards([])
        self._raw.hide()
        self._status.setText("")

    def _fill(self, segments) -> None:
        self._tiles["total"].set_value(human_duration(total_seconds(segments)))
        self._tiles["focus"].set_value(human_duration(focus_seconds(segments)))
        apps = top_apps(segments, limit=1)
        self._tiles["top"].set_value(apps[0]["app"] if apps else "—")
        self._tiles["switch"].set_value(f"{switch_count(segments)} 次")

        start, end = today_range(time.time())
        # 合并放数据层（纯函数、有测试）—— 渲染代码里的计算没法单测，
        # 一旦算错是**静默画错**。
        self._timeline.set_segments(merge_segments(segments), start=start, end=end)

        self._rank.set_items(
            [{"label": a["app"], "value": a["seconds"], "category": a["category"]}
             for a in top_apps(segments, limit=5)],
            value_text=human_duration,
        )

    def _render_advice(self) -> None:
        text = self._advice_buffer
        if self._analyzing:
            # 流式期间不渲染：模型输出的是 JSON，逐块画只会闪一堆半截的
            # `{"headline": …`。进度由状态行表达。
            self._summary.set_summary("")
            self._show_cards([])
            self._raw.hide()
            return
        if is_structured(text):
            report = parse_report(text)
            if report:
                # 总结照原样显示，即使建议被「忽略」光了 —— 它说的是**今天的状态**，
                # 不是某一条建议的附属品，独立成立。
                self._summary.set_summary(report.summary)
                self._show_cards(self._filter_ignored(list(report.advices)))
                self._raw.hide()
                return
            # 合法 JSON 但空结果（模型回了 `[]`）—— 落到下面原样显示，
            # 让用户看得见模型到底回了什么，而不是一片空白
        self._summary.set_summary("")
        self._show_cards([])
        self._raw.setPlainText(text)
        self._raw.show()              # 空文本时显示 placeholder（引导文案）

    def _filter_ignored(self, advices) -> list:
        plugin = self._plugin()
        if plugin is None:
            return list(advices or [])
        return plugin.filter_ignored(advices)

    def _show_cards(self, advices) -> None:
        """只负责把建议铺到卡片上。

        这里**不**顺手同步专注状态 —— 卡片的 `set_advice` 自己会跟随它记住的
        当前状态（见 `AdviceCard.set_advice`），而「全局状态变了」由
        `_on_focus_state` / `reload` 推。两处都做一遍的话，任何一处被删掉
        测试都照样绿 —— 反向验证时正是这么发现两条实现互相兜底的。
        """
        for i, card in enumerate(self._cards):
            if i < len(advices):
                card.set_advice(advices[i])
                card.show()
            else:
                card.hide()

    def _update_status(self, plugin) -> None:
        if not plugin.is_enabled():
            self.set_status("采集已关闭 —— 已有数据不会被删，打开开关继续记录")
        elif plugin.advice_is_stale(_TODAY_DAYS):
            self.set_status("记录有更新，可以重新生成一次建议")
        else:
            self.set_status("")

    def _on_toggle(self, checked: bool) -> None:
        plugin = self._plugin()
        if plugin is None:
            self.warn_no_plugin()
            return
        if not plugin.set_enabled(bool(checked)):
            self._chk_enabled.blockSignals(True)
            self._chk_enabled.setChecked(not checked)
            self._chk_enabled.blockSignals(False)
            self._status.setText("保存设置失败，开关已回退")
            return
        self._refresh()
        if checked:
            self._status.setText("已开启。正常用电脑即可，数据只留在本机。")
        else:
            self._status.setText("已关闭采集。已有的记录还在，可点「清空行为数据」删除。")

    def _on_analyze(self) -> None:
        plugin = self._plugin()
        if plugin is None:
            self.warn_no_plugin()
            return
        message = plugin.generate(_TODAY_DAYS)
        if message:
            self.set_analyzing(False)
            self._status.setText(message)

    def _on_focus(self) -> None:
        self._start_focus(self._focus_minutes())

    def _focus_minutes(self) -> int:
        """顶部按钮默认的专注时长 —— 取番茄钟页设置的那个值。

        写死 25 会在用户把工作时长改成 45 之后变成一句谎话：
        按钮说 25，实际跑 45。
        """
        try:
            return max(1, int(config_manager.get("tomato.work_duration", 25)))
        except Exception:  # noqa: BLE001
            return 25

    def _focus_button_text(self, state: str, kind: str = "work") -> str:
        # 文案与建议卡、番茄钟页共用同一份（见 `focus_label`）——
        # 同一状态在不同入口必须是同一个词。
        return focus_label(state, self._focus_minutes(), kind)

    def _focus_status(self) -> dict:
        """读番茄钟实况。计时器是可选插件 —— 没有就报「不在专注」。"""
        timer = getattr(self.app, "timer", None) if self.app else None
        if timer is None:
            return {"state": "idle"}
        try:
            return timer.get_status()
        except Exception:  # noqa: BLE001
            return {"state": "idle"}

    def _focus_timer(self):
        return getattr(self.app, "timer", None) if self.app else None

    def _on_focus_state(self, state: str) -> None:
        """专注状态变了 —— 同步**每一个**入口。

        不做这一步的话，点完「开始专注」按钮还写着「开始 25 分钟专注」，
        用户会以为没点上（这正是 P2.18 要修的那个「没有直观反馈」）。
        P2.19 补的是：原来只有顶部那一个按钮跟着变，而用户点的是**建议卡**
        上的按钮 —— 它一动不动、还能再点一次。
        """
        self._sync_focus_entries(state)
        if state == "finished":
            self._status.setText("本次专注结束 —— 记录已更新，可以重新生成一次建议")

    def _sync_focus_entries(self, state: str | None = None) -> None:
        """把「现在到底在不在专注」同步到今日页的每个入口。

        为什么必须一处收口（P2.19）
            入口本来就有四个（今日页顶部按钮、每张建议卡上的按钮、番茄钟页
            按钮、番茄钟对话框），而「专注进行中」这个状态是**全局唯一**的。
            同步逻辑散在各处，加一个入口就漏一个 —— 用户偏偏点到漏掉的那个。
            收进一个函数，新入口只要记得调它。

        `state` 传 None 时读计时器实况；`_on_focus_state` 有权威的 state 参数
        就直接用 —— 它来自同一个计时器，再读一次只会多一个不一致的窗口。
        """
        status = self._focus_status()
        if state is None:
            state = str(status.get("state") or "idle")
        kind = str(status.get("type") or "work")
        running = state in ("running", "paused")
        # 「没有插件」和「此刻不在专注」是两件事：前者按钮永远不可用，
        # 后者才该亮着。不加这个判断，一次 `_show_cards` 就会把
        # 「插件缺失 → 按钮禁用」的降级状态重新点亮。
        usable = self._plugin() is not None

        self._btn_focus.setEnabled(usable and not running)
        self._btn_focus.setText(self._focus_button_text(state, kind))
        apply_phase(self._btn_focus, state)
        for card in self._cards:
            card.set_focus_state(state, kind=kind)

    def _on_focus_pause(self) -> None:
        timer = self._focus_timer()
        if timer is not None:
            timer.pause()
        self._focus_card.tick()

    def _on_focus_resume(self) -> None:
        timer = self._focus_timer()
        if timer is not None:
            timer.resume()
        self._focus_card.tick()

    def _on_focus_stop(self) -> None:
        timer = self._focus_timer()
        if timer is not None:
            timer.stop()
        self._focus_card.tick()

    def _start_focus(self, minutes: int) -> bool:
        """开始专注。返回是否真的起来了（调用方要据实记录「影响范围」）。"""
        plugin = self._plugin()
        if plugin is None:
            self.warn_no_plugin()
            return False
        if plugin.start_focus(minutes):
            self._status.setText(f"已开始 {minutes} 分钟专注 —— 结束后再回来看小结")
            # 立刻读一次，别让用户等最多 1 秒才看到卡片出现
            self._focus_card.tick()
            return True
        # 两种失败原因分开说 —— 合在一句里用户不知道该去修什么
        if self._focus_timer() is None:
            self._status.setText("番茄钟插件未加载，无法开始专注")
        else:
            self._status.setText("专注计时已经在跑了 —— 先结束，或等它走完")
        return False

    def _on_card_decided(self, advice, action: str) -> None:
        """用户对一条建议做了决定 —— **一处收口**：留痕在这里做。

        为什么采纳和忽略必须走同一条路
            两者都是「人对 AI 建议的反应」，都要能回答「凭什么、当时什么
            情况、影响了什么」。分成两个槽函数的后果是：忽略有留痕、
            采纳没有 —— 而采纳恰恰是更有说服力的协同证据。

        `action` 来自 `AdviceCard.decided`，取值与 `engine.activity`
        的 `ACTION_ADOPT` / `ACTION_IGNORE` 一致。
        """
        plugin = self._plugin()
        if plugin is None:
            self.warn_no_plugin()
            return
        if action == ACTION_ADOPT:
            action_obj = getattr(advice, "action", None)
            minutes = (int(getattr(action_obj, "minutes") or 0)
                       if getattr(action_obj, "is_actionable", False) else 0)
            if minutes <= 0:
                minutes = self._focus_minutes()
            started = self._start_focus(minutes)
            ok, message = plugin.record_decision(
                advice, action, outcome={"focus_started": started,
                                         "focus_minutes": minutes})
        elif action == ACTION_IGNORE:
            ok, message = plugin.record_decision(advice, action)
        else:
            # 未知类型不猜、也不留痕 —— 留一条语义不明的记录比不记更糟
            return
        if not ok:
            self._status.setText(f"决定没能记录：{message}")
            return
        self._status.setText(message)
        self._render_advice()

    def _on_clear(self) -> None:
        plugin = self._plugin()
        if plugin is None:
            self.warn_no_plugin()
            return
        center = getattr(self, "center", None)
        if center is not None and hasattr(center, "confirm"):
            if not center.confirm(
                "清空行为数据",
                "将删除本机记录的全部活动分段与已生成的建议。\n"
                "此操作不可撤销，会话历史不受影响。",
            ):
                return
        removed = plugin.clear_data()
        self._advice_buffer = ""
        self._refresh()
        self._status.setText(f"已清空 {removed} 条记录")

    def warn_no_plugin(self) -> None:
        center = getattr(self, "center", None)
        if center is not None and hasattr(center, "warn"):
            center.warn("今日", _ACTIVITY_NO_PLUGIN)


# ================================================================
# 页面：趋势
# ================================================================

#: 趋势页的时间范围：(显示名, 天数)。
#: 最长 30 天必须 ≤ `activity.retention_days` 的默认值 —— 否则这个视图
#: 开箱就只有一部分数据（`_trend_footer` 会在两者不一致时如实提示）。
_TREND_RANGES = (("近 7 天", 7), ("近 30 天", 30))

#: 30 天时每几根柱子标一个日期 —— 全标会糊成一片
_TICK_STEP = 6

_EMPTY_TREND_NO_DATA = (
    "这段时间还没有记录",
    "开启活动采集后用几天电脑，这里就会出现每天的节奏对比。\n"
    "今天的数据在「今日」页。",
)
_EMPTY_TREND_NO_PLUGIN = ("活动建议插件未加载", _ACTIVITY_NO_PLUGIN)


def _day_ticks(rows) -> tuple:
    """给每日柱状图挑几个日期刻度（`AxisLabels` 要的 `(fraction, text)`）。

    刻度落在**柱子的中心**（`(i + 0.5) / n`），不是柱子的左边缘 ——
    标在边缘会让人以为刻度对应的是柱子的开始时刻。
    """
    n = len(rows)
    if n == 0:
        return ()
    if n <= 7:
        picks = list(range(n))
    else:
        picks = list(range(0, n, _TICK_STEP))
        if n - 1 not in picks:
            picks.append(n - 1)
    return tuple(
        ((i + 0.5) / n, f"{rows[i]['day']} {rows[i]['weekday']}") for i in picks
    )


def _compare_text(comparison: dict, days: int) -> str:
    """「与上周期对比」那一句话。

    上周期为 0 时**必须**单独说清楚 —— `delta_ratio` 是 None，
    直接算百分比会除零，而显示「增长 0%」是假话（其实是从无到有）。
    """
    previous = comparison["previous"]["total"]
    delta = comparison["delta_seconds"]
    if comparison["delta_ratio"] is None:
        return f"上一个 {days} 天没有记录，无法比较。"

    if abs(delta) < 60:
        return f"和上一个 {days} 天基本持平（都是 {human_duration(previous)} 左右）。"

    direction = "多" if delta > 0 else "少"
    percent = abs(comparison["delta_ratio"]) * 100
    return (
        f"比上一个 {days} 天{direction} {human_duration(abs(delta))}"
        f"（{percent:.0f}%），上周期共 {human_duration(previous)}。"
    )


def _hour_text(peak, buckets, days: int) -> str:
    if peak is None:
        return "这段时间里没有记录到应用切换。"
    average = buckets[peak] / max(1, int(days))
    return (
        f"{hour_label(peak)} 切换最频繁：共 {buckets[peak]} 次，"
        f"平均每天 {average:.1f} 次。"
    )


def _trend_footer(retention_days: int, days: int) -> str:
    """底部一句「数据边界」—— **只在真的会影响读图时才说**。

    原来无条件显示「数据只在本机，保留最近 N 天，不出网。」：
    那句话在隐私卡片 / 今日页已经说过，每页重复一遍就成了噪音，
    而它并不帮助理解眼前这张图。

    真正需要用户知道的是**另一种情况**：保留天数少于所选范围 ——
    那时更早的日子是真的没数据，不说清就会被读成「那几天没干活」。
    """
    if int(retention_days) >= int(days):
        return ""
    return (
        f"当前只保留最近 {int(retention_days)} 天，更早的日子没有数据 —— "
        "可在设置里调大 activity.retention_days。"
    )


class TrendPage(Page):
    """趋势 —— 把最近一段时间摊开看。

    为什么和「今日」分成两页而不是一个范围选择器
        两个问题的形状不一样：「今天」要的是**逐段**的细节（时间轴到分钟），
        「趋势」要的是**跨天**的形状（每天一根柱子）。塞进一页会出现
        「选了 30 天，那时间轴画哪一天」这种没法回答的问题。
        一页只回答一个问题。

    为什么对比的是「上一个同长周期」而不是「上个月」
        「近 30 天」的上一个 30 天是确定的、紧邻的、不重叠也不留缝。
        「上个月」在不同月份长度下会引入「这个月比上个月少 2 天」的噪声。
    """

    title = "趋势"
    hint = "最近一段时间摊开看：每天的深度工作、时间构成、最容易被打断的时段。"

    # ---------------- 构建 ----------------

    def _build_body(self, layout):
        head = QWidget(self)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(SPACING["sm"])
        hl.addWidget(SectionLabel("范围", head))
        self._seg_range = SegmentedControl(
            [label for label, _ in _TREND_RANGES], 0, head
        )
        self._seg_range.changed.connect(lambda _i: self.reload())
        hl.addWidget(self._seg_range)
        hl.addStretch()
        layout.addWidget(head)

        layout.addWidget(self._build_dashboard())

        self._empty = EmptyState("trend", *_EMPTY_TREND_NO_DATA, parent=self)
        self._empty.hide()
        layout.addWidget(self._empty)

    def _build_dashboard(self) -> QWidget:
        box = QWidget(self)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SPACING["md"])

        # --- 概览仪表盘（与「今日」同一套：头条数字更宽 + primary 着色）---
        self._overview = OverviewBoard("本周期概览", box)
        self._tiles = {
            "total": StatTile("本周期总时长", icon_name="clock", primary=True),
            "daily": StatTile("日均", icon_name="trend"),
            "focus": StatTile("深度工作", icon_name="rocket"),
        }
        for key, tile in self._tiles.items():
            self._overview.add_tile(key, tile, stretch=2 if key == "total" else 1)
        lay.addWidget(self._overview)

        # --- 每天的深度工作 ---
        lay.addWidget(SectionLabel("每天的深度工作", box))
        self._chart = BarChart(height=140)
        lay.addWidget(self._chart)
        self._chart_axis = AxisLabels()
        lay.addWidget(self._chart_axis)
        self._compare = PageHint("", box)
        lay.addWidget(self._compare)

        # --- 时间构成 / 最容易被打断的时段 ---
        bottom = QHBoxLayout()
        bottom.setSpacing(SPACING["lg"])

        left = QVBoxLayout()
        left.setSpacing(SPACING["sm"])
        left.addWidget(SectionLabel("时间构成", box))
        self._rank = RankBar(limit=5)
        left.addWidget(self._rank)
        left.addStretch(1)
        bottom.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(SPACING["sm"])
        right.addWidget(SectionLabel("最容易被打断的时段", box))
        self._hours = BarChart(height=140, bar_width=10)
        right.addWidget(self._hours)
        self._hours_axis = AxisLabels()
        right.addWidget(self._hours_axis)
        self._hours_hint = PageHint("", box)
        right.addWidget(self._hours_hint)
        right.addStretch(1)
        bottom.addLayout(right, 1)

        lay.addLayout(bottom, 1)

        self._footer = PageHint("", box)
        lay.addWidget(self._footer)

        self._dashboard = box
        return box

    # ---------------- 页面钩子 ----------------

    def selected_days(self) -> int:
        i = self._seg_range.index()
        if not 0 <= i < len(_TREND_RANGES):
            i = 0
        return _TREND_RANGES[i][1]

    def reload(self):
        plugin = _activity_plugin(self.app)
        if plugin is None:
            self._set_empty(_EMPTY_TREND_NO_PLUGIN)
            return

        days = self.selected_days()
        # 取 2 倍：本周期 + 紧邻的上一个同长周期（对比要用）
        segments = plugin.segments_for(days * 2) or []
        if not segments:
            self._set_empty(_EMPTY_TREND_NO_DATA)
            return

        self._empty.hide()
        self._dashboard.show()
        self._fill(segments, days, plugin)

    def save(self) -> bool:
        return True

    # ---------------- 内部 ----------------

    def _set_empty(self, text) -> None:
        self._dashboard.hide()
        self._empty.set_text(*text)
        self._empty.show()

    def _fill(self, segments, days: int, plugin) -> None:
        comparison = compare_periods(segments, days=days)
        current = comparison["current"]
        # 只统计**本周期**。`segments` 是插件给的 `days * 2` 天（含上周期，
        # 对比要用），直接拿去算「时间构成 / 按小时打断」会算成两个周期的量 ——
        # 同一页上「本周期总时长」是 7 天、「时间构成」却是 14 天。
        this_period = current["segments"]

        self._tiles["total"].set_value(human_duration(current["total"]))
        self._tiles["daily"].set_value(human_duration(current["total"] / days))
        self._tiles["focus"].set_value(human_duration(current["focus"]))

        rows = daily_totals(segments, days=days)
        self._chart.set_data(
            [{"value": r["focus"]} for r in rows], highlight=len(rows) - 1
        )
        self._chart_axis.set_labels(_day_ticks(rows))
        self._compare.setText(_compare_text(comparison, days))

        self._rank.set_items(
            [{"label": c["category"], "value": c["seconds"],
              "category": c["category"]}
             for c in category_totals(this_period)],
            value_text=human_duration,
        )

        buckets = hour_switches(this_period)
        peak = busiest_hour(this_period)
        self._hours.set_data([{"value": v} for v in buckets], highlight=peak)
        self._hours_axis.set_labels(
            tuple(((h + 0.5) / HOURS_PER_DAY, f"{h}:00")
                  for h in range(0, HOURS_PER_DAY, 6))
        )
        self._hours_hint.setText(_hour_text(peak, buckets, days))

        footer = _trend_footer(plugin.retention_days(), days)
        self._footer.setText(footer)
        # 没话说时整行收掉 —— 留一个空 QLabel 会白占一段间距
        self._footer.setVisible(bool(footer))


# ================================================================
# 页面：协同记录（人机决策证据链）
# ================================================================

#: 过滤项：(显示名, `engine.activity` 里的动作常量)。空串 = 全部。
_DECISION_FILTERS = (("全部", ""), ("采纳", ACTION_ADOPT), ("忽略", ACTION_IGNORE))


class DecisionLogPage(Page):
    """人机协同的**证据链**：每条建议被采纳 / 忽略时的依据、现场与影响。

    为什么值得单独一页（而不是在「今日」页塞一个小列表）
        「今日」页回答的是「我今天干得怎么样」，这一页回答的是
        「**我和 AI 是怎么协作的**」—— 前者是结论，后者是过程与凭据。
        评审看的是后者：能逐条核对「AI 凭什么这么说、人凭什么同意」，
        这比再多几个图表更能说明「人机协同」不是一句口号。

    为什么每条都带「当时的数据现场」
        结论会过期、建议会重新生成。只有当场快照能证明
        「他做决定时看到的就是这些数据」—— 事后补记的数字
        证明不了任何事。
    """

    title = "协同记录"
    hint = "你采纳或忽略每条建议时的依据、数据现场与影响范围 —— 逐条可核对。"

    #: 表格行高：结论列会换行，比常规行高一点
    _ROW_HEIGHT = 40

    #: 详情区高度的下限 / 上限（按内容算，见 `_fit_detail`）
    _DETAIL_MIN = 168
    _DETAIL_MAX = 460
    #: 小于这个宽度就不做「按内容算高度」—— 控件还没布局过，估出来的行数没有意义
    _DETAIL_MIN_WIDTH = 200

    def _build_body(self, layout):
        # --- 统计 + 过滤 ---
        bar = QWidget(self)
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(SPACING["sm"])
        self._summary = PageHint("", bar)
        bl.addWidget(self._summary, 1)
        self._filter = SegmentedControl([label for label, _ in _DECISION_FILTERS])
        self._filter.changed.connect(lambda _i: self.reload())
        bl.addWidget(self._filter)
        layout.addWidget(bar)

        # --- 证据链表格 ---
        self._table = QTableWidget(0, 4, self)
        self._table.setHorizontalHeaderLabels(["时间", "决定", "建议结论", "影响范围"])
        configure_table(self._table)
        hh = self._table.horizontalHeader()
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setDefaultSectionSize(self._ROW_HEIGHT)
        self._table.itemSelectionChanged.connect(self._on_row_selected)
        layout.addWidget(self._table)

        # --- 单条留痕的完整内容 ---
        self._detail_card = FormCard("这一条决定的完整留痕", self)
        self._detail = QPlainTextEdit(self._detail_card)
        self._detail.setObjectName("decisionDetail")
        self._detail.setReadOnly(True)
        self._detail.setUndoRedoEnabled(False)
        self._detail.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        # **必须开自动换行**：上下文那行是「今日；现场 6 段记录；累计 1 小时 30 分；
        # 数据范围 14:38–16:08；建议生成于 14:08；…」这种长句，不换行就被
        # 右边缘切掉 —— 而这一页卖的正是「能逐条核对」，看不全等于没留痕。
        # （QPlainTextEdit 的默认是 NoWrap，与 QTextEdit 相反；会话历史页那处
        # 显式设过，这里是新页，漏了。目检 S17 抓到。）
        self._detail.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        # 高度按**内容**定（下限 / 上限见类常量）：短留痕不浪费版面，
        # 长留痕不用在这么小的盒子里滚 —— 这一页的用法就是「逐条核对」，
        # 而页面本身已经在滚动区里（`Page` 把 body 放进 QScrollArea），
        # 所以往上长是安全的。
        self._detail.setFixedHeight(self._DETAIL_MIN)
        self._detail.setProperty("role", "info")
        self._detail.setFont(theme().font_mono)
        self._detail.setPlaceholderText("在上面的表格里点一条决定，这里显示它的依据与上下文。")
        self._detail_card.add_widget(self._detail)
        layout.addWidget(self._detail_card)

        # --- 动作 ---
        actions = QWidget(self)
        al = QHBoxLayout(actions)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(SPACING["sm"])
        self._btn_export = Button("导出证据链…", "accent", parent=actions,
                                  icon_name="save")
        self._btn_export.clicked.connect(self._on_export)
        btn_refresh = Button("刷新", parent=actions, icon_name="refresh")
        btn_refresh.clicked.connect(self.reload)
        al.addWidget(self._btn_export)
        al.addWidget(btn_refresh)
        al.addStretch()
        layout.addWidget(actions)

        self._empty = EmptyState(
            "file-check", "还没有决策记录",
            "在「今日」页对一条建议点「采纳」或「忽略」后，这里会留下完整的证据链。",
            self)
        layout.addWidget(self._empty)

        self._notes = []

    # ----- 数据 -----

    def reload(self):
        plugin = _activity_plugin(self.app)
        if plugin is None:
            self._notes = []
            self._table.setRowCount(0)
            self._summary.setText(_ACTIVITY_NO_PLUGIN)
            self._empty.setVisible(False)
            self._detail_card.setVisible(False)
            self._btn_export.setEnabled(False)
            return

        index = max(0, int(self._filter.index()))
        action = _DECISION_FILTERS[index][1]
        self._notes = plugin.decision_log(limit=500, action=action)
        self._fill_table()

        adopted = plugin.count_decisions(ACTION_ADOPT)
        ignored = plugin.count_decisions(ACTION_IGNORE)
        self._summary.setText(
            f"共 {adopted + ignored} 条决定（采纳 {adopted} / 忽略 {ignored}）。"
            "每条都含推荐依据、决定时的数据现场与影响范围。")
        # 空态与表格互斥：两者同时出现会让用户以为「有数据但画不出来」
        has_any = bool(adopted or ignored)
        self._table.setVisible(has_any)
        self._empty.setVisible(not has_any)
        # 「没有记录」时**整页要自洽**：只藏表格还不够 —— 旁边那块
        # 「这一条决定的完整留痕」空卡和「导出证据链…」按钮会同时挂在那里，
        # 一边说「还没有决策记录」一边请你导出，用户只能理解为界面坏了。
        # 导出用**禁用**而不是隐藏：它解释「这里本来有个功能」，且不跳版；
        # 「刷新」保持可用 —— 去今日页做一次决定再回来，是这个空态的下一步。
        # （规格断言只钉了表格与空态互斥，这一处是目检 S17 抓到的。）
        self._detail_card.setVisible(has_any)
        self._btn_export.setEnabled(has_any)
        if not has_any:
            self._detail.setPlainText("")
            self._detail.setFixedHeight(self._DETAIL_MIN)

    def _fill_table(self):
        self._table.setRowCount(0)
        for note in self._notes:
            row = self._table.rowCount()
            self._table.insertRow(row)
            stamp = (datetime.fromtimestamp(note.at).strftime("%m-%d %H:%M")
                     if note.at else "—")
            for col, text in enumerate(
                    (stamp, note.action_label, note.headline, note.impact)):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setToolTip(
                        datetime.fromtimestamp(note.at).strftime("%Y-%m-%d %H:%M:%S")
                        if note.at else "")
                self._table.setItem(row, col, item)
        if self._notes:
            self._table.selectRow(0)
        else:
            self._detail.setPlainText("")
            self._detail.setFixedHeight(self._DETAIL_MIN)

    def _on_row_selected(self) -> None:
        rows = self._table.selectionModel().selectedRows() \
            if self._table.selectionModel() else []
        index = rows[0].row() if rows else -1
        if not (0 <= index < len(self._notes)):
            return
        self._detail.setPlainText(_note_text(self._notes[index]))
        self._fit_detail()

    def _fit_detail(self) -> None:
        """把详情区高度调到「内容刚好放得下」（夹在 `_DETAIL_MIN` / `_DETAIL_MAX` 之间）。

        为什么不让它固定成一个高度：留痕的长短差得很远 ——
        一条只有一行证据的和一条三行证据 + 长上下文的，共用 148px 的结果
        就是后者永远要在盒子里滚（而外面明明还有地方）。

        为什么自己数行、不用 `document().size()`
            `QPlainTextDocumentLayout` 是**惰性排版**的：控件没画过之前
            `document().size()` / `documentLayout().documentSize()` 都返回
            「一行」的高度（实测 14px），照它设高度等于永远贴着下限 ——
            第一版就是这么写的，目检图里那块还是被切掉。
            这里改用 `QFontMetrics` 自己算换行后的行数：确定、可单测，
            不依赖 Qt 什么时候愿意排版。
        """
        fm = QFontMetrics(self._detail.font())
        width = self._detail.viewport().width()
        if width < self._DETAIL_MIN_WIDTH:
            # 还没布局过（`reload()` 发生在 `__init__` 里，那时宽度还没定）。
            # 拿一个几十像素的宽度去估换行，行数会算到天上、每次都顶到上限，
            # 显示出来还会「先很高、show 完缩回去」。宁可不改，交给 showEvent。
            return
        lines = 0
        for raw in self._detail.toPlainText().split("\n"):
            if not raw:
                lines += 1
                continue
            lines += max(1, math.ceil(fm.horizontalAdvance(raw) / width))
        # 留两行余量：① 估算按字符宽度算，实际换行可能因为标点 / 空格提前断；
        # ② `QPlainTextEdit` 文档还有上下 margin（默认 4px 各一边）。
        # 宁可多两行空白，也不要在盒子里再套一层滚动。
        needed = (lines + 2) * fm.lineSpacing() + 12
        self._detail.setFixedHeight(
            max(self._DETAIL_MIN, min(self._DETAIL_MAX, needed)))

    def showEvent(self, event) -> None:  # noqa: N802 —— Qt 命名
        super().showEvent(event)
        # 宽度要等布局算完才知道，而 `reload()` 发生在 `__init__` 里（那时宽度还没定）
        self._fit_detail()

    def _on_export(self) -> None:
        plugin = _activity_plugin(self.app)
        if plugin is None:
            self.center.warn("协同记录", _ACTIVITY_NO_PLUGIN)
            return
        # 判据是**条数**而不是「导出文本空不空」：`format_notes([])` 仍会给出
        # 一份带标题的文档（那是对的，导出物必须自解释）。拿文本当判据，
        # 这个分支永远不会触发，用户会走进一个「保存空文件」的对话框。
        if not plugin.count_decisions():
            self.center.warn("导出失败", "还没有决策记录可导出。")
            return
        text = plugin.export_decisions()
        default = f"协同证据链_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
        path, _f = QFileDialog.getSaveFileName(
            self, "导出人机协同证据链", str(Path.home() / default),
            "文本文件 (*.txt)")
        if not path:
            return
        try:
            Path(path).write_text(text, encoding="utf-8")
        except OSError as e:  # noqa: BLE001
            self.center.warn("导出失败", f"{type(e).__name__}: {e}")
            return
        self.center.info("已导出", f"证据链已保存到：\n{path}")


def _note_text(note) -> str:
    """单条留痕 → 详情区的纯文本。

    与 `format_notes` 的导出格式**同一套字段**，但这里是给屏幕看的：
    多一行「建议指纹」，方便对着数据库或日志核对同一条建议。
    """
    lines = [
        f"决定：{note.action_label}",
        f"建议结论：{note.headline}",
        f"建议指纹：{note.fingerprint}",
        "",
        "推荐依据（AI 给出、用户据此判断）：",
    ]
    lines += [f"  · {b}" for b in note.basis] or ["  · （模型未提供证据）"]
    lines += [
        "",
        "上下文（决定那一刻的数据现场）：",
        f"  {format_context(note.context)}",
        "",
        "影响范围：",
        f"  {note.impact or '（未记录）'}",
    ]
    if note.at:
        lines.append("")
        lines.append("决定时间：" + datetime.fromtimestamp(
            note.at).strftime("%Y-%m-%d %H:%M:%S"))
    return "\n".join(lines)


# ================================================================
# 页面：应用分类（纠正系统的判定）
# ================================================================

#: 列表回看多少天。归类是**按应用**生效的（改一次，全部历史跟着变），
#: 但列表得能看见「最近在用什么」—— 7 天是个够用又不至于太长的窗口。
_APP_CATEGORY_DAYS = 7

#: 下拉里代表「不手动指定，用系统判定」的那一项。
_AUTO_LABEL = "自动判定"


class AppCategoryPage(Page):
    """把某个应用手动归到指定类别 —— 自动判定之外的那个出口。

    为什么需要这一页
        「工作 / 学习 / 沟通 / 娱乐」的自动判定只能看进程名和窗口标题，
        它不可能知道你的 Chrome 是在写文档还是在刷视频。与其把分类器
        越写越复杂（越复杂越难解释、也越容易再判错），不如给它一个**出口**：
        判错了，用户改一次，从此这个应用都按他说的算。

    为什么粒度是「应用」而不是「每一段」
        同一个应用的多个段归成一类才有意义（改一次生效全部历史）。
        段级覆盖会让「这个应用到底算什么」失去唯一答案，而所有统计
        （深度工作时长、按类别构成）都建立在「一个应用一个类别」上。

    为什么改动「对历史也生效」
        覆盖发生在**读取时**（`store._rows`），原始 `category` 列从没被改过。
        所以用户看到的永远是「按他说的算」，而「系统当初判成什么」仍然
        查得到（表格里的「系统判定」列），撤销也只是删掉一行覆盖记录。
    """

    title = "应用分类"
    hint = ("系统按进程名与窗口标题自动判定类别。判错的应用在这里改成你要的类别，"
            "改动对该应用的全部记录生效（含历史）。")

    #: 表格行高 —— 「归类」列里放的是下拉框，比纯文字行要高一点
    _ROW_HEIGHT = 40
    #: 表体高度的下限 / 上限（按行数算，见 `_fit_table`）
    _TABLE_MIN = 180
    _TABLE_MAX = 480
    #: 表头高度（`configure_table` 之后就是固定的，不必等布局）
    _HEADER_HEIGHT = 34

    def _build_body(self, layout):
        # --- 分类项与判定依据 ---
        # 文案取自 `engine.activity.category.CATEGORY_RULES`，**不在页面里重写一份** ——
        # 重写一份的下场是改了分类器忘了改这里，页面开始说假话。
        rules = FormCard("分类项与判定依据", self)
        for name in CATEGORIES:
            rules.add(name, PageHint(CATEGORY_RULES.get(name, ""), rules))
        layout.addWidget(rules)

        # --- 应用列表 ---
        self._toolbar = QWidget(self)
        bl = QHBoxLayout(self._toolbar)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(SPACING["sm"])
        self._summary = PageHint("", self._toolbar)
        bl.addWidget(self._summary, 1)
        self._btn_reset_all = Button("全部恢复自动判定", parent=self._toolbar,
                                     icon_name="refresh")
        self._btn_reset_all.clicked.connect(self._on_reset_all)
        bl.addWidget(self._btn_reset_all)
        layout.addWidget(self._toolbar)

        self._table = QTableWidget(0, 4, self)
        self._table.setHorizontalHeaderLabels(
            ["应用", "停留时长", "系统判定", "你的归类"])
        configure_table(self._table)
        hh = self._table.horizontalHeader()
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        hh.resizeSection(3, 150)
        self._table.verticalHeader().setDefaultSectionSize(self._ROW_HEIGHT)
        self._table.setFixedHeight(self._TABLE_MIN)
        layout.addWidget(self._table)

        self._status = PageHint("", self)
        layout.addWidget(self._status)

        self._empty = EmptyState(
            "monitor", "还没有可归类的应用",
            "打开「今日」页的采集开关，正常用一会儿电脑，"
            "这里会列出最近出现过的应用。", self)
        layout.addWidget(self._empty)

        self._rows = []

    # ----- 数据 -----

    def _plugin(self):
        return _activity_plugin(self.app)

    def reload(self):
        plugin = self._plugin()
        if plugin is None:
            self._rows = []
            self._table.setRowCount(0)
            self._summary.setText(_ACTIVITY_NO_PLUGIN)
            self._table.setVisible(False)
            self._btn_reset_all.setEnabled(False)
            self._status.setText("")
            self._empty.setVisible(True)
            return

        self._rows = plugin.app_totals(_APP_CATEGORY_DAYS)
        manual = plugin.app_categories()

        if not self._rows:
            # 空态要**整页自洽**：那一行是「列表工具栏」（汇总 + 恢复按钮），
            # 没有列表就没有工具栏 —— 留着的话会出现「没有应用可归类，却请你
            # 恢复归类」的禁用按钮孤零零挂在右边，和下面「还没有可归类的应用」
            # 互相打架；再叠一句状态说明就是第三遍说同一件事。
            # 整行隐藏，说明交给空态本身（目检 S18 抓到的）。
            self._table.setRowCount(0)
            self._table.setVisible(False)
            self._toolbar.setVisible(False)
            self._status.setText("")
            self._empty.setVisible(True)
            return

        self._empty.setVisible(False)
        self._table.setVisible(True)
        self._toolbar.setVisible(True)
        self._fill_table()

        total = len(self._rows)
        changed = sum(1 for r in self._rows if r.get("manual"))
        self._summary.setText(
            f"近 {_APP_CATEGORY_DAYS} 天用过 {total} 个应用，"
            + (f"其中 {changed} 个已手动归类。" if changed else "全部按系统判定。"))
        self._btn_reset_all.setEnabled(bool(manual))
        self._status.setText(
            "「系统判定」是分类器给出的结果，只读；「你的归类」是你的选择，优先。")

    def _fill_table(self):
        self._table.setRowCount(0)
        for row in self._rows:
            index = self._table.rowCount()
            self._table.insertRow(index)
            app = str(row.get("app") or "unknown")
            # 被手动改过的行：`category` 是覆盖后的值，`auto_category` 才是系统判定
            auto = str(row.get("auto_category") or row.get("category") or "其他")
            current = str(row.get("category") or auto)

            name_item = QTableWidgetItem(app)
            if row.get("manual"):
                # 改过的行用强调色 —— 汇总行说「其中 1 个已手动归类」，
                # 用户得能一眼找到是哪一个，不能让他逐行读下拉框。
                name_item.setForeground(QBrush(theme().color("accent")))
                name_item.setToolTip(f"你把它从「{auto}」改成了「{current}」")
            self._table.setItem(index, 0, name_item)
            self._table.setItem(index, 1, QTableWidgetItem(
                human_duration(row.get("seconds") or 0.0)))
            self._table.setItem(index, 2, QTableWidgetItem(auto))
            self._table.setCellWidget(index, 3,
                                      self._make_combo(app, auto, current))
        self._fit_table()

    def _make_combo(self, app: str, auto: str, current: str) -> QWidget:
        """「你的归类」下拉框。

        第一项是 `自动判定`（= 不覆盖，回到系统判定），后面是五个类别。
        用 `activated` 而不是 `currentIndexChanged` —— 后者在**程序设置
        索引**时也会触发，回填状态时会把每一行都当成一次用户操作写进库。
        """
        holder = QWidget(self._table)
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(0, SPACING["xs"], SPACING["sm"], SPACING["xs"])
        combo = QComboBox(holder)
        combo.addItem(_AUTO_LABEL)
        combo.addItems(list(CATEGORIES))
        # 只有「确实覆盖过」才把下拉指到那个类别；否则停在「自动判定」——
        # 覆盖值与系统判定相同时不算覆盖（见 `_on_category_changed`）。
        combo.setCurrentIndex(
            combo.findText(current) if current in CATEGORIES and current != auto else 0
        )
        combo.activated.connect(
            lambda _i, a=app, c=combo, au=auto: self._on_category_changed(a, c, au))
        lay.addWidget(combo)
        return holder

    def _fit_table(self) -> None:
        """按行数定表体高度：行少时不留一大片空白，行多时表内滚动。

        与协同记录页的详情区不同，这里的高度**可以直接算出来**
        （行高是常量、行数已知），不依赖 Qt 什么时候排版 ——
        所以不需要那个「宽度不够就先不改」的守卫。
        """
        rows = max(1, self._table.rowCount())
        needed = self._HEADER_HEIGHT + rows * self._ROW_HEIGHT + 4
        self._table.setFixedHeight(
            max(self._TABLE_MIN, min(self._TABLE_MAX, needed)))

    # ----- 交互 -----

    def _on_category_changed(self, app: str, combo, auto: str) -> None:
        plugin = self._plugin()
        if plugin is None:
            return
        label = str(combo.currentText())
        if label == _AUTO_LABEL or label == auto:
            # 两种都等于「不需要覆盖」：选了「自动判定」，或者选的正好等于
            # 系统判定。后者若写成一条覆盖记录，下次刷新时下拉会跳回
            # 「自动判定」（因为 `apply_overrides` 不认为它与自动判定不同），
            # 用户会以为「选了没保存上」。所以这里一律走**撤销**。
            ok, message = plugin.clear_app_category(app)
            if not ok:
                # 本来就没有覆盖 —— 不是错误，只是「保持系统判定」
                ok, message = True, f"「{app}」保持系统判定「{auto}」"
        else:
            ok, message = plugin.set_app_category(app, label)
        if ok:
            # 归类会改变「深度工作」与「按类别构成」，进而改变缓存建议的有效性
            # （指纹里带了归类，见 `plugin._data_signature`）—— 所以整页重来一次，
            # 而不是只改这一行，免得汇总行还写着旧数字。
            self.reload()
            # **动作反馈必须在 reload 之后写**：reload 会把状态行重置成
            # 常驻说明，先写就被盖掉了 —— 用户点完下拉等于没有任何反馈
            # （「点完没反馈」是本项目踩过好几次的老毛病）。
            self._status.setText(message)
        else:
            self._status.setText(message)

    def _on_reset_all(self) -> None:
        plugin = self._plugin()
        if plugin is None:
            return
        removed = plugin.clear_app_categories()
        self.reload()
        # 同 `_on_category_changed`：反馈要写在 reload 之后才不会被盖掉
        self._status.setText(
            f"已恢复 {removed} 个应用的自动判定。" if removed else "没有需要恢复的归类。")


# ================================================================
# 主窗口
# ================================================================

#: 导航分组：(组名, [(图标, 标题, 页面类), ...])
#:
#: 为什么要分组（P2.14）
#:     10 个平级项铺一长条，用户找不到东西 —— 尤其「今日」这种主功能
#:     混在设置项里等于藏起来了。分成「数据 / 功能 / 系统」三组后，
#:     「我来看数据」和「我要改设置」是两个明显不同的入口。
#:
#: 顺序即重要性：**数据组放最上面且默认打开「今日」** ——
#: 这是把活动洞察升级成主功能的关键一步，不能又排到设置后面。
NAV_GROUPS = [
    ("数据", [
        ("monitor", "今日", TodayPage),
        ("trend", "趋势", TrendPage),
        ("sliders", "应用分类", AppCategoryPage),
        ("file-check", "协同记录", DecisionLogPage),
    ]),
    ("功能", [
        ("palette", "外观", AppearancePage),
        ("sliders", "行为", BehaviorPage),
        ("clock", "番茄钟", TomatoPage),
        ("sparkles", "AI 服务", AIServicePage),
        ("history", "会话历史", SessionsPage),
        ("wrench", "预设", PresetsPage),
    ]),
    ("系统", [
        ("puzzle", "插件", PluginsPage),
        ("shield", "隐私与数据", PrivacyPage),
        ("scroll", "日志", LogsPage),
        ("info", "关于", AboutPage),
    ]),
]

#: 扁平化的导航项（组名不在这里）—— 保持这个形状是因为：
#:   ① 页面顺序 = 导航顺序，`len(_pages) == len(NAV_ITEMS)` 这类断言仍然成立；
#:   ② S8 预览脚本与既有测试都按 (图标, 标题, 类) 三元组遍历。
NAV_ITEMS = [item for _group, items in NAV_GROUPS for item in items]


class ControlCenter(QMainWindow):
    """控制中心主窗口。"""

    closing = Signal()

    def __init__(self, app=None, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle(f"{APP_NAME} · 控制中心")
        self.setMinimumSize(880, 600)
        self.resize(980, 660)

        self._build_toolbar()
        self._build_body()
        self._build_statusbar()

        theme().changed.connect(self._on_theme_changed)
        self.refresh_status()

    # ------------------------------------------------------------ 工具栏

    def _build_toolbar(self):
        tb = QToolBar("main", self)
        tb.setObjectName("mainToolBar")
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(tb)
        self._toolbar = tb

        self._btn_theme = ToolButton("moon", "切换浅色 / 深色主题")
        self._btn_theme.clicked.connect(self._toggle_theme)
        tb.addWidget(self._btn_theme)

        btn_refresh = ToolButton("refresh", "重新载入当前页")
        btn_refresh.clicked.connect(self.reload_current)
        tb.addWidget(btn_refresh)

        btn_save = ToolButton("save", "保存当前页设置", accent=True)
        btn_save.clicked.connect(self.save_current)
        tb.addWidget(btn_save)

        tb.addSeparator()

        btn_cfg = ToolButton("folder", "打开配置目录")
        btn_cfg.clicked.connect(lambda: open_path(CONFIG_DIR))
        tb.addWidget(btn_cfg)

        btn_log = ToolButton("terminal", "打开日志目录")
        btn_log.clicked.connect(lambda: open_path(LOG_DIR))
        tb.addWidget(btn_log)

        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        btn_about = ToolButton("info", "关于")
        btn_about.clicked.connect(lambda: self.goto("关于"))
        tb.addWidget(btn_about)

    # ------------------------------------------------------------ 主体

    def _build_body(self):
        central = QWidget(self)
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self._nav = NavList(central, width=208)
        self._stack = QStackedWidget(central)
        self._stack.setObjectName("workspace")

        self._pages: list[Page] = []
        # 页序号 → 导航行号。插了分组标题行以后**行号不再等于页序号**，
        # 所有「跳到第 i 页」的地方都必须经这张表（`goto` 也一样）。
        self._nav_rows: list[int] = []
        for group_label, items in NAV_GROUPS:
            self._nav.add_group(group_label)
            for icon_name, label, page_cls in items:
                self._nav_rows.append(self._nav.count())
                self._nav.add_nav(icon_name, label)
                page = page_cls(self, self._stack)
                self._pages.append(page)
                self._stack.addWidget(page)

        self._nav.currentRowChanged.connect(self._on_nav_row_changed)
        if self._nav_rows:
            self._nav.setCurrentRow(self._nav_rows[0])

        row.addWidget(self._nav)
        row.addWidget(self._stack, 1)
        self.setCentralWidget(central)

    def _on_nav_row_changed(self, row: int) -> None:
        """导航行 → 工作区页。

        分组标题行不可选中，正常不会走到这里；仍做映射而不是直接把
        `row` 当页号 —— 一旦将来有人给标题行加了可选中标志，
        直接当页号会静默跳到错误的页面。
        """
        if row in self._nav_rows:
            self._stack.setCurrentIndex(self._nav_rows.index(row))

    # ------------------------------------------------------------ 状态栏

    def _build_statusbar(self):
        sb = QStatusBar(self)
        sb.setSizeGripEnabled(False)
        self.setStatusBar(sb)

        self._busy = BusyIndicator("处理中…", sb)
        sb.addPermanentWidget(self._busy)

        self._lbl_theme = QLabel("", sb)
        self._lbl_model = QLabel("", sb)
        self._lbl_plugins = QLabel("", sb)
        for w in (self._lbl_theme, self._lbl_model, self._lbl_plugins):
            sb.addPermanentWidget(w)

    def store(self):
        """会话 / 预设数据库（进程级共享单例）。

        与 AI 插件共用同一个 SQLite 连接 —— 各开各的连接在 WAL 下并发写会
        撞 `database is locked`。取不到时返回 `None`，页面自行降级为空状态。
        """
        try:
            from engine.ai import shared_store

            return shared_store()
        except Exception as e:  # noqa: BLE001
            log_manager.error(f"打开会话数据库失败: {e}")
            return None

    def continue_session(self, session_id, messages) -> bool:
        """把一条历史会话交给 AI 面板继续对话。

        为什么用鸭子类型而不是 `import AIAssistantPlugin`
            控制中心不该硬依赖某个插件 —— 插件可以被禁用或整个移除。
            取不到就明确告诉用户「不是坏了，是 AI 插件没开」，
            比抛异常或静默失败好得多。
        """
        pm = getattr(self.app, "plugin_manager", None)
        plugin = pm.get_plugin("ai_assistant") if pm is not None else None
        if plugin is None or not hasattr(plugin, "continue_session"):
            self.warn(
                "继续对话",
                "AI 助手插件未加载，无法继续对话。\n"
                "可在「插件」页确认它是否被禁用。",
            )
            return False
        if not plugin.continue_session(session_id, messages):
            self.warn(
                "继续对话",
                "AI 面板未就绪 —— 可能 AI 功能已在配置里禁用，或 UI 尚未初始化。",
            )
            return False
        self.statusMessage("已把会话载入 AI 面板，接着问就好")
        return True

    def refresh_status(self):
        t = theme()
        self._lbl_theme.setText(f"主题 {t.name}")
        model = config_manager.get("ai.model", "") or "未配置"
        self._lbl_model.setText(f"模型 {model}")
        pm = getattr(self.app, "plugin_manager", None) if self.app else None
        count = len(pm.get_all_plugins()) if pm else 0
        self._lbl_plugins.setText(f"插件 {count}")

    def set_busy(self, busy: bool, text: str = "处理中…"):
        if busy:
            self._busy.start(text)
        else:
            self._busy.stop()

    def _on_theme_changed(self):
        self._btn_theme.set_icon("sun" if theme().dark else "moon")
        self.refresh_status()

    def _toggle_theme(self):
        set_theme(THEME_LIGHT if theme().dark else THEME_DARK)
        self.refresh_status()

    # ------------------------------------------------------------ 动作

    def current_page(self) -> Page | None:
        return self._pages[self._stack.currentIndex()] if self._pages else None

    def goto(self, title: str) -> None:
        for i, page in enumerate(self._pages):
            if page.title == title:
                if i < len(self._nav_rows):
                    self._nav.setCurrentRow(self._nav_rows[i])
                return

    def reload_current(self):
        page = self.current_page()
        if page is None:
            return
        with busy_cursor():
            page.reload()
        self.statusMessage(f"已重新载入「{page.title}」")

    def save_current(self):
        page = self.current_page()
        if page is None:
            return
        try:
            ok = page.save()
        except Exception as e:  # noqa: BLE001 —— 保存失败必须可见，不能静默
            log_manager.error(f"保存设置失败: {e}")
            self.warn("保存失败", f"{type(e).__name__}: {e}")
            return
        if ok:
            self.info("已保存", f"「{page.title}」的设置已写入配置文件。")
        self.refresh_status()

    # ----- 提示 -----

    def statusMessage(self, text: str, timeout: int = 4000):
        self.statusBar().showMessage(text, timeout)

    def info(self, title: str, text: str):
        self.statusMessage(text)
        log_manager.info(f"[控制中心] {title}: {text}")

    def warn(self, title: str, text: str):
        from presentation.dialogs import message_box

        message_box(self, QMessageBox.Icon.Warning, title, text)

    def confirm(self, title: str, text: str) -> bool:
        from presentation.dialogs import message_box

        return message_box(
            self, QMessageBox.Icon.Question, title, text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes

    # ------------------------------------------------------------ 生命周期

    def closeEvent(self, event):
        # 关闭 = 隐藏：实例留着，下次打开是瞬时的。
        # （quitOnLastWindowClosed 已是 False，退出只走托盘菜单的「退出」。）
        event.ignore()
        self.hide()
        self.closing.emit()


# ================================================================
# 单例入口
# ================================================================

_instance: ControlCenter | None = None


def control_center(app=None) -> ControlCenter:
    """取（必要时创建）控制中心单例。"""
    global _instance
    if _instance is None:
        _instance = ControlCenter(app=app)
    elif app is not None:
        _instance.app = app
    return _instance


def open_control_center(app=None) -> ControlCenter:
    """显示控制中心（已打开则提到最前，不重复建窗）。"""
    win = control_center(app)
    win.show()
    win.raise_()
    win.activateWindow()
    return win


def reset_instance() -> None:
    """丢弃单例（测试专用）。"""
    global _instance
    _instance = None
