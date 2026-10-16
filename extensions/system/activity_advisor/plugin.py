# -*- coding: utf-8 -*-
"""活动建议插件 —— 采集本机活动，交给 AI 分析后给出节奏建议与规划。

隐私边界（本插件的核心约束，改代码前先读一遍）
    1. **不自己启动传感器**。`main.py::_start_sensors()` 已经在跑
       `WindowMonitor` / `InputMonitor` / `TimeTrigger`（宠物状态机共用）；
       重复启动会装两个键盘钩子。这里只 `subscribe`。
    2. **默认关闭**。`activity.enabled` 为 false 时连订阅都不做，不落任何数据。
       开关在控制中心「活动建议」页一键切换，**立即生效**（不重启）。
    3. **落库字段由 `engine.activity.store` 的表结构决定** —— 那里没有存
       窗口标题的列，所以「不小心记下标题」在结构上就做不到。
    4. **出网的只有摘要**。`build_summary()` 是纯函数，可单独审阅它发了什么。
    5. **空闲 / 全屏信号不产生新字段**：空闲只用来**剪掉「人不在」的时长**，
       全屏只用来**免打扰**。两者都不参与「记录了什么」。

主动提醒为什么做得这么克制
    用户不该为了看建议而记着点按钮；但也不该被频繁打扰。
    所以「收工小结」是**一天最多一次**，外加一串免打扰条件
    （全屏 / 专注计时中 / 人不在 / 还没到点 / 今天没数据）。
    判定逻辑全在 `engine.activity.reminder.should_nudge` —— 纯函数、可单测。

线程模型
    `_on_window_active` / `_on_tick` 由事件总线在**发布者线程**里同步调用，
    必须极快，且**不能碰 Qt**。所有回主线程的 UI 更新都经 `_bridge`
    （一个活在主线程的 QObject）—— Qt 的队列连接只在 QObject 之间生效，
    把信号直接连到普通 Python 方法会退化成直连，等于在工作线程里动控件。
"""
from __future__ import annotations

import json
import time
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal

from event_bus import event_bus
from engine.activity import (
    ACTION_ADOPT,
    ACTION_IGNORE,
    ACTIONS,
    ADVISOR_PRESET,
    ActivityStore,
    ActivityTracker,
    AdviceReport,
    DecisionNote,
    build_advisor_prompt,
    build_context,
    build_note,
    build_summary,
    focus_seconds,
    format_notes,
    human_duration,
    normalize_app,
    parse_report,
    should_nudge,
    since_for_days,
    today_range,
)
from extensions.base_plugin import BasePlugin, MenuAction

from .dialog import ActivityAdvisorDialog

#: 摘要里出现这两句说明「没有可用数据」，不必浪费一次调用。
_EMPTY_MARKERS = ("没有采集到", "不足以分析")

#: 「今天已经提醒过」的状态位（存在 activity.db 里，清空数据时一起归零）。
_LAST_NUDGE_KEY = "last_nudged_at"

#: 本机保留天数的兜底值（配置读不到时用）。
#: **必须 ≥「趋势」页最长的范围（30 天）** —— 否则那个视图开箱就是坏的。
#: 配置默认值在 `data/config_manager.py::DEFAULT_CONFIG` 与 `config.default.json`
#: 两处（改配置要同时改，见 AGENTS.md）。
DEFAULT_RETENTION_DAYS = 30

#: 每日深度工作的目标时长（分钟）—— 常驻指示的进度环拿它当分母。
#: 240 = 4 小时：一个「认真上了一天班」的量级，不是让人每天都能刷满的数字。
#: 刷满的进度环等于没有信息量，所以这个默认值刻意偏高一点。
DEFAULT_FOCUS_GOAL_MINUTES = 240

#: 建议缓存的范围键：日报 / 周报各一份。
_SCOPE_DAY = "day"
_SCOPE_WEEK = "week"


def _parse_note(row: dict) -> Optional[DecisionNote]:
    """库里的一行 → `DecisionNote`。解析不了就丢掉，别让半条数据流到界面。"""
    raw = str(row.get("note") or "")
    if not raw:
        return None
    try:
        return DecisionNote.from_dict(json.loads(raw))
    except (ValueError, TypeError):
        return None


