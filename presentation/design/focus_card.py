# -*- coding: utf-8 -*-
"""专注倒计时卡 —— 把「已开始专注」从一行状态文字变成一块看得见的进度。

为什么必须有它（P2.18）
    原来点「开始 25 分钟专注」只往页面底部写一行字，页面其余部分毫无变化：
    看不到还剩多久、看不到能不能停、看不到它是不是真的开始了。
    用户的第一反应是「点了没反应」。这不是文案问题 ——
    **一个持续几十分钟的状态，必须有同样持续的可见载体**。

为什么用 1 秒轮询而不是订阅 TIMER_TICK
    番茄钟在**工作线程**里跑循环。事件总线是同步的，把 Qt 槽直接连上去
    等于在工作线程里动控件（Qt 只在 QObject 之间做队列连接）。
    轮询 `timer.get_status()` 只读几个属性，没有线程问题，也不依赖
    事件总线的连接语义 —— 与番茄钟对话框的做法一致。

为什么控件只读、动作靠信号往外发
    卡片不持有计时器：它拿一个 `status_provider` 只读状态，
    按钮只发 `*_requested` 信号。这样单测可以直接喂一个假状态，
    不必搭一个真的番茄钟，也不会出现「卡片偷偷改了计时器」这种耦合。
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout

from .theme import theme
from .tokens import SPACING
from .widgets import Button

#: 轮询间隔。倒计时要看得出在走 —— 1 秒是与番茄钟对话框一致的值。
TICK_MS = 1_000

#: 计时类型 —— 「工作」和「休息」在界面上是两个词，不能混着说。
KIND_WORK = "work"
KIND_BREAK = "break"

#: 卡片只在 running / paused 时展开；idle / finished 一律收起。
ACTIVE_STATES = ("running", "paused")

#: 「专注入口」按钮共用的 objectName —— 今日页顶部按钮与建议卡上的按钮都用它。
#: QSS 里那条 `#focusEntry[phase="…"]` 必须同名（有测试钉住两者一致）。
#: 为什么要靠 id 抬特异度：按钮是真的 `setEnabled(False)`，不压过通用的
#: `QPushButton:disabled` 就会被那片灰盖住，而这里要的是「正在进行」不是「坏了」。
FOCUS_ENTRY_ID = "focusEntry"


def apply_phase(widget, state: str) -> None:
    """把专注状态挂成 `phase` 属性并重新 polish —— 属性选择器不重刷不生效。

    为什么属性叫 `phase` 而不是 `focus`（P2.19 实测踩到）
        `focus` 是 **QWidget 的内建 bool 属性**（QSS 里还是 `:focus` 伪状态）。
        `setProperty("focus", "running")` 之后 `property("focus")` 读回来是
        `False` —— 字符串值被内建属性吞掉，于是 `QPushButton[focus="running"]`
        **永远不匹配**，且不报任何错。现象极具误导性：属性「设上了」、
        `unpolish/polish` 也调了、样式就是不变 —— 看起来像层叠顺序或
        特异度问题，实则是名字撞了内建属性。
        实测对照：`[focus=…]` 渲染出通用禁用灰 `#f3f3f3`，`[phase=…]`
        立刻出琥珀 `#9c5b00`。**给控件属性取名前，先查一遍 QWidget 的
        内建属性与 QSS 伪状态名单。**
    """
    flag = state if state in ACTIVE_STATES else None
    widget.setProperty("phase", flag)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


def _is_break(kind) -> bool:
    return str(kind or KIND_WORK) == KIND_BREAK


def format_clock(seconds) -> str:
    """`12:05` —— 与番茄钟对话框、托盘提示同一套格式。"""
    try:
        total = max(0, int(seconds))
    except (TypeError, ValueError):
        total = 0
    return f"{total // 60:02d}:{total % 60:02d}"


def duration_text(seconds) -> str:
    """`5400` → `90 分钟`。读不出来就给空串（调用方据此决定省不省这一段）。"""
    try:
        total = max(0, int(seconds))
    except (TypeError, ValueError):
        return ""
    minutes = int(round(total / 60))
    return f"{minutes} 分钟" if minutes else ""


def focus_label(state: str, minutes: int = 0, kind: str = "work") -> str:
    """专注**入口按钮**的文案 —— 所有入口共用这一份。

    为什么必须共用（P2.19）
        同一时刻只有一个计时在跑，而界面上有四个「开始专注」入口
        （今日页顶部 / 建议卡 / 番茄钟页 / 番茄钟对话框）。文案各写各的，
        就会出现「一个写着专注中、另一个还写着开始」的自相矛盾 ——
        而用户看到的偏偏是自己视线里那一个。
        文案收在一处，「同一状态同一个词」就成了结构性保证，不靠自觉。
    """
    if state == "running":
        return "休息中…" if _is_break(kind) else "专注中…"
    if state == "paused":
        return "休息已暂停" if _is_break(kind) else "已暂停"
    return f"开始 {max(0, int(minutes or 0))} 分钟专注"


def focus_title(state: str, kind: str = "work", total: int = 0) -> str:
    """倒计时卡标题 —— 说清「在做什么」和**这一轮多长**。

    为什么要把时长写进标题（P2.19）
        建议卡上承诺的是「开始 90 分钟专注」，点下去以后卡里只剩一个在走的
        `12:34` —— 用户没法核对它到底按 90 分钟跑、还是按默认的 25 分钟。
        总时长是那句承诺的唯一凭据，必须可见。
        （顺带修掉一个旧错：休息阶段原来也写「专注中」。）
    """
    if state not in ACTIVE_STATES:
        return ""
    what = "休息" if _is_break(kind) else "专注"
    span = duration_text(total)
    suffix = f" · {span}" if span else ""
    return f"{what}已暂停{suffix}" if state == "paused" else f"{what}中{suffix}"


class FocusCard(QFrame):
    """专注倒计时卡：状态标题 + MM:SS + 进度条 + 暂停/结束。"""

    pause_requested = Signal()
    resume_requested = Signal()
    stop_requested = Signal()
    #: 状态变化（"idle" / "running" / "paused" / "finished"）。
    #: 页面据此同步顶部那个「开始专注」按钮 —— 否则会出现
    #: 「卡里写着专注中，按钮还写着开始」这种自相矛盾的界面。
    state_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("focusCard")
        self._provider: Optional[Callable[[], dict]] = None
        self._state = "idle"

        lay = QVBoxLayout(self)
        lay.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        lay.setSpacing(SPACING["sm"])

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(SPACING["sm"])
        self._title = QLabel("", self)
        self._title.setObjectName("focusTitle")
        self._clock = QLabel("00:00", self)
        self._clock.setObjectName("focusClock")
        self._clock.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        font = QFont(theme().font_mono)
        font.setPointSizeF(theme().font.pointSizeF() + 6)
        font.setWeight(QFont.Weight.DemiBold)
        self._clock.setFont(font)
        head.addWidget(self._title)
        head.addStretch(1)
        head.addWidget(self._clock)
        lay.addLayout(head)

        self._bar = QProgressBar(self)
        self._bar.setObjectName("focusBar")
        self._bar.setTextVisible(False)
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        lay.addWidget(self._bar)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACING["sm"])
        self._btn_pause = Button("暂停", "default", self, icon_name="pause")
        self._btn_pause.clicked.connect(self.pause_requested.emit)
        self._btn_resume = Button("继续", "accent", self, icon_name="play")
        self._btn_resume.clicked.connect(self.resume_requested.emit)
        self._btn_stop = Button("结束专注", "flat", self, icon_name="stop")
        self._btn_stop.clicked.connect(self.stop_requested.emit)
        row.addWidget(self._btn_pause)
        row.addWidget(self._btn_resume)
        row.addWidget(self._btn_stop)
        row.addStretch(1)
        lay.addLayout(row)

        self._poll = QTimer(self)
        self._poll.setInterval(TICK_MS)
        self._poll.timeout.connect(self.tick)

        self.hide()

    # ----- 接线 -----

    def set_status_provider(self, provider: Optional[Callable[[], dict]]) -> None:
        """接上「怎么读计时器实况」。传 None = 停止轮询（页面不可见时）。

        传函数而不是计时器对象：卡片只需要「读」，不需要「控制」。
        """
        self._provider = provider
        if provider is None:
            self._poll.stop()
            self.update_from({"state": "idle"})
            return
        if not self._poll.isActive():
            self._poll.start()
        self.tick()

    def tick(self) -> None:
        """按秒轮询一次。读不到就当「不在专注」—— 计时器是可选插件。"""
        provider = self._provider
        if provider is None:
            return
        try:
            status = provider() or {}
        except Exception:  # noqa: BLE001
            return
        self.update_from(status)

    # ----- 数据 -----

    def update_from(self, status: dict) -> bool:
        """按计时器状态刷新卡片。返回「状态是否变了」。

        `state` 取 "idle" / "running" / "paused" / "finished"。
        除 running / paused 外一律收起卡片 —— 空闲和已完成都不该占着位置。
        """
        state = str((status or {}).get("state") or "idle")
        active = state in ACTIVE_STATES
        previous, self._state = self._state, state

        if active:
            self._title.setText(focus_title(state, (status or {}).get("type"),
                                            (status or {}).get("total")))
            self._clock.setText(format_clock((status or {}).get("remaining")))
            self._bar.setValue(self._percent((status or {}).get("progress")))
            self._btn_pause.setVisible(state == "running")
            self._btn_resume.setVisible(state == "paused")
            # 暂停态整卡换成 warning 语义色 —— 光看标题字太小，
            # 而「停住了」是用户最需要一眼看出来的状态。
            #
            # 属性**同时挂在卡片和进度条上**：`QFrame#focusCard[paused] QProgressBar::chunk`
            # 这种「祖先属性 + 子控件」的选择器在 Qt 上不可靠（目检时发现
            # 边框与时钟都变色了，进度条却还是强调色）。子控件直接挂属性最稳。
            flag = "true" if state == "paused" else None
            self.setProperty("paused", flag)
            self._bar.setProperty("paused", flag)
            self._repolish()
            self.show()
        else:
            self.hide()

        if state != previous:
            self.state_changed.emit(state)
        return state != previous

    @staticmethod
    def _percent(progress) -> int:
        try:
            ratio = float(progress)
        except (TypeError, ValueError):
            return 0
        if ratio != ratio:                     # NaN
            return 0
        return max(0, min(100, int(round(ratio * 100))))

    def _repolish(self) -> None:
        """`[paused="true"]` 这类属性选择器要重新 polish 才会生效。

        子控件也要一起 —— 属性挂在它自己身上时，只 polish 父级不够。
        """
        for widget in (self, self._bar):
            style = widget.style()
            style.unpolish(widget)
            style.polish(widget)

    # ----- 只读（测试与目检）-----

    def state(self) -> str:
        return self._state

    def clock_text(self) -> str:
        return self._clock.text()

    def title_text(self) -> str:
        return self._title.text()

    def bar_value(self) -> int:
        return self._bar.value()

    def is_active(self) -> bool:
        """卡片是否处于「展开」状态（用 isHidden —— 祖先没 show 时 isVisible 恒假）。"""
        return not self.isHidden()

    def button_visible(self, name: str) -> bool:
        btn = {"pause": self._btn_pause, "resume": self._btn_resume,
               "stop": self._btn_stop}.get(name)
        return btn is not None and not btn.isHidden()
