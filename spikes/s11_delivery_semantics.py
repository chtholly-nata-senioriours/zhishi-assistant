#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S11 — 投递语义：REPLACE 与 PASTE 的结果文本必须不同

背景
    2026-10-12 实测发现「替换原文」与「粘贴到前台」**走的是同一条路径** ——
    `paste_to_foreground()` 的签名里根本没有投递方式，两种 kind 都只是
    「写剪贴板 + Ctrl+V」。于是：

      · 选区还在时，PASTE 也会把原文**替换**掉（本该插入）
      · 选区丢了时，REPLACE 退化成插入（本该替换）

    用户看到「点了替换原文，原文还在」。修法是在粘贴前**取消选区**：
      replace → 不动选区，Ctrl+V 覆盖它
      paste   → 先按一下 Right 取消选区，Ctrl+V 在选区末尾插入

本 spike 做什么
    在**真实记事本**上跑两种投递，比对**结果文本**：

        基准 "AAA BBB CCC"，先选中 "AAA"，投递 "XXX"
            REPLACE → "XXX BBB CCC"      选区被覆盖，原文消失
            PASTE   → "AAAXXX BBB CCC"   取消选区后插入，原文保留

    两臂结果相同 → 语义未分离，FAIL。

为什么用窗口消息而不是全局按键注入
    本机会话里合成按键（pynput / SendInput）**落不下去** —— 与 S10 同源，
    是桌面会话状态问题，不是被测代码的问题。因此本 spike 把「粘贴」换成
    向编辑控件投 `WM_PASTE`，把「取消选区」换成投 `VK_RIGHT` 消息。

    ⚠ 诚实标注：本 spike 验证的是**语义**（有没有取消选区 → 结果文本差异）。
      真实按键序列本身由 `tests/test_injector.py` 覆盖（断言 Right 出现在
      Ctrl+V 之前、两种 kind 的按键序列不同）。

`--legacy` 自证
    加 `--legacy` 让两臂都保持选区（模拟改造前的行为）。此时**期望 FAIL** ——
    这是探针的自证：证明它真的能区分「语义分离」与「语义未分离」。

踩过的坑（每一个都真实发生过）
    · Windows 11 新版记事本的编辑控件是 `RichEditD2DPT`，**不是**经典 `Edit`
    · 消息必须发给编辑控件；发给主窗口只会改到**标题栏**
    · 记事本是**单实例**：`notepad.exe` 把文件交给已有实例后自己退出，
      所以 `Popen().pid` **不是** UI 进程 → 用「操作前后窗口集合差集」定位
    · 必须确认目标窗口打开的是**本次的临时文件**，否则可能动到用户的文档

用法
    python dev_bootstrap.py spikes/s11_delivery_semantics.py
    python dev_bootstrap.py spikes/s11_delivery_semantics.py --json
    python dev_bootstrap.py spikes/s11_delivery_semantics.py --legacy   # 期望 FAIL
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

#: 基准文本。第一个词会被选中，投递内容会覆盖/插入到它那里。
BASE = "AAA BBB CCC"
#: 投递内容 —— 故意与任何词都不同，便于辨认。
PAYLOAD = "XXX"
#: 临时文件名（同时用作「这个窗口打开的是我的文件吗」的凭据）。
MARK = "petgame_delivery_semantics.txt"

WM_PASTE = 0x0302
EM_SETSEL = 0x00B1
EM_GETSEL = 0x00B0

EXPECT = {
    "replace": f"{PAYLOAD} BBB CCC",       # 选区被覆盖
    "paste": f"AAA{PAYLOAD} BBB CCC",      # 选区保留，结果插在其后
}


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


def _find_edit(hwnd) -> int | None:
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


