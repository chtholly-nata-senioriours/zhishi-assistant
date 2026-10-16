# -*- coding: utf-8 -*-
"""文本注入 —— 把 AI 的回答送回用户手边。

> ⚠ **2026-10-12：本模块当前没有接入 UI。**
> 面板上的「替换原文 / 粘贴到前台」已移除（见 `AGENTS.md` §4.6），
> `AIAssistantPlugin` 也不再持有 `Injector`。代码与测试**保留**，原因有二：
>   1. 它是「跨应用投递」这件事的唯一实测记录（下面那张代价分解表）；
>   2. 若日后要恢复，接线只需在 `plugin._on_delivery()` 里加回两个分支。
> 之所以移除：注入能否成功**无法自检** —— 受限会话 / 提权窗口下系统会静默
> 丢弃合成输入，而 `_send_paste()` 不抛异常、照样返回 True，于是面板会
> 谎报「已替换原文」。一个会谎报成功、时灵时不灵的功能不如不要。
> 若将来恢复，请先解决「成功判定」：注入后校验目标窗口内容，而不是看有没有抛异常。

三种投递方式（对应 `engine.ai.types.DeliveryKind`）
    copy    只写剪贴板，不动前台应用
    replace 选中原文 → 粘贴译文，**选区被覆盖**（原文消失）
    paste   光标处插入译文，**原文保留**

为什么 replace 与 paste 必须分开实现
    两者都只是「写剪贴板 + Ctrl+V」，看上去可以共用一条路径，于是最初
    真的共用了 —— 结果是**行为完全一样**：

      · 选区还在时，PASTE 也会把原文替换掉（本该插入）
      · 选区丢了时，REPLACE 退化成插入（本该替换）

    用户看到的是「点了替换，原文还在」或「点了粘贴，原文没了」。
    区别只在**粘贴前有没有取消选区**：
      replace → 不动选区，Ctrl+V 覆盖它
      paste   → 先按一下 Right 取消选区，Ctrl+V 在选区末尾插入

性能（实测，2026-10-12）
    `paste_to_foreground()` 全程分解（真实屏幕、本进程持有剪贴板）：

    | 段 | 代价 | 说明 |
    |---|---|---|
    | `backup()` | 0.2 ms | Qt 读剪贴板全格式 |
    | `set_clipboard()` | 1.4 ms | 本进程持有；**外部持有时 113 ms**（与 R14 同源） |
    | `_send_paste()` | 3–8 ms | pynput 注入 Ctrl+V |
    | `_pump()` | **123.7 ms** | 等目标应用读走剪贴板，**固定开销** |
    | `restore()` | 0.8 ms | set 之后已是本进程持有，所以快 |
    | **合计** | **134.7 ms** | 外部持有剪贴板时 240.8 ms |

    两处值得记：
      · `restore()` 并不慢 —— 一旦 `set_clipboard()` 成功，所有权已在本进程，
        还原只是本进程内的写。慢的是**第一次** `set_clipboard()`。
      · `_pump()` 的 120ms 是**有语义必要**的固定等待（剪贴板是延迟渲染的，
        目标应用 Ctrl+V 时才来要数据；提前还原会粘到旧内容），
        但它只在**粘贴确实发出后**才需要 —— 失败时不再白等。

`pynput.keyboard.Controller()` 构造是一次性 **71ms** 开销，之后每次按键约 1ms。
与 `selection.py` 共用缓存实例（`keyboard_controller()`），
避免首次投递时把 71ms 加到用户等待上。
"""
from __future__ import annotations

import time

from PySide6.QtWidgets import QApplication

from .selection import SelectionService, keyboard_controller

#: 发完 Ctrl+V 后，等目标应用把剪贴板内容读走，再还原剪贴板。
#: 剪贴板是「延迟渲染」的：目标应用响应 Ctrl+V 时才会向所有者要数据。
#: 若在此之前还原，它拿到的会是还原后的**旧内容** —— 表现为「粘出来的是
#: 上一次复制的东西」或干脆粘不上。实测多数应用 30–50ms 内读完，留 120ms 余量。
RESTORE_DELAY = 0.12

#: 取消选区后、发 Ctrl+V 前的缓冲。让目标应用先把「取消选中」处理完，
#: 否则两次按键可能被合并/乱序。
DESELECT_DELAY = 0.01


class Injector:
    """把文本注入到前台窗口。"""

    def __init__(self, selection: SelectionService | None = None):
        self._sel = selection or SelectionService()

    # ----- 剪贴板方案（快）-----

    def paste_to_foreground(
        self,
        text: str,
        restore_clipboard: bool = True,
        clear_selection: bool = False,
    ) -> bool:
        """写剪贴板 + Ctrl+V。返回**是否确实发出了**粘贴按键。

        clear_selection
            False（默认，对应「替换原文」）—— 保持目标应用的现有选区，
                Ctrl+V 会**覆盖**选区：原文消失、译文就位。
            True（对应「粘贴到前台」）—— 先按一下 Right 取消选区
                （有选区时 Right 只取消选中、不移动光标），再粘贴，
                于是译文**插入**在选区末尾，原文保留。

        返回值的语义
            只有「Ctrl+V 确实注入了」才返回 True。旧实现里 `_send_paste`
            吞掉异常且不返回值，于是本方法**恒返回 True** ——
            调用方的「粘贴失败」分支永远不可达。现在如实返回。
        """
        if not text:
            return False
        backup = self._sel.backup() if restore_clipboard else None
        try:
            self._sel.set_clipboard(text)
            QApplication.processEvents()
            ok = self._send_paste(clear_selection=clear_selection)
            if ok:
                # 只有真的粘出去了才需要等目标应用读走剪贴板；
                # 失败时立即还原，不白等这 120ms。
                self._pump(RESTORE_DELAY)
            return ok
        except Exception:
            return False
        finally:
            if restore_clipboard and backup is not None:
                self._sel.restore(backup)

    # ----- 逐字键入（慢，兜底）-----

    def type_text(self, text: str, interval: float = 0.01) -> bool:
        """逐字键入。不受剪贴板影响，但慢且受输入法干扰。返回是否完成。"""
        if not text:
            return False
        try:
            c = keyboard_controller()   # 缓存实例
            for ch in text:
                c.type(ch)
                if interval:
                    time.sleep(interval)
            return True
        except Exception:
            return False

    # ----- 内部 -----

    @staticmethod
    def _send_paste(clear_selection: bool = False) -> bool:
        """注入 Ctrl+V（可选先取消选区）。返回是否成功发出按键。

        异常一律转成 `False` —— 调用方据此给用户提示。**不要**在这里
        静默吞掉失败，否则「粘贴失败」永远显示不出来。
        """
        try:
            from pynput import keyboard as pk

            c = keyboard_controller()   # 缓存实例，不重复付 71ms 构造开销
            if clear_selection:
                # Right 在「有选区」时只取消选中并把光标落到选区末尾；
                # 在「无选区」时会让光标右移一格 —— 所以只在确实采到过
                # 选区时才由调用方要求取消（见 plugin._on_delivery）。
                c.press(pk.Key.right)
                c.release(pk.Key.right)
                time.sleep(DESELECT_DELAY)
            c.press(pk.Key.ctrl_l)
            c.press("v")
            c.release("v")
            c.release(pk.Key.ctrl_l)
            return True
        except Exception:
            return False

    @staticmethod
    def _pump(seconds: float) -> None:
        deadline = time.perf_counter() + seconds
        while time.perf_counter() < deadline:
            QApplication.processEvents()
            time.sleep(0.005)