def _cfg_number(config, key: str, default, cast=float):
    """读一个数值配置，取不到 / 读不动时回退默认值。

    **不要写成 `config.get(key, default) or default`** —— 0 是合法值：
    `nudge_hour = 0` 表示「过零点就提醒」，`min_segment_seconds = 0`
    表示「不过滤碎片」，而 `0 or 18` 会把它们**悄悄改成 18**。
    这个坑真实踩过：测试里设 0 却怎么都不触发，查了半天。
    """
    raw = config.get(key, default)
    if raw is None:
        return cast(default)
    try:
        return cast(raw)
    except (TypeError, ValueError):
        return cast(default)


class _ViewBridge(QObject):
    """跨线程 → 主线程的搬运工。

    这个 QObject 在 `on_ui_ready`（主线程）里创建，所以任何线程 emit 它，
    Qt 都会把投递排到主线程的队列里。视图（页面 / 对话框）只连它。
    """

    chunk = Signal(str)         # 流式增量
    done = Signal(str)          # 完整文本
    error = Signal(str)         # 错误信息
    status = Signal(str)        # 状态行
    analyzing = Signal(bool)    # 是否正在分析
    nudge = Signal(str, str)    # 收工小结（标题, 正文）


class ActivityAdvisorPlugin(BasePlugin):
    """活动建议插件。"""

    def __init__(self):
        super().__init__()
        self._enabled = False
        self._store: Optional[ActivityStore] = None
        self._tracker: Optional[ActivityTracker] = None
        self._manager = None
        self._dialog: Optional[ActivityAdvisorDialog] = None
        self._views: List[object] = []
        self._bridge: Optional[_ViewBridge] = None
        self._config_sig = None
        self._active_session: Optional[str] = None
        self._last_nudged_at: Optional[float] = None
        # 本次分析的落库目标（done 时写缓存用）
        self._pending_scope = _SCOPE_DAY
        self._pending_signature = "0"
        self._pending_text = ""

    # ----- 生命周期 -----

    def on_load(self, app) -> bool:
        self._enabled = bool(app.config.get("activity.enabled", False))
        return True

    def on_ui_ready(self, app) -> None:
        # 放在这里而不是 on_load：on_load 阶段 UI 还没建好，
        # `app.input_monitor` / `app.tray_icon` 也未必存在。
        self._bridge = _ViewBridge()
        self._bridge.chunk.connect(self._dispatch_chunk)
        self._bridge.done.connect(self._dispatch_done)
        self._bridge.error.connect(self._dispatch_error)
        self._bridge.status.connect(self._dispatch_status)
        self._bridge.analyzing.connect(self._dispatch_analyzing)
        self._bridge.nudge.connect(self._show_nudge)

        if self._enabled:
            self._start_collecting()

    def on_unload(self) -> None:
        self._stop_collecting()
        if self._manager is not None:
            try:
                self._manager.shutdown()
            except Exception:
                pass
            self._manager = None
        if self._dialog is not None:
            try:
                self._dialog.close()
            except Exception:
                pass
            self._dialog = None
        self._views.clear()

    # ----- 菜单 -----

    def get_menu_actions(self):
        # 「今日概览」把用户带到主窗口的「今日」页；「开始 45 分钟专注」是
        # 一条**立即能用**的出口 —— 看到环没走满时，托盘上就能直接开工，
        # 不必先开窗口再找按钮。
        return [
            MenuAction("今日概览", self._open, category="tools"),
            MenuAction("开始 45 分钟专注", lambda: self.start_focus(45),
                       category="tools"),
        ]

    # ----- 对外：供控制中心「活动建议」页使用（鸭子类型）-----

    def is_enabled(self) -> bool:
        return bool(self._enabled)

    def set_enabled(self, enabled: bool) -> bool:
        """一键开关：写配置 + **立即生效**。

        重启才生效的开关等于没做 —— 用户点完看不到任何变化，
        会以为坏了。这里直接起停采集。
        """
        enabled = bool(enabled)
        try:
            self.app.config.set("activity.enabled", enabled)
            self.app.config.save()
        except Exception:
            return False

        self._enabled = enabled
        if enabled:
            self._start_collecting()
        else:
            self._stop_collecting()
        return True

    def attach_view(self, view) -> None:
        """登记一个视图（页面 / 对话框）。

        视图实现这几个方法即可（缺哪个就跳过哪个）：
            set_status(str) / set_advice(str)
            append_advice(str) / set_analyzing(bool)

        `set_overview(str)` 是**旧的纯文本协议**，只有插件自己的对话框还用 ——
        「今日」页改成自己拉分段数据画图（文字概览里没有逐段起止时间），
        所以它不实现这个方法，插件广播时会被自动跳过。
        """
        if view is not None and view not in self._views:
            self._views.append(view)

    def detach_view(self, view) -> None:
        try:
            self._views.remove(view)
        except ValueError:
            pass

    def overview(self, days: int = 1) -> str:
        """本地概览（**不出网**）。没有采集时给明确提示。"""
        if self._store is None:
            return "采集未开启。打开上面的开关即可开始记录。"
        return build_summary(self._segments_for(days))

    def cached_advice(self, days: int = 1) -> str:
        """上次生成的建议（本地缓存）。没有则空串。"""
        if self._store is None:
            return ""
        row = self._store.get_advice(self._scope_for(days))
        return str(row.get("text") or "") if row else ""

    def advice_is_stale(self, days: int = 1) -> bool:
        """缓存是否已过期（数据变了）。供页面提示「数据已更新」。"""
        if self._store is None:
            return False
        row = self._store.get_advice(self._scope_for(days))
        if not row:
            return False
        return str(row.get("signature") or "") != self._data_signature(days)

    def segments_for(self, days: int = 1) -> List[dict]:
        """取原始活动分段（本机，不出网）。

        「今日」页要画时间轴，光有 `overview()` 那段文字不够 ——
        文字里没有逐段的起止时间。这里把分段原样交给页面，**合并由
        `engine.activity.timeline.merge_segments` 做**（纯函数、有测试），
        页面不自己算。

        「趋势」页要跟**上一个同长周期**比，所以它会传 `days * 2`。
        """
        return self._segments_for(days)

    # ----- 应用分类（自动判定 + 用户手动归类）-----

    def app_totals(self, days: int = 7) -> List[dict]:
        """近 N 天出现过的应用：时长 / 段数 / 当前类别 / 是否被手动改过。

        `category` 已经是**叠加过手动归类**的值（覆盖在 store 的读路径上做，
        见 `engine.activity.store._rows`），`auto_category` 只在被改过时才存在。
        页面据此显示「自动判定 工作 → 已改为 学习」这种对照。
        """
        if self._store is None:
            return []
        rows = self._store.totals_by_app(since_for_days(days, time.time()))
        manual = self._store.app_categories()
        for row in rows:
            row["manual"] = normalize_app(row.get("app")) in manual
        return rows

    def app_categories(self) -> Dict[str, str]:
        """全部手动归类（`应用名 → 类别`）。"""
        if self._store is None:
            return {}
        try:
            return self._store.app_categories()
        except Exception:  # noqa: BLE001 —— 读不到按「没有手动归类」处理
            return {}

    def set_app_category(self, app: str, category: str) -> Tuple[bool, str]:
        """把某个应用归到指定类别，返回 `(成功, 给人看的一句话)`。"""
        if self._store is None:
            return False, "采集未开启，无法保存归类"
        if not self._store.set_app_category(app, category):
            # 唯一的失败原因是类别不在受限枚举里（或应用名为空）——
            # 界面只给五个选项，所以走到这里说明调用方传错了。
            return False, f"无法把「{app}」归到「{category}」"
        return True, f"已把「{app}」归到「{category}」"

    def clear_app_category(self, app: str) -> Tuple[bool, str]:
        """撤销某个应用的手动归类（回到自动判定）。"""
        if self._store is None:
            return False, "采集未开启，无法修改归类"
        if not self._store.clear_app_category(app):
            return False, f"「{app}」本来就没有手动归类"
        return True, f"「{app}」已恢复为自动判定"

    def clear_app_categories(self) -> int:
        """撤销全部手动归类，返回撤销条数。"""
        if self._store is None:
            return 0
        try:
            return self._store.clear_app_categories()
        except Exception:  # noqa: BLE001
            return 0

    def retention_days(self) -> int:
        """本机保留多少天记录（页面要如实告诉用户，不能只写个死数字）。

        比它更长的范围注定只有一部分数据 —— 页面必须据此提示，
        否则「近 30 天」看着像坏了。
        """
        return int(_cfg_number(self.app.config, "activity.retention_days",
                               DEFAULT_RETENTION_DAYS, int))

    def focus_goal_seconds(self) -> float:
        """每日深度工作目标（秒）。配置读不到时用 `DEFAULT_FOCUS_GOAL_MINUTES`。"""
        minutes = _cfg_number(self.app.config, "activity.focus_goal_minutes",
                              DEFAULT_FOCUS_GOAL_MINUTES, int)
        return max(60.0, float(minutes) * 60.0)

    def focus_progress(self, days: int = 1) -> dict:
        """今日深度工作进度（给**常驻指示**用）。

        返回 `{"focus": 秒, "goal": 秒, "ratio": 0–1, "enabled": bool}`。

        为什么不让托盘自己算
            「深度工作 = 类别为『工作』的段之和」是一条口径，页面、摘要、
            趋势页都用它。托盘只该要一个**数字**，不该知道这条口径 ——
            否则又多一处「两处口径不一致」的机会。
        """
        goal = self.focus_goal_seconds()
        if not self._enabled or self._store is None:
            # 关闭时明确报 `enabled=False`：托盘据此画「关闭态」，
            # 而不是画一个空环（空环会被读成「今天一点没干」）。
            return {"focus": 0.0, "goal": goal, "ratio": 0.0, "enabled": False}
        focus = float(focus_seconds(self._segments_for(days)))
        return {
            "focus": focus,
            "goal": goal,
            "ratio": min(1.0, focus / goal) if goal > 0 else 0.0,
            "enabled": True,
        }

    def structured_report(self, days: int = 1) -> AdviceReport:
        """把缓存的建议解析成「总结 + 建议」，**并过滤掉用户已忽略的**。

        过滤必须在这里做而不是页面里
            「忽略」是一条要长期生效的状态（存在 `activity.db`）。
            如果只在页面里过滤，换个视图（对话框）就又会冒出来。
        """
        text = self.cached_advice(days)
        if not text:
            return AdviceReport()
        report = parse_report(text)
        return AdviceReport(
            summary=report.summary,
            advices=tuple(self.filter_ignored(list(report.advices))),
        )

    def structured_advice(self, days: int = 1) -> List:
        """只取建议列表（`structured_report` 的兼容版，老调用方还在用）。"""
        return list(self.structured_report(days).advices)

    def filter_ignored(self, advices: List) -> List:
        """去掉用户已忽略的建议（按指纹）。

        页面拿到「刚生成完的新建议」时也要走这里 —— 否则刚忽略完的建议
        会在下一次生成后立刻复活。
        """
        ignored = self.ignored_fingerprints()
        if not ignored:
            return list(advices or [])
        return [a for a in (advices or [])
                if getattr(a, "fingerprint", "") not in ignored]

    def ignored_fingerprints(self) -> set:
        if self._store is None:
            return set()
        try:
            return self._store.ignored_fingerprints()
        except Exception:
            return set()

    def ignore_advice(self, fingerprint: str, headline: str = "") -> bool:
        """忽略一条建议（长期生效）。返回是否写成功。

        只写「别再出现」的标记。**完整的决策留痕走 `record_decision()`** ——
        那里才记录用户凭什么忽略、当时数据什么样。两条都写，但分工不同：
        这个管过滤，那个管审计。
        """
        if self._store is None or not fingerprint:
            return False
        try:
            self._store.ignore_advice(str(fingerprint), str(headline or ""))
        except Exception:
            return False
        return True

    # ----- 人机协同决策留痕（采纳 / 忽略的证据链）-----

    def record_decision(self, advice, action: str, *, outcome=None,
                        days: int = 1) -> Tuple[bool, str]:
        """为用户的一次决定留痕，返回 `(成功, 给人看的一句话)`。

        为什么留痕在这里做，而不是在页面里
            页面只有一个 `Advice` 对象；「当时的数据现场」只有插件拿得到
            （分段、缓存建议的生成时间、专注是否在跑）。放在这里，
            留痕的完整性不依赖某个界面记得传参。

        `outcome` 只对采纳有意义：`{"focus_started": bool, "focus_minutes": int}`。
        它让「点了采纳但计时已经在跑」这种情况被如实记下来 ——
        记成「已开始」会是一条假证据，比不记更糟。
        """
        if self._store is None or advice is None:
            return False, "采集未开启，无法记录这次决定"
        if action not in ACTIONS:
            return False, f"未知的决定类型：{action}"
        try:
            context = build_context(
                days, self._segments_for(days),
                summary=self._cached_summary(days),
                advice_created_at=self._advice_created_at(self._scope_for(days)),
                advice_stale=self.advice_is_stale(days),
                focus_running=self.focus_running(),
                generated_by="activity_advisor",
            )
            note = build_note(advice, action, context=context, outcome=outcome)
        except ValueError as e:
            return False, f"留痕失败：{e}"
        except Exception as e:  # noqa: BLE001 —— 留痕失败不该让用户的点击没反应
            return False, f"留痕失败：{type(e).__name__}: {e}"

        try:
            self._store.record_decision(
                note.fingerprint, note.headline, note.action, json.dumps(
                    note.to_dict(), ensure_ascii=False)
            )
        except Exception as e:  # noqa: BLE001
            return False, f"留痕写入失败：{type(e).__name__}: {e}"

        if action == ACTION_IGNORE:
            # 「别再出现」的标记必须一起写，否则忽略只进了留痕、建议还在。
            self.ignore_advice(note.fingerprint, note.headline)
        return True, self._decision_message(note)

    @staticmethod
    def _decision_message(note: DecisionNote) -> str:
        if note.action == ACTION_ADOPT:
            return "已记录这次采纳：依据、当时的数据与影响都已留档。"
        return "已忽略这条建议，并记录本次决定（依据与上下文留档）。"

    def decision_log(self, limit: int = 200, action: str = "") -> List[DecisionNote]:
        """决策留痕（新的在前）。`action` 传 `adopt` / `ignore` 可过滤。

        解析也在这里做一次 —— 页面拿到的直接是可显示的 `DecisionNote`，
        不需要各自 json.loads（那是第二次实现，迟早有一处漏掉缺省值）。
        """
        if self._store is None:
            return []
        try:
            rows = self._store.decisions(limit=limit, action=action or None)
        except Exception:
            return []
        notes: List[DecisionNote] = []
        for row in rows:
            note = _parse_note(row)
            if note is not None:
                notes.append(note)
        return notes

    def count_decisions(self, action: str = "") -> int:
        if self._store is None:
            return 0
        try:
            return self._store.count_decisions(action or None)
        except Exception:
            return 0

    def export_decisions(self) -> str:
        """把留痕导成一份审计文本（界面直接写文件）。"""
        return format_notes(self.decision_log(limit=100000))

    def _cached_summary(self, days: int) -> str:
        """当前缓存建议自带的那段总结（没有则空串）。"""
        text = self.cached_advice(days)
        if not text:
            return ""
        try:
            return parse_report(text).summary
        except Exception:  # noqa: BLE001 —— 总结拿不到不影响留痕
            return ""

    def _advice_created_at(self, scope: str) -> float:
        """这条建议是什么时候生成的（没有缓存则 0）。"""
        if self._store is None:
            return 0.0
        try:
            row = self._store.get_advice(scope) or {}
            return float(row.get("created_at") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def generate(self, days: int = 1) -> str:
        """生成建议。返回一句给用户看的状态（空串表示已成功发起）。"""
        if not self._enabled or self._store is None:
            return "采集未开启，无法分析"
        segments = self._segments_for(days)
        summary = build_summary(segments)
        if any(marker in summary for marker in _EMPTY_MARKERS):
            return "记录太少，先正常用一会儿电脑再来"
        if not self._ensure_manager():
            return "AI 未就绪（可能没配 API Key）"

        self._pending_scope = self._scope_for(days)
        self._pending_signature = self._data_signature(days)
        self._pending_text = ""
        self._broadcast("set_advice", "")
        self._broadcast("set_analyzing", True)
        self._broadcast("set_status", "正在分析…（摘要已发送到 AI 服务）")
        try:
            self._active_session = self._manager.ask(
                build_advisor_prompt(summary, days=days),
                preset=ADVISOR_PRESET,
                # 活动分析不进会话历史 —— 否则「会话历史」页会被每天的日报刷屏
                persist=False,
            )
        except Exception as e:  # noqa: BLE001
            self._broadcast("set_analyzing", False)
            return f"发起分析失败：{type(e).__name__}"
        return ""

    def clear_data(self) -> int:
        """清空行为数据（分段 + 建议缓存）。返回删除的分段条数。"""
        if self._store is None:
            return 0
        removed = self._store.clear()
        self._last_nudged_at = None
        return removed

    def start_focus(self, minutes: int = 25) -> bool:
        """开始一个专注时段（把建议变成动作，而不是又一段文字）。

        复用番茄钟插件挂在 `app.timer` 上的实例 —— 不新建计时器，
        否则会和番茄钟页显示的状态对不上。

        分钟数必须**显式传下去**：建议卡上的按钮写着「开始 45 分钟专注」，
        点下去就得是 45 分钟（P2.18 之前这里丢掉了这个参数，实际跑 25 分钟）。
        """
        timer = getattr(self.app, "timer", None)
        if timer is None:
            return False
        try:
            if timer.is_running():
                return False
            return bool(timer.start("work", minutes=int(minutes)))
        except Exception:
            return False

    def focus_running(self) -> bool:
        """专注计时是否在跑（页面 / 常驻指示据此决定要不要画专注态）。"""
        timer = getattr(self.app, "timer", None)
        if timer is None:
            return False
        try:
            return bool(timer.is_running() or timer.is_paused())
        except Exception:
            return False

    def last_nudged_at(self) -> Optional[float]:
        return self._last_nudged_at

    # ----- 采集 -----

    def _start_collecting(self) -> None:
        if self._tracker is not None:
            return
        cfg = self.app.config

        self._store = ActivityStore()
        # 启动时先按保留期清一次，避免库随时间无限增长
        try:
            self._store.prune(_cfg_number(cfg, "activity.retention_days", 7, int))
        except Exception:
            pass
        self._last_nudged_at = self._read_last_nudge()

        self._tracker = ActivityTracker(
            self._store,
            key_rate_provider=self._key_rate,
            idle_provider=self._idle,
            exclude_apps=list(cfg.get("activity.exclude_apps", []) or []),
            min_segment_seconds=_cfg_number(
                cfg, "activity.min_segment_seconds", 5.0
            ),
            away_seconds=_cfg_number(cfg, "activity.away_seconds", 300.0),
        )
        event_bus.subscribe("WINDOW_ACTIVE", self._on_window_active)
        event_bus.subscribe("TIME_TICK", self._on_tick)

    def _stop_collecting(self) -> None:
        if self._tracker is None and self._store is None:
            return
        try:
            event_bus.unsubscribe("WINDOW_ACTIVE", self._on_window_active)
        except Exception:
            pass
        try:
            event_bus.unsubscribe("TIME_TICK", self._on_tick)
        except Exception:
            pass
        try:
            if self._tracker is not None:
                self._tracker.flush()      # 把当前段收尾，别丢掉最后一段
        except Exception:
            pass
        self._tracker = None
        if self._store is not None:
            self._store.close()
            self._store = None

    def _on_window_active(self, event) -> None:
        """事件总线回调 —— 必须极快，只做一次 record()。"""
        tracker = self._tracker
        if tracker is None:
            return
        data = (event or {}).get("data") or {}
        try:
            tracker.record(data.get("process", ""), data.get("category", "其他"))
        except Exception:
            pass

    def _on_tick(self, event=None) -> None:
        """`TIME_TICK`（5 分钟一次）：驱动空闲检查 + 收工小结。"""
        tracker = self._tracker
        if tracker is None:
            return
        try:
            tracker.tick()
        except Exception:
            pass
        try:
            self._maybe_nudge()
        except Exception:
            pass

    def _key_rate(self) -> int:
        """取当前敲击频率 —— 复用主程序的 InputMonitor，不自己装钩子。"""
        monitor = getattr(self.app, "input_monitor", None)
        if monitor is None:
            return 0
        try:
            return int(monitor.get_key_rate())
        except Exception:
            return 0

    def _idle(self) -> float:
        from engine.activity import system_idle_seconds

        return system_idle_seconds()

    # ----- 收工小结 -----

    def _maybe_nudge(self) -> None:
        """一天最多推一次「收工小结」，且有一串免打扰条件。"""
        now = time.time()
        start, end = today_range(now)
        try:
            has_data = bool(self._store.segments_between(start, end))
        except Exception:
            has_data = False

        ok, _reason = should_nudge(
            now=now,
            enabled=self._enabled,
            nudge_enabled=bool(self.app.config.get("activity.nudge_enabled", True)),
            nudge_hour=_cfg_number(self.app.config, "activity.nudge_hour", 18, int),
            last_nudged_at=self._last_nudged_at,
            has_data_today=has_data,
            fullscreen=self._is_fullscreen(),
            timer_running=self._is_timer_running(),
            away=bool(self._tracker is not None and self._tracker.is_away()),
        )
        if not ok:
            return

        self._last_nudged_at = now
        try:
            self._store.set_meta(_LAST_NUDGE_KEY, str(now))
        except Exception:
            pass
        if self._bridge is not None:
            self._bridge.nudge.emit("今日小结", self._nudge_text())

    def _nudge_text(self) -> str:
        now = time.time()
        start, end = today_range(now)
        try:
            total = sum(float(s.get("seconds") or 0.0)
                        for s in self._store.segments_between(start, end))
        except Exception:
            total = 0.0
        return (f"今天已记录 {human_duration(total)}。"
                "打开控制中心 →「活动建议」看看小结与建议。")

    def _show_nudge(self, title: str, body: str) -> None:
        """在主线程弹托盘气泡（**不抢焦点、不弹窗**）。"""
        tray = getattr(self.app, "tray_icon", None)
        if tray is not None:
            try:
                tray.show_message(title, body, 6000)
            except Exception:
                pass
        # 页面正开着就顺手刷新一下状态行
        self._broadcast("set_status", body)

    def _read_last_nudge(self) -> Optional[float]:
        if self._store is None:
            return None
        raw = self._store.get_meta(_LAST_NUDGE_KEY)
        try:
            return float(raw) if raw else None
        except (TypeError, ValueError):
            return None

    def _is_fullscreen(self) -> bool:
        try:
            from sensor.window_monitor import is_foreground_fullscreen

            return bool(is_foreground_fullscreen())
        except Exception:
            return False

    def _is_timer_running(self) -> bool:
        timer = getattr(self.app, "timer", None)
        try:
            return bool(timer is not None and timer.is_running())
        except Exception:
            return False

    # ----- 分析 -----

    def _ensure_manager(self) -> bool:
        """按配置构建 / 重建 SessionManager（配置变了才重建）。"""
        sig = self._signature()
        if self._manager is not None and sig == self._config_sig:
            return True
        try:
            from engine.ai import build_from_config

            if self._manager is not None:
                self._manager.shutdown()
            self._manager = build_from_config(self.app.config)
            self._manager.chunk.connect(self._on_chunk)
            self._manager.done.connect(self._on_done)
            self._manager.error.connect(self._on_error)
            self._config_sig = sig
            return True
        except Exception:
            self._manager = None
            return False

    def _signature(self):
        """配置指纹 —— 只取 key 的前 4 位，避免完整密钥在内存里多留一份。"""
        cfg = self.app.config
        return (
            cfg.get("ai.provider", ""),
            cfg.get("ai.base_url", ""),
            cfg.get("ai.model", ""),
            str(cfg.get("ai.api_key", "") or "")[:4],
            bool(cfg.get("ai.enabled", True)),
        )

    def _data_signature(self, days: int) -> str:
        """数据指纹：条数 + 总秒数 + 起止时间 + **手动归类**。任一变化都说明记录变了。

        用途：缓存建议只在**数据真的变了**时才重算 ——
        否则每次打开页面都重新调一次模型，既慢又费钱。

        为什么手动归类也要进指纹
            摘要里有「按类别」那一段，深度工作时长也按类别算。用户把
            chrome.exe 从「其他」改成「工作」之后，摘要内容变了，但条数 /
            总时长 / 起止**一个都没变** —— 指纹不变的话，页面上那份建议
            就是照着旧分类写的，而且不会被标成「已过期」，用户看到的
            是一份与他刚做的修改相矛盾的文字，还查不出原因。
        """
        segments = self._segments_for(days)
        if not segments:
            return "0"
        total = sum(float(s.get("seconds") or 0.0) for s in segments)
        start = min(float(s.get("start_at") or 0.0) for s in segments)
        end = max(float(s.get("end_at") or 0.0) for s in segments)
        override = ";".join(
            f"{k}={v}" for k, v in sorted(self.app_categories().items())
        )
        return f"{len(segments)}:{int(total)}:{int(start)}:{int(end)}:{override}"

    def _segments_for(self, days: int) -> List[dict]:
        """取「最近 N 个**自然日**」的分段。

        用 `since_for_days` 而不是 `now - days*86400` —— 后者是滚动窗口，
        日报会混进昨天的数据（见 `engine.activity.schedule`）。
        """
        if self._store is None:
            return []
        return self._store.segments_since(since_for_days(days, time.time()))

    @staticmethod
    def _scope_for(days: int) -> str:
        return _SCOPE_DAY if int(days) <= 1 else _SCOPE_WEEK

    def _on_chunk(self, sid: str, delta: str) -> None:
        if sid != self._active_session:
            return
        self._pending_text += delta
        if self._bridge is not None:
            self._bridge.chunk.emit(delta)

    def _on_done(self, sid: str, full: str) -> None:
        if sid != self._active_session:
            return
        text = full or self._pending_text
        if self._store is not None and text:
            try:
                self._store.save_advice(
                    self._pending_scope, self._pending_signature, text
                )
            except Exception:
                pass
        if self._bridge is not None:
            self._bridge.done.emit(text)
            self._bridge.analyzing.emit(False)
            self._bridge.status.emit("分析完成（已缓存，下次打开直接可见）")

    def _on_error(self, sid: str, message: str) -> None:
        if sid != self._active_session:
            return
        if self._bridge is not None:
            self._bridge.analyzing.emit(False)
            self._bridge.status.emit(f"分析失败：{str(message)[:80]}")

    # ----- 广播到视图（主线程）-----

    def _broadcast(self, method: str, *args) -> None:
        for view in list(self._views):
            fn = getattr(view, method, None)
            if fn is None:
                continue
            try:
                fn(*args)
            except Exception:
                pass

    def _dispatch_chunk(self, delta: str) -> None:
        self._broadcast("append_advice", delta)

    def _dispatch_done(self, text: str) -> None:
        self._broadcast("set_advice", text)

    def _dispatch_error(self, message: str) -> None:
        self._broadcast("set_status", message)

    def _dispatch_status(self, text: str) -> None:
        self._broadcast("set_status", text)

    def _dispatch_analyzing(self, running: bool) -> None:
        self._broadcast("set_analyzing", running)

    # ----- 对话框 -----

    def _open(self) -> None:
        """打开控制中心的「今日」页。

        为什么不再弹自己的对话框（P2.14）
            「今日」已经升级成主窗口的一等页面。插件再弹一个功能重复的
            对话框，就成了**两个互不同步的孤岛** —— 同一份数据两套 UI，
            改一处忘一处。控制中心起不来时才退回自己的对话框，
            保证插件单独也能用。
        """
        try:
            from presentation.control_center import open_control_center

            win = open_control_center(self.app)
            goto = getattr(win, "goto", None)
            if callable(goto):
                goto("今日")
            return
        except Exception:  # noqa: BLE001 —— UI 起不来不该让插件整个失效
            pass
        self._open_dialog()

    def _open_dialog(self) -> None:
        if self._dialog is None:
            self._dialog = ActivityAdvisorDialog(
                target_label=self._target_label(),
                enabled=self._enabled,
                parent=self._parent_window(),
            )
            self._dialog.analyze_requested.connect(self._on_analyze)
            self._dialog.clear_requested.connect(self._on_clear)
            self._dialog.range_changed.connect(lambda _days: self._refresh_overview())
            self.attach_view(self._dialog)
            self._dialog.finished.connect(lambda _r: self.detach_view(self._dialog))
        self._refresh_overview()
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()

    def _refresh_overview(self) -> None:
        if self._dialog is None:
            return
        if self._store is None:
            self._dialog.set_status("采集未开启")
            return
        days = self._dialog.selected_days()
        self._dialog.set_overview(self.overview(days))
        self._dialog.set_status(f"本地共 {self._store.count()} 段记录")

    def _on_analyze(self, days: int) -> None:
        if self._dialog is not None and self._store is not None:
            self._dialog.set_overview(self.overview(days))
        message = self.generate(days)
        if message and self._dialog is not None:
            self._dialog.set_analyzing(False)
            self._dialog.set_status(message)

    def _on_clear(self) -> None:
        if self._dialog is None:
            return
        if self._store is None:
            self._dialog.set_status("采集未开启，没有数据")
            return
        removed = self.clear_data()
        self._dialog.set_advice("")
        self._refresh_overview()
        self._dialog.set_status(f"已清空 {removed} 条记录")

    # ----- 辅助 -----

    def _target_label(self) -> str:
        """给用户看的「数据发到哪」标签。"""
        base = str(self.app.config.get("ai.base_url", "") or "").strip()
        model = str(self.app.config.get("ai.model", "") or "").strip()
        if not base:
            return ""
        return f"{base}（模型 {model}）" if model else base

    def _parent_window(self):
        ui = getattr(self.app, "ui_manager", None)
        return getattr(ui, "window", None) if ui is not None else None
