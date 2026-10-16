# -*- coding: utf-8 -*-
"""活动记录持久化（sqlite3 标准库，零 Qt 依赖）。

为什么单独一个库文件
    会话历史在 `ai.db`，行为记录在 `activity.db` —— 语义完全不同：
    「清空行为数据」不该动用户的会话历史，反过来也一样。
    各用一个文件，删除 / 备份 / 迁移互不牵连。

隐私由**表结构**保证
    `segments` 表里**没有**窗口标题、按键内容、剪贴板、截图的列。
    这不是「代码里记得别写」的君子约定，而是**根本没地方写** ——
    想把标题加进来必须先改 schema，绕不过 review。
    对应的单元测试直接断言「表里没有 title 列」。

    `advices` 表存的是**模型输出的建议文本**（本地缓存，避免重复调用），
    不是用户内容 —— 它由聚合摘要生成，摘要里本来就只有应用名和时长。
    `decisions` 表存**用户对建议做了什么决定**：note 里的上下文只允许
    聚合数字（条数 / 时长 / 起止），窗口标题这类字段连键都进不去
    （`engine.activity.decision._clean_context` 是白名单）。
    `app_categories` 表只存**应用名 → 类别**（两个都是系统自己的标识符），
    不含任何用户内容；它让用户能纠正「系统把这个应用判错了」。
    加新表 / 新列之前先问：它会不会把用户内容带出去。
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

from data.paths import pet_path

from .category import (
    CATEGORIES,
    OTHER,
    apply_overrides,
    is_valid_category,
    normalize_app,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS segments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    app        TEXT    NOT NULL,
    category   TEXT    NOT NULL DEFAULT '其他',
    start_at   REAL    NOT NULL,
    end_at     REAL    NOT NULL,
    seconds    REAL    NOT NULL,
    key_rate   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_segments_start ON segments(start_at);

CREATE TABLE IF NOT EXISTS advices (
    scope      TEXT PRIMARY KEY,
    signature  TEXT NOT NULL,
    text       TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ignored_advices (
    fingerprint TEXT PRIMARY KEY,
    headline    TEXT NOT NULL,
    ignored_at  REAL NOT NULL
);

-- 用户手动指定的「这个应用算什么类别」。
-- 为什么不 UPDATE 掉 segments 里的 category：那一列是**系统当时的判定**，
-- 是证据（与 P1-4 的决策留痕同一条纪律）。手动归类是「后来人的判断」，
-- 两层分开存，原始观测才不会被篡改，用户也能撤销回自动判定。
-- 读取时在 Python 层叠加（`category.apply_overrides`），SQL 层不做 ——
-- 一处实现，不会出现「SQL 一份、Python 一份」两个都没验证的局面。
CREATE TABLE IF NOT EXISTS app_categories (
    app        TEXT PRIMARY KEY,
    category   TEXT NOT NULL,
    updated_at REAL NOT NULL
);

-- 人机协同决策留痕：用户对一条建议做了什么决定、凭什么、当时数据什么样。
-- 与 ignored_advices 的分工：后者只回答「别再出现」（一条标记），
-- 前者回答「凭什么、当时什么情况、影响了什么」（可审计的证据链）。
-- note 列是 JSON（见 engine.activity.decision.DecisionNote.to_dict）。
CREATE TABLE IF NOT EXISTS decisions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL,
    headline    TEXT NOT NULL,
    action      TEXT NOT NULL,
    decided_at  REAL NOT NULL,
    note        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_time ON decisions(decided_at);
"""

DAY_SECONDS = 86400.0


def _top_key(acc: Dict[str, float], default: str = OTHER) -> str:
    """取占比最大的键；并列时按名字取第一个。

    必须**确定性** —— 同一个查询两次给出不同答案的话，界面会自己跟自己打架。
    """
    if not acc:
        return default
    return max(sorted(acc.items()), key=lambda kv: kv[1])[0]


def default_db_path() -> Path:
    """活动库路径 —— 与 `ai.db` 同目录，但**不同文件**。"""
    return pet_path("activity.db")


