# -*- coding: utf-8 -*-
"""AI 助手插件 —— 把 L1(native) / L2(engine.ai) / L3(ai_panel) 组装成完整功能。

唤起时序（执行框架 §8.2，公理 A2「感知延迟即产品」）
    1. 快照前台窗口
    2. **以非激活方式**显示面板 —— 用户立刻看到「它来了」
    3. 采集选中文本（此时原应用仍持有焦点，Ctrl+C 才取得到东西）
    4. 采集完成后才激活面板、聚焦输入框
    Esc/关闭 → 隐藏面板 → 还原前台焦点

若把 2 和 4 合并（一上来就抢焦点），Ctrl+C 会复制到面板自己的输入框，
取选中文本必然失败 —— 这是本插件最容易写错的地方。
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from event_bus import event_bus
from extensions.base_plugin import BasePlugin, MenuAction
from data.log_manager import log_manager

from engine.ai import ChatMessage, DeliveryKind, build_from_config, get_preset, shared_store

from native.capture import CaptureService
from native.foreground import ForegroundGuard
from native.selection import SelectionService, warmup_clipboard, warmup_keyboard

from presentation.ai_panel import AIPanel
from presentation.overlay_select import OverlaySelect

from .modes import MODES, SRC_SCREENSHOT, SRC_SELECTION, get_mode


class AIAssistantPlugin(BasePlugin):
    """AI 助手。"""

    def __init__(self):
        super().__init__()
        self._panel: AIPanel | None = None
        self._overlay: OverlaySelect | None = None
        self._manager = None
        # 借用的**共享** Store（见 engine.ai.store.shared_store）—— 本插件
        # 不负责关闭它，控制中心要读同一份会话 / 预设数据。
        self._store = None
        self._foreground = ForegroundGuard()
        self._selection = SelectionService()
        self._capture = CaptureService()

        self._active_sid: str | None = None
        self._last_result: str = ""
        #: 本次唤起采集到的选区文本 —— 只用于日志与提示。
        #: （2026-10-12 之前它还决定「粘贴到前台」要不要先取消选区；
        #:  投递到前台已移除，见 `AGENTS.md` §4.6。）
        self._context_text: str = ""
        #: 对话上下文（「继续对话」用）。
        #:   `_history` 累积本会话已发生的问答，逐轮送进模型当上下文；
        #:   `_active_session_id` 非空 = **续接**已有会话，落库走 append 而非新建。
        #: 热键唤起是全新会话，两者都会被重置（见 invoke）。
        self._history: list[ChatMessage] = []
        self._active_session_id: str | None = None
        self._restore_hwnd: int = 0
        self._config_sig: tuple = ()
        self._settings_dlg = None

    # ================================================== 生命周期

    def on_load(self, app) -> bool:
        log_manager.info("AI 助手插件已加载")
        return True

    def on_ui_ready(self, app) -> None:
        """UI 就绪：预热面板 + 构建 AI 会话管理器。"""
        if not app.config.get("ai.enabled", True):
            log_manager.info("AI 助手已在配置中禁用")
            return

        # --- 面板预热（必须在热键回调之前完成）---
        self._panel = AIPanel()
        self._panel.submitted.connect(self._on_submit)
        self._panel.cancelled.connect(self._on_cancelled)
        self._panel.delivery_requested.connect(self._on_delivery)
        self._panel.settings_requested.connect(self._open_settings)
        self._panel.warm_up()

        self._overlay = OverlaySelect()
        self._overlay.selected.connect(self._on_region_selected)
        self._overlay.cancelled.connect(self._on_capture_cancelled)
        # 遮罩同样必须预热：它是全屏自绘窗口，首次绘制代价高。
        # 不预热时 Alt+S 会稳定阻塞主线程约 100ms（M2 实测）。
        self._overlay.warm_up()

        # --- 预热键盘控制器与剪贴板 ---
        # 两者都有**一次性**冷启动开销，必须挪出用户的首次感知路径：
        #   pynput Controller() 构造 ≈ 71ms（实测）
        #   首次访问剪贴板        ≈ 88ms（实测，跨进程格式枚举）
        # 不预热的话，用户第一次按热键会看到「面板出来了但卡住约 0.1 秒」。
        if warmup_keyboard():
            log_manager.info("键盘控制器已预热")
        if warmup_clipboard():
            log_manager.info("剪贴板已预热")

        self._ensure_manager(force=True)
        log_manager.info("AI 面板已预热")

    def on_unload(self) -> None:
        if self._settings_dlg:
            self._settings_dlg.close()
            self._settings_dlg = None
        if self._panel:
            self._panel.close()
            self._panel = None
        if self._manager:
            self._manager.shutdown()
            self._manager = None
        # 共享 Store 由进程统一持有（退出时 `close_shared_store()`），
        # 这里只解除引用 —— 否则控制中心正在读的会话数据会被关掉。
        self._store = None

    def register_hotkeys(self):
        cfg = self.app.config if self.app else None
        if not cfg or not cfg.get("ai.enabled", True):
            return []
        bindings = []
        for mode in MODES.values():
            combo = (cfg.get(f"ai.{mode.hotkey_config_key}", "") or "").strip()
            if combo:
                bindings.append((combo, (lambda m=mode.id: self.invoke(m))))
        return bindings

    def get_menu_actions(self):
        """托盘 / 右键菜单入口 —— 热键失效时的兜底通道（风险 R1）。"""
        actions = []
        for mode in MODES.values():
            cfg = self.app.config if self.app else None
            combo = (cfg.get(f"ai.{mode.hotkey_config_key}", "") or "") if cfg else ""
            label = f"{mode.title}（{combo.upper()}）" if combo else mode.title
            actions.append(
                MenuAction(label, (lambda m=mode.id: self.invoke(m)), category="ai")
            )
        # 设置入口也放一份到托盘 —— 面板没唤起时也能改配置
        actions.append(MenuAction("AI 服务设置…", self._open_settings, category="ai"))
        return actions

    # ================================================== 唤起

    def invoke(self, mode_id: str) -> None:
        """唤起面板。热键回调 / 菜单回调都走这里。"""
        if self._panel is None:
            log_manager.warning("AI 面板尚未就绪")
            return

        mode = get_mode(mode_id)
        self._ensure_manager()
        # 有了这行，「按了没反应」才能区分是热键没到、还是选区为空。
        log_manager.info(f"唤起模式: {mode.id} ({mode.title})")

        # 每次唤起都重置选区记忆 —— 上一次的选区不该影响这一次的投递语义
        self._context_text = ""
        # 热键唤起 = 全新会话：清掉上一轮的上下文与续接目标。
        # （「继续对话」走 continue_session()，那条路径会主动填这两个字段。）
        self._history = []
        self._active_session_id = None

        # 1) 快照前台窗口，供关闭时还原焦点
        self._restore_hwnd = self._foreground.snapshot()

        event_bus.publish("HOTKEY_TRIGGERED", {"mode": mode_id})

        # 截图模式走独立遮罩流程
        if mode.input_source == SRC_SCREENSHOT:
            self._start_capture(mode_id)
            return

        # 2) 先以非激活方式显示 —— 原应用保持焦点
        self._panel.move_to_cursor_screen()
        self._panel.show_passive(mode_id)
        QApplication.processEvents()

        # 3) 采集选中文本（此时焦点还在原应用上）
        text = ""
        if mode.input_source == SRC_SELECTION:
            text = self._selection.get_selected()
            self._context_text = text
            if text:
                self._panel.set_context(text)
                self._panel.set_hint(f"已取到 {len(text)} 字")
                log_manager.info(f"选区采集成功: {len(text)} 字")
            else:
                self._panel.set_hint("未检测到选中文本")
                log_manager.warning(
                    f"选区采集为空（模式 {mode.id}）—— "
                    f"auto_submit={mode.auto_submit}，不会发起请求"
                )

        # 4) 采集完成，现在才抢焦点
        self._panel.activate_for_input()

        if mode.auto_submit and text:
            self._on_submit(text)

    # ================================================== 截图流程

    def _start_capture(self, mode_id: str) -> None:
        if self._panel:
            self._panel.hide()
        if self._overlay:
            self._overlay.start()

    def _on_capture_cancelled(self) -> None:
        self._restore_focus()

    def _on_region_selected(self, rect) -> None:
        pixmap = self._capture.grab_region(rect.x(), rect.y(), rect.width(), rect.height())
        if pixmap.isNull():
            log_manager.warning("截图失败（区域为空）")
            self._restore_focus()
            return
        data_url = self._capture.to_data_url(pixmap)
        self._panel.move_to_cursor_screen()
        self._panel.show_for_input("capture")
        self._submit_with_image(data_url)

    def _submit_with_image(self, data_url: str) -> None:
        if self._manager is None:
            return
        self._panel.begin_stream()
        self._active_sid = self._manager.ask(
            "请描述并解释这张截图的内容。",
            preset=get_preset("ask"),
            language=self._cfg("ai.default_language", "zh"),
            image_data_url=data_url,
        )
        # 记下 id，这样在面板里接着追问时能续上同一条会话
        self._active_session_id = self._active_sid

    # ================================================== 会话

    def _on_submit(self, text: str) -> None:
        if self._manager is None or not text:
            return
        mode = get_mode(self._panel._mode) if self._panel else get_mode("ask")
        self._panel.begin_stream()
        event_bus.publish("AI_REQUEST", {"mode": mode.id, "chars": len(text)})
        log_manager.info(
            f"发起请求: mode={mode.id} preset={mode.preset_id} chars={len(text)} "
            f"session={self._active_session_id or '(新)'} 上下文={len(self._history)} 条"
        )

        # 顺序要紧：先把**之前**的历史取出来送进模型，再把这次的问题记进
        # 上下文。反过来的话当前问题会被重复送两遍。
        history = list(self._history) or None
        self._history.append(ChatMessage("user", text))

        self._active_sid = self._manager.ask(
            text,
            preset=get_preset(mode.preset_id),
            language=self._cfg("ai.default_language", "zh"),
            length=self._cfg("ai.response_length", "auto"),
            history=history,
            session_id=self._active_session_id,
        )
        # 新建会话时 manager 生成 id 并返回；续接时返回的还是原 id。
        # 两种情况都记下来，下一轮才续得上。
        self._active_session_id = self._active_sid

    def _on_chunk(self, sid: str, delta: str) -> None:
        if sid == self._active_sid and self._panel:
            self._panel.append_chunk(delta)

    def _on_done(self, sid: str, full: str) -> None:
        if sid != self._active_sid:
            return
        self._last_result = full
        if full:
            # 助手回复也要进上下文，否则多轮续接只有 user 侧
            self._history.append(ChatMessage("assistant", full))
        if self._panel:
            self._panel.set_result(full)
        event_bus.publish("AI_DONE", {"chars": len(full)})

    def _on_error(self, sid: str, message: str) -> None:
        if sid != self._active_sid:
            return
        if self._panel:
            self._panel.set_error(message)
        log_manager.error(f"AI 调用失败: {message}")
        event_bus.publish("AI_ERROR", {"message": message})

    def _on_cancelled(self) -> None:
        if self._manager and self._active_sid:
            self._manager.cancel(self._active_sid)
            event_bus.publish("AI_CANCEL", {"session": self._active_sid})
        self._restore_focus()

    # ================================================== 继续对话

    def continue_session(self, session_id: str, messages) -> bool:
        """把控制中心里选中的一条历史会话接过来继续问。

        由 `ControlCenter.continue_session()` 调用。两者之间**不做硬依赖** ——
        控制中心用鸭子类型（`hasattr(plugin, "continue_session")`），
        于是 AI 插件没加载时控制中心照常工作，只是给出提示。

        返回是否成功唤起：面板未就绪（插件被禁用 / UI 还没起）时返回 False，
        调用方据此给用户明确提示，而不是静默失败。
        """
        if self._panel is None or not session_id:
            return False
        self._ensure_manager()
        if self._manager is None:
            return False

        self._history = list(messages or [])
        self._active_session_id = session_id
        self._context_text = ""
        self._last_result = ""

        # 顺序要紧：show_mode() 内部会 clear_content()，历史必须填在**它之后**
        self._panel.move_to_cursor_screen()
        self._panel.show_mode("ask", activating=True)
        self._panel.load_history(self._history)
        log_manager.info(
            f"继续对话: session={session_id}，载入 {len(self._history)} 条历史"
        )
        return True

    # ================================================== 投递

    def _on_delivery(self, kind: str) -> None:
        """把结果送回用户手边。

        目前只剩一种方式：**复制到剪贴板** —— 写剪贴板，不碰前台应用。

        「替换原文 / 粘贴到前台」已于 2026-10-12 移除（见 `AGENTS.md` §4.6）。
        它们靠向外部应用注入 Ctrl+V：在受限会话 / 提权窗口 / 前台不是可粘贴
        控件时，系统会**静默丢弃**合成输入 —— 而 `_send_paste()` 不会抛异常、
        照样返回 True，于是面板会谎报「已替换原文」。一个会谎报成功、
        时灵时不灵的功能，不如不要。
        """
        if kind != DeliveryKind.COPY:
            return
        text = self._last_result or (self._panel._output.content() if self._panel else "")
        if not text:
            return
        self._selection.set_clipboard(text)
        if self._panel:
            self._panel.set_status("已复制到剪贴板")

    def _restore_focus(self) -> None:
        if self._restore_hwnd and self._foreground.available:
            self._foreground.restore(self._restore_hwnd)

    # ================================================== 设置（热切换）

    def _open_settings(self) -> None:
        """打开 AI 服务设置。单例：已打开则提到前面，不重复建窗。"""
        from presentation.ai_settings_dialog import AISettingsDialog

        if self._settings_dlg is not None:
            self._settings_dlg.raise_()
            self._settings_dlg.activateWindow()
            return

        dlg = AISettingsDialog(
            config=self.app.config if self.app else None,
            busy_check=self._is_streaming,
        )
        dlg.applied.connect(self._on_settings_applied)
        dlg.finished.connect(lambda _=0: self._forget_settings_dlg())
        self._settings_dlg = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _forget_settings_dlg(self) -> None:
        self._settings_dlg = None

    def _is_streaming(self) -> bool:
        """是否正在生成回答 —— 供设置对话框决定要不要提示「会中断」。"""
        if not self._active_sid or self._manager is None:
            return False
        return self._manager.is_running(self._active_sid)

    def _on_settings_applied(self) -> None:
        """配置已写入磁盘 —— 立刻重建 SessionManager，无需重启。

        为什么 `force=True` 其实可省、但仍显式传
            `_ensure_manager()` 本身就会比对 `_signature()`，下次唤起也会重建。
            但那样用户要「先改配置、再按一次热键」才生效；
            force 让生效发生在点「保存并生效」的当下 —— 这才是「热切换」。
        """
        self._ensure_manager(force=True)
        ok = self._manager is not None
        model = self._cfg("ai.model", "")
        if self._panel:
            self._panel.set_status(
                f"已切换到 {model}" if ok else "配置切换失败，详见日志"
            )
        log_manager.info(
            f"AI 配置热切换: base_url={self._cfg('ai.base_url', '')} "
            f"model={model} manager={'ok' if ok else 'failed'}"
        )

    # ================================================== 内部

    def _cfg(self, key: str, default=None):
        return self.app.config.get(key, default) if self.app else default

    def _signature(self) -> tuple:
        """配置指纹：任何影响 provider/模型 的字段都必须在这里，
        否则改配置后不会重建 SessionManager（改了也不生效）。"""
        return (
            self._cfg("ai.provider", ""),
            self._cfg("ai.base_url", ""),
            self._cfg("ai.model", ""),
            self._cfg("ai.vision_model", ""),
            self._cfg("ai.api_key", ""),
            self._cfg("ai.api_key_ref", ""),
            self._cfg("ai.request_timeout", 60),
        )

    def _ensure_manager(self, force: bool = False) -> None:
        """按配置构建 / 重建 SessionManager（配置变了才重建）。"""
        sig = self._signature()
        if not force and self._manager is not None and sig == self._config_sig:
            return
        try:
            if self._store is None:
                self._store = shared_store()
            if self._manager is not None:
                self._manager.shutdown()
            self._manager = build_from_config(self.app.config, store=self._store)
            self._manager.chunk.connect(self._on_chunk)
            self._manager.done.connect(self._on_done)
            self._manager.error.connect(self._on_error)
            self._config_sig = sig
        except Exception as e:  # noqa: BLE001
            log_manager.error(f"AI 会话管理器初始化失败: {e}")
            self._manager = None
