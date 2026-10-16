# -*- coding: utf-8 -*-
"""S13：今日页 / 趋势页目检（P2.14）。

用**假数据**渲染「今日」页与「趋势」页，浅深两套各出几张 PNG，
供人工目检（规格断言测不出「看起来对不对」）。

为什么用假数据
    这个脚本的产物是给人看的图片。一旦接真实数据，就会把用户真实的
    应用使用记录画进图里（S8 踩过同样的坑：渲染前必须换临时库）。

产物：spikes/results/ui_design/
    today_{light,dark}.png          组件拼装样张（概览 / 时间轴 / 排行 / 建议）
    today_page_{light,dark}.png     整页：今日（含左侧导航分组）
    today_empty_{light,dark}.png    整页：采集关闭时的引导态
    trend_{light,dark}.png          整页：趋势（近 7 天，保留 30 天）
    trend_30d_light.png             整页：趋势（近 30 天 —— 刻度会抽稀）
    trend_short_light.png           整页：趋势（保留 7 天却选近 30 天 —— 底部要提示）
    today_focus_{light,dark}.png    整页：专注进行中（倒计时卡 + 按钮变状态 + 总结块）
    today_focus_paused_{light,dark}.png  整页：专注已暂停（卡片换 warning 语义色）

用法：python dev_bootstrap.py spikes/s13_today_preview.py

两个必须遵守的渲染前提（各踩过一次）
    1. **不要设 QT_QPA_PLATFORM=offscreen** —— offscreen 平台拿不到中文字形，
       渲染出来全是豆腐块，图完全没法目检（S8 注释里已记过这条）。
    2. **必须调 `install(app)`** —— `set_theme()` 只对**已注册**的 QApplication
       重装 QSS / 字体（`_reapply` 遍历 `_installed_apps`）。没调 install 就
       等于什么都没装：中文豆腐块 + 所有 QSS 背景色全部丢失。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QColor, QImage, QPalette               # noqa: E402
from PySide6.QtWidgets import (                                # noqa: E402
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from engine.activity import (                                  # noqa: E402
    DAY_SECONDS,
    Advice,
    AdviceAction,
    day_start,
    focus_seconds,
    human_duration,
    merge_segments,
    since_for_days,
    switch_count,
    today_range,
    top_apps,
    total_seconds,
)
from presentation.design import install, set_theme                # noqa: E402
from presentation.design.theme import theme                       # noqa: E402
from presentation.design.advice_card import AdviceCard        # noqa: E402
from presentation.design.charts import (                       # noqa: E402
    RankBar,
    StatTile,
    TimelineBar,
)
from presentation.design.widgets import SectionLabel           # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "results" / "ui_design"
OUT_DIR.mkdir(parents=True, exist_ok=True)

#: 衬底颜色 —— 刻意与窗口底色拉开（S8 同款）：浅色主题给冷灰蓝、
#: 深色主题给灰蓝，这样控件的描边、圆角、留白才看得出来。
_BACKDROP = {"light": "#B9C6DA", "dark": "#3E4859"}

app = QApplication.instance() or QApplication([])
# 必须先注册，set_theme() 才会真的把 QSS / 字体装上去（见文件头说明）。
install(app)


# ---------------------------------------------------------------- 假数据

def _seg(day: float, app_name: str, cat: str, h1: int, m1: int, h2: int, m2: int) -> dict:
    start = day + h1 * 3600 + m1 * 60
    end = day + h2 * 3600 + m2 * 60
    return {"app": app_name, "category": cat, "start_at": start, "end_at": end,
            "seconds": float(end - start), "key_rate": 0}


def _fake_day() -> list:
    """一天的活动 —— 与设计稿里那张时间轴一致。"""
    day = day_start(time.time())
    return [
        _seg(day, "微信", "沟通", 8, 0, 9, 30),
        _seg(day, "VS Code", "工作", 9, 30, 11, 0),
        _seg(day, "微信", "沟通", 11, 0, 11, 20),
        _seg(day, "Chrome", "浏览", 11, 20, 12, 0),
        # ↓ 下面三段会被合并成一整段 13:30–15:00 ——
        #   后两段是「切走几十秒又切回来」留下的碎片，
        #   不合并的话时间轴上就是两根看不清的细线。
        _seg(day, "VS Code", "工作", 13, 30, 14, 0),
        _seg(day, "VS Code", "工作", 14, 0, 14, 30),
        _seg(day, "VS Code", "工作", 14, 30, 15, 0),
        _seg(day, "微信", "沟通", 15, 0, 15, 30),
        _seg(day, "VS Code", "工作", 15, 30, 17, 0),
    ]


def _fake_advices() -> list:
    return [
        Advice(
            headline="上午的深度工作被切成 4 段，每段不到 40 分钟",
            evidence=("微信在 08:00–12:00 打断 9 次", "VS Code 最长连续 1h30m"),
            action=AdviceAction(kind="focus", minutes=45, label="开始 45 分钟专注"),
        ),
        Advice(
            headline="下午 15:00 后节奏变碎，切换了 11 次窗口",
            evidence=("其中 7 次在 VS Code 与 Chrome 之间来回", "平均停留 8 分钟"),
            action=AdviceAction(kind="focus", minutes=25, label="开始 25 分钟专注"),
        ),
    ]


def _fake_history(days: int = 60) -> list:
    """过去 `days` 天的假历史（**不含今天** —— 今天用 `_fake_day()`）。

    为什么是 60 天
        趋势页最长看近 30 天，还要跟**上一个同长周期**比 —— 所以页面会
        向插件要 `days * 2`，60 天才能把「近 30 天」那张图填满。

    为什么造形状而不是随机数
        随机数看不出对错。这里刻意留出三种形状：
          · 工作日两段深度工作，周末大多整天空着 → 柱状图要有 0 高度的柱子；
          · 每天上午 10 点前后固定切几次 → 「最容易被打断的时段」要有个峰；
          · 有几天的时长明显更长 → 「与上周期对比」那句话要有方向。
    """
    today = day_start(time.time())
    out = []
    for i in range(1, days + 1):
        day = today - i * DAY_SECONDS
        if time.localtime(day).tm_wday >= 5 and i % 3:
            continue                                  # 周末大多不干活 —— 留出空柱
        out.extend([
            _seg(day, "VS Code", "工作", 9, 30, 11, 0),
            _seg(day, "微信", "沟通", 11, 0, 11, 20),     # 上午这几切造出 11 点的峰
            _seg(day, "Chrome", "浏览", 11, 20, 12, 0),
            _seg(day, "VS Code", "工作", 13, 30, 15, 0),
            _seg(day, "微信", "沟通", 15, 0, 15, 30),
            _seg(day, "VS Code", "工作", 15, 30, 17, 0),
        ])
        if i % 5 == 0:                                # 每五天来一个「加班日」
            out.append(_seg(day, "VS Code", "工作", 20, 0, 22, 0))
    return out


# ---------------------------------------------------------------- 组装

def _build(segments: list) -> QWidget:
    root = QWidget()
    root.setObjectName("workspace")
    root.resize(900, 700)
    # 真实应用里页面是透明的，透出控制中心窗口的 window 底色。
    # 预览图没有父窗口，不自己填一层就会露出衬底色（看起来像页面断了半截）。
    pal = root.palette()
    pal.setColor(QPalette.ColorRole.Window, theme().color("window"))
    root.setPalette(pal)
    root.setAutoFillBackground(True)
    lay = QVBoxLayout(root)
    lay.setContentsMargins(16, 16, 16, 16)
    lay.setSpacing(16)

    # --- 概览 4 块 ---
    grid = QGridLayout()
    grid.setSpacing(10)
    tiles = [
        ("今日总时长", human_duration(total_seconds(segments))),
        ("深度工作", human_duration(focus_seconds(segments))),
        ("最长应用", (top_apps(segments, limit=1) or [{"app": "—"}])[0]["app"]),
        ("切换打断", f"{switch_count(segments)} 次"),
    ]
    for i, (label, value) in enumerate(tiles):
        grid.addWidget(StatTile(label, value), 0, i)
    lay.addLayout(grid)

    # --- 时间轴 ---
    start, end = today_range(time.time())
    lay.addWidget(SectionLabel("今天的时间去哪了"))
    timeline = TimelineBar()
    timeline.set_segments(merge_segments(segments), start=start, end=end)
    lay.addWidget(timeline)

    # --- 排行 + 建议 ---
    bottom = QHBoxLayout()
    bottom.setSpacing(16)

    left = QVBoxLayout()
    left.setSpacing(8)
    left.addWidget(SectionLabel("应用排行"))
    rank = RankBar(limit=5)
    rank.set_items(
        [{"label": a["app"], "value": a["seconds"], "category": a["category"]}
         for a in top_apps(segments, limit=5)],
        value_text=human_duration,
    )
    left.addWidget(rank)
    left.addStretch(1)
    bottom.addLayout(left, 1)

    right = QVBoxLayout()
    right.setSpacing(8)
    right.addWidget(SectionLabel("AI 建议"))
    for advice in _fake_advices():
        card = AdviceCard()
        card.set_advice(advice)
        right.addWidget(card)
    right.addStretch(1)
    bottom.addLayout(right, 1)

    lay.addLayout(bottom, 1)
    return root


def _snap(widget: QWidget, name: str, theme_name: str) -> None:
    # show() 才会走 polish —— QSS 的背景色是在这一步套上去的，
    # 光 render() 一个没 show 过的控件会拿到「没上过样式」的样子。
    # 挪到屏幕外，避免在用户桌面上闪一个窗口。
    widget.move(-4000, -4000)
    widget.show()
    app.processEvents()
    app.processEvents()
    img = QImage(widget.size(), QImage.Format.Format_ARGB32)
    img.fill(QColor(_BACKDROP[theme_name]))
    widget.render(img)
    path = OUT_DIR / f"{name}.png"
    img.save(str(path))
    widget.close()
    print(f"[渲染] {path}")


# ---------------------------------------------------------------- 整页目检

class _StubPlugin:
    """给目检脚本用的**假**活动插件。

    为什么不用真插件
        真插件会打开 `~/.pet_demo/activity.db` —— 那是**用户真实的使用记录**，
        渲染进图片就等于把用户隐私画出来了（S8 踩过同样的坑：渲染前必须换临时库）。
        这里只实现「今日」页用到的那几个方法，数据全是编的。

    为什么用鸭子类型就能接上
        控制中心对插件本来就是鸭子类型调用（不 import 插件类）——
        所以一个普通对象就能当插件用，这也是那条设计的直接好处。
    """

    def __init__(self, segments, advice, enabled=True, retention=30):
        self._segments = list(segments)
        self._advice = advice
        self._enabled = bool(enabled)
        self._retention = int(retention)

    def is_enabled(self):
        return self._enabled

    def set_enabled(self, enabled):
        self._enabled = bool(enabled)
        return True

    def attach_view(self, view):
        self._view = view

    def segments_for(self, days=1):
        # 与真插件同口径：按**自然日**窗口切（`since_for_days`，不是 now-N*86400）。
        # 趋势页靠这个拿「本周期 + 上周期」两段，口径不一致就白比了。
        cut = since_for_days(days, time.time())
        return [s for s in self._segments if s["start_at"] >= cut]

    def retention_days(self):
        return self._retention

    def cached_advice(self, days=1):
        return self._advice

    def advice_is_stale(self, days=1):
        return False

    def ignored_fingerprints(self):
        return set()

    def filter_ignored(self, advices):
        return list(advices or [])

    def generate(self, days=1):
        return ""

    def start_focus(self, minutes=25):
        return True

    def clear_data(self):
        return 0


class _StubTimer:
    """假番茄钟 —— 专注卡与悬浮球都靠 `get_status()` 读它。"""

    def __init__(self, remaining: int = 12 * 60 + 34, progress: float = 0.5,
                 paused: bool = False):
        self.status = {
            "state": "paused" if paused else "running",
            "type": "work",
            "remaining": remaining,
            "total": 25 * 60,
            "progress": progress,
            "formatted": f"{remaining // 60:02d}:{remaining % 60:02d}",
            # 番茄钟页会读这个字段（页面级的「今日完成 N 个」）
            "today_count": 3,
        }

    def get_status(self):
        return dict(self.status)

    def is_running(self):
        return self.status["state"] == "running"

    def is_paused(self):
        return self.status["state"] == "paused"


class _StubPluginManager:
    def __init__(self, plugin):
        self._plugin = plugin

    def get_plugin(self, name):
        return self._plugin if name == "activity_advisor" else None

    def get_all_plugins(self):
        # 必须返回空：状态栏的插件数只是预览产物，而「插件」页会去读
        # 每个插件的 `manifest` —— 假插件没有那东西，塞进去会直接崩。
        return {}


def _snap_page(segments, name: str, theme_name: str, *, enabled: bool = True,
               page: str = "今日", range_index: int = 0,
               retention: int = 30, height: int = 700,
               focus: tuple | None = None) -> None:
    """渲染**整页**（含左侧导航分组）—— 组件拼起来的样子才算数。

    `range_index` 只对趋势页有意义（0 = 近 7 天，1 = 近 30 天）。
    `height` 默认 700（真实窗口高度）；想看清折叠线以下的内容
    （如趋势页底部那句「保留多少天」）就调高。
    """
    import tempfile
    import types

    import engine.ai as engine_ai
    from engine.ai.store import Store as AIStore
    from presentation.control_center import ControlCenter, reset_instance

    # 控制中心构造时会建「会话历史」页 —— 换成临时库，
    # 免得预览脚本去读用户的真实会话（同上：不把真实数据画进图里）。
    engine_ai.shared_store = lambda *a, **k: AIStore(
        Path(tempfile.mkdtemp(prefix="s13_preview_")) / "preview.db"
    )

    # P2.18：模型输出改成「总结 + 建议数组」。总结块只在有内容时才画，
    # 所以这里必须给一段真总结，否则目检图里根本看不到那块。
    advice = json.dumps(
        {
            "summary": "今天 5 小时里有 2 小时是深度工作，但上午被切得很碎，"
                       "下午 15:00 之后几乎没连上过 30 分钟。",
            "advices": [
                {"headline": "上午的深度工作被切成 4 段，每段不到 40 分钟",
                 "evidence": ["微信在 08:00–12:00 打断 9 次", "VS Code 最长连续 1h30m"],
                 "action": {"kind": "focus", "minutes": 45,
                            "label": "开始 45 分钟专注"}},
                {"headline": "下午 15:00 后节奏变碎，切换了 11 次窗口",
                 "evidence": ["其中 7 次在 VS Code 与 Chrome 之间来回", "平均停留 8 分钟"],
                 "action": {"kind": "focus", "minutes": 25,
                            "label": "开始 25 分钟专注"}},
            ],
        },
        ensure_ascii=False,
    )
    stub = _StubPlugin(segments, advice, enabled=enabled, retention=retention)
    fake_app = types.SimpleNamespace(plugin_manager=_StubPluginManager(stub))
    if focus is not None:
        fake_app.timer = _StubTimer(*focus)

    reset_instance()
    cc = ControlCenter(app=fake_app)
    cc.resize(1060, height)
    cc.goto(page)
    if focus is not None:
        # 专注卡只在「读得到计时器」时才展开，而它平时靠 showEvent 接上 provider
        # —— 离屏预览里页面没被真正 show，所以要手动接一次。
        target_page = next(p for p in cc._pages if p.title == page)
        target_page._focus_card.set_status_provider(target_page._focus_status)
    if range_index:
        target = next(p for p in cc._pages if p.title == page)
        target._seg_range.set_index(range_index, emit=True)
    _snap(cc, name, theme_name)


def main() -> int:
    segments = _fake_day()
    merged = merge_segments(segments)
    print(f"[数据] 今日 合并前 {len(segments)} 段 → 合并后 {len(merged)} 段")

    # 整页预览用「今天 + 过去 60 天」——趋势页要向插件要 days*2 天。
    past = _fake_history(60)
    history = segments + past
    days_hit = len({int(s["start_at"] // DAY_SECONDS) for s in past})
    print(f"[数据] 今日 {len(segments)} 段；过去 60 天 {len(past)} 段 / {days_hit} 个自然日有记录")

    for theme_name in ("light", "dark"):
        set_theme(theme_name, persist=False)
        _snap(_build(segments), f"today_{theme_name}", theme_name)
        _snap_page(history, f"today_page_{theme_name}", theme_name)
        # 默认关闭采集时的引导态（第一张卡仍然是开关 + 边界说明）
        _snap_page([], f"today_empty_{theme_name}", theme_name, enabled=False)
        _snap_page(history, f"trend_{theme_name}", theme_name, page="趋势")
        # P2.18：专注进行中 —— 倒计时卡 + 顶部按钮变状态 + 环改画本次专注
        _snap_page(history, f"today_focus_{theme_name}", theme_name,
                   focus=(12 * 60 + 34, 0.5))
        _snap_page(history, f"today_focus_paused_{theme_name}", theme_name,
                   focus=(12 * 60 + 34, 0.5, True))

    # 浅色再补两张「边界情形」：刻度抽稀 / 保留天数不够的提示。
    # 后者拉高窗口 —— 那句「数据只在本机，保留最近 N 天」在 700px 窗口里
    # 落在折叠线以下，不拉高根本目检不到。
    set_theme("light", persist=False)
    _snap_page(history, "trend_30d_light", "light", page="趋势", range_index=1)
    _snap_page(history, "trend_short_light", "light", page="趋势",
               range_index=1, retention=7, height=1000)

    # P2.19：专注进行中时**建议卡**长什么样。
    # 700px 窗口里建议卡落在折叠线以下，而这次要修的正是卡片上的按钮 ——
    # 不拉高就等于没目检。两张（进行中 / 已暂停）浅深各一套。
    for theme_name in ("light", "dark"):
        set_theme(theme_name, persist=False)
        _snap_page(history, f"today_focus_cards_{theme_name}", theme_name,
                   focus=(12 * 60 + 34, 0.5), height=1560)
        _snap_page(history, f"today_focus_cards_paused_{theme_name}", theme_name,
                   focus=(12 * 60 + 34, 0.5, True), height=1560)

    print()
    print("RESULT: 已生成预览图，请人工目检")
    return 0


if __name__ == "__main__":
    sys.exit(main())
