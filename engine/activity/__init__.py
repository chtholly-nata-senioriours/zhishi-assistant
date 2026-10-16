# -*- coding: utf-8 -*-
"""活动分析核心层（L2）。

与 `engine/ai` 平级：负责「行为 → 摘要 → 提示词」这一段**纯逻辑**。
不含 UI、不订阅事件、不直接调模型 —— 调用方（插件）负责接线。

设计约束（与 `engine/ai` 一致）
    - **不得 import `presentation` / `extensions` / `native`**（依赖单向向上）。
    - 全部是纯 Python，**零 Qt 依赖**，可脱离 Qt 单测。

快速上手
    from engine.activity import ActivityStore, ActivityTracker, build_summary
    store = ActivityStore()
    tracker = ActivityTracker(store)
    tracker.record("code.exe", "工作")
    tracker.flush()
    print(build_summary(store.segments_since(0)))
"""
from __future__ import annotations

from .advice import (
    ACTION_FOCUS,
    ACTION_NONE,
    ADVICE_JSON_SPEC,
    ALLOWED_FOCUS_MINUTES,
    MAX_ADVICES,
    MAX_EVIDENCE,
    MAX_SUMMARY_CHARS,
    Advice,
    AdviceAction,
    AdviceReport,
    advice_fingerprint,
    advice_to_text,
    is_structured,
    parse_advices,
    parse_report,
)
from .advisor import ADVISOR_PRESET, ADVISOR_SYSTEM_PROMPT, build_advisor_prompt
from .category import (
    CATEGORIES,
    CATEGORY_RULES,
    COMM,
    FOCUS_CATEGORIES,
    FUN,
    OTHER,
    PROCESS_TABLES,
    STUDY,
    TITLE_TABLES,
    WORK,
    apply_overrides,
    classify,
    explain,
    is_valid_category,
    normalize_app,
    process_stem,
)
from .decision import (
    ACTION_ADOPT,
    ACTION_IGNORE,
    ACTIONS,
    ACTION_LABELS,
    CONTEXT_KEYS,
    DecisionNote,
    build_context,
    build_note,
    format_context,
    format_notes,
)
from .idle import system_idle_seconds
from .reminder import DEFAULT_NUDGE_HOUR, should_nudge
from .schedule import (
    clock_hour,
    day_start,
    human_day,
    same_day,
    since_for_days,
    today_range,
)
from .store import DAY_SECONDS, ActivityStore, default_db_path
from .summary import (
    DEFAULT_TOP_APPS,
    build_summary,
    human_duration,
    longest_focus_seconds,
)
from .timeline import (
    DEFAULT_MERGE_GAP,
    HOURS_PER_DAY,
    WORK_CATEGORY,
    busiest_hour,
    category_totals,
    compare_periods,
    daily_totals,
    focus_seconds,
    hour_label,
    hour_of_day,
    hour_switches,
    merge_segments,
    period_bounds,
    switch_count,
    top_apps,
    total_seconds,
    weekday_label,
)
from .tracker import DEFAULT_AWAY_SECONDS, DEFAULT_MIN_SEGMENT_SECONDS, ActivityTracker

__all__ = [
    # 存储
    "ActivityStore", "default_db_path", "DAY_SECONDS",
    # 分段
    "ActivityTracker", "DEFAULT_MIN_SEGMENT_SECONDS", "DEFAULT_AWAY_SECONDS",
    # 摘要
    "build_summary", "human_duration", "longest_focus_seconds", "DEFAULT_TOP_APPS",
    # 结构化建议
    "Advice", "AdviceAction", "parse_advices", "advice_to_text",
    "advice_fingerprint", "is_structured", "ADVICE_JSON_SPEC",
    "ACTION_FOCUS", "ACTION_NONE", "ALLOWED_FOCUS_MINUTES", "MAX_ADVICES", "MAX_EVIDENCE",
    # 总结 + 建议（一次生成的完整结果）
    "AdviceReport", "parse_report", "MAX_SUMMARY_CHARS",
    # 人机协同决策留痕（采纳 / 忽略的证据链）
    "DecisionNote", "build_note", "build_context", "format_notes", "format_context",
    "ACTION_ADOPT", "ACTION_IGNORE", "ACTIONS", "ACTION_LABELS", "CONTEXT_KEYS",
    # 预设与提示词
    "ADVISOR_PRESET", "ADVISOR_SYSTEM_PROMPT", "build_advisor_prompt",
    # 自然日语义
    "day_start", "same_day", "since_for_days", "today_range", "clock_hour", "human_day",
    # 时间轴 / 趋势聚合
    "merge_segments", "daily_totals", "category_totals", "top_apps",
    "total_seconds", "focus_seconds", "switch_count", "weekday_label",
    "WORK_CATEGORY", "DEFAULT_MERGE_GAP",
    # 分类口径（工作 / 学习 / 沟通 / 娱乐 / 其他）+ 用户手动归类
    "CATEGORIES", "CATEGORY_RULES", "FOCUS_CATEGORIES",
    "WORK", "STUDY", "COMM", "FUN", "OTHER",
    "PROCESS_TABLES", "TITLE_TABLES",
    "classify", "explain", "process_stem", "normalize_app",
    "is_valid_category", "apply_overrides",
    # 按小时的打断分布 + 周期对比（趋势页）
    "hour_of_day", "hour_label", "hour_switches", "busiest_hour", "HOURS_PER_DAY",
    "period_bounds", "compare_periods",
    # 空闲信号
    "system_idle_seconds",
    # 收工小结时机
    "should_nudge", "DEFAULT_NUDGE_HOUR",
]
