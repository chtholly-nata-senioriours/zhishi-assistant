#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""M1 端到端验证 —— 「选中文本 → Alt+Q → 面板流式回答 → Esc 还原焦点」

这不是单元测试，而是把 P1 的全部零件串起来跑一遍真链路：
    PluginManager（T1 包加载）→ on_ui_ready（T3 预热）→ HotkeyService（S1 注册）
    → 合成 Alt+Q（真实 WM_HOTKEY）→ SelectionService（S2 采集）
    → SessionManager 流式 → AIPanel 渲染 → ForegroundGuard 还原焦点（S3）

同时用主线程心跳探针确认流式期间没有阻塞（S4 的方法）。

用法
    python spikes/m1_verify.py
"""
from __future__ import annotations

import time

from _common import Report, bootstrap, force_foreground, stats

bootstrap()

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QTextEdit  # noqa: E402

from engine.ai.provider import Provider  # noqa: E402
from extensions.plugin_manager import PluginManager  # noqa: E402
from native.foreground import ForegroundGuard  # noqa: E402
from native.hotkey import HotkeyService  # noqa: E402

TARGET_TEXT = "HELLO_M1_PROBE"
FAKE_TOKENS = ("M1-", "FAKE-", "ANSWER")


class FakeProvider(Provider):
    name = "fake"

    def stream(self, messages, model, **opts):
        for t in FAKE_TOKENS:
            time.sleep(0.02)
            yield t


class Host:
    """最小宿主：只提供插件需要的那几个属性。"""

    def __init__(self):
        from data.config_manager import config_manager
        from data.log_manager import log_manager

        self.config = config_manager
        self.log = log_manager
        self.ui_manager = None
        self.hotkeys = None
        self.plugin_manager = None
        # 部分既有插件会写这些字段
        self.note_manager = None
        self.timer = None
        self.state_machine = None
        self.rule_engine = None


def pump(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def press_hotkey(combo: str) -> None:
    from pynput import keyboard as pk

    from native.selection import keyboard_controller

    mods = {"alt": pk.Key.alt_l, "ctrl": pk.Key.ctrl_l, "shift": pk.Key.shift_l}
    parts = [p.strip().lower() for p in combo.split("+")]
    key = parts[-1]
    held = [mods[p] for p in parts[:-1] if p in mods]

    # 用共享缓存实例：新建 Controller() 要 71ms（一次性），
    # 属于夹具开销，不该算进被测延迟。
    c = keyboard_controller()
    for m in held:
        c.press(m)
    c.press(key)
    c.release(key)
    for m in reversed(held):
        c.release(m)


def press_hotkey_timed(hb: "Heartbeat", combo: str) -> float:
    """合成热键并把这段「夹具耗时」登记到心跳探针，返回耗时(ms)。

    SendInput 会阻塞调用线程（首次调用还要初始化键盘布局，约 50–60ms），
    这是夹具开销而非应用阻塞。不剔除的话，测出的最大间隔恒等于按键耗时，
    把真实问题掩盖掉。
    """
    t0 = time.perf_counter()
    press_hotkey(combo)
    t1 = time.perf_counter()
    hb.mark_harness(t0, t1)
    return round((t1 - t0) * 1000, 1)


class Heartbeat:
    """主线程心跳探针：记录相邻心跳的最大间隔，并给出最大间隔发生的位置。

    统计时剔除被标记的「夹具耗时」窗口（见 press_hotkey_timed）。
    """

    def __init__(self, app=None):
        self._beats: list[float] = []
        self._on = False
        self._t0 = 0.0
        self._harness: list[tuple[float, float]] = []
        self._timer = QTimer()
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._beat)
        self._timer.start()

    def _beat(self):
        if self._on:
            self._beats.append(time.perf_counter())

    def start(self):
        self._beats.clear()
        self._harness.clear()
        self._t0 = time.perf_counter()
        self._on = True

    def mark_harness(self, t0: float, t1: float) -> None:
        """标记一段「夹具自身耗时」的时间窗，统计时剔除。"""
        self._harness.append((t0, t1))

    def _overlaps_harness(self, a: float, b: float) -> bool:
        return any(not (b < h0 or a > h1) for h0, h1 in self._harness)

    def stop(self) -> dict:
        self._on = False
        b = self._beats
        raw = [(b[i + 1] - b[i]) * 1000 for i in range(len(b) - 1)]
        kept = [
            (raw[i], b[i], b[i + 1])
            for i in range(len(raw))
            if not self._overlaps_harness(b[i], b[i + 1])
        ]
        gaps = [g for g, _, _ in kept]
        out = stats(gaps)
        out["raw_max"] = round(max(raw), 2) if raw else 0.0
        out["excluded"] = len(raw) - len(gaps)
        if kept:
            worst = max(range(len(kept)), key=lambda i: kept[i][0])
            out["worst_at_ms"] = round((kept[worst][1] - self._t0) * 1000, 1)
            out["worst_ms"] = round(kept[worst][0], 1)
        return out


def main() -> int:
    rep = Report(
        "M1",
        "端到端闭环：选中文本 → Alt+Q → 流式回答 → Esc 还原焦点",
        "P1 全部零件串起来后，M1 链路可跑通且主线程不阻塞",
        "全链路各环节均通过 → PASS",
    )

    app = QApplication.instance() or QApplication([])
    guard = ForegroundGuard()
    hb = Heartbeat(app)

    # ---------- 1. 宿主装配 ----------
    host = Host()
    host.hotkeys = HotkeyService()
    host.hotkeys.install(app)
    host.plugin_manager = PluginManager(app=host)
    host.plugin_manager.discover_and_load()

    plugins = host.plugin_manager.get_all_plugins()
    rep.metric("已加载插件", sorted(plugins.keys()))
    rep.check("ai_assistant 插件已加载（验证 T1 包加载）",
              "ai_assistant" in plugins)

    plugin = plugins.get("ai_assistant")
    if plugin is None:
        rep.finish("FAIL")
        return 1

    # ---------- 2. on_ui_ready（T3）----------
    plugin.on_ui_ready(host)
    rep.check("AI 面板已预热", plugin._panel is not None)
    rep.check("会话管理器已构建", plugin._manager is not None)

    registered = []
    for combo, cb in plugin.register_hotkeys():
        ok = host.hotkeys.register(combo, cb)
        registered.append((combo, ok))
    rep.metric("热键注册结果", registered)
    rep.check("三组热键全部注册成功",
              len(registered) == 3 and all(ok for _, ok in registered))

    # 注入假 provider，避免真实网络调用
    plugin._manager.configure(provider=FakeProvider())
    rep.check("已注入假 Provider", isinstance(plugin._manager.provider, FakeProvider))

    # 标记「取选中文本」这段设计内等待（详见 m2_verify.py 的同类注释）：
    # 内部有刻意的 ~250ms 等待，等目标应用把 Ctrl+C 落进剪贴板（ADR-5）。
    # 这是设计内的等待，不是应用在忙，故从「主线程是否被意外阻塞」统计中剔除。
    # 面板在此之前已经显示（公理 A2），用户感知不受影响。
    sel_cost = {}
    _sel_orig = plugin._selection.get_selected

    def _timed_get_selected(timeout_ms: int = 250) -> str:
        t0 = time.perf_counter()
        try:
            return _sel_orig(timeout_ms)
        finally:
            t1 = time.perf_counter()
            hb.mark_harness(t0, t1)
            sel_cost["ms"] = round((t1 - t0) * 1000, 1)

    plugin._selection.get_selected = _timed_get_selected

    # ---------- 3. 目标窗口（模拟「用户正在别的应用里选中文字」）----------
    target = QTextEdit()
    target.setWindowTitle("M1 — 模拟原应用")
    target.resize(420, 180)
    target.setPlainText(TARGET_TEXT)
    target.show()
    target.raise_()
    pump(400)

    hwnd_target = int(target.winId())
    # 用 ForegroundGuard 强制抢前台（Windows 前台锁会让 activateWindow 静默失败，
    # 表现为间歇性取不到选中文本）
    ok_fg = force_foreground(guard, hwnd_target, pump)
    target.setFocus()
    target.selectAll()
    pump(200)

    rep.metric("目标窗口句柄", hex(hwnd_target))
    rep.check("目标窗口持有焦点", ok_fg and guard.current() == hwnd_target,
              f"fg={hex(guard.current())} 期望={hex(hwnd_target)}")

    # ---------- 4. 合成 Alt+Q ----------
    panel = plugin._panel
    hb.start()
    press_cost = press_hotkey_timed(hb, "alt+q")
    pump(1400)          # 等：热键 → 面板显示 → 采集选中文本 → 激活
    gaps_1 = hb.stop()
    rep.metric("取选中文本耗时（设计内等待，已剔除）", sel_cost.get("ms"), " ms")
    rep.metric("合成按键耗时（夹具，已剔除）", press_cost, " ms")
    rep.metric("[唤起] 最大心跳间隔", gaps_1["max"], " ms")
    rep.metric("[唤起] 剔除前原始最大间隔", gaps_1.get("raw_max"), " ms")
    rep.metric("[唤起] 最大间隔出现位置", gaps_1.get("worst_at_ms"), " ms（自唤起起算）")

    rep.check("面板已可见", panel.isVisible())
    got = panel.input_text()
    rep.metric("输入框内容", repr(got))
    rep.check("选中文本已填入输入框（验证 S2 采集链路）", got == TARGET_TEXT, repr(got))

    # ---------- 5. 提交并等待流式 ----------
    hb.start()
    t_c = time.perf_counter()
    panel._on_submit()
    t_d = time.perf_counter()
    rep.metric("提交调用耗时（主线程同步部分）", round((t_d - t_c) * 1000, 1), " ms")
    pump(1800)
    gaps_2 = hb.stop()
    rep.metric("[流式] 最大心跳间隔", gaps_2["max"], " ms")
    rep.metric("[流式] 最大间隔出现位置", gaps_2.get("worst_at_ms"), " ms（自提交起算）")

    rendered = panel._output.content()
    rep.metric("面板渲染内容", repr(rendered))
    rep.check("流式回答已渲染",
              "".join(FAKE_TOKENS) in rendered, repr(rendered))

    worst = max(gaps_1["max"], gaps_2["max"])
    rep.metric("两阶段最大心跳间隔", worst, " ms")
    rep.check("[唤起] 主线程未阻塞（≤60ms）", gaps_1["max"] <= 60, f"{gaps_1['max']} ms")
    rep.check("[流式] 主线程未阻塞（≤60ms）", gaps_2["max"] <= 60, f"{gaps_2['max']} ms")

    # ---------- 6. Esc 关闭并还原焦点 ----------
    panel._on_close()
    pump(600)

    rep.check("面板已隐藏", not panel.isVisible())
    rep.check("焦点已还原到目标窗口（验证 S3 链路）",
              guard.current() == hwnd_target,
              f"fg={hex(guard.current())} 期望={hex(hwnd_target)}")

    # ---------- 7. 桌宠隐藏时功能不受影响（公理 A1 判据）----------
    rep.note("本验证全程未创建桌宠窗口，功能链路完整 —— 满足公理 A1 判据")

    target.close()

    ok = all(c["ok"] for c in rep.checks if c["ok"] is not None)
    rep.finish("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