def _make_injector(edit, legacy: bool):
    """构造一个「用窗口消息投递」的 Injector。

    `--legacy` 时两臂都保持选区（模拟改造前的行为）。
    """
    from native.injector import Injector
    from native.selection import SelectionService

    class _MessageInjector(Injector):
        def __init__(self, target, selection, legacy_mode: bool):
            super().__init__(selection)
            self.target = target
            self.legacy = legacy_mode

        def _send_paste(self, clear_selection: bool = False) -> bool:
            import win32api
            import win32con

            try:
                if clear_selection and not self.legacy:
                    win32api.PostMessage(self.target, win32con.WM_KEYDOWN, win32con.VK_RIGHT, 0)
                    win32api.PostMessage(self.target, win32con.WM_KEYUP, win32con.VK_RIGHT, 0)
                    time.sleep(0.08)
                win32api.SendMessage(self.target, WM_PASTE, 0, 0)
                return True
            except Exception as e:  # noqa: BLE001
                print("  注入异常:", e)
                return False

    return _MessageInjector(edit, SelectionService(), legacy)


def main() -> int:
    import win32api
    import win32con
    import win32gui
    from PySide6.QtWidgets import QApplication

    as_json = "--json" in sys.argv
    legacy = "--legacy" in sys.argv

    app = QApplication.instance() or QApplication([])  # noqa: F841 —— Injector 需要

    tmp = Path(tempfile.gettempdir()) / MARK
    tmp.write_text("", encoding="utf-8")

    proc = None
    hwnd = None
    results: dict = {}
    try:
        before = _snap_notepads()
        proc = subprocess.Popen(["notepad.exe", str(tmp)])
        time.sleep(3.5)
        new = _snap_notepads() - before

        if new:
            hwnd = sorted(new)[0]
        else:
            # 复用已有实例（新文件开在新标签页）→ 按标题找
            hwnd = next(
                (h for h in _snap_notepads() if MARK in win32gui.GetWindowText(h)), None
            )
        if not hwnd:
            return _inconclusive("未定位到本次打开的记事本窗口")

        title = win32gui.GetWindowText(hwnd)
        print("记事本窗口:", title)
        if MARK not in title:
            # 安全阀：不确定这个窗口是不是我们的，绝不动它
            return _inconclusive(f"窗口标题不含 {MARK}，不动未知文档")

        edit = _find_edit(hwnd)
        if not edit:
            return _inconclusive("未找到编辑控件")

        inj = _make_injector(edit, legacy)

        def get_text() -> str:
            buf = ctypes.create_unicode_buffer(512)
            win32gui.SendMessage(edit, win32con.WM_GETTEXT, 512, buf)
            return buf.value

        def reset_and_select_first_word() -> str:
            win32gui.SendMessage(edit, win32con.WM_SETTEXT, 0, BASE)
            time.sleep(0.25)
            win32gui.SendMessage(edit, EM_SETSEL, 0, 3)   # 选中 "AAA"
            time.sleep(0.25)
            sel = win32gui.SendMessage(edit, EM_GETSEL, 0, 0)
            return f"选区={win32api.LOWORD(sel)},{win32api.HIWORD(sel)}"

        for label, clear in (("replace", False), ("paste", True)):
            state = reset_and_select_first_word()
            if get_text() != BASE:
                return _inconclusive(f"{label}: 基准文本写入失败")
            print(f"  [{label:7s}] 投递前 {state}  文本={get_text()!r}")
            ok = inj.paste_to_foreground(PAYLOAD, clear_selection=clear)
            time.sleep(0.3)
            results[label] = get_text()
            print(f"  [{label:7s}] ok={ok}  结果={results[label]!r}")
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

    r, p = results.get("replace"), results.get("paste")
    if r is None or p is None:
        return _inconclusive("有一臂没取到结果")

    if legacy:
        passed = (r == p)
        print("\n[--legacy] 期望两臂相同（模拟改造前的行为）")
    else:
        passed = (r == EXPECT["replace"] and p == EXPECT["paste"])

    print("\n判定:", "PASS" if passed else "FAIL")
    if not legacy:
        print(f"  REPLACE 覆盖原文 → {r!r}（期望 {EXPECT['replace']!r}）")
        print(f"  PASTE  保留原文 → {p!r}（期望 {EXPECT['paste']!r}）")
        if r == p:
            print("  ★ 两臂结果相同 —— 语义未分离")

    if as_json:
        print(json.dumps(
            {"base": BASE, "payload": PAYLOAD, "legacy": legacy,
             "replace": r, "paste": p, "expect": EXPECT, "pass": passed},
            ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
