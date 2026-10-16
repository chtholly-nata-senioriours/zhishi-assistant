# -*- coding: utf-8 -*-
"""系统空闲时长（只读「强度」，不碰内容）。

用途：把「人不在电脑前」的时间从活动段里剪掉。
    没有这个信号时，上午 10:00 打开 Chrome、中午出去吃饭、13:00 回来 ——
    这段会被记成「Chrome 3 小时」。有了它，结束点会被拉回
    「最后一次输入的时刻」，时长才对得上用户的直觉。

为什么用 `GetLastInputInfo` 而不是 pynput
    pynput 只知道「本进程监听期间有没有输入」；系统空闲时间是全桌面的
    既有事实，`GetLastInputInfo` 一次调用就能读到（Win32，零新依赖）。

隐私边界
    本模块**只返回一个秒数**。没有按键内容、没有窗口、没有鼠标位置。
    加任何新返回值之前先问一句：它会不会把用户内容带出去。
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


class _LASTINPUTINFO(ctypes.Structure):
    """`GetLastInputInfo` 需要的结构体 —— `cbSize` 必须先填对，否则调用失败。"""

    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]


def system_idle_seconds() -> float:
    """距离上一次**全系统**输入过去了多少秒。

    非 Windows、调用失败、或 tick 回绕时一律返回 `0.0` ——
    这是**安全默认**：调用方据此认为「用户一直在」，宁可少剪也不误剪。
    （`GetTickCount` 约 49.7 天回绕一次，回绕瞬间会算出负数，同样归零。）
    """
    if sys.platform != "win32":
        return 0.0
    try:
        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        elapsed_ms = int(ctypes.windll.kernel32.GetTickCount()) - int(info.dwTime)
        if elapsed_ms <= 0:
            return 0.0
        return elapsed_ms / 1000.0
    except Exception:  # noqa: BLE001 —— 探针失败不该让采集崩掉
        return 0.0
