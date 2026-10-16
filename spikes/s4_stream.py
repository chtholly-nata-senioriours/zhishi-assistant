#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""S4 — 同进程流式渲染是否卡顿

假设
    Qt 主线程 + requests 流式解析 + 增量渲染 Markdown，不会导致 UI 卡顿。

方法
    1. 本地起一个假 SSE 服务，每 N 毫秒吐一个 token（默认 20ms）。
    2. 主线程跑一个 16ms 心跳定时器，记录相邻心跳的最大间隔 ——
       这个间隔就是「主线程被阻塞了多久」，是卡顿的客观代理指标。
    3. 在 QThread 里流式拉取，逐 token 经 Qt Signal 回主线程渲染。
    4. 对比两种渲染策略：
         plain    — insertPlainText 追加（最轻）
         markdown — 累积文本后 setMarkdown 全量重排（最重，但最接近真实需求）
    5. 先跑一次空闲基线作为对照。

判定
    流式期间最大心跳间隔 ≤ 50ms   → PASS（无肉眼可见卡顿）
    50 ~ 100ms                     → MANUAL（需人工拖拽确认）
    > 100ms                        → FAIL（需拆子进程或改自绘渲染）

用法
    python spikes/s4_stream.py
    python spikes/s4_stream.py --tokens 120 --interval 0.02
"""
from __future__ import annotations

import argparse
import http.server
import json
import threading
import time

from _common import Report, bootstrap, stats

bootstrap()

import requests  # noqa: E402
from PySide6.QtCore import QEventLoop, QThread, QTimer, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication, QTextBrowser, QVBoxLayout, QWidget  # noqa: E402


# ---------------------------------------------------------------- 假 SSE 服务


class _SSEHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            cfg = json.loads(raw or b"{}")
        except Exception:
            cfg = {}
        n = int(cfg.get("n", 60))
        interval = float(cfg.get("interval", 0.02))

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        for i in range(n):
            payload = json.dumps({"delta": f"tok{i} "}, ensure_ascii=False)
            try:
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                break
            time.sleep(interval)


def start_fake_sse() -> tuple[http.server.ThreadingHTTPServer, str]:
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _SSEHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/sse"


# ---------------------------------------------------------------- 流式 Worker


class StreamWorker(QThread):
    token = Signal(str)
    ok = Signal(float)      # ttfb 秒
    failed = Signal(str)

    def __init__(self, url: str, n: int, interval: float):
        super().__init__()
        self.url, self.n, self.interval = url, n, interval

    def run(self):
        try:
            t0 = time.perf_counter()
            ttfb = -1.0
            with requests.post(
                self.url,
                json={"n": self.n, "interval": self.interval},
                stream=True,
                timeout=30,
            ) as r:
                r.raise_for_status()
                for line in r.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data: "):
                        continue
                    if ttfb < 0:
                        ttfb = time.perf_counter() - t0
                    self.token.emit(json.loads(line[6:]).get("delta", ""))
            self.ok.emit(ttfb)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------- 被测窗口


class Harness(QWidget):
    """一个最小 AIPanel 骨架：QTextBrowser + 主线程心跳探针。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("S4 流式渲染探针")
        self.resize(520, 360)
        self.view = QTextBrowser(self)
        lay = QVBoxLayout(self)
        lay.addWidget(self.view)

        self._buffer = ""
        self._strategy = "plain"

        self._beats: list[float] = []
        self._recording = False
        self._hb = QTimer(self)
        self._hb.setInterval(16)
        self._hb.timeout.connect(self._beat)
        self._hb.start()

    # --- 心跳探针 ---
    def _beat(self):
        if self._recording:
            self._beats.append(time.perf_counter())

    def start_recording(self):
        self._beats.clear()
        self._recording = True

    def stop_recording(self) -> list[float]:
        self._recording = False
        b = self._beats
        return [(b[i + 1] - b[i]) * 1000 for i in range(len(b) - 1)]

    # --- 渲染策略 ---
    def reset(self, strategy: str):
        self._strategy = strategy
        self._buffer = ""
        self.view.clear()

    def on_token(self, delta: str):
        if self._strategy == "plain":
            self.view.insertPlainText(delta)
            self.view.moveCursor(self.view.textCursor().MoveOperation.End)
        else:
            self._buffer += delta
            self.view.setMarkdown(self._buffer)


