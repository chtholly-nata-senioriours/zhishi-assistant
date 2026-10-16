# -*- coding: utf-8 -*-
"""窗口层级行为 —— 点击即置顶。

背景（用户实测报的问题）
    「打开多窗口时确保点击的窗口在上层」——点回来的窗口没有跑到前面。

根因有两层
    1. **置顶层内不分先后**。ShellWindow / AIPanel 都带 `WindowStaysOnTopHint`
       （Windows 上是 `WS_EX_TOPMOST`），而对话框**没有**。于是置顶的
       AI 面板永远压在设置对话框上面 —— 点对话框也翻不上去，因为
       `WS_EX_TOPMOST` 窗口始终高于非置顶窗口。
    2. 同处置顶层的窗口之间，z 序由**激活顺序**决定，不显式 raise 就不会
       自动跑到前面（Windows 对 `WS_EX_TOOLWINDOW` 尤其如此）。

本模块解决第 2 层；第 1 层由 `dialogs.GlassDialog` 统一加上
`WindowStaysOnTopHint` 解决 —— **两者必须一起改**，只改一个仍然有问题。

为什么这里只有 `raise_to_front()`，不代管 `mousePressEvent`
    代管 `mousePressEvent` 看似更省事，实际会**重复触发**：
    子类重写 `mousePressEvent` 并调用 `super()` 时，混入类的同名方法
    会在同一次点击里再跑一遍 `raise_() + activateWindow()`。
    三个窗口（ShellWindow / AIPanel / GlassDialog）本来就要重写
    `mousePressEvent` 做拖拽，所以改成**显式调用** ——
    一次点击一次置顶，行为可预测。

用法
    混入时放在 Qt 基类**之前**：:

        class ShellWindow(RaiseOnClickMixin, QWidget): ...

    然后在自己的 `mousePressEvent` 开头调用 `self.raise_to_front()`。
"""
from __future__ import annotations


class RaiseOnClickMixin:
    """鼠标按下 → 把本窗口提到同级最上层。"""

    def raise_to_front(self) -> None:
        """把窗口提到同级最上层并激活。

        异常吞掉是有意的：窗口正在关闭时底层 C++ 对象可能已销毁，
        `raise_()` 会抛 `RuntimeError`。层级调整失败不该让点击事件崩掉。
        """
        try:
            self.raise_()
            self.activateWindow()
        except RuntimeError:
            pass
