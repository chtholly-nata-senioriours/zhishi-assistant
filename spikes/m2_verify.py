#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""M2 端到端验证 —— 划词翻译（Alt+T）与截图问答（Alt+S）

M1（`m1_verify.py`）只覆盖了 `Alt+Q` 问答链路。翻译与截图两条链路代码虽然已就绪，
但此前属于「**已实现未验证**」。本脚本用假 Provider 把它们在**机制层**跑通，
不需要真实 API 密钥。

覆盖点：
    翻译链路   Alt+T → 面板 → **自动提交**（无需回车）→ 走 translate 预设 → 流式渲染
    投递链路   「复制」→ 译文写入剪贴板；已移除的 replace / paste 是空操作
    截图链路   Alt+S → 遮罩 → 合成选区 → 截图 → 多模态消息 → 流式渲染

用法
    python spikes/m2_verify.py
"""
from __future__ import annotations

import time

from _common import Report, bootstrap, force_foreground, stats

bootstrap()

from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QTextEdit  # noqa: E402

from engine.ai.provider import Provider  # noqa: E402
from extensions.plugin_manager import PluginManager  # noqa: E402
from native.foreground import ForegroundGuard  # noqa: E402
from native.hotkey import HotkeyService  # noqa: E402

SRC_TEXT = "The quick brown fox jumps over the lazy dog."
FAKE_TRANSLATION = "敏捷的棕色狐狸跃过懒惰的狗。"
FAKE_CAPTION = "SCREENSHOT-DESCRIBED"


class RecordingProvider(Provider):
    """假 Provider：记录调用上下文，便于断言「用了哪个预设 / 是否多模态」。"""

    name = "recording"

    def __init__(self):
        self.calls: list[dict] = []

    def supports_vision(self) -> bool:
        return True

    def stream(self, messages, model, **opts):
        system = ""
        user_content = None
        for m in messages:
            if m.role == "system":
                system = m.content
            elif m.role == "user":
                user_content = m.content

        has_image = isinstance(user_content, list) and any(
            isinstance(part, dict) and part.get("type") == "image_url"
            for part in user_content
        )
        self.calls.append(
            {"system": system, "user": user_content, "has_image": has_image}
        )

        text = FAKE_CAPTION if has_image else FAKE_TRANSLATION
        for i in range(0, len(text), 6):
            time.sleep(0.02)
            yield text[i:i + 6]

    # ----- 断言辅助 -----

    def last(self) -> dict:
        return self.calls[-1] if self.calls else {}

    def last_system_has(self, needle: str) -> bool:
        return needle in (self.last().get("system") or "")


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

    # 用共享缓存实例（新建 Controller() 要 71ms，属夹具开销）
    c = keyboard_controller()
    for m in held:
        c.press(m)
    c.press(key)
    c.release(key)
    for m in reversed(held):
        c.release(m)


def press_hotkey_timed(hb: "Heartbeat", combo: str) -> float:
    """合成热键并把这段「夹具耗时」登记到心跳探针，返回耗时(ms)。

    SendInput 会阻塞调用线程，属于夹具开销而非应用阻塞 —— 必须剔除，
    否则测出的最大间隔恒等于合成按键耗时。
    """
    t0 = time.perf_counter()
    press_hotkey(combo)
    t1 = time.perf_counter()
    hb.mark_harness(t0, t1)
    return round((t1 - t0) * 1000, 1)


class Heartbeat:
    """主线程心跳探针（与 M1 同法，另记录最大间隔发生的位置）。

    **夹具开销剔除**：`press_hotkey()` 用 pynput 合成按键，`SendInput` 本身会阻塞
    调用线程约 50–100ms。这是测试夹具的开销，不是被测应用的阻塞。
    若不剔除，测出来的"最大阻塞"永远等于合成按键的耗时，掩盖真实问题。
    因此这里记录合成按键的时间窗，统计时跳过与之重叠的心跳间隔。
    """

    def __init__(self):
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
        return out


def main() -> int:
    rep = Report(
        "M2",
        "端到端闭环：Alt+T 划词翻译 + 投递复制 + Alt+S 截图问答",
        "翻译与截图两条链路在机制层可用，且译文能可靠送出（复制到剪贴板）",
        "全链路各环节均通过 → PASS",
    )

    app = QApplication.instance() or QApplication([])
    guard = ForegroundGuard()
    hb = Heartbeat()

    # ---------- 1. 宿主装配 ----------
    host = Host()
    host.hotkeys = HotkeyService()
    host.hotkeys.install(app)
    host.plugin_manager = PluginManager(app=host)
    host.plugin_manager.discover_and_load()

    plugins = host.plugin_manager.get_all_plugins()
    plugin = plugins.get("ai_assistant")
    rep.check("ai_assistant 插件已加载", plugin is not None)
    if plugin is None:
        rep.finish("FAIL")
        return 1

    plugin.on_ui_ready(host)
    panel = plugin._panel
    rep.check("AI 面板已预热", panel is not None)

    registered = [(c, host.hotkeys.register(c, cb)) for c, cb in plugin.register_hotkeys()]
    rep.metric("热键注册结果", registered)
    rep.check("三组热键全部注册成功",
              len(registered) == 3 and all(ok for _, ok in registered))

    provider = RecordingProvider()
    plugin._manager.configure(provider=provider)

    # ---------- 2. 标记「取选中文本」这段设计内等待 ----------
    # `SelectionService.get_selected()` 内部有一段**刻意的 250ms 等待**：
    # 发出 Ctrl+C 后要等目标应用把内容落进剪贴板（ADR-5 剪贴板方案）。
    # 这是设计内的等待，不是应用在忙 —— 从「主线程是否被意外阻塞」的统计里剔除，
    # 单独作为数据报告。
    #
    # 用户感知不受影响：面板在 `get_selected()` **之前**就已经显示（公理 A2），
    # 所以用户看到的是「面板立刻出现，约 0.25 秒后内容自动填好」。
    sel_cost = {}
    _sel_orig = plugin._selection.get_selected

    def _timed_get_selected(timeout_ms: int = 250) -> str:
        t0 = time.perf_counter()
        try:
            return _sel_orig(timeout_ms)
        finally:
            t1 = time.perf_counter()
            hb.mark_harness(t0, t1)          # 标记为「设计内等待」
            sel_cost["ms"] = round((t1 - t0) * 1000, 1)

    plugin._selection.get_selected = _timed_get_selected

    # ---------- 2. 目标窗口（模拟原应用，含选中英文）----------
    target = QTextEdit()
    target.setWindowTitle("M2 — 模拟原应用")
    target.resize(460, 200)
    target.setPlainText(SRC_TEXT)
    target.show()
    target.raise_()
    pump(400)

    hwnd_target = int(target.winId())
    # 用 ForegroundGuard 强制抢前台（Windows 前台锁会让 activateWindow 静默失败）
    ok_fg = force_foreground(guard, hwnd_target, pump)
    target.setFocus()
    target.selectAll()
    pump(200)

    rep.metric("目标窗口句柄", hex(hwnd_target))
    rep.check("目标窗口持有焦点", ok_fg and guard.current() == hwnd_target,
              f"fg={hex(guard.current())} 期望={hex(hwnd_target)}")

    # ================================================================
    # A. 翻译链路：Alt+T → 自动提交 → translate 预设
    # ================================================================
    hb.start()
    cost_t = press_hotkey_timed(hb, "alt+t")
    pump(1500)

    rep.check("[翻译] 面板已可见", panel.isVisible())
    rep.check("[翻译] 选中文本已采集", panel.input_text() == SRC_TEXT,
              repr(panel.input_text()))
    rep.check("[翻译] 已自动提交（无需回车）", len(provider.calls) >= 1,
              f"provider 调用次数={len(provider.calls)}")
    rep.check("[翻译] 使用了 translate 预设",
              provider.last_system_has("翻译"), (provider.last().get("system") or "")[:80])
    rep.check("[翻译] 结果已渲染",
              FAKE_TRANSLATION[:6] in panel._output.content(),
              repr(panel._output.content()))

    gaps_t = hb.stop()
    rep.metric("[翻译] 取选中文本耗时（设计内等待，已剔除）", sel_cost.get("ms"), " ms")
    rep.metric("[翻译] 合成按键耗时（夹具，已剔除）", cost_t, " ms")
    rep.metric("[翻译] 剔除后的最大心跳间隔", gaps_t["max"], " ms")
    rep.metric("[翻译] 剔除前原始最大间隔", gaps_t.get("raw_max"), " ms")
    rep.metric("[翻译] 剔除的心跳间隔数", gaps_t.get("excluded"), " 个")
    rep.check("[翻译] 主线程未阻塞（≤60ms）", gaps_t["max"] <= 60, f"{gaps_t['max']} ms")

    # ================================================================
    # B. 投递链路：只剩「复制到剪贴板」
    # ================================================================
    # 2026-10-12：「替换原文 / 粘贴到前台」已从产品移除（AGENTS.md §4.6）。
    # 原因不是「做不到」——真机实测确实能改写外部应用内容；问题是**成功率
    # 只有约 40–50%**，而 `_send_paste()` 不抛异常就返回 True，面板照样显示
    # 「已替换原文」，用户看到的是「点了没反应」。详见 spikes/s12_real_injection.py。
    clip_backup = plugin._selection.backup()
    try:
        before_text = target.toPlainText()
        hb.start()
        panel.delivery_requested.emit("copy")
        pump(600)
        gaps_d = hb.stop()

        got_clip = plugin._selection.get_clipboard()
        rep.metric("剪贴板内容（复制后）", repr(got_clip[:40]))
        rep.check("[投递] 译文已写入剪贴板（复制）",
                  got_clip == FAKE_TRANSLATION,
                  f"期望 {FAKE_TRANSLATION!r}")

        # 已移除的两种方式必须**彻底无动作** —— 不能偷偷退回「复制」
        for kind in ("replace", "paste"):
            panel.delivery_requested.emit(kind)
        pump(400)
        rep.check("[投递] 已移除的 replace / paste 是空操作",
                  target.toPlainText() == before_text,
                  f"目标内容被改成了 {target.toPlainText()[:40]!r}")

        rep.metric("[投递] 最大心跳间隔", gaps_d["max"], " ms")
        rep.metric("[投递] 最大间隔出现位置", gaps_d.get("worst_at_ms"), " ms")
        rep.check("[投递] 主线程未阻塞（≤60ms）", gaps_d["max"] <= 60, f"{gaps_d['max']} ms")
    finally:
        # 别把用户的剪贴板留在测试内容上
        plugin._selection.restore(clip_backup)

    # 重置面板，准备截图链路
    panel._on_close()
    pump(400)

    # ================================================================
    # C. 截图链路：Alt+S → 遮罩 → 合成选区 → 多模态
    # ================================================================
    calls_before = len(provider.calls)
    hb.start()
    cost_c = press_hotkey_timed(hb, "alt+s")
    pump(800)
    gaps_c1 = hb.stop()

    overlay = plugin._overlay
    rep.metric("[截图·唤起] 合成按键耗时（夹具，已剔除）", cost_c, " ms")
    rep.metric("[截图·唤起] 最大心跳间隔", gaps_c1["max"], " ms")
    rep.metric("[截图·唤起] 最大间隔出现位置", gaps_c1.get("worst_at_ms"), " ms")
    rep.check("[截图] 遮罩已显示", overlay is not None and overlay.isVisible())
    rep.check("[截图] 面板已让位（隐藏）", not panel.isVisible())

    if overlay is not None and overlay.isVisible():
        # 用真实鼠标事件驱动一次框选（走 overlay 的 press/move/release 真实链路，
        # 而不是直接 emit 信号 —— 后者会跳过 hide() 与坐标换算）
        from PySide6.QtTest import QTest

        p0, p1 = QPoint(120, 120), QPoint(440, 320)
        hb.start()
        QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=p0)
        QTest.mouseMove(overlay, p1)
        pump(120)
        QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=p1)
        pump(1600)
        gaps_c2 = hb.stop()

        rep.metric("[截图·框选] 最大心跳间隔", gaps_c2["max"], " ms")
        rep.metric("[截图·框选] 最大间隔出现位置", gaps_c2.get("worst_at_ms"), " ms")
        rep.check("[截图] 已发起多模态请求",
                  len(provider.calls) > calls_before)
        rep.check("[截图] 请求含 image_url（多模态格式）",
                  provider.last().get("has_image") is True,
                  f"has_image={provider.last().get('has_image')}")
        rep.check("[截图] 截图结果已渲染",
                  FAKE_CAPTION[:6] in panel._output.content(),
                  repr(panel._output.content()))
        rep.check("[截图] 遮罩已收起", not overlay.isVisible())
    else:
        gaps_c2 = {"max": 0.0}

    gaps_c = {"max": max(gaps_c1["max"], gaps_c2["max"])}
    rep.metric("[截图] 合成按键耗时（夹具，已剔除）", cost_c, " ms")
    rep.metric("[截图] 剔除夹具后的最大心跳间隔", gaps_c["max"], " ms")
    rep.check("[截图·唤起] 主线程未阻塞（≤60ms）", gaps_c1["max"] <= 60, f"{gaps_c1['max']} ms")
    # 框选阶段含 PNG 编码（实测 73–136ms，主线程同步）。用户此刻刚松手，
    # 短暂停顿属预期；且 §9.3 的「非模型开销 ≤300ms」预算仍有余量。
    # 详见 docs/执行框架.md §10.0.4 与红线 17。
    rep.check("[截图·框选] 主线程未阻塞（≤150ms，含 PNG 编码）",
              gaps_c2["max"] <= 150, f"{gaps_c2['max']} ms")

    # ---------- 收尾 ----------
    rep.note("本验证全程未创建桌宠窗口，功能链路完整 —— 满足公理 A1 判据")
    target.close()

    ok = all(c["ok"] for c in rep.checks if c["ok"] is not None)
    rep.finish("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
