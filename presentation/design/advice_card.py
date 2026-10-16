# -*- coding: utf-8 -*-
"""建议卡 —— 一条结构化建议的呈现（结论 / 证据 / 动作）。

为什么不做成一个只读文本框
    纯文本建议有四个毛病：不可扫读（要读完整段才知道在说什么）、
    不可执行（说了「该专注」却没有按钮）、不可忽略（没有出口）、
    不可追溯（结论和证据混在一起，用户没法核对 AI 凭什么这么说）。
    拆成三段之后，每一条建议都变成一张**可扫读、可核对、可执行、
    可忽略**的卡片 —— 这是「建议」从输出变成交互的关键一步。

为什么接 `Advice` 对象而不是散装参数
    `Advice` 在 `engine.activity.advice`，是纯 Python（零 Qt），
    导入方向也对（presentation → engine）。用对象比传五个字符串
    更难写错，也让「动作是受限枚举」这个约束一直带在身上。
"""
from __future__ import annotations

import html
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from .focus_card import FOCUS_ENTRY_ID, apply_phase, focus_label
from .tokens import SPACING
from .widgets import Button

if TYPE_CHECKING:                      # 只在类型检查时导入
    from engine.activity import Advice
    # 运行时不导入：控件只读 `advice` 的属性，不需要类型对象本身。
    # 这样 `import presentation.design` 不会连带把引擎层拉进来。