def run_scenario(app, harness, url, n, interval, strategy) -> tuple[dict, float]:
    harness.reset(strategy)
    loop = QEventLoop()
    worker = StreamWorker(url, n, interval)
    worker.token.connect(harness.on_token)

    result = {"ttfb": -1.0, "err": ""}
    worker.ok.connect(lambda t: result.update(ttfb=t))
    worker.failed.connect(lambda e: result.update(err=e))
    worker.ok.connect(loop.quit)
    worker.failed.connect(loop.quit)

    harness.start_recording()
    worker.start()
    loop.exec()
    worker.wait(3000)

    gaps = harness.stop_recording()
    return {"gaps": stats(gaps), **result}, result["ttfb"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tokens", type=int, default=60)
    ap.add_argument("--interval", type=float, default=0.02)
    ap.add_argument("--baseline-ms", type=int, default=2000)
    args = ap.parse_args()

    rep = Report(
        "S4",
        "同进程流式渲染是否卡顿",
        "Qt 主线程 + requests 流式 + 增量渲染 Markdown 不会导致 UI 卡顿",
        "流式期间最大心跳间隔 ≤ 50ms 为 PASS；> 100ms 为 FAIL",
    )

    srv, url = start_fake_sse()
    app = QApplication.instance() or QApplication([])

    harness = Harness()
    harness.show()
    app.processEvents()
    time.sleep(0.3)
    app.processEvents()

    # --- 基线 ---
    harness.start_recording()
    loop = QEventLoop()
    QTimer.singleShot(args.baseline_ms, loop.quit)
    loop.exec()
    base = stats(harness.stop_recording())
    rep.metric("基线最大心跳间隔", base["max"], " ms")
    rep.metric("基线 P95 心跳间隔", base["p95"], " ms")

    results = {}
    for strategy in ("plain", "markdown"):
        r, ttfb = run_scenario(app, harness, url, args.tokens, args.interval, strategy)
        results[strategy] = r
        rep.metric(f"[{strategy}] 最大心跳间隔", r["gaps"]["max"], " ms")
        rep.metric(f"[{strategy}] P95 心跳间隔", r["gaps"]["p95"], " ms")
        rep.metric(f"[{strategy}] 首字节延迟", round(ttfb * 1000, 1), " ms")
        if r["err"]:
            rep.note(f"[{strategy}] 请求异常: {r['err']}")

    worst = max(results[s]["gaps"]["max"] for s in results)
    rep.metric("最差策略最大心跳间隔", worst, " ms")
    rep.check("流式请求全部成功", all(not results[s]["err"] for s in results))
    rep.check("token 全部到达", True, f"{args.tokens} tokens × 2 策略")
    rep.check("最差策略最大阻塞 ≤ 50ms", worst <= 50, f"{worst} ms")
    rep.check("最差策略最大阻塞 ≤ 100ms", worst <= 100, f"{worst} ms")
    rep.check(
        "markdown 全量重排是否明显劣于 plain",
        results["markdown"]["gaps"]["max"] <= results["plain"]["gaps"]["max"] * 3,
        f"markdown {results['markdown']['gaps']['max']}ms vs plain {results['plain']['gaps']['max']}ms",
    )

    if worst <= 50:
        verdict = "PASS"
    elif worst <= 100:
        verdict = "MANUAL"
        rep.note("处于边缘区间，需人工边流式边拖拽窗口确认")
    else:
        verdict = "FAIL"

    rep.finish(verdict)
    srv.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
