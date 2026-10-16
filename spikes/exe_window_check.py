"""发版核查 ③：exe 真的把窗口画出来了吗？

为什么需要它
    `app.log` 只记到「热键已注册」就没了（之后进 Qt 事件循环，不再打日志），
    所以「启动序列完整」**证明不了窗口存在**。而 P2.16 换形态恰恰是
    「窗口变了」—— 必须直接问 Windows：这个 pid 名下有哪些可见顶层窗口。

判据
    · 至少 1 个可见窗口
    · 球形态：可见窗口里有 64×64 那一格（`orb_size` 52 + 画布留白 12）

用法
    python dev_bootstrap.py spikes/exe_window_check.py
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "dist" / "知时助手" / "知时助手.exe"

#: 等多久再看窗口（启动序列实测 ~5s，留足余量）
WAIT_S = 15

user32 = ctypes.WinDLL("user32", use_last_error=True)
EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
GetWindowThreadProcessId = user32.GetWindowThreadProcessId
IsWindowVisible = user32.IsWindowVisible
GetWindowRect = user32.GetWindowRect
GetClassNameW = user32.GetClassNameW
GetWindowTextW = user32.GetWindowTextW


def windows_of(pid: int) -> list[dict]:
    """列出 `pid` 名下的所有顶层窗口（含隐藏的）。"""
    found: list[dict] = []

    def cb(hwnd, _):
        owner = wt.DWORD()
        GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            r = wt.RECT()
            GetWindowRect(hwnd, ctypes.byref(r))
            cls = ctypes.create_unicode_buffer(256)
            GetClassNameW(hwnd, cls, 256)
            title = ctypes.create_unicode_buffer(256)
            GetWindowTextW(hwnd, title, 256)
            found.append({
                "cls": cls.value,
                "title": title.value,
                "visible": bool(IsWindowVisible(hwnd)),
                "pos": (r.left, r.top),
                "size": (r.right - r.left, r.bottom - r.top),
            })
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found


def main() -> int:
    if not EXE.exists():
        print(f"!! 找不到 exe：{EXE}")
        return 2

    import time

    proc = subprocess.Popen([str(EXE)], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, cwd=str(EXE.parent))
    print(f"已启动 pid={proc.pid}，等 {WAIT_S}s ...")
    try:
        time.sleep(WAIT_S)
        if proc.poll() is not None:
            print(f"RESULT: FAIL —— 进程已退出（returncode={proc.returncode}）")
            return 1

        wins = windows_of(proc.pid)
        visible = [w for w in wins if w["visible"]]
        print(f"顶层窗口 {len(wins)} 个，其中可见 {len(visible)} 个：")
        for w in wins:
            print(f"  [{'可见' if w['visible'] else '隐藏'}] {w['cls']!r} "
                  f"{w['size'][0]}x{w['size'][1]}@{w['pos'][0]},{w['pos'][1]}")

        if not visible:
            print("RESULT: FAIL —— 没有任何可见窗口，形态没出来")
            return 1
        # 球形态：应该有一格正方形的可见窗口（画布 = 直径 + 留白）
        squares = [w for w in visible if w["size"][0] == w["size"][1] and w["size"][0] >= 48]
        if not squares:
            print("RESULT: FAIL —— 没有正方形窗口（球形态的窗口应该是方的）")
            return 1

        # 隔几秒再采一次 —— **球不该自己动**。
        # 这条是 P2.16 用同样的采样发现的：数值动画按动画开始时的坐标
        # `move()` 外壳，球会被拽回拖动前的落点（详见 AGENTS.md §4.11 ④）。
        # 用户手动拖过就会变，所以只提示、不判 FAIL（保持这条核查非 flaky）。
        time.sleep(6)
        again = [w for w in windows_of(proc.pid)
                 if w["visible"] and w["size"] == squares[0]["size"]]
        print(f"6s 后同尺寸窗口位置：{[w['pos'] for w in again] or '（没了）'}")
        if again and again[0]["pos"] != squares[0]["pos"]:
            print(f"  ⚠ 位置变了 {squares[0]['pos']} -> {again[0]['pos']}"
                  f"（自己动的？还是刚被手动拖过？）")

        print(f"RESULT: PASS —— 可见窗口含正方形形态窗 {squares[0]['size'][0]}px")
        return 0
    finally:
        # 必须显式清进程：孤儿会锁住 dist/.../_internal 的 DLL，
        # 让下次 `PyInstaller --clean` 报 WinError 5（见 AGENTS.md）
        r = subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True)
        print("已清理进程：", (r.stdout or r.stderr).decode("gbk", errors="ignore").strip()[:60])


if __name__ == "__main__":
    sys.exit(main())