class AdviceSummary(QFrame):
    """建议区顶部的「总结」段 —— 一句话概括今天的状态。

    为什么它值得单独一块（P2.18）
        生成结果原来只有一排并列的建议卡：读完 3 张卡还得自己归纳
        「所以今天我到底怎么样」。总结就是那次归纳，放在卡片**上方**当锚点 ——
        先看结论、再看依据，顺序和读一份简报一致。

    为什么空总结要整块收起
        模型没给 `summary`（或读到的是旧缓存里的裸数组）时，
        画一个空框比不画更糟 —— 用户会以为「总结生成失败了」。
        所以「没有内容」和「有内容」在界面上必须是两种样子。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("adviceSummary")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(SPACING["md"], SPACING["sm"], SPACING["md"], SPACING["sm"])
        lay.setSpacing(SPACING["xs"])

        self._label = QLabel("总结", self)
        self._label.setObjectName("adviceSummaryLabel")
        self._text = QLabel(self)
        self._text.setObjectName("adviceSummaryText")
        self._text.setWordWrap(True)
        lay.addWidget(self._label)
        lay.addWidget(self._text)

        self.hide()

    def set_summary(self, text: str) -> None:
        text = str(text or "").strip()
        self._text.setText(text)
        self.setVisible(bool(text))

    def summary(self) -> str:
        return self._text.text()

    def has_summary(self) -> bool:
        # isHidden 而不是 isVisible：后者要求祖先全可见，页面没 show 时恒为 False
        return (not self.isHidden()) and bool(self._text.text())


class AdviceCard(QFrame):
    """一张建议卡。"""

    #: 用户做了决定 —— `(Advice, action)`，`action` 是 `adopt` / `ignore`。
    #: 为什么两个按钮合成**一个**信号：采纳和忽略都要走同一条
    #: 「决策留痕」路径（见 `engine.activity.decision`）。分成两个信号时，
    #: 「原来只有忽略会留痕，采纳也要」只能靠第二个槽函数自觉补上 ——
    #: 那种依赖自觉的接线，正是漏掉它的原因。
    decided = Signal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("adviceCard")
        self._advice: Advice | None = None
        self._minutes = 0
        self._focus_state = "idle"

        lay = QVBoxLayout(self)
        lay.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        lay.setSpacing(SPACING["sm"])

        # --- 结论 ---
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(SPACING["sm"])
        self._accent = QFrame(self)
        self._accent.setObjectName("adviceAccent")
        self._accent.setFixedWidth(3)
        self._headline = QLabel(self)
        self._headline.setObjectName("adviceHeadline")
        self._headline.setWordWrap(True)
        head.addWidget(self._accent)
        head.addWidget(self._headline, 1)
        lay.addLayout(head)

        # --- 证据 ---
        self._evidence = QLabel(self)
        self._evidence.setObjectName("adviceEvidence")
        self._evidence.setWordWrap(True)
        self._evidence.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self._evidence)

        # --- 动作 ---
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACING["sm"])
        self._btn_action = Button("", "accent", self, icon_name="play")
        # 与今日页顶部那个「开始专注」按钮共用同一个 id 与同一套 QSS ——
        # 同一状态在同一个页面上不能有两个样子
        self._btn_action.setObjectName(FOCUS_ENTRY_ID)
        self._btn_action.clicked.connect(self._on_action)
        self._btn_ignore = Button("忽略", "flat", self)
        self._btn_ignore.clicked.connect(self._on_ignore)
        row.addWidget(self._btn_action)
        row.addWidget(self._btn_ignore)
        row.addStretch(1)
        lay.addLayout(row)

    # ----- 数据 -----

    def set_advice(self, advice: Advice) -> None:
        self._advice = advice
        self._headline.setText(advice.headline)

        evidence = list(advice.evidence or ())
        # 证据用富文本换行；必须转义 —— 内容来自模型，可能带 < >
        self._evidence.setText(
            "<br>".join(html.escape(e) for e in evidence)
        )
        self._evidence.setVisible(bool(evidence))

        action = advice.action
        self._minutes = int(action.minutes) if action.is_actionable else 0
        self._btn_action.setVisible(action.is_actionable)
        if action.is_actionable:
            self._btn_action.setText(action.label)
        # 卡片可能是**专注已经在跑的时候**才渲染出来的（生成建议 →
        # 期间点了专注）—— 新卡片必须直接落在当前状态上，不能先亮着再变。
        self.set_focus_state(self._focus_state)

    def set_focus_state(self, state: str, kind: str = "work") -> None:
        """跟随全局专注状态 —— 非 idle 时按钮换文案并禁用。

        为什么卡片按钮必须自己跟着变（P2.19）
            这就是用户报的那个 bug：点了「开始 90 分钟专注」之后按钮还是
            原样，既看不出点上了、也还能再点一次。反馈必须落在**手指所在处**
            —— 倒计时卡出现在这一列的上方，用户滚在建议列表中间时看不见它。

            同时「同一时刻只有一个计时」意味着**其他卡上的按钮也要一起锁**：
            不锁的话那些按钮点下去只会得到一句「已经在跑了」——
            一个可点却必然失败的按钮比一个灰按钮更糟。
        """
        self._focus_state = str(state or "idle")
        # 没有可执行动作的卡（空卡 / `kind="none"`）不参与同步：它连按钮都
        # 没显示，去改它的文案只会让「这张卡是不是空卡」变得判断不出来。
        # 状态仍然记下 —— 将来这张卡被填上建议时能直接落在正确状态上。
        if self._advice is None or not self._advice.action.is_actionable:
            return
        if self._focus_state == "idle":
            self._btn_action.setText(self._advice.action.label)
            self._btn_action.setEnabled(True)
        else:
            self._btn_action.setText(focus_label(self._focus_state, kind=kind))
            self._btn_action.setEnabled(False)
        self._paint_focus_flag()

    def _paint_focus_flag(self) -> None:
        """按钮**真的被禁用**（防重复启动），但视觉上不能是通用禁用态那片灰：
        灰读起来是「坏了」，而这里要表达的是「正在进行中」。琥珀（warning）
        是悬浮球与托盘环给专注态用的同一个语义色，三者口径一致。

        属性名与 id 的坑见 `focus_card.apply_phase`。
        """
        apply_phase(self._btn_action, self._focus_state)

    def advice(self) -> Advice | None:
        return self._advice

    def headline(self) -> str:
        return self._headline.text()

    def evidence_text(self) -> str:
        return self._evidence.text()

    def evidence_visible(self) -> bool:
        # 用 isHidden() 而不是 isVisible()：后者要求所有祖先都可见，
        # 控件还没 show 时恒为 False。
        return not self._evidence.isHidden()

    def action_visible(self) -> bool:
        return not self._btn_action.isHidden()

    def action_text(self) -> str:
        return self._btn_action.text()

    def action_minutes(self) -> int:
        return self._minutes

    def action_enabled(self) -> bool:
        """动作按钮当前能不能点（专注进行中时为 False）。"""
        return self._btn_action.isEnabled()

    def focus_state(self) -> str:
        return self._focus_state

    # ----- 内部 -----

    def _on_action(self) -> None:
        # 动作常量从引擎层取（唯一口径），但**运行时才导入** ——
        # 见文件顶部：`presentation.design` 不该把 engine 拖进来。
        from engine.activity import ACTION_ADOPT

        if self._advice is not None and self._minutes > 0:
            self.decided.emit(self._advice, ACTION_ADOPT)

    def _on_ignore(self) -> None:
        from engine.activity import ACTION_IGNORE

        if self._advice is not None:
            self.decided.emit(self._advice, ACTION_IGNORE)
