# -*- coding: utf-8 -*-
"""选中文本与剪贴板服务。

方案：备份剪贴板 → 模拟 Ctrl+C → 读剪贴板 → 还原剪贴板。
（UI Automation 方案无副作用但复杂度高，留 v2。）

S2 spike 实测结论
    - 全 MIME 格式备份/还原无损（纯文本 + HTML 双格式校验通过）；
    - 无选中、空剪贴板等边界场景均正常。

踩过的坑
    等待 Ctrl+C 生效**不能**用裸 `time.sleep()` —— 那会阻塞 Qt 事件循环，
    导致本进程内的目标窗口无法处理 WM_COPY。必须泵事件循环（见 `_wait`）。
    对**其他进程**的目标窗口而言 sleep 无妨，但统一泵事件更安全。

性能（实测）
    构造 `pynput.keyboard.Controller()` 是**一次性 71ms** 的开销，之后每次按键约 1ms。
    因此**绝不能**在每次调用时新建 Controller —— 那会把 71ms 直接加到用户按热键后的
    首次响应上。统一走 `keyboard_controller()` 缓存。

性能（R14 整改，两处）
    早期实现 `get_selected()` 总耗时呈双峰（253ms / 565ms），两个峰各有原因：

    1. **253ms 峰 = 固定等待**。发完 Ctrl+C 后无条件 `_wait(max(delay, timeout_ms))`。
       → 改为「30ms 响应窗口 + 8ms 轮询」，一读到内容立即返回。
    2. **565ms 峰 = 清空剪贴板的跨进程协商**。旧实现用 `clip.clear()` 制造
       空基准，而清空要等前一个所有者进程响应，实测 **330ms**；用户的剪贴板
       通常有内容，所以这 330ms 是**常态**而非偶发。
       → 改用 `clipboard_sequence()`（纯读，0.001ms）判断「是否发生了新的复制」，
       **完全不清空剪贴板**。
"""
from __future__ import annotations

import ctypes
import time
from typing import Dict, Optional

from PySide6.QtCore import QByteArray, QMimeData
from PySide6.QtWidgets import QApplication

DEFAULT_COPY_DELAY = 0.18

#: 发完 Ctrl+C 后，先给目标应用一个**最小响应窗口**再开始轮询。
#: 多数应用 10–30ms 内就把内容写进剪贴板了；留一点点余量避免空转。
SETTLE_DELAY = 0.03

#: 剪贴板轮询间隔。8ms 足以覆盖应用写剪贴板的抖动，又不会空转烧 CPU。
POLL_INTERVAL = 0.008

# 共享的 pynput 键盘控制器（构造昂贵，缓存复用）
_KEYBOARD = None


def clipboard_sequence() -> int:
    """剪贴板序列号 —— 剪贴板内容每变化一次就 +1。

    为什么需要它（R14 的另一半）
        旧实现靠 `QClipboard.clear()` 制造一个「空剪贴板」基准，再判断 Ctrl+C
        是否写进了东西。但**清空剪贴板要等前一个所有者进程响应**
        （Windows 的跨进程剪贴板所有权协商），实测在记事本持有剪贴板时要
        **330ms** —— 这正是 R14 双峰里 565ms 那一峰的来源，而且因为用户的
        剪贴板通常**有内容**，这 330ms 是常态而不是偶发。

        序列号是纯读，实测 **0.001ms**，且不需要打开剪贴板。
        「序列号变了」等价于「确实发生了一次新的复制」，语义比清空更准。

    返回 `-1` 表示 API 不可用（非 Windows）—— 调用方需回退到清空方案。
    """
    try:
        return int(ctypes.windll.user32.GetClipboardSequenceNumber())
    except Exception:  # noqa: BLE001
        return -1


def keyboard_controller():
    """返回共享的 pynput 键盘控制器（首次调用会付约 71ms 的构造开销）。

    `native/selection.py` 与 `native/injector.py` 共用同一个实例。
    """
    global _KEYBOARD
    if _KEYBOARD is None:
        from pynput import keyboard as pk

        _KEYBOARD = pk.Controller()
    return _KEYBOARD


def warmup_keyboard() -> bool:
    """预热键盘控制器。启动期调用可把 71ms 挪出用户的首次热键响应。"""
    try:
        keyboard_controller()
        return True
    except Exception:
        return False


def warmup_clipboard() -> bool:
    """预热剪贴板。

    实测：Windows 上**首次**访问剪贴板要付一次性 **~88ms** 开销
    （剪贴板初始化 + 跨进程格式枚举），之后每次仅 0.1–0.4ms。

    若不预热，这 88ms 会落在用户第一次按热键之后 ——
    面板已经画出来了，但内容填不进去、界面卡住近 0.1 秒。
    启动期做一次「读 + 还原」即可把成本挪走。

    注意：**只在备份非空时才还原**，避免把用户剪贴板清空。
    """
    try:
        svc = SelectionService()
        backup = svc.backup()      # 只读，不改剪贴板
        if backup:
            svc.restore(backup)    # 写回同样内容，验证写入路径
        return True
    except Exception:
        return False


