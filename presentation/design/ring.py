# -*- coding: utf-8 -*-
"""进度环的共享定义 —— 托盘图标与悬浮球画的是**同一个量**。

为什么要单独一个模块
    托盘图标（16px，画在任务栏上）和悬浮球（52px，画在壁纸上）表达的
    都是「今日深度工作进度」；专注计时进行中时，两者又同时改画「本次专注进度」
    （P2.18）。各写各的话，两处的状态判定迟早会漂，
    用户会看到两个互相矛盾的指示。所以「画的是哪个量」「什么算达成」
    「什么算没在记录」只在这里定义一次（`ring_view`）。

    这里**只有语义，没有配色** —— 两者的底色不同（托盘底是桌宠图，
    球底是深色球体），底槽与进度弧本来就该各自定。共用的只有
    「一圈白描边」这个跨越底色的通用做法。

为什么颜色写死、不取主题（S14 实测结论）
    这个环的背景由**操作系统**决定（任务栏 / 壁纸），跟应用主题毫无关系。
    取主题色的后果实测过两次：`light` 主题的 `text_disabled = #1F1F1F`
    在深色任务栏上**完全消失**；`chart_track = #DCDCDC` 在深色任务栏上
    被读成**满环**。所以一律「固定色 + 一圈白描边」——
    这些常量**不进 `Palette`**、不参与主题切换。
"""
from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtGui import QColor

#: 五态。为什么要分开「关闭」和「0 进度」
#:     空环会被读成「今天一点没干」，而真相是「根本没在记录」。
#:     这两件事对用户的含义完全不同，指示必须能区分。
STATE_OFF = "off"          # 采集关闭 —— 中性灰
STATE_ACTIVE = "active"    # 记录中、未达目标 —— 进度弧
STATE_DONE = "done"        # 已达 / 超过目标 —— 满环
#: 专注计时进行中（P2.18）—— 环临时改画**本次专注**的进度，不是今日进度。
#: 必须与 `STATE_ACTIVE` 分开：不分开的话，一个走到 40% 的环会被读成
#: 「今天只完成了 40%」，而真相是「这轮专注还剩 60%」。两者含义完全不同。
STATE_FOCUS = "focus"
#: 专注暂停中 —— 同一个量，但要能看出「它停住了」（配色压暗）。
STATE_FOCUS_PAUSED = "focus_paused"

#: 跨越底色的通用做法：白描边保证在**深色**背景上勾得出轮廓。
#: 这是托盘环与球环唯一共用的颜色。
OUTLINE = QColor(255, 255, 255, 235)


def activity_state(enabled: bool, ratio: float) -> str:
    """进度环的三态判定（纯函数，可单测）。"""
    if not enabled:
        return STATE_OFF
    return STATE_DONE if float(ratio) >= 1.0 else STATE_ACTIVE


def _clamp(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def ring_view(
    *,
    enabled: bool,
    ratio: float,
    focus_ratio: Optional[float] = None,
    focus_paused: bool = False,
) -> Tuple[str, float]:
    """环该画成什么样 —— 返回 `(状态, 进度)`。

    托盘图标与悬浮球**共用这一个判定**。为什么非共用不可
        两处都画「一个环」，只要口径有一处不同，同一时刻就会出现两个
        互相矛盾的指示（P2.14 已经在配色上踩过一次）。所以「专注中环改画
        本次专注」这条规则只写在这里一次。

    `focus_ratio is None` 表示**不在专注**（不是「专注进度为 0」）——
    此时环回到「今日深度工作进度」的语义。暂停中的专注仍有进度值，
    所以不能拿 0 当「没有」用。
    """
    if focus_ratio is not None:
        state = STATE_FOCUS_PAUSED if focus_paused else STATE_FOCUS
        return state, _clamp(focus_ratio)
    return activity_state(bool(enabled), _clamp(ratio)), _clamp(ratio)