class ActivityStore:
    """活动分段的本地库。线程安全（内部加锁）。"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else default_db_path()
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            # 与 ai.db 同样的取舍：WAL + NORMAL，避免每次 commit 都 fsync。
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ----- 写 -----

    def add_segment(self, app: str, category: str, start_at: float,
                    end_at: float, key_rate: int = 0) -> None:
        """写入一段活动。

        `seconds` 由起止时间**算出来**，不接受调用方传入 ——
        否则迟早会出现「seconds 与 start/end 对不上」的脏数据，
        而所有统计都建立在 seconds 上。
        """
        seconds = max(0.0, float(end_at) - float(start_at))
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO segments (app, category, start_at, end_at, seconds, key_rate)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (app or "unknown", category or "其他",
                 float(start_at), float(end_at), seconds, int(key_rate)),
            )

    # ----- 读 -----
    #
    # 所有读路径都必须经过 `_rows()` —— 它是「用户手动分类」生效的**唯一**出口。
    # 绕过它直接 execute 的查询会读出一份没有覆盖的数据，而且**不会报错**
    # （界面上表现为「改了分类但排行没变」）。新增读方法时照抄这个模式。

    def _rows(self, sql: str, params: tuple = ()) -> List[dict]:
        """执行一条 segments 查询，并在 Python 层叠加用户的手动分类。

        **不要在别处再实现一遍覆盖逻辑** —— SQL 里 JOIN 一张、Python 里叠一张，
        两边都会「看起来在工作」，删掉任一处测试都照样绿（同一件事有两个实现
        = 两个都没验证）。
        """
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        if rows and "app" not in rows[0].keys():
            # 覆盖表是按 app 查的：SQL 漏掉 app 列 → 覆盖**静默失效**
            # （不报错，只是「改了分类但数字没变」）。这种错最难查，
            # 所以在这里直接炸，而不是返回一份看起来正常的数据。
            raise ValueError("segments 查询必须带 app 列，否则手动分类不会生效")
        return apply_overrides([dict(r) for r in rows], self.app_categories())

    def segments_since(self, since: float) -> List[dict]:
        return self._rows(
            "SELECT app, category, start_at, end_at, seconds, key_rate"
            " FROM segments WHERE end_at >= ? ORDER BY start_at",
            (float(since),),
        )

    def segments_between(self, start: float, end: float) -> List[dict]:
        """取 `[start, end)` 的分段 —— 「今日小结」按自然日切片时用。

        与 `segments_since` 的差别在**上界**：只给「起点」会把跨天的
        长段算进今天，日报于是比实际偏大。
        """
        return self._rows(
            "SELECT app, category, start_at, end_at, seconds, key_rate"
            " FROM segments WHERE end_at >= ? AND start_at < ? ORDER BY start_at",
            (float(start), float(end)),
        )

    def totals_by_app(self, since: float) -> List[dict]:
        """按应用聚合：总时长 + 段数，按时长降序。

        聚合放在 Python 层（不走 SQL 的 GROUP BY）—— 分类要先叠加用户覆盖
        才能分组，SQL 里做不到这件事。数据量是「30 天 × 每天几百段」，
        Python 聚合的开销可以忽略。
        """
        rows = self._rows(
            "SELECT app, category, seconds FROM segments WHERE end_at >= ?",
            (float(since),),
        )
        acc: Dict[str, dict] = {}
        for row in rows:
            app = str(row.get("app") or "unknown")
            item = acc.setdefault(
                app, {"app": app, "seconds": 0.0, "segments": 0,
                      "_by_cat": {}, "_by_auto": {}},
            )
            seconds = float(row.get("seconds") or 0.0)
            cat = str(row.get("category") or OTHER)
            item["seconds"] += seconds
            item["segments"] += 1
            item["_by_cat"][cat] = item["_by_cat"].get(cat, 0.0) + seconds
            # `auto_category` 只在被手动归类过时才有（见 `category.apply_overrides`）。
            # **这一项不能丢**：「应用分类」页靠它显示「系统判定」那一列，
            # 丢了之后该列会被覆盖后的值污染 —— 于是这页最该看的那组对照
            # （系统判成什么 / 你改成了什么）直接消失，而汇总行还写着
            # 「N 个已手动归类」，用户找不到是哪几个。目检 S18 抓到的。
            auto = str(row.get("auto_category") or cat)
            item["_by_auto"][auto] = item["_by_auto"].get(auto, 0.0) + seconds

        out: List[dict] = []
        for item in acc.values():
            # 一个应用理论上只有一个类别（分类只看进程名 + 标题），但标题会变，
            # 所以取**占比最大**的那个。
            item["category"] = _top_key(item.pop("_by_cat"))
            auto = _top_key(item.pop("_by_auto"))
            if auto != item["category"]:
                item["auto_category"] = auto
            out.append(item)
        out.sort(key=lambda x: x["seconds"], reverse=True)
        return out

    def totals_by_category(self, since: float) -> List[dict]:
        # **必须把 app 也选出来** —— 覆盖表是按 app 查的，少这一列的话
        # `apply_overrides` 拿不到键，会静默返回一份没覆盖的数据（不报错）。
        rows = self._rows(
            "SELECT app, category, seconds FROM segments WHERE end_at >= ?",
            (float(since),),
        )
        acc: Dict[str, float] = {}
        for row in rows:
            cat = str(row.get("category") or OTHER)
            acc[cat] = acc.get(cat, 0.0) + float(row.get("seconds") or 0.0)
        return [
            {"category": c, "seconds": v}
            for c, v in sorted(acc.items(), key=lambda kv: (-kv[1], kv[0]))
        ]

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute(
                "SELECT COUNT(*) FROM segments").fetchone()[0])

    def total_seconds(self, since: float = 0.0) -> float:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(seconds), 0) FROM segments WHERE end_at >= ?",
                (float(since),),
            ).fetchone()
        return float(row[0] or 0.0)

    # ----- 用户手动分类（覆盖自动判定）-----

    def app_categories(self) -> Dict[str, str]:
        """取全部「应用 → 手动类别」。读路径每次都会调它（这张表很小）。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT app, category FROM app_categories").fetchall()
        return {str(r[0]): str(r[1]) for r in rows}

    def set_app_category(self, app: str, category: str,
                         now: Optional[float] = None) -> bool:
        """把某个应用手动归到指定类别。返回是否写成功。

        类别必须是 `category.CATEGORIES` 里的一个 —— **受限枚举**：
        界面上只有五个选项，库里就不该出现第六种取值（否则统计里会冒出
        一个谁也解释不了的类别，而且不报错）。
        """
        name = normalize_app(app)
        if not name or not is_valid_category(category):
            return False
        stamp = time.time() if now is None else float(now)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO app_categories (app, category, updated_at)"
                " VALUES (?, ?, ?)"
                " ON CONFLICT(app) DO UPDATE SET"
                " category = excluded.category, updated_at = excluded.updated_at",
                (name, str(category), stamp),
            )
        return True

    def clear_app_category(self, app: str) -> bool:
        """撤销某个应用的手动归类 —— 它回到**自动判定**。

        因为覆盖只发生在读取时、原始 `category` 列从没被改过，撤销是零代价的：
        删掉这一行，读出来就是当初系统判的那个类别。
        """
        name = normalize_app(app)
        if not name:
            return False
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM app_categories WHERE app = ?", (name,))
            return bool(cur.rowcount)

    def clear_app_categories(self) -> int:
        """清空全部手动归类，返回删除条数。"""
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM app_categories")
            return cur.rowcount or 0

    def count_app_categories(self) -> int:
        with self._lock:
            return int(self._conn.execute(
                "SELECT COUNT(*) FROM app_categories").fetchone()[0])

    # ----- 维护 -----

    def prune(self, retention_days: int, now: Optional[float] = None) -> int:
        """删掉超过保留期的分段，返回删除条数。

        `retention_days <= 0` 视为「不保留」——直接返回 0，
        免得调用方误传 0 就把整库清空了（那是 `clear()` 的职责）。
        """
        if retention_days <= 0:
            return 0
        cutoff = (time.time() if now is None else float(now)) - retention_days * DAY_SECONDS
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM segments WHERE end_at < ?", (cutoff,))
            return cur.rowcount or 0

    def clear(self) -> int:
        """一键清空**行为数据**（分段 + 缓存的建议 + 已忽略标记），返回删除的分段条数。

        建议与忽略标记一起删 —— 它们都是根据用户的活动产生的，
        留着等于没清干净。尤其「已忽略」若不删，用户清空后新生成的建议
        仍会被旧标记挡掉，还找不到原因。
        决策留痕（`decisions`）也一起删：它同样是**用户行为的产物**，
        用户点「清空行为数据」时有权把它一并带走。
        返回值只报分段条数，是为了让调用方显示「已清空 N 条记录」时
        数字对得上用户的理解（建议是 1 条，不是「记录」）。

        **不动 `app_categories`** —— 那不是行为数据，是用户的**偏好设置**：
        「Chrome 算工作」是他对工具的判断，不该因为清空记录就被抹掉
        （抹掉之后还得重设一遍，而且他不会知道为什么）。要清它走
        `clear_app_categories()`。
        """
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM segments")
            self._conn.execute("DELETE FROM advices")
            self._conn.execute("DELETE FROM ignored_advices")
            self._conn.execute("DELETE FROM decisions")
            return cur.rowcount or 0

    # ----- 建议缓存 -----

    def get_advice(self, scope: str) -> Optional[dict]:
        """取某个范围（`day` / `week`）缓存的建议，没有则 `None`。

        缓存的意义不只是省钱：它让「打开即有内容」成为可能 ——
        用户进页面直接看到上次的结论，而不是又要点一次「生成」。
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT scope, signature, text, created_at FROM advices WHERE scope = ?",
                (str(scope),),
            ).fetchone()
        return dict(row) if row else None

    def save_advice(self, scope: str, signature: str, text: str,
                    now: Optional[float] = None) -> None:
        """写入 / 覆盖某个范围的建议缓存（每个 scope 只留最新一条）。"""
        stamp = time.time() if now is None else float(now)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO advices (scope, signature, text, created_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(scope) DO UPDATE SET"
                " signature = excluded.signature,"
                " text = excluded.text,"
                " created_at = excluded.created_at",
                (str(scope), str(signature), str(text), stamp),
            )

    def clear_advices(self) -> int:
        """只删缓存的建议（分段保留）。返回删除条数。"""
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM advices")
            return cur.rowcount or 0

    def count_advices(self) -> int:
        with self._lock:
            return int(self._conn.execute(
                "SELECT COUNT(*) FROM advices").fetchone()[0])

    # ----- 被忽略的建议 -----

    def ignore_advice(self, fingerprint: str, headline: str = "",
                      now: Optional[float] = None) -> None:
        """记下「用户不想再看到这条建议」。

        存指纹而不是建议本身：建议是每次生成的，没有稳定 id；
        指纹由结论文本归一化后算出（见 `engine.activity.advice`），
        所以「只差数字和标点」的重复也会被挡住。
        重复忽略同一条不会报错（`ON CONFLICT` 覆盖时间戳）。
        """
        stamp = time.time() if now is None else float(now)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO ignored_advices (fingerprint, headline, ignored_at)"
                " VALUES (?, ?, ?)"
                " ON CONFLICT(fingerprint) DO UPDATE SET"
                " headline = excluded.headline, ignored_at = excluded.ignored_at",
                (str(fingerprint), str(headline), stamp),
            )

    def ignored_fingerprints(self) -> Set[str]:
        """所有被忽略的建议指纹 —— 渲染前用它过滤。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT fingerprint FROM ignored_advices").fetchall()
        return {str(r[0]) for r in rows}

    def count_ignored(self) -> int:
        with self._lock:
            return int(self._conn.execute(
                "SELECT COUNT(*) FROM ignored_advices").fetchone()[0])

    def clear_ignored(self) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM ignored_advices")
            return cur.rowcount or 0

    # ----- 人机协同决策留痕（采纳 / 忽略的完整证据链）-----

    def record_decision(self, fingerprint: str, headline: str, action: str,
                        note_json: str, now: Optional[float] = None) -> int:
        """写入一条决策留痕，返回自增 id。

        `note_json` 是 `DecisionNote.to_dict()` 的 JSON —— 表本身只存
        「定位 + 索引」四列，证据内容整段放 JSON。这样以后给留痕加字段
        不必改 schema，而老库读出来仍然可用（缺字段走缺省值）。
        """
        stamp = time.time() if now is None else float(now)
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO decisions (fingerprint, headline, action, decided_at, note)"
                " VALUES (?, ?, ?, ?, ?)",
                (str(fingerprint), str(headline), str(action), stamp, str(note_json)),
            )
            return int(cur.lastrowid or 0)

    def decisions(self, limit: int = 200, action: Optional[str] = None) -> List[dict]:
        """取决策留痕（新的在前）。`action` 传 `adopt` / `ignore` 可过滤。

        返回的是「行 + 解析后的 note」：调用方要显示完整证据，
        不该自己再去 json.loads 一遍（那是第二次实现）。
        """
        sql = ("SELECT id, fingerprint, headline, action, decided_at, note"
               " FROM decisions")
        params: list = []
        if action:
            sql += " WHERE action = ?"
            params.append(str(action))
        sql += " ORDER BY decided_at DESC, id DESC LIMIT ?"
        params.append(max(1, int(limit)))
        with self._lock:
            rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]

    def count_decisions(self, action: Optional[str] = None) -> int:
        sql = "SELECT COUNT(*) FROM decisions"
        params: tuple = ()
        if action:
            sql += " WHERE action = ?"
            params = (str(action),)
        with self._lock:
            return int(self._conn.execute(sql, params).fetchone()[0])

    def clear_decisions(self) -> int:
        """只删决策留痕（分段与建议缓存保留）。返回删除条数。"""
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM decisions")
            return cur.rowcount or 0

    # ----- 状态位（键值对）-----

    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """读一个状态位。

        放在活动库里而不是配置文件里，是因为「清空行为数据」时
        这些状态（比如「今天提醒过了」）理应一起归零 —— 否则用户清空后
        当天再也收不到提醒，还找不到原因。
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key = ?", (str(key),)
            ).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(key), str(value)),
            )

    # ----- 生命周期 -----

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
