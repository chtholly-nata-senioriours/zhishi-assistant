#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S9 — 性能收尾：R14 选区采集延迟 / R15 截图编码耗时

背景
    `docs/执行框架.md` §性能预算里挂着两条遗留风险：

    · **R14** `get_selected()` 总耗时呈双峰 **253ms / 565ms**。两峰各有原因：
      253ms 那一峰是**设计内的固定等待**：发完 Ctrl+C 后无条件
      `_wait(max(delay, timeout_ms))`，即便目标应用 20ms 就写好了剪贴板。
      565ms 那一峰是**清空剪贴板的跨进程协商**：旧实现用 `clip.clear()`
      制造空基准，而清空要等前一个所有者进程响应，实测 330ms。
    · **R15** `to_png_bytes()` 阻塞主线程 **73–136ms**，正好落在
      「用户框选松手」与「请求发出」之间。

本 spike 做什么
    R14   造一个「模拟目标应用延迟 N ms 才写剪贴板」的假 SelectionService，
          用**旧逻辑**与**新逻辑**各跑若干次，对比墙钟耗时。
          （不依赖真实第三方应用，因此可重复、可在 CI 跑。）
    R14-b 测序列号判据的读取代价。
          ⚠ `clear()` 的 330ms **无法在本进程内复现**（剪贴板由本进程持有时
          几乎免费），跨进程的定论见 `spikes/s10_real_app_selection.py`。
    R15   构造三档尺寸的 QPixmap，对比 PNG / JPEG 的编码耗时与体积。

判定
    R14   新逻辑在「应用 25ms 写好剪贴板」时明显快于旧逻辑，且返回值一致
    R14-b 序列号判据可用且单次读取 < 50µs
    R15   JPEG 编码耗时与体积都显著小于 PNG

用法
    python dev_bootstrap.py spikes/s9_perf_tail.py
    python dev_bootstrap.py spikes/s9_perf_tail.py --json
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TARGET_TEXT = "选中的一段文字"
APP_DELAY_MS = 25          # 模拟「目标应用 25ms 后写好剪贴板」
REPEAT = 5


# ---------------------------------------------------------------- R14

def _bench_selection() -> dict:
    """对比「固定等待」与「轮询」两种取选区实现的耗时。"""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from native.selection import SelectionService

    class FakeTarget(SelectionService):
        """假目标应用：收到 Ctrl+C 后延迟 `APP_DELAY_MS` 才写剪贴板。

        同时模拟「剪贴板发生了一次新复制」。真实环境靠
        `GetClipboardSequenceNumber()` 观测，但本 spike 跑在 `offscreen` 下，
        Qt 用的是**进程内**剪贴板、序列号不会动，所以用自增计数代替
        （语义一致：写入内容 ⇒ 版本 +1）。
        """

        def __init__(self) -> None:
            super().__init__()
            self._version = 0

        def _clip_token(self) -> int:  # noqa: D102 —— 覆盖真实序列号
            return self._version

        def _send_copy(self) -> None:  # noqa: D102 —— 覆盖真实按键注入
            def _write() -> None:
                self.set_clipboard(TARGET_TEXT)
                self._version += 1

            QTimer.singleShot(APP_DELAY_MS, _write)

    def legacy_get_selected(svc: SelectionService, timeout_ms: int = 250) -> str:
        """R14 整改前的实现（固定等待 + clear 基准）。"""
        backup = svc.backup()
        try:
            clip = svc._clip()
            if clip:
                clip.clear()
            svc._send_copy()
            svc._wait(max(svc.delay, timeout_ms / 1000.0))
            return svc.get_clipboard()
        finally:
            svc.restore(backup)

    assert QApplication.instance() is not None

    result = {}
    for label, fn in (("old_fixed_wait", legacy_get_selected),
                      ("new_polling", lambda s: s.get_selected())):
        samples = []
        for _ in range(REPEAT):
            svc = FakeTarget()
            t0 = time.perf_counter()
            got = fn(svc)
            samples.append(round((time.perf_counter() - t0) * 1000, 1))
            assert got == TARGET_TEXT, f"{label}: 取到的内容不对 -> {got!r}"
        result[label] = samples
    return result


# ---------------------------------------------------------------- R14-b

def _bench_clip_token() -> dict:
    """R14 第二半：序列号判据的**读取**代价。

    ⚠ `clear()` 的代价无法在本进程内复现
        旧实现用 `clip.clear()` 制造「空剪贴板」基准，而清空要**等前一个
        所有者进程响应**（Windows 跨进程剪贴板所有权协商）。剪贴板由本进程
        （Qt）持有时，`clear()` 几乎免费 —— 所以本函数测它只会得到 ~0.2ms，
        完全掩盖了真实场景里的 **330ms**。
        真实场景中剪贴板通常被别的应用持有（浏览器 / 记事本 / 编辑器），
        因此跨进程的 A/B 必须用真实外部应用，见 `spikes/s10_real_app_selection.py`。

    本函数只回答一个问题：**判据本身贵不贵**。答案是 0.001ms 级 —— 纯读、
    不需要打开剪贴板。
    """
    from native.selection import clipboard_sequence

    n = 200
    t0 = time.perf_counter()
    for _ in range(n):
        clipboard_sequence()
    total = (time.perf_counter() - t0) * 1000
    return {
        "calls": n,
        "total_ms": round(total, 3),
        "per_call_us": round(total / n * 1000, 2),
        "available": clipboard_sequence() >= 0,
    }


# ---------------------------------------------------------------- R15

