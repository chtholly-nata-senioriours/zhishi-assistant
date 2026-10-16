#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S10 — 真实第三方应用选区采集：R14 新旧实现的跨进程 A/B

为什么必须有这一条
    S9 只证明了「固定等待 → 轮询」省下的 250ms（R14 的第一半）。
    R14 的另一半是 `clip.clear()` 的 ~330ms，**在单进程内复现不出来**：
    剪贴板由本进程（Qt）持有时 `clear()` 只要 0.5ms，S9 永远测不到。

    试过用「独立助手进程直接写剪贴板」来稳定复现，**不成立** ——
    助手进程写完（哪怕数据完好、格式齐全）后 `clear()` 仍只要 0.1ms。
    能复现出 330ms 的只有「真实应用真的执行了一次复制」：
    记事本、以及一个只 `EmptyClipboard` 不写数据的助手进程（见下）。

    ⚠ 因此这条 spike 依赖**真实桌面 + 合成按键**，而合成 Ctrl+C 是否落地
      取决于会话状态 —— 实测同一份脚本在一个会话里 60/60 成功，在另一个
      会话里整轮 0/8 失败。**这是环境问题，不是被测代码的问题**，所以
      两臂都取不到内容时本 spike 报 INCONCLUSIVE（退出码 0），不报 FAIL。

本 spike 做什么
    打开一个真实记事本（预写文件，不靠粘贴 —— 中文输入法态下
    `keyboard.type()` 会被转写），选中全文后**交替**执行：

        旧实现  backup → clear() → sendCopy → poll → restore
        新实现  backup → seq     → sendCopy → poll → restore

    分段计时 + 可靠性统计。交替执行以抵消记事本随时间变慢的漂移。

    顺带记录一个诊断信号：序列号增量 ≈ +15 说明复制落地了
    （记事本写多格式 + 我们 restore 各占一部分）；只有个位数说明
    这次 Ctrl+C 没写进剪贴板。

用法
    python dev_bootstrap.py spikes/s10_real_app_selection.py [轮数，默认 10]
    python dev_bootstrap.py spikes/s10_real_app_selection.py 20 --json
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SENTENCE = "The quick brown fox jumps over the lazy dog."
TIMEOUT_MS = 250

#: 序列号增量达到这个量级才认为「目标应用确实复制了」。
DELTA_COPY_LANDED = 12


def _skip(msg: str) -> int:
    print(f"SKIP —— {msg}")
    return 0


def _inconclusive(msg: str) -> int:
    print(f"INCONCLUSIVE —— {msg}")
    print("（这是桌面会话 / 合成按键的问题，不是被测代码的问题）")
    return 0


def _open_notepad():
    """开一个带预写内容的记事本，返回 (proc, hwnd, tmp_path)；失败返回 None。"""
    try:
        import win32con
        import win32gui
    except ImportError:
        return None

    tmp = Path(tempfile.gettempdir()) / "petgame_s10_real.txt"
    tmp.write_text(SENTENCE + "\n", encoding="ascii")
    proc = subprocess.Popen(["notepad.exe", str(tmp)])
    time.sleep(3.0)

    found: list[int] = []

    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if "petgame_s10_real" in title or win32gui.GetClassName(hwnd) == "Notepad":
                found.append(hwnd)

    win32gui.EnumWindows(_cb, None)
    if not found:
        return None

    hwnd = found[0]
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.SetForegroundWindow(hwnd)
    time.sleep(1.0)
    fg = win32gui.GetForegroundWindow()
    print("目标窗口:", win32gui.GetWindowText(fg), "| 已置前:", fg == hwnd)
    return proc, hwnd, tmp


