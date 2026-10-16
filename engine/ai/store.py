# -*- coding: utf-8 -*-
"""会话与预设持久化（sqlite3 标准库，零 Qt 依赖）。

库文件默认落在 `~/.pet_demo/ai.db`，与 config_manager 的目录保持一致。
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import List, Optional

from data.paths import pet_path

from .types import ChatMessage, Preset

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    preset_id   TEXT NOT NULL DEFAULT 'ask',
    title       TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE TABLE IF NOT EXISTS presets (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    system_prompt     TEXT NOT NULL,
    default_delivery  TEXT NOT NULL DEFAULT 'panel',
    description       TEXT NOT NULL DEFAULT ''
);
"""


def default_db_path() -> Path:
    return pet_path("ai.db")


def _flatten(content) -> str:
    """把消息内容压成可入库的字符串。

    多模态消息的 content 是数组（含 base64 图片），直接 str() 会把
    几百 KB 的 data URL 塞进数据库，所以只留文字部分。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
        text = "\n".join(p for p in parts if p)
        return f"{text}\n[图片]" if text else "[图片]"
    return str(content)


class Store:
    """轻量 SQLite 封装。线程安全（内部加锁）。"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else default_db_path()
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            # WAL + NORMAL：把每次 commit 的 fsync 成本降下来。
            # M1 实测：默认配置下连续多次 commit 会在主线程吃掉 150ms+。
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ----- 会话 -----

    def create_session(self, session_id: str, preset_id: str = "ask",
                       title: str = "") -> None:
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO sessions (id, preset_id, title, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (session_id, preset_id, title, now, now),
            )
            self._conn.commit()

    def save_exchange(self, session_id: str, preset_id: str, title: str,
                      messages: List[ChatMessage]) -> None:
        """一次事务写入「会话 + 全部消息」。

        为什么批量：每次 commit 都是一次 fsync。逐条写会产生 3+ 次 commit，
        M1 实测在主线程要 150ms+。合并成一个事务后只剩一次。
        （真正的解法是把它放到工作线程里调用，见 session.py）
        """
        now = time.time()
        rows = [
            (session_id, m.role, _flatten(m.content), now)
            for m in messages
            if m.role != "system"
        ]
        with self._lock, self._conn:      # connection 作为上下文管理器 = 单事务
            self._conn.execute(
                "INSERT OR REPLACE INTO sessions"
                " (id, preset_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, preset_id, title, now, now),
            )
            if rows:
                self._conn.executemany(
                    "INSERT INTO messages (session_id, role, content, created_at)"
                    " VALUES (?, ?, ?, ?)",
                    rows,
                )

    def append_message(self, session_id: str, role: str, content: str) -> None:
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (session_id, role, content, now),
            )
            self._conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id)
            )

    def append_exchange(self, session_id: str, user_content) -> None:
        """续接已有会话：只追加**这一次**的提问。

        为什么不能复用 `save_exchange()`
            它是给「新建会话」用的 —— `INSERT OR REPLACE INTO sessions` 会把
            `created_at` 重置为现在、并用新提问覆盖标题；而 `messages` 是
            **追加**语义，续接时整段历史已在库里，再写一遍就重复了。

        与 `append_message` 的区别只是接受多模态 content（会走 `_flatten`）。
        """
        self.append_message(session_id, "user", _flatten(user_content))

    def session_exists(self, session_id: str) -> bool:
        """会话是否已在库里 —— `ask()` 据此决定「新建」还是「续接」。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM sessions WHERE id = ? LIMIT 1", (session_id,)
            ).fetchone()
        return row is not None

    def set_title(self, session_id: str, title: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET title = ? WHERE id = ?", (title, session_id)
            )
            self._conn.commit()

    def list_sessions(self, limit: int = 50) -> List[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_messages(self, session_id: str) -> List[ChatMessage]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
        return [ChatMessage(r["role"], r["content"]) for r in rows]

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            self._conn.commit()

    # ----- 自定义预设 -----

    def save_preset(self, preset: Preset) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO presets"
                " (id, name, system_prompt, default_delivery, description)"
                " VALUES (?, ?, ?, ?, ?)",
                (preset.id, preset.name, preset.system_prompt,
                 preset.default_delivery, preset.description),
            )
            self._conn.commit()

    def list_presets(self) -> List[Preset]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM presets ORDER BY id").fetchall()
        return [Preset.from_row(dict(r)) for r in rows]

    def delete_preset(self, preset_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM presets WHERE id = ?", (preset_id,))
            self._conn.commit()

    # ----- 生命周期 -----

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass


# ---------------------------------------------------------------- 共享单例

_SHARED: Optional[Store] = None
_SHARED_LOCK = threading.Lock()


def shared_store(db_path: Optional[Path] = None) -> Store:
    """进程级共享 Store（懒创建）。

    为什么必须是单例
        AI 插件（写会话）与控制中心（读会话 / 改预设）访问的是同一个库文件。
        各开各的连接在 WAL 下虽然能并发**读**，但并发**写**会撞
        `database is locked`；而且每开一个连接都要重跑一遍 schema。
        全进程共用一个连接、读写都排在同一把 RLock 后面，最省心也最省资源。

    注意
        调用方**不要**自行 `close()` —— 单例的生命周期由进程统一管理
        （退出时走 `close_shared_store()`）。
    """
    global _SHARED
    with _SHARED_LOCK:
        if _SHARED is None:
            _SHARED = Store(db_path)
        return _SHARED


def close_shared_store() -> None:
    """关闭共享实例（进程退出时调用；测试里也用它重置状态）。"""
    global _SHARED
    with _SHARED_LOCK:
        if _SHARED is not None:
            _SHARED.close()
            _SHARED = None
