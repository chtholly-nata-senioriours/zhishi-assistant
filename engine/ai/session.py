# -*- coding: utf-8 -*-
"""会话编排（仅依赖 PySide6.QtCore，不碰任何界面控件）。

职责：
    - 把「预设 + 输入 + 上下文」组装成消息
    - 在线程池里跑 provider.stream()，逐块回传
    - 支持取消
    - 落库

线程模型
    ask() 在主线程调用，立刻返回 session_id；
    真正的网络请求在 ThreadPoolExecutor 里跑，结果经 Qt 信号回主线程。
    信号跨线程投递由 Qt 自动排队，UI 侧无需自己加锁。

    **注意**：绝不能在 event_bus 的同步回调里直接调用 ask() 的阻塞版本 ——
    本类本身不阻塞，但调用方若在回调里等待结果就会冻结感知层。
"""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, Signal

from .prompt import build_messages, get_preset
from .provider import Provider, build_user_content
from .store import Store
from .types import ChatMessage, Preset


class SessionManager(QObject):
    """AI 会话编排器。"""

    started = Signal(str)          # session_id
    chunk = Signal(str, str)       # session_id, 增量
    done = Signal(str, str)        # session_id, 完整文本
    error = Signal(str, str)       # session_id, 错误信息

    def __init__(
        self,
        provider: Provider,
        model: str,
        store: Optional[Store] = None,
        max_workers: int = 2,
        vision_model: Optional[str] = None,
    ):
        super().__init__()
        self._provider = provider
        self._model = model
        self._vision_model = (vision_model or "").strip()
        self._store = store
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ai")
        self._cancel_flags: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    # ----- 配置 -----

    @property
    def provider(self) -> Provider:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    @property
    def vision_model(self) -> str:
        """多模态（截图问答）专用模型；未配置时回退到主模型。"""
        return self._vision_model or self._model

    def configure(self, provider: Optional[Provider] = None,
                  model: Optional[str] = None,
                  vision_model: Optional[str] = None) -> None:
        if provider is not None:
            self._provider = provider
        if model is not None:
            self._model = model
        if vision_model is not None:
            self._vision_model = vision_model.strip()

    def model_for(self, has_image: bool) -> str:
        """按「是否带图」选择模型。

        为什么需要两个模型
            纯文本模型（如 DeepSeek-V3）价格低、速度快，但**看不懂图**；
            截图问答必须换成视觉模型（如 Qwen3-VL）。
            聚合平台（硅基流动 / OpenRouter）同一把 key 可调多个模型，
            因此按请求类型分流是最省钱的用法。
        """
        if has_image and self._vision_model:
            return self._vision_model
        return self._model

    # ----- 发起 -----

    def ask(
        self,
        text: str,
        preset: Optional[Preset] = None,
        context: str = "",
        language: str = "zh",
        length: str = "auto",
        image_data_url: Optional[str] = None,
        history: Optional[List[ChatMessage]] = None,
        persist: bool = True,
        session_id: Optional[str] = None,
    ) -> str:
        """发起一次问答，立刻返回 session_id。结果经信号回传。

        session_id
            不传（默认）→ **新建**一条会话，id 随机生成。
            传已有 id → **续接**该会话：`history` 作为上下文送进模型，
            落库时只追加这次的提问（不重写整段历史、不动创建时间与标题）。
            控制中心「会话历史 → 继续对话」走的就是这条路径。

        注意：`session_id` 只影响落库与后续追踪，**不影响**送进模型的消息 ——
        上下文由 `history` 决定。两者要一起传，否则续接出来的对话会丢上下文。
        """
        preset = preset or get_preset("ask")
        sid = session_id or uuid.uuid4().hex[:12]
        continuing = bool(session_id)

        messages = build_messages(
            preset, text, context=context,
            language=language, length=length, history=history,
        )
        if image_data_url:
            # 把最后一条 user 消息换成多模态格式
            messages[-1] = ChatMessage(
                "user", build_user_content(text, image_data_url)
            )

        flag = threading.Event()
        with self._lock:
            self._cancel_flags[sid] = flag

        # 带图则走视觉模型（未配置则回退主模型）
        model = self.model_for(bool(image_data_url))

        # 注意：这里**不能**落库。ask() 运行在主线程，SQLite 的 commit 是 fsync，
        # M1 实测会让主线程阻塞 150ms+。落库一律放到工作线程里做（见 _run）。
        self.started.emit(sid)
        self._pool.submit(
            self._run, sid, messages, preset, flag, persist, text[:40], model, continuing
        )
        return sid

    # ----- 取消 -----

    def cancel(self, session_id: str) -> bool:
        with self._lock:
            flag = self._cancel_flags.get(session_id)
        if flag is None:
            return False
        flag.set()
        return True

    def is_running(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._cancel_flags

    def shutdown(self) -> None:
        with self._lock:
            for flag in self._cancel_flags.values():
                flag.set()
        self._pool.shutdown(wait=False, cancel_futures=True)

    # ----- 内部 -----

    def _run(self, sid: str, messages: List[ChatMessage], preset: Preset,
             flag: threading.Event, persist: bool, title: str = "",
             model: Optional[str] = None, continuing: bool = False) -> None:
        buf: List[str] = []
        model = model or self._model

        # 落库放在工作线程（一次事务），避免阻塞主线程
        if persist and self._store:
            try:
                if continuing:
                    # 续接：历史已在库里，只追加**这次**的提问。
                    # 用 save_exchange 会把 created_at 重置、标题被覆盖，
                    # 而且整段历史会被重复写入。
                    self._store.append_exchange(sid, messages[-1].content)
                else:
                    self._store.save_exchange(sid, preset.id, title, messages)
            except Exception:
                pass

        try:
            for delta in self._provider.stream(messages, model):
                if flag.is_set():
                    break
                buf.append(delta)
                self.chunk.emit(sid, delta)

            full = "".join(buf)
            if persist and self._store and full:
                try:
                    self._store.append_message(sid, "assistant", full)
                except Exception:
                    pass
            self.done.emit(sid, full)

        except Exception as e:  # noqa: BLE001
            partial = "".join(buf)
            if partial:
                self.done.emit(sid, partial)
            self.error.emit(sid, f"{type(e).__name__}: {e}")
        finally:
            with self._lock:
                self._cancel_flags.pop(sid, None)


def make_session_manager(provider: Provider, model: str,
                         store: Optional[Store] = None,
                         vision_model: Optional[str] = None) -> SessionManager:
    return SessionManager(provider, model, store=store, vision_model=vision_model)
