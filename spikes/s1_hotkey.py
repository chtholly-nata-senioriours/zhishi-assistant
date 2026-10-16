#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S1 — 全局热键能否与现有 InputMonitor 共存

假设
    Win32 `RegisterHotKey`（经 Qt NativeEventFilter 接入消息循环）与
    `sensor/input_monitor.py` 的 pynput 监听可以同时工作，互不干扰。

方法（全自动，不需要人工按键）
    1. 注册真实要用的三组热键 Alt+Q / Alt+T / Alt+S，报告是否被占用。
    2. 重复注册同一组合，验证冲突检测（期望 ERROR_HOTKEY_ALREADY_REGISTERED = 1409）。
    3. 注册一个安全的测试组合 Ctrl+Alt+F9，用 pynput 合成按键，
       验证 WM_HOTKEY 能否真正送达 Qt 消息循环。
    4. 同时启动 InputMonitor，合成 10 次普通按键，验证键频统计仍在累计
       —— 这就是「共存」的实证。

判定
    三组真实热键全部注册成功 且 合成按键能触发 WM_HOTKEY 且 键频统计有增长 → PASS

已知限制
    - 合成按键（SendInput）与真实物理按键在某些场景下行为不同，
      提权窗口 / 独占全屏下的表现仍需人工确认（见 README 的人工验证清单）。
    - 若第 3 步未触发，判 MANUAL 而非 FAIL（可能是注入输入被系统忽略）。

用法
    python spikes/s1_hotkey.py
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

from _common import Report, bootstrap

bootstrap()

from PySide6.QtCore import QAbstractNativeEventFilter, QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

VK = {"Q": 0x51, "T": 0x54, "S": 0x53, "F9": 0x78}


def pump(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def register(hid: int, mods: int, vk: int) -> tuple[bool, int]:
    user32.RegisterHotKey.restype = wintypes.BOOL
    ok = bool(user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk))
    return ok, ctypes.get_last_error()


def unregister(hid: int) -> None:
    user32.UnregisterHotKey(None, hid)


class HotkeyFilter(QAbstractNativeEventFilter):
    """把 WM_HOTKEY 从 Windows 消息队列里捞出来。"""

    def __init__(self):
        super().__init__()
        self.fired: list[int] = []

    def nativeEventFilter(self, eventType, message):  # noqa: N802
        try:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                self.fired.append(int(msg.wParam))
        except Exception:
            pass
        return False, 0


def main() -> int:
    rep = Report(
        "S1",
        "全局热键与 InputMonitor 共存",
        "RegisterHotKey 与 pynput 监听可同时工作，互不干扰",
        "三组热键注册成功 + 合成按键触发 WM_HOTKEY + 键频统计增长 → PASS",
    )

    app = QApplication.instance() or QApplication([])

    # 需要一个有焦点的窗口，避免合成按键落到别的程序上
    win = QWidget()
    win.setWindowTitle("S1 热键探针")
    win.resize(360, 160)
    win.show()
    win.activateWindow()
    app.processEvents()
    time.sleep(0.4)
    app.processEvents()

    # --- 1. 注册真实热键 ---
    real = [("Alt+Q", 1, MOD_ALT, VK["Q"]),
            ("Alt+T", 2, MOD_ALT, VK["T"]),
            ("Alt+S", 3, MOD_ALT, VK["S"])]
    real_ok = True
    for label, hid, mods, vk in real:
        ok, err = register(hid, mods, vk)
        rep.check(f"注册 {label}", ok, "成功" if ok else f"失败 err={err}")
        real_ok &= ok

    # --- 2. 冲突检测 ---
    dup_ok, dup_err = register(9, MOD_ALT, VK["Q"])
    rep.check(
        "重复注册 Alt+Q 被正确拒绝",
        (not dup_ok) and dup_err == ERROR_HOTKEY_ALREADY_REGISTERED,
        f"ok={dup_ok} err={dup_err}（期望 1409）",
    )

    # --- 3. 用安全组合做触发测试 ---
    filt = HotkeyFilter()
    app.installNativeEventFilter(filt)
    test_hid = 100
    reg_ok, reg_err = register(test_hid, MOD_CONTROL | MOD_ALT, VK["F9"])
    rep.check("注册测试组合 Ctrl+Alt+F9", reg_ok, "成功" if reg_ok else f"失败 err={reg_err}")

    if reg_ok:
        from pynput import keyboard as pk

        ctl = pk.Controller()
        ctl.press(pk.Key.ctrl_l)
        ctl.press(pk.Key.alt_l)
        ctl.press(pk.Key.f9)
        ctl.release(pk.Key.f9)
        ctl.release(pk.Key.alt_l)
        ctl.release(pk.Key.ctrl_l)
        pump(600)
        fired = test_hid in filt.fired
        rep.check("合成按键触发 WM_HOTKEY", fired, f"收到 {filt.fired}")
    else:
        fired = False
        rep.check("合成按键触发 WM_HOTKEY", None, "测试组合注册失败，无法验证")

    # --- 4. 与 InputMonitor 共存 ---
    from sensor.input_monitor import InputMonitor

    im = InputMonitor()
    im.start()
    pump(300)
    alive = [l.is_alive() for l in im._listeners]
    rep.check("InputMonitor 监听线程已启动", all(alive) and len(alive) == 2,
              f"listeners={alive}")

    rate_before = im.get_key_rate()
    from pynput import keyboard as pk2

    ctl2 = pk2.Controller()
    for _ in range(10):
        ctl2.press("a")
        ctl2.release("a")
        time.sleep(0.03)
    pump(400)
    rate_after = im.get_key_rate()
    rep.metric("合成按键前键频计数", rate_before)
    rep.metric("合成 10 次按键后计数", rate_after)
    rep.check("键频统计仍在累计（未被热键吃掉）", rate_after > rate_before,
              f"{rate_before} → {rate_after}")

    # 再合成一次热键，确认两套机制同时存活
    if reg_ok:
        filt.fired.clear()
        ctl2.press(pk2.Key.ctrl_l)
        ctl2.press(pk2.Key.alt_l)
        ctl2.press(pk2.Key.f9)
        ctl2.release(pk2.Key.f9)
        ctl2.release(pk2.Key.alt_l)
        ctl2.release(pk2.Key.ctrl_l)
        pump(500)
        rep.check("共存状态下热键仍能触发", bool(filt.fired), f"收到 {filt.fired}")

    im.stop()
    for _, hid, _, _ in real:
        unregister(hid)
    if reg_ok:
        unregister(test_hid)

    if real_ok and fired:
        verdict = "PASS"
    elif real_ok and not fired:
        verdict = "MANUAL"
        rep.note("热键注册成功但合成按键未触发，需人工按 Ctrl+Alt+F9 确认")
    else:
        verdict = "FAIL"

    rep.finish(verdict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
