#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""spike 公共设施：环境引导 + 结果采集 + 统计工具。

所有 spike 脚本共用本模块，保证：
  - 环境引导与 dev_bootstrap.py 完全一致（不重复实现）
  - 输出格式统一，结果落盘到 spikes/results/*.json
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = Path(__file__).resolve().parent / "results"

# Windows 控制台中文输出
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def bootstrap() -> None:
    """复用 dev_bootstrap.py 的环境引导，避免逻辑重复。"""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import dev_bootstrap  # noqa: E402

    dev_bootstrap.bootstrap()


# ---------------------------------------------------------------- 统计


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "n": len(values),
        "mean": round(sum(values) / len(values), 2),
        "p50": round(percentile(values, 0.50), 2),
        "p95": round(percentile(values, 0.95), 2),
        "max": round(max(values), 2),
    }


# ---------------------------------------------------------------- 报告


class Report:
    """统一的检查项 + 指标 + 结论收集器。"""

    def __init__(self, spike_id: str, title: str, hypothesis: str, criterion: str):
        self.spike_id = spike_id
        self.title = title
        self.hypothesis = hypothesis
        self.criterion = criterion
        self.checks: list[dict] = []
        self.metrics: dict = {}
        self.notes: list[str] = []
        print("=" * 66)
        print(f"{spike_id} — {title}")
        print("=" * 66)
        print(f"假设: {hypothesis}")
        print(f"判定: {criterion}")
        print("-" * 66)

    def check(self, desc: str, ok: bool | None, detail: str = "") -> None:
        """ok=None 表示无法自动判定，需人工确认。"""
        self.checks.append({"desc": desc, "ok": ok, "detail": detail})
        mark = {True: "PASS", False: "FAIL", None: "MANUAL"}[ok]
        line = f"  [{mark:6}] {desc}"
        if detail:
            line += f"  ({detail})"
        print(line)

    def metric(self, key: str, value, unit: str = "") -> None:
        self.metrics[key] = value
        print(f"  [DATA  ] {key} = {value}{unit}")

    def note(self, text: str) -> None:
        self.notes.append(text)
        print(f"  [NOTE  ] {text}")

    def finish(self, verdict: str) -> dict:
        """verdict: PASS / FAIL / MANUAL / ERROR"""
        result = {
            "spike": self.spike_id,
            "title": self.title,
            "hypothesis": self.hypothesis,
            "criterion": self.criterion,
            "verdict": verdict,
            "checks": self.checks,
            "metrics": self.metrics,
            "notes": self.notes,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out = RESULTS_DIR / f"{self.spike_id}.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print("-" * 66)
        print(f"结论: {verdict}")
        print(f"结果已写入: {out}")
        print()
        return result


def has_qt() -> bool:
    try:
        import PySide6  # noqa: F401
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 夹具工具


def force_foreground(guard, hwnd: int, pump, timeout_ms: int = 3000) -> bool:
    """把 hwnd 抢到前台，直到成功或超时。返回是否抢到。

    为什么测试夹具也需要这个
        Windows 有前台锁：当前进程不是前台进程时，`SetForegroundWindow` 会**静默失败**。
        夹具里若只用 `activateWindow()` + `raise_()`，目标窗口**有时**抢不到前台，
        于是 `Ctrl+C` 取不到选中文本、「替换原文」粘到别的窗口 ——
        表现为**间歇性失败**（10 次里错 1 次），是最难排查的一类问题。

        这里复用产品自己的 `ForegroundGuard.restore()`（AttachThreadInput 解锁），
        把夹具的前置条件变成确定性的。

    Args:
        guard: `native.foreground.ForegroundGuard` 实例
        hwnd: 目标窗口句柄
        pump: 事件循环泵函数（`pump(ms)`），由调用方提供以免 _common 依赖 Qt
        timeout_ms: 超时（毫秒）
    """
    deadline = time.perf_counter() + timeout_ms / 1000
    while time.perf_counter() < deadline:
        if guard.current() == hwnd:
            return True
        guard.restore(hwnd)
        pump(80)
    return guard.current() == hwnd