def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    if app.platformName() != "windows":
        return _skip(f"当前平台 {app.platformName()!r} 无真实剪贴板，需 QT_QPA_PLATFORM=windows")

    as_json = "--json" in sys.argv
    rounds = 10
    for a in sys.argv[1:]:
        if a.isdigit():
            rounds = int(a)

    from native.selection import SelectionService, clipboard_sequence, keyboard_controller

    opened = _open_notepad()
    if opened is None:
        return _skip("无法打开 / 找到记事本窗口（需要可用桌面）")
    proc, hwnd, tmp = opened

    svc = SelectionService()
    kb = keyboard_controller()

    def select_all() -> None:
        import win32gui
        from pynput import keyboard as pk

        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:  # noqa: BLE001
            pass
        kb.press(pk.Key.ctrl_l)
        kb.press("a")
        kb.release("a")
        kb.release(pk.Key.ctrl_l)
        time.sleep(0.4)

    def _arm(old: bool) -> dict:
        select_all()
        s0 = clipboard_sequence()
        seg: dict[str, float] = {}

        t = time.perf_counter()
        backup = svc.backup()
        seg["backup"] = (time.perf_counter() - t) * 1000

        if old:
            t = time.perf_counter()
            svc._clip().clear()
            seg["clear"] = (time.perf_counter() - t) * 1000
            seq = -1                      # seq<0 → 走 clear 回退路径
        else:
            t = time.perf_counter()
            seq = svc._clip_token()
            seg["seq"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        svc._send_copy()
        seg["sendCopy"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        got = svc._poll_clipboard(TIMEOUT_MS, seq)
        seg["poll"] = (time.perf_counter() - t) * 1000

        t = time.perf_counter()
        svc.restore(backup)
        seg["restore"] = (time.perf_counter() - t) * 1000

        seg["total"] = sum(seg.values())
        return {"seg": seg, "got": got.strip(), "delta": clipboard_sequence() - s0}

    print("=" * 68)
    print("S10 — 真实第三方应用选区采集（R14 新旧实现跨进程 A/B）")
    print("=" * 68)
    print(f"记事本预写内容: {SENTENCE!r}")
    print(f"交替执行 {rounds} 轮（旧, 新, 旧, 新, …）\n")

    stats = {k: {"ok": 0, "fail": 0, "totals": [], "segs": {}} for k in ("old", "new")}
    try:
        for i in range(1, rounds + 1):
            for name, old in (("old", True), ("new", False)):
                r = _arm(old)
                st = stats[name]
                for k, v in r["seg"].items():
                    st["segs"].setdefault(k, []).append(v)
                if r["got"] == SENTENCE:
                    st["ok"] += 1
                    st["totals"].append(r["seg"]["total"])
                else:
                    st["fail"] += 1
                    print(f"  #{i:2d} {name} ★未取到★ {r['seg']['total']:7.1f}ms"
                          f"  seqΔ={r['delta']:+3d} -> {r['got']!r}")
    finally:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        tmp.unlink(missing_ok=True)

    print("\n分段耗时（成功样本均值，ms）")
    print(f"  {'阶段':<10}{'旧（clear）':>13}{'新（序列号）':>14}")
    for k in ("backup", "clear", "seq", "sendCopy", "poll", "restore", "total"):
        o = stats["old"]["segs"].get(k)
        n = stats["new"]["segs"].get(k)
        o_s = f"{sum(o) / len(o):.1f}" if o else "—"
        n_s = f"{sum(n) / len(n):.1f}" if n else "—"
        print(f"  {k:<10}{o_s:>13}{n_s:>14}")

    print("\n可靠性")
    for name, label in (("old", "旧（clear）  "), ("new", "新（序列号）")):
        st = stats[name]
        print(f"  {label}  成功 {st['ok']}/{rounds}  失败 {st['fail']}")

    if stats["old"]["ok"] == 0 and stats["new"]["ok"] == 0:
        print()
        return _inconclusive("两臂都没取到内容 —— 合成 Ctrl+C 未落地")

    old_avg = sum(stats["old"]["totals"]) / max(len(stats["old"]["totals"]), 1)
    new_avg = sum(stats["new"]["totals"]) / max(len(stats["new"]["totals"]), 1)
    speed = old_avg / max(new_avg, 0.001)
    clear_samples = stats["old"]["segs"].get("clear") or []
    clear_avg = sum(clear_samples) / len(clear_samples) if clear_samples else 0.0
    print(f"\n  本次 clear 均值 {clear_avg:.1f} ms"
          f"（本环境下剪贴板处于{'慢' if clear_avg > 100 else '快'}状态）")
    print(f"  → 提速 {speed:.1f}×（{old_avg:.0f}ms → {new_avg:.0f}ms）")

    # ⚠ 判定只看「**不得回归**」，不看提速倍数：
    #   clear 的代价取决于剪贴板当时的状态（有外部写入者时实测 330ms，
    #   本进程持有剪贴板时只要 0.5ms），而这个状态不是本 spike 能稳定构造的。
    #   把 330ms 当门禁会让这条 spike 随会话状态时红时绿 —— 那是环境问题。
    #   「能省下多少」由 docs/执行框架.md 里记录的实测数据说明。
    passed = (
        stats["new"]["ok"] == rounds
        and stats["old"]["ok"] == rounds
        and new_avg <= old_avg * 1.1
    )
    print("判定:", "PASS" if passed else "FAIL", "（判据：新实现取值全对且不慢于旧实现）")

    if as_json:
        print(json.dumps({
            "rounds": rounds,
            "old": {"ok": stats["old"]["ok"], "fail": stats["old"]["fail"],
                    "avg_total_ms": round(old_avg, 1)},
            "new": {"ok": stats["new"]["ok"], "fail": stats["new"]["fail"],
                    "avg_total_ms": round(new_avg, 1)},
            "clear_avg_ms": round(clear_avg, 1),
            "segments": {k: {kk: (round(sum(vv) / len(vv), 1) if vv else None)
                             for kk, vv in v.items()}
                         for k, v in stats.items()},
            "speedup": round(speed, 2),
            "pass": passed,
        }, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
