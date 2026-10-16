#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S12 — 真实按键注入：pynput 的 Ctrl+V 到底能不能落到外部应用？

结论（2026-10-12 实测，**与 S10/S11 原来的说法不一致**）

    1. **注入是通的**。在真实记事本上用真 pynput 发 Ctrl+V，结果文本
       `'XXX BBB CCC'` —— 选区确实被覆盖，通道可用。
    2. **但成功率只有约 40–50%**。同一个探针连跑 10 次：**4 PASS / 6 FAIL**，
       失败与成功交错出现（不是「跑一阵就坏」的状态漂移）。
       抓到的失败形态之一是结果文本 `'v BBB CCC'` —— 字母 v 落下去了、
       **Ctrl 没生效**。
    3. **不是沙箱拦的**。探针会直接问 `SendInput` 的返回值：
       沙箱内、沙箱外**都返回 2/2**（接受）。所以 S10/S11 里
       「本机会话合成按键落不下去」的结论**不准确** —— 真相不是「不work」，
       而是「**时灵时不灵**」。

    这条结论直接决定了产品决策：投递到前台已从产品里移除
    （`AGENTS.md` §4.6）。理由不是「做不到」，而是「**做不到可靠，且代码
    察觉不到失败**」—— `_send_paste()` 不抛异常就返回 True，面板照样显示
    「已替换原文」，用户看到的就是「点了没反应」。

试过但**没用**的两个假设（写在这里，省得后人重走）
    `--no-restore`  怀疑 120ms 后还原剪贴板太早，目标应用读到旧内容
                    → 交错对照 6 次：restore 1P/2F、no-restore 2P/1F，**无相关**
    `--key-delay`   怀疑 `press(Ctrl)` 与 `press("v")` 之间没有间隔
                    → 插入 40ms 后连跑 5 次：**5 次全 FAIL**，反而更糟

    所以别再调时序参数了。真要恢复这个功能，第一步必须是
    **可验证的成功判定**（注入后回读目标窗口内容），而不是继续猜延迟。

本 spike 做什么
    在真实记事本上，用真的 pynput 发一次 Ctrl+V，比对结果文本：

        基准 "AAA BBB CCC"，先选中 "AAA"，剪贴板写入 "XXX"
            REPLACE 语义（保持选区）→ "XXX BBB CCC"   选区被覆盖
            注入未生效              → "AAA BBB CCC"   纹丝不动

    S11 验**语义**（用窗口消息，确定性）；S12 验**通道**（真按键，概率性）。

用法
    python dev_bootstrap.py spikes/s12_real_injection.py
    python dev_bootstrap.py spikes/s12_real_injection.py --json
    python dev_bootstrap.py spikes/s12_real_injection.py --no-restore   # 隔离还原时序
    python dev_bootstrap.py spikes/s12_real_injection.py --key-delay    # 隔离按键间隔

    ⚠ 判定是**概率性**的：单次 PASS 不能证明稳定，单次 FAIL 也不能证明坏。
      要看结论请连跑多次统计（`for i in $(seq 10); do ...; done`）。