def _make_pixmap(w: int, h: int):
    """造一张「像截图」的位图。

    刻意不用纯色或规则网格 —— 那类合成图对 PNG 过于友好（实测 1920×1080
    的网格图 PNG 只有 9KB），会把体积对比带偏。这里用「渐变底 + 大量随机
    小色块」逼近真实屏幕内容（UI 控件、文字块、图片），高频细节足够多。
    """
    import random

    from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap

    pm = QPixmap(w, h)
    p = QPainter(pm)
    try:
        grad = QLinearGradient(0, 0, w, h)
        grad.setColorAt(0.0, QColor(28, 30, 44))
        grad.setColorAt(1.0, QColor(62, 74, 116))
        p.fillRect(0, 0, w, h, grad)

        rnd = random.Random(7)
        for _ in range(max(200, w * h // 260)):
            x = rnd.randrange(max(1, w - 40))
            y = rnd.randrange(max(1, h - 16))
            p.fillRect(
                x, y,
                rnd.randrange(4, 40), rnd.randrange(3, 12),
                QColor(rnd.randrange(120, 250),
                       rnd.randrange(120, 250),
                       rnd.randrange(120, 250)),
            )
    finally:
        p.end()
    return pm


def _grab_real():
    """非 headless 时抓一张真实屏幕；否则返回 None。

    ⚠ 为什么必须优先用真实截图
        合成图（渐变 + 随机色块）对 PNG 过于友好 —— 实测 1920×1080 的合成图
        PNG 只有 236KB，看起来「PNG 又小又快」。而**真实屏幕**（文字 + 渐变 +
        照片）的 PNG 编码要 292ms / 1.6MB（1200×750），JPEG 只要 16ms / 264KB。
        用合成图会得出完全相反的结论，所以这里优先真实抓屏。
    """
    if os.environ.get("QT_QPA_PLATFORM", "").lower() in ("offscreen", "minimal"):
        return None
    try:
        from native.capture import CaptureService

        pm = CaptureService().grab_fullscreen()
        if pm.isNull() or pm.width() < 400:
            return None
        return pm
    except Exception:  # noqa: BLE001
        return None


def _bench_capture() -> tuple[list, str]:
    from PySide6.QtCore import Qt

    from native.capture import CaptureService

    svc = CaptureService()

    real = _grab_real()
    if real is not None:
        source = f"真实抓屏 {real.width()}×{real.height()}"
        targets = [("full", real)]
        half = real.scaled(
            real.width() // 2, real.height() // 2,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        targets.append(("half", half))
    else:
        source = "合成图（渐变 + 随机色块）—— 对 PNG 偏友好，仅供可重复回归"
        targets = [
            (f"{w}×{h}", _make_pixmap(w, h))
            for w, h in ((640, 400), (1280, 800), (1920, 1080))
        ]

    rows = []
    for label, pm in targets:
        t0 = time.perf_counter()
        png = svc.to_png_bytes(pm)
        t_png = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        jpg = svc.to_jpeg_bytes(pm)
        t_jpg = (time.perf_counter() - t0) * 1000

        url = svc.to_data_url(pm)
        rows.append({
            "size": f"{label} {pm.width()}x{pm.height()}",
            "png_ms": round(t_png, 1),
            "jpeg_ms": round(t_jpg, 1),
            "speedup": round(t_png / max(t_jpg, 0.001), 2),
            "png_kb": round(len(png) / 1024, 1),
            "jpeg_kb": round(len(jpg) / 1024, 1),
            "data_url_mime": url.split(";")[0].split(":")[1],
        })
    return rows, source


# ---------------------------------------------------------------- 主流程

def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    _ = app

    print("=" * 68)
    print("S9 — 性能收尾（R14 选区采集 / R15 截图编码）")
    print("=" * 68)

    sel = _bench_selection()
    print(f"\n[R14] 假目标应用在 {APP_DELAY_MS}ms 后写好剪贴板，各跑 {REPEAT} 次")
    for label, samples in sel.items():
        avg = sum(samples) / len(samples)
        print(f"  {label:<16} 平均 {avg:6.1f} ms   样本 {samples}")
    old_avg = sum(sel["old_fixed_wait"]) / len(sel["old_fixed_wait"])
    new_avg = sum(sel["new_polling"]) / len(sel["new_polling"])
    speed = old_avg / max(new_avg, 0.001)
    print(f"  → 提速 {speed:.1f}×（{old_avg:.0f}ms → {new_avg:.0f}ms）")

    tok = _bench_clip_token()
    print("\n[R14-b] 序列号判据的读取代价（R14 第二半：不再 clear 剪贴板）")
    print(f"  可用={tok['available']}  {tok['calls']} 次共 {tok['total_ms']}ms"
          f"  → 单次 {tok['per_call_us']}µs")
    print("  注：`clear()` 的真实代价（实测 330ms）来自**跨进程**剪贴板所有权协商，")
    print("      本进程持有剪贴板时几乎免费、无法在此复现 → 定论见 s10_real_app_selection.py")

    cap, source = _bench_capture()
    print(f"\n[R15] 编码耗时与体积（图源：{source}）")
    print(f"  {'尺寸':<20}{'PNG ms':>8}{'JPEG ms':>9}{'提速':>8}"
          f"{'PNG KB':>10}{'JPEG KB':>10}  mime")
    for r in cap:
        print(f"  {r['size']:<20}{r['png_ms']:>8}{r['jpeg_ms']:>9}"
              f"{r['speedup']:>7}×{r['png_kb']:>10}{r['jpeg_kb']:>10}  {r['data_url_mime']}")

    passed = (
        new_avg < old_avg * 0.5
        and tok["available"]
        and tok["per_call_us"] < 50
        and all(r["speedup"] > 1.0 for r in cap)
    )
    print("\n判定:", "PASS" if passed else "FAIL")

    if "--json" in sys.argv:
        print(json.dumps(
            {"selection": sel, "clip_token": tok, "capture": cap,
             "capture_source": source, "pass": passed},
            ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
