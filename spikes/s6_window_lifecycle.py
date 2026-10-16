#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S6 — 窗口生命周期：关闭对话框不应退出应用

背景（用户实测报的 bug）
    打开「AI 服务设置」对话框，关掉它 —— **整个应用退出了**。

根因假设
    `QApplication.quitOnLastWindowClosed` 默认 **True**。
    本项目两个常驻窗口都是 `Qt.Tool`：
        ShellWindow (ui_renderer.py) / AIPanel (ai_panel.py)
        → FramelessWindowHint | WindowStaysOnTopHint | Tool
    `Qt.Tool` 窗口**不计入**「最后窗口」判定，于是关掉设置对话框
    （真正的 QDialog）后 Qt 认为没有窗口了 → quit。

⚠ 写这个 spike 时踩的坑（第一版是错的）
    `lastWindowClosed` **只在事件循环运行期间才会发出**
    （Qt 源码 `QGuiApplicationPrivate::emitLastWindowClosed()` 里有 `in_exec` 判断）。
    第一版没跑 `app.exec()`，于是无论对错都"没触发"，把假设误判成了"未复现"。
    正确做法：跑真事件循环，用 `aboutToQuit` + "存活计时器"来判定。

    另外 `QApplication` 无法销毁重建，`quitOnLastWindowClosed` 又是全局状态，
    所以**每个用例单开一个子进程**，保证互不污染。

判定
    1. 复现：默认设置 + Tool 常驻窗口 → 关掉对话框后应用**退出**
    2. 修复：`setQuitOnLastWindowClosed(False)` → 应用**存活**
    3. 对照：常驻窗口不是 Tool → 默认设置下也**存活**
       （印证根因确实是 Tool 类型，而不是别的）

用法
    python dev_bootstrap.py spikes/s6_window_lifecycle.py          # 跑全部用例
    python spikes/s6_window_lifecycle.py --case tool-default       # 跑单个用例（子进程用）
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------- 子进程模式

CASES = {
    # name: (quit_on_last_window_closed, resident_is_tool)
    "tool-default": (True, True),     # 当前产品形态（应复现退出）
    "tool-fixed": (False, True),      # 修复后（应存活）
    "plain-default": (True, False),   # 对照组（应存活）
}


def _run_one_case(quit_on_last: bool, resident_is_tool: bool) -> dict:
    """在真事件循环里跑一个用例。返回 {'survived': bool}。"""
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication, QDialog, QWidget

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(quit_on_last)

    flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
    if resident_is_tool:
        flags |= Qt.WindowType.Tool

    resident = QWidget(None, flags)      # 模拟桌宠 / AI 面板
    resident.resize(140, 140)
    resident.show()

    dlg = QDialog(None)                  # 模拟设置对话框
    dlg.resize(240, 180)
    dlg.show()

    state = {"survived": False}

    # 80ms 后关掉对话框 —— 这就是用户点「关闭」的时刻
    QTimer.singleShot(80, dlg.close)

    def _survival_probe():
        # 能跑到这里说明应用没被关对话框带崩
        state["survived"] = True
        app.exit(0)

    QTimer.singleShot(500, _survival_probe)

    app.exec()          # ← 关键：必须真跑事件循环
    return state


def _child_main(case: str) -> int:
    quit_on_last, is_tool = CASES[case]
    result = _run_one_case(quit_on_last, is_tool)
    print(json.dumps(result))
    return 0


# ---------------------------------------------------------------- 父进程模式


def main() -> int:
    from spikes._common import Report, bootstrap

    bootstrap()

    if "--case" in sys.argv:
        idx = sys.argv.index("--case")
        return _child_main(sys.argv[idx + 1])

    rep = Report(
        "S6",
        "窗口生命周期：关闭对话框不应退出应用",
        "Tool 类型常驻窗口不计入「最后窗口」，导致关闭对话框时应用退出",
        "默认设置下退出（复现）+ 关闭开关后存活（修复）+ 非 Tool 对照存活 → PASS",
    )

    observed = {}
    for name in CASES:
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--case", name],
            capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        )
        line = (proc.stdout or "").strip().splitlines()
        try:
            observed[name] = json.loads(line[-1])["survived"]
        except Exception:
            observed[name] = None
            rep.note(f"{name} 子进程输出异常: {(proc.stdout or '')[-200:]} {(proc.stderr or '')[-200:]}")
        print(f"  用例 {name}: survived={observed[name]}")

    rep.check("复现：默认设置 + Tool 常驻窗口 → 关掉对话框后应用退出",
              observed.get("tool-default") is False,
              "已复现" if observed.get("tool-default") is False else "未复现")
    rep.check("修复：setQuitOnLastWindowClosed(False) → 应用存活",
              observed.get("tool-fixed") is True,
              "已修复" if observed.get("tool-fixed") is True else "仍会退出")
    rep.check("对照：常驻窗口非 Tool → 默认设置下也存活",
              observed.get("plain-default") is True,
              "印证根因是 Tool 类型" if observed.get("plain-default") is True else "对照组也退出，另有原因")

    ok = (observed.get("tool-default") is False
          and observed.get("tool-fixed") is True
          and observed.get("plain-default") is True)
    print()
    rep.finish("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