class SelectionService:
    """选中文本获取（剪贴板方案）。"""

    def __init__(self, delay: float = DEFAULT_COPY_DELAY):
        self.delay = delay

    # ----- 剪贴板 -----

    @staticmethod
    def _clip():
        return QApplication.clipboard()

    def backup(self) -> Dict[str, bytes]:
        """备份剪贴板**全部** MIME 格式（只备份纯文本会丢富文本格式）。"""
        clip = self._clip()
        if clip is None:
            return {}
        md = clip.mimeData()
        if md is None:
            return {}
        out: Dict[str, bytes] = {}
        for fmt in md.formats():
            out[fmt] = bytes(md.data(fmt))
        return out

    def restore(self, data: Dict[str, bytes]) -> None:
        clip = self._clip()
        if clip is None:
            return
        if not data:
            clip.clear()
            return
        md = QMimeData()
        for fmt, raw in data.items():
            md.setData(fmt, QByteArray(raw))
        clip.setMimeData(md)

    def get_clipboard(self) -> str:
        clip = self._clip()
        return (clip.text() if clip else "") or ""

    def set_clipboard(self, text: str) -> None:
        clip = self._clip()
        if clip:
            clip.setText(text)

    # ----- 选中文本 -----

    def get_selected(self, timeout_ms: int = 250) -> str:
        """取当前选中文本。失败或无选中时返回空串，且剪贴板必被还原。

        性能（R14 整改，两步）
            1. 旧实现发完 Ctrl+C 后**固定等待** `max(delay, timeout_ms)`，
               每次调用无条件付约 250ms → 改为「30ms 响应窗口 + 8ms 轮询」。
            2. 旧实现还要 `clip.clear()` 制造空基准，而**清空剪贴板要等前一个
               所有者进程响应**，实测 330ms（且因用户剪贴板通常有内容而是常态）
               → 改用 `clipboard_sequence()` 判据，**完全不清空剪贴板**。

        为什么序列号判据是安全的
            Ctrl+C 真的产生内容时，目标应用必然调用 `SetClipboardData`，
            序列号随之 +1；没有选中文本时应用根本不碰剪贴板，序列号不变。
            序列号变了但内容仍为空（应用分两步写）时继续等，不提前返回。
        """
        backup = self.backup()
        try:
            clip = self._clip()
            seq = self._clip_token()
            if seq < 0 and clip:
                # 序列号 API 不可用 → 回退到「清空剪贴板」的老办法保语义
                clip.clear()
            self._send_copy()
            return self._poll_clipboard(timeout_ms, seq)
        except Exception:
            return ""
        finally:
            self.restore(backup)

    # ----- 内部 -----

    def _clip_token(self) -> int:
        """剪贴板「版本」判据 —— 变化即代表发生了一次新的复制。

        抽成方法是为了留一条**测试接缝**：单元测试跑在 `offscreen` 平台下，
        Qt 用的是**进程内**剪贴板，根本不触碰 Windows 剪贴板，
        `setText()` / `clear()` 前后 `GetClipboardSequenceNumber()` 纹丝不动
        （实测都是同一个值）。真实运行走 `clipboard_sequence()`。

        返回 `-1` 表示无法判定，调用方回退到「清空剪贴板」方案。
        """
        return clipboard_sequence()

    def _poll_clipboard(self, timeout_ms: int, seq_before: int) -> str:
        """轮询直到「剪贴板确实更新了」或超时（返回空串）。"""
        deadline = time.perf_counter() + max(0.05, timeout_ms / 1000.0)
        self._wait(min(self.delay, SETTLE_DELAY))   # 给目标应用一点处理时间
        while True:
            if seq_before < 0:
                text = self.get_clipboard()          # 回退路径：靠 clear 保证语义
                if text:
                    return text
            elif self._clip_token() != seq_before:
                text = self.get_clipboard()
                if text:
                    return text
                # 版本变了但内容为空 → 应用可能分两步写，继续等
            if time.perf_counter() >= deadline:
                return ""
            self._wait(POLL_INTERVAL)

    @staticmethod
    def _send_copy() -> None:
        try:
            from pynput import keyboard as pk

            c = keyboard_controller()   # 缓存实例，不重复付 71ms 构造开销
            c.press(pk.Key.ctrl_l)
            c.press("c")
            c.release("c")
            c.release(pk.Key.ctrl_l)
        except Exception:
            pass

    @staticmethod
    def _wait(seconds: float) -> None:
        """泵事件循环等待 —— 不能用裸 time.sleep()，见模块 docstring。

        步进压到 2ms：轮询间隔是 8ms，若步进仍是 5ms，实际轮询周期会被
        拖成 10ms 以上，白白吃掉刚省下来的延迟。
        """
        deadline = time.perf_counter() + seconds
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                break
            QApplication.processEvents()
            time.sleep(min(0.002, remaining))
