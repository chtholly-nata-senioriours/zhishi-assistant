#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""M3 端到端验证 —— 设置 UI 热切换（不需要真实 API）

前面 M1 / M2 验证的是「唤起 → 问答 / 翻译 / 截图」。本脚本验证的是**配置本身**：
在程序里改服务商 / 模型 / Key 并保存后，AI 请求是不是真的换了目的地。

为什么用两个本地假服务
    「配置里的字符串变了」和「配置生效了」是两回事。
    只断言 `config.get("ai.model")` 变了毫无意义 —— 必须证明
    **请求真的打到了新地址**。所以起两个假服务 A / B，
    切换配置后确认 B 收到请求、A 不再收到。

覆盖点：
    入口        面板齿轮按钮存在且发 settings_requested
    单例        重复打开设置不会建出第二个窗口
    测试连接    走真实网络链路（打到本地假服务），结果回写状态区
    落盘        保存后配置写入 user_config.json
    热切换      SessionManager 被重建，新配置立刻生效
    真的生效    切换后发起的问答打到新服务

用法
    python dev_bootstrap.py spikes/m3_verify.py

⚠ 本脚本会**临时改写** `~/.pet_demo/user_config.json`，结束时自动还原
  （即使中途异常，finally 也会还原）。
"""
from __future__ import annotations

import json
import pathlib
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from _common import Report, bootstrap, stats

bootstrap()

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from engine.ai import get_preset  # noqa: E402
from extensions.plugin_manager import PluginManager  # noqa: E402
from native.hotkey import HotkeyService  # noqa: E402

USER_CONFIG = pathlib.Path.home() / ".pet_demo" / "user_config.json"


# ================================================================ 假服务


class FakeAPI:
    """极简 OpenAI 兼容服务：`/models` + `/chat/completions`(SSE)，并记录收到的请求。"""

    def __init__(self, tag: str, models: list[str], reply: str):
        self.tag = tag
        self.models = models
        self.reply = reply
        self.chat_requests: list[dict] = []
        self.model_queries = 0
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._make_handler())
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def stop(self) -> None:
        try:
            self.httpd.shutdown()
        except Exception:
            pass

    def _make_handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.endswith("/models"):
                    outer.model_queries += 1
                    body = json.dumps(
                        {"data": [{"id": m} for m in outer.models]}
                    ).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    payload = json.loads(raw or b"{}")
                except ValueError:
                    payload = {}
                outer.chat_requests.append({
                    "path": self.path,
                    "model": payload.get("model"),
                    "stream": payload.get("stream"),
                })
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for tok in outer.reply:
                    chunk = json.dumps({"choices": [{"delta": {"content": tok}}]})
                    self.wfile.write(f"data: {chunk}\n\n".encode())
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

            def log_message(self, *args):    # 静音
                pass

        return Handler


# ================================================================ 宿主


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


def wait_until(predicate, app, timeout: float = 10.0) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


# ================================================================ 主流程


def main() -> int:
    rep = Report(
        "M3",
        "设置 UI 热切换端到端验证",
        "在程序内改配置并保存后，AI 请求真的换到新地址（无需重启）",
        "保存后 SessionManager 重建；切换后请求打到新服务；主线程不阻塞",
    )

    backup = USER_CONFIG.read_text(encoding="utf-8") if USER_CONFIG.exists() else None

    srv_a = FakeAPI("A", ["model-A", "model-A-vl"], reply="FROM-A")
    srv_b = FakeAPI("B", ["model-B", "model-B-vl"], reply="FROM-B")
    rep.metric("假服务 A", srv_a.base_url)
    rep.metric("假服务 B", srv_b.base_url)

    app = QApplication.instance() or QApplication([])

    try:
        # ---------- 1. 起插件，初始配置指向 A ----------
        host = Host()
        host.config.set("ai.enabled", True)
        host.config.set("ai.base_url", srv_a.base_url)
        host.config.set("ai.model", "model-A")
        host.config.set("ai.vision_model", "model-A-vl")
        host.config.set("ai.api_key", "test-key")
        host.config.set("ai.request_timeout", 30)

        host.hotkeys = HotkeyService()
        host.hotkeys.install(app)
        host.plugin_manager = PluginManager(app=host)
        host.plugin_manager.discover_and_load()
        plugins = host.plugin_manager.get_all_plugins()
        if "ai_assistant" not in plugins:
            rep.check("ai_assistant 插件已加载", False, f"实际: {list(plugins)}")
            rep.finish("FAIL")
            return 1
        plugin = plugins["ai_assistant"]
        plugin.on_ui_ready(host)
        pump(200)

        rep.check("ai_assistant 插件已加载并完成 on_ui_ready", True)
        rep.check("初始 SessionManager 指向假服务 A",
                  plugin._manager is not None
                  and plugin._manager.provider.base_url == srv_a.base_url,
                  f"base_url={getattr(plugin._manager.provider, 'base_url', None)}")
        rep.check("初始 model = model-A",
                  plugin._manager is not None and plugin._manager.model == "model-A",
                  f"model={getattr(plugin._manager, 'model', None)}")

        # ---------- 2. 面板入口 ----------
        panel = plugin._panel
        rep.check("面板已预热", panel is not None)
        has_gear = hasattr(panel, "_btn_settings") and panel._btn_settings is not None
        rep.check("面板存在设置（齿轮）按钮", has_gear,
                  panel._btn_settings.text() if has_gear else "")

        fired = []
        panel.settings_requested.connect(lambda: fired.append(1))
        panel._btn_settings.click()
        pump(60)
        rep.check("点击齿轮发出 settings_requested 信号", len(fired) == 1,
                  f"信号次数={len(fired)}")
        rep.check("点齿轮后面板自动钉住（不会被对话框挤关）", panel._pinned is True)

        # 托盘兜底入口：热键/面板都不可用时也能改配置
        menu = plugin.get_menu_actions()
        labels = [a.name for a in menu]
        rep.check("托盘菜单含 3 个模式 + 1 个设置入口", len(menu) == 4, str(labels))
        rep.check("托盘菜单含「AI 服务设置…」",
                  any("设置" in n for n in labels), str(labels))

        # 上一步已经真正打开了对话框（信号连到 plugin._open_settings）
        dlg = plugin._settings_dlg
        rep.check("设置对话框已打开", dlg is not None)

        # ---------- 3. 单例 ----------
        plugin._open_settings()
        pump(40)
        rep.check("重复打开不会建第二个窗口（单例）",
                  plugin._settings_dlg is dlg)

        if dlg is None:
            rep.finish("FAIL")
            return 1

        rep.check("对话框回填了当前配置",
                  dlg._base_url_edit.text() == srv_a.base_url
                  and dlg._model_combo.currentText() == "model-A",
                  f"{dlg._base_url_edit.text()} / {dlg._model_combo.currentText()}")

        # ---------- 4. 测试连接（打到 B，验证异步链路）----------
        before_b_models = srv_b.model_queries
        dlg._base_url_edit.setText(srv_b.base_url)
        dlg._model_combo.setCurrentText("model-B")
        dlg._vision_combo.setCurrentText("model-B-vl")

        t0 = time.perf_counter()
        dlg._on_test()
        call_cost = (time.perf_counter() - t0) * 1000
        rep.metric("测试连接调用耗时（主线程同步部分）", round(call_cost, 1), " ms")
        rep.check("测试连接不阻塞主线程（≤20ms）", call_cost <= 20, f"{call_cost:.1f} ms")

        ok = wait_until(lambda: not dlg._testing, app, timeout=20)
        rep.check("测试连接在超时内完成", ok)
        rep.check("测试连接真的打到了假服务 B",
                  srv_b.model_queries > before_b_models,
                  f"/models 请求数 {before_b_models} → {srv_b.model_queries}")
        rep.check("测试结果为成功（状态区显示连接正常）",
                  "连接正常" in dlg._status.text(),
                  dlg._status.text().splitlines()[0] if dlg._status.text() else "")
        rep.check("真实模型列表已灌入候选（替换硬编码）",
                  "model-B" in [dlg._model_combo.itemText(i)
                                for i in range(dlg._model_combo.count())],
                  str([dlg._model_combo.itemText(i)
                       for i in range(dlg._model_combo.count())]))

        # ---------- 5. 保存 → 热切换 ----------
        a_req_before = len(srv_a.chat_requests)
        dlg._save()
        pump(120)

        rep.check("配置已写入 user_config.json",
                  "model-B" in USER_CONFIG.read_text(encoding="utf-8"))
        rep.check("SessionManager 已重建并指向假服务 B",
                  plugin._manager is not None
                  and plugin._manager.provider.base_url == srv_b.base_url,
                  f"base_url={getattr(plugin._manager.provider, 'base_url', None)}")
        rep.check("新模型已生效（model = model-B）",
                  plugin._manager is not None and plugin._manager.model == "model-B",
                  f"model={getattr(plugin._manager, 'model', None)}")
        rep.check("视觉模型已生效（vision = model-B-vl）",
                  plugin._manager is not None
                  and plugin._manager.vision_model == "model-B-vl",
                  f"vision={getattr(plugin._manager, 'vision_model', None)}")
        rep.check("保存后对话框已关闭", plugin._settings_dlg is None)

        # ---------- 6. 切换后的请求真的打到 B ----------
        done: list[str] = []
        plugin._manager.done.connect(lambda sid, full: done.append(full))
        b_req_before = len(srv_b.chat_requests)
        plugin._manager.ask("ping", preset=get_preset("ask"), persist=False)

        ok = wait_until(lambda: bool(done), app, timeout=15)
        rep.check("切换后问答正常返回", ok, repr(done[:1]))
        rep.check("回答来自假服务 B（内容 FROM-B）",
                  bool(done) and done[0] == "FROM-B", repr(done[:1]))
        rep.check("请求真的打到了 B",
                  len(srv_b.chat_requests) > b_req_before,
                  f"B 收到 {b_req_before} → {len(srv_b.chat_requests)}")
        rep.check("请求没有再打到 A（旧地址已弃用）",
                  len(srv_a.chat_requests) == a_req_before,
                  f"A 收到 {a_req_before} → {len(srv_a.chat_requests)}")
        if srv_b.chat_requests:
            last = srv_b.chat_requests[-1]
            rep.metric("B 收到的请求", f"model={last['model']} stream={last['stream']}")
            rep.check("请求体带的是新模型名", last["model"] == "model-B",
                      str(last["model"]))

        # ---------- 7. 再切回 A，确认可反复切换 ----------
        plugin._open_settings()
        dlg2 = plugin._settings_dlg
        rep.check("可以再次打开设置（单例已释放）", dlg2 is not None and dlg2 is not dlg)
        if dlg2 is not None:
            dlg2._base_url_edit.setText(srv_a.base_url)
            dlg2._model_combo.setCurrentText("model-A")
            dlg2._vision_combo.setCurrentText("model-A-vl")
            dlg2._save()
            pump(120)
            rep.check("切回 A 后 base_url 回到 A",
                      plugin._manager.provider.base_url == srv_a.base_url,
                      f"base_url={plugin._manager.provider.base_url}")

            a_before2 = len(srv_a.chat_requests)
            done.clear()
            plugin._manager.done.connect(lambda sid, full: done.append(full))
            plugin._manager.ask("ping", preset=get_preset("ask"), persist=False)
            wait_until(lambda: bool(done), app, timeout=15)
            rep.check("切回后请求打到 A（可反复热切换）",
                      len(srv_a.chat_requests) > a_before2,
                      f"A 收到 {a_before2} → {len(srv_a.chat_requests)}")

        # ---------- 8. 主线程心跳 ----------
        beats: list[float] = []
        tm = QTimer()
        tm.setInterval(16)
        tm.timeout.connect(lambda: beats.append(time.perf_counter()))
        tm.start()
        plugin._open_settings()
        dlg3 = plugin._settings_dlg
        if dlg3 is not None:
            dlg3._base_url_edit.setText(srv_b.base_url)
            dlg3._on_test()
            wait_until(lambda: not dlg3._testing, app, timeout=20)
            dlg3.reject()
        pump(120)
        tm.stop()
        gaps = [(beats[i + 1] - beats[i]) * 1000 for i in range(len(beats) - 1)]
        g = stats(gaps)
        rep.metric("主线程最大心跳间隔", g["max"], " ms")
        rep.check("全程主线程未阻塞（≤120ms）", g["max"] <= 120, f"{g['max']} ms")

        plugin.on_unload()

    finally:
        # 还原用户配置 —— 脚本改了别人的真实配置，必须还回去
        if backup is not None:
            USER_CONFIG.write_text(backup, encoding="utf-8")
            rep.note("已还原 ~/.pet_demo/user_config.json")
        srv_a.stop()
        srv_b.stop()

    failed = [c for c in rep.checks if c["ok"] is False]
    rep.finish("PASS" if not failed else "FAIL")
    return 0 if not failed else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