"""
from __future__ import annotations

import ctypes
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

#: 基准文本。第一个词会被选中，投递内容会覆盖它。
BASE = "AAA BBB CCC"
#: 剪贴板内容 —— 故意与任何词都不同，便于辨认。
PAYLOAD = "XXX"
#: 期望结果：REPLACE 语义（选区被覆盖）
EXPECT = f"{PAYLOAD} BBB CCC"
#: 临时文件名，同时用作「这个窗口打开的是我的文件吗」的凭据。
MARK = "petgame_inject_probe.txt"

EM_SETSEL = 0x00B1


def _sendinput_capability() -> tuple[int, int]:
    """直接调 `SendInput`，看**操作系统**收不收合成输入。

    为什么要单独问这一句
        pynput 不检查 `SendInput` 的返回值 —— 被拦时它照样「成功返回」，
        调用方完全察觉不到。于是「注入没生效」既可能是环境拦了，也可能是
        目标窗口不对，光看 pynput 的结果分不出来。

        `SendInput` 的返回值 = 成功插入的事件数。**返回 0 = 被拦**，
        通常是 UIPI（目标窗口提权）或运行环境限制；此时 `GetLastError`
        多为 5（拒绝访问）。

    发的是 `VK_F24` —— 这个键在 Windows 上没有默认行为，不会干扰任何东西。

    Returns:
        (插入事件数, GetLastError)
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)

    ULONG_PTR = ctypes.c_size_t

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class MOUSEINPUT(ctypes.Structure):
        # ⚠ 必须有它：x64 上 INPUT 的大小由**最大**的那个联合体成员决定，
        #   而 MOUSEINPUT（32 字节）比 KEYBDINPUT（24 字节）大。
        #   只声明 KEYBDINPUT 会让 sizeof(INPUT)=32 而不是 40，
        #   SendInput 直接报 ERROR_INVALID_PARAMETER(87) —— 和「被系统拦掉」
        #   长得一模一样，极易误判。踩过一次。
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class _INPUTunion(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    VK_F24 = 0x87

    expected = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
    if ctypes.sizeof(INPUT) != expected:
        raise AssertionError(
            f"INPUT 结构体大小 {ctypes.sizeof(INPUT)} != {expected}，SendInput 会报 87"
        )

    events = (INPUT * 2)(
        INPUT(type=INPUT_KEYBOARD, u=_INPUTunion(ki=KEYBDINPUT(VK_F24, 0, 0, 0, 0))),
        INPUT(type=INPUT_KEYBOARD, u=_INPUTunion(ki=KEYBDINPUT(VK_F24, 0, KEYEVENTF_KEYUP, 0, 0))),
    )
    ctypes.set_last_error(0)
    n = user32.SendInput(2, events, ctypes.sizeof(INPUT))
    return int(n), ctypes.get_last_error()


def _inconclusive(msg: str) -> int:
    print(f"INCONCLUSIVE —— {msg}")
    return 0


def _snap_notepads() -> set:
    """当前所有可见记事本顶层窗口。"""
    import win32gui

    out: set = set()

    def _cb(h, _):
        if win32gui.IsWindowVisible(h) and win32gui.GetClassName(h) == "Notepad":
            out.add(h)

    win32gui.EnumWindows(_cb, None)
    return out


def _find_edit(hwnd):
    """找编辑控件。新版记事本用 RichEditD2DPT，老版用 Edit。"""
    import win32gui

    kids: list = []

    def _child(h, _):
        kids.append((h, win32gui.GetClassName(h)))

    win32gui.EnumChildWindows(hwnd, _child, None)
    for want in ("RichEditD2DPT", "Edit", "RichEdit20W", "RichEdit50W"):
        hit = next((h for h, cls in kids if cls == want), None)
        if hit:
            return hit
    print("  可用子窗口:", sorted({cls for _, cls in kids}))
    return None


def main() -> int:
    import win32con
    import win32gui
    from PySide6.QtWidgets import QApplication

    from native.foreground import ForegroundGuard
    from native.injector import Injector
    from native.selection import SelectionService, keyboard_controller

    as_json = "--json" in sys.argv
    app = QApplication.instance() or QApplication([])  # noqa: F841

    print("=== 0) pynput 可用性 ===")
    try:
        keyboard_controller()
    except Exception as e:  # noqa: BLE001
        return _inconclusive(f"pynput 构造失败: {type(e).__name__}: {e}")
    print("  keyboard_controller() OK")

    print("=== 0.5) SendInput 能力（OS 收不收合成输入）===")
    n_ins, err = _sendinput_capability()
    if n_ins == 2:
        print(f"  ✓ SendInput 接受（插入 {n_ins}/2 个事件）—— 环境没有拦合成输入")
    else:
        print(f"  ✗ SendInput 被拦（插入 {n_ins}/2 个事件，GetLastError={err}）")
        print("    常见原因：目标窗口提权（UIPI，err=5）/ 进程完整性级别更低")
        print("    ⚠ 实测沙箱内、沙箱外**都返回 2/2** —— 沙箱不是原因。")
        print("      所以「注入没生效」不能拿沙箱当解释，要看下面的结果文本。")

    tmp = Path(tempfile.gettempdir()) / MARK
    tmp.write_text("", encoding="utf-8")

    proc = None
    hwnd = None
    result = None
    try:
        print("=== 1) 打开记事本 ===")
        before = _snap_notepads()
        proc = subprocess.Popen(["notepad.exe", str(tmp)])
        time.sleep(3.5)
        new = _snap_notepads() - before
        # 记事本是单实例：新文件可能开在已有实例的新标签页里
        hwnd = sorted(new)[0] if new else next(
            (h for h in _snap_notepads() if MARK in win32gui.GetWindowText(h)), None
        )
        if not hwnd:
            return _inconclusive("未定位到本次打开的记事本窗口")
        # 安全阀：不确定这个窗口是不是我们的，绝不动它
        if MARK not in win32gui.GetWindowText(hwnd):
            return _inconclusive(f"窗口标题不含 {MARK}，不动未知文档")

        edit = _find_edit(hwnd)
        if not edit:
            return _inconclusive("未找到编辑控件")
        print(f"  主窗口={hwnd}  编辑控件={edit}")

        def get_text() -> str:
            buf = ctypes.create_unicode_buffer(512)
            win32gui.SendMessage(edit, win32con.WM_GETTEXT, 512, buf)
            return buf.value

        win32gui.SendMessage(edit, win32con.WM_SETTEXT, 0, BASE)
        time.sleep(0.3)
        win32gui.SendMessage(edit, EM_SETSEL, 0, 3)   # 选中 "AAA"
        time.sleep(0.3)
        print(f"  基准文本={get_text()!r}（已选中 'AAA'）")

        print("=== 2) 记事本设为前台 ===")
        guard = ForegroundGuard()
        ok_fg = guard.restore(hwnd)
        time.sleep(0.4)
        print(f"  restore()={ok_fg}  当前前台={guard.current()}（目标={hwnd}）")
        if not ok_fg:
            return _inconclusive("抢前台失败 —— 按键必然落不到目标")

        # `SetForegroundWindow` 只保证**窗口**在前台，不保证键盘焦点落在哪个
        # 子控件上。焦点不在编辑控件时 Ctrl+V 会落空 —— 表现为「注入成功但
        # 文本没变」。所以显式把焦点交给编辑控件。
        # 跨线程 SetFocus 要先 AttachThreadInput，否则静默失败。
        import win32api
        import win32process

        cur_tid = win32api.GetCurrentThreadId()
        tgt_tid = win32process.GetWindowThreadProcessId(hwnd)[0]
        attached = False
        try:
            if tgt_tid and tgt_tid != cur_tid:
                win32process.AttachThreadInput(cur_tid, tgt_tid, True)
                attached = True
            win32gui.SetFocus(edit)
        finally:
            if attached:
                try:
                    win32process.AttachThreadInput(cur_tid, tgt_tid, False)
                except Exception:
                    pass
        time.sleep(0.2)
        print(f"  已把键盘焦点交给编辑控件 {edit}")

        print("=== 3) 写剪贴板 + 真实 pynput Ctrl+V ===")
        sel = SelectionService()
        sel.set_clipboard(PAYLOAD)
        time.sleep(0.2)
        print(f"  剪贴板={sel.get_clipboard()!r}")

        # `restore_clipboard=True` 时，`paste_to_foreground` 会在 120ms 后把
        # 剪贴板还原成「粘贴前的内容」。**如果目标应用读剪贴板晚于这 120ms**，
        # 它读到的就是还原后的旧内容 —— 表现为「粘出来什么都没变」。
        # `--no-restore` 关掉还原，用来验证这个假设。
        restore = "--no-restore" not in sys.argv
        print(f"  restore_clipboard={restore}")

        t0 = time.perf_counter()
        if "--key-delay" in sys.argv:
            # 假设：`_send_paste` 里 `press(Ctrl)` 与 `press("v")` 之间没有间隔，
            # 目标应用可能先收到 `v` 再收到 Ctrl 的状态 —— 于是打出的是**字母 v**
            # 而不是粘贴（实测抓到过结果文本 'v BBB CCC'）。
            # 这里在两者之间插一段等待，验证能不能把偶发压下去。
            from native.injector import DESELECT_DELAY

            class _DelayedInjector(Injector):
                @staticmethod
                def _send_paste(clear_selection: bool = False) -> bool:
                    try:
                        from pynput import keyboard as pk

                        c = keyboard_controller()
                        if clear_selection:
                            c.press(pk.Key.right)
                            c.release(pk.Key.right)
                            time.sleep(DESELECT_DELAY)
                        c.press(pk.Key.ctrl_l)
                        time.sleep(0.04)        # ← 等 Ctrl 真的被系统登记
                        c.press("v")
                        time.sleep(0.02)
                        c.release("v")
                        time.sleep(0.02)
                        c.release(pk.Key.ctrl_l)
                        return True
                    except Exception:
                        return False

            inj = _DelayedInjector(sel)
            print("  使用 --key-delay：Ctrl 与 v 之间插了 40ms")
        else:
            inj = Injector(sel)

        ok = inj.paste_to_foreground(
            PAYLOAD, restore_clipboard=restore, clear_selection=False)
        dt = (time.perf_counter() - t0) * 1000
        time.sleep(0.5)
        result = get_text()
        print(f"  _send_paste 返回={ok}  全程={dt:.1f}ms")
        print(f"  结果文本={result!r}")
    finally:
        if proc:
            try:
                proc.terminate()
            except Exception:
                pass
        if hwnd:
            try:
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:
                pass
        tmp.unlink(missing_ok=True)

    passed = result == EXPECT
    print("\n判定:", "PASS" if passed else "FAIL")
    if passed:
        print(f"  ✓ 真实按键注入生效（{result!r}）")
        print("    ⚠ 但这只是**一次**成功 —— 实测成功率约 40–50%，单次 PASS 不等于稳定。")
    else:
        print(f"  ✗ 这一次没生效（{result!r}，期望 {EXPECT!r}）")
        if result == BASE:
            print("    文本纹丝不动 —— 按键根本没落到目标控件。")
        elif "v" in result and PAYLOAD not in result:
            print("    出现了字母 v —— **Ctrl 没生效**，修饰键丢了。")
        print("    ⚠ 这是概率性的（实测约 40–50% 会失败），不代表代码必坏。")
        print("      要下结论请连跑多次统计成功率。")

    if as_json:
        print(json.dumps(
            {"base": BASE, "payload": PAYLOAD, "result": result,
             "expect": EXPECT, "pass": passed},
            ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
