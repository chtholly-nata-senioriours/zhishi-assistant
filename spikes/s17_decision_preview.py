# -*- coding: utf-8 -*-
"""S17：「协同记录」页 + 密钥保存位置控件目检（v1.8.0）。

为什么必须单独看一眼
    这一页卖的就是「**可解释**」三个字。规格断言能证明「有几行、点一下出什么」，
    证明不了「推荐依据 / 上下文 / 影响范围三段读起来是不是一份能交给别人看的凭据」
    「筛选器挤不挤」「详情区高度够不够」。密钥那两档同理：
    「明文」这一档的**代价写没写清楚**、脱敏后的样子像不像一把钥匙，只能看图。

两条纪律（沿用 S13 / S15 / S16，各踩过一次）
    ① **假数据也要走真实构造路径**：留痕用 `build_note()` 真造，
       不手搓 dict —— 手搓的话预览图里的字段与真实留痕一旦漂移，
       这张图就开始骗人（而它本来是用来说服人的）。
    ② 渲染前提：不设 `QT_QPA_PLATFORM=offscreen`（中文会变豆腐块）；
       必须先 `install(app)` 再 `set_theme()`；快照前 `show()` 且窗口
       **挪到屏幕外**（`move(-4000, -4000)`），不然会在用户桌面上闪一下。

数据安全
    在 import 任何项目模块**之前**把 `PET_DEMO_HOME` 指到新建临时目录。
    预览里那把钥匙是**假**的（`sk-preview-…`），并且真的走 DPAPI 写进
    **临时目录** —— 不碰用户的系统凭据库、不碰 `~/.pet_demo`。
    （若某台机器的后端是 `keyring`，本脚本**跳过**写入：往用户真实的
    系统凭据库里塞假条目是越界的，宁可少一张图。）

产物：spikes/results/ui_design/
    decisions_{light,dark}.png        整页：协同记录（3 条留痕 + 选中第一条看详情）
    decisions_empty_light.png         整页：一条都没有时的空状态
    key_store_light.png               密钥「保存位置 = 系统密钥库」的样子（脱敏后）
    key_plain_light.png               密钥「保存位置 = 配置文件（明文）」的样子（退路）

用法：python dev_bootstrap.py spikes/s17_decision_preview.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ============================================================
# 必须在 import 项目模块**之前**换数据根 —— 模块级代码，不是函数。
# config_manager 是进程级单例，import 那一刻就 _load_config() → save()。
# ============================================================
_PREVIEW_HOME = Path(tempfile.mkdtemp(prefix="s17_decision_home_"))
os.environ["PET_DEMO_HOME"] = str(_PREVIEW_HOME)

#: 假的钥匙 —— 只为看清「脱敏之后长什么样」。绝不写成任何真实 key 的形状。
FAKE_KEY = "sk-preview-not-a-real-key-0123456789"
FAKE_ENTRY = "api.deepseek.com"


def _seed_key() -> None:
    """把假钥匙真的存一次（走 DPAPI 真实路径，落在临时数据根里）。

    为什么不留空让界面显示「（未设置）」：那样就看不到脱敏的样子，
    而这正是这一档最需要目检的地方。
    """
    from data import key_store

    if key_store.backend_name() == "dpapi":
        ok, why = key_store.store_key(FAKE_ENTRY, FAKE_KEY)
        print(f"[种数据] 假钥匙 → {'已写入' if ok else '写入失败'}（{why}）")
    else:
        # 后端是 keyring 时**不写** —— 那会往用户真实的系统凭据库里塞假条目
        print(f"[种数据] 后端是 {key_store.backend_name()}，跳过写入（不污染用户的凭据库）")


_seed_key()

from PySide6.QtGui import QColor, QImage                                  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget                       # noqa: E402

from engine.activity import (                                             # noqa: E402
    ACTION_ADOPT,
    ACTION_IGNORE,
    Advice,
    AdviceAction,
    build_context,
    build_note,
    format_notes,
)
from presentation.design import install, set_theme                        # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "results" / "ui_design"
OUT_DIR.mkdir(parents=True, exist_ok=True)

#: 衬底颜色 —— 与窗口底色拉开，控件的描边 / 圆角 / 留白才看得出来（S13 同款）
_BACKDROP = {"light": "#B9C6DA", "dark": "#3E4859"}

app = QApplication.instance() or QApplication([])
install(app)


# ============================================================
# 假留痕 —— 用 `build_note()` 真造（见 docstring 纪律 ①）
# ============================================================

def _segments(count: int, seconds: float, base: float) -> list[dict]:
    return [{"app": "code.exe", "category": "工作", "start_at": base + i * 900,
             "end_at": base + i * 900 + seconds, "seconds": seconds}
            for i in range(count)]


def _fake_notes() -> list:
    """三条留痕：采纳（真开始了专注）/ 采纳（计时已在跑）/ 忽略。

    刻意造出**三种不同的影响范围** —— 只有它们并排出现，才看得出
    「记的是实际结果」这件事在界面上是有区别的。
    """
    now = time.time()
    deep = Advice(
        headline="上午的深度工作被切成 4 段，每段不到 40 分钟",
        evidence=("微信在 08:00–12:00 打断 9 次", "VS Code 最长连续 1h30m"),
        action=AdviceAction(kind="focus", minutes=45, label="开始 45 分钟专注"),
    )
    afternoon = Advice(
        headline="下午 15:00 后节奏变碎，切换了 11 次窗口",
        evidence=("其中 7 次在 VS Code 与 Chrome 之间来回", "平均停留 8 分钟"),
        action=AdviceAction(kind="focus", minutes=25, label="开始 25 分钟专注"),
    )
    night = Advice(
        headline="22:00 之后仍有 50 分钟前台活跃，建议提前收工",
        evidence=("近 7 天有 4 天在 22:00 后继续工作",),
        action=AdviceAction(kind="none", minutes=0),
    )
    ctx = lambda n, sec, base, **kw: build_context(  # noqa: E731
        1, _segments(n, sec, base), generated_by="activity_advisor", **kw)

    return [
        build_note(deep, ACTION_ADOPT,
                   context=ctx(4, 2400, now - 6 * 3600, advice_created_at=now - 7 * 3600),
                   outcome={"focus_started": True, "focus_minutes": 45},
                   now=now - 5 * 3600),
        build_note(afternoon, ACTION_ADOPT,
                   context=ctx(9, 600, now - 3 * 3600, advice_created_at=now - 4 * 3600,
                               advice_stale=True),
                   outcome={"focus_started": False, "focus_minutes": 25},
                   now=now - 2 * 3600),
        build_note(night, ACTION_IGNORE,
                   context=ctx(6, 900, now - 90 * 60, advice_created_at=now - 2 * 3600,
                               focus_running=True),
                   now=now - 45 * 60),
    ]


# ============================================================
# 测试替身
# ============================================================

class _StubPlugin:
    """够「协同记录」页用的假活动插件（鸭子类型，见 `_activity_plugin`）。

    为什么不用真插件：真插件会打开 `~/.pet_demo/activity.db` ——
    那是**用户真实的使用记录**，渲染进图片就等于把隐私画出来了。
    控制中心对插件本来就是鸭子类型调用，所以一个普通对象就能当插件用。

    除留痕那几个方法外，其余是**控制中心构造时其它页会顺手调到的**
    （今日页要 `segments_for` / 隐私页要 `retention_days` …），
    少一个就会在 `ControlCenter.__init__` 里当场崩 —— 预览脚本也不例外。
    `set_enabled` 不能省：`_activity_plugin()` 拿它当「这真是个活动插件」的判据。
    """

    def __init__(self, notes):
        self._notes = list(notes)

    # ----- 留痕（本脚本真正要看的东西）-----

    def decision_log(self, limit: int = 200, action: str = "") -> list:
        items = [n for n in self._notes if not action or n.action == action]
        return list(reversed(items))[:limit]      # 新的在前（与真实实现同序）

    def count_decisions(self, action: str = "") -> int:
        return len([n for n in self._notes if not action or n.action == action])

    def export_decisions(self) -> str:
        return format_notes(self._notes)

    # ----- 其它页顺手会调到的 -----

    def is_enabled(self) -> bool:
        return True

    def set_enabled(self, *_a, **_k) -> bool:
        return True

    def attach_view(self, view) -> None:
        self._view = view

    def retention_days(self) -> int:
        return 30

    def segments_for(self, days: int = 1) -> list:
        return []

    def cached_advice(self, days: int = 1) -> str:
        return ""

    def advice_is_stale(self, days: int = 1) -> bool:
        return False

    def ignored_fingerprints(self) -> set:
        return set()

    def filter_ignored(self, advices) -> list:
        return list(advices or [])

    def generate(self, days: int = 1) -> str:
        return ""

    def start_focus(self, minutes: int = 25) -> bool:
        return True

    def clear_data(self) -> int:
        return 0

    def app_totals(self, days: int = 7) -> list:
        """「应用分类」页要读这个（v1.9.0 新增页面）。

        控制中心的 `reload()` 是**全量**刷新的，缺了这个方法会 AttributeError，
        哪怕本脚本只渲染「协同记录」页。
        """
        return []

    def app_categories(self) -> dict:
        return {}


class _StubPluginManager:
    def __init__(self, plugin):
        self._plugin = plugin

    def get_plugin(self, name):
        return self._plugin if name == "activity_advisor" else None

    def get_all_plugins(self):
        # 必须返回空：状态栏会去读每个插件的 `manifest`，假插件没有那东西
        return {}


class _FakeConfig:
    """`ConfigManager` 的最小替身（表单只 get / set / save）。"""

    def __init__(self, values):
        self.vals = values
        self.saved = 0

    def get(self, key, default=None):
        cur = self.vals
        for part in key.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur

    def set(self, key, value):
        parts = key.split(".")
        cur = self.vals
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = value

    def save(self):
        self.saved += 1


# ============================================================
# 渲染
# ============================================================

def _snap(widget: QWidget, name: str, theme_name: str) -> None:
    widget.move(-4000, -4000)          # 离屏渲染，别在用户桌面上闪窗口
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


def _snap_page(notes, name: str, theme_name: str, *, height: int = 780,
               select_first: bool = False) -> None:
    """渲染整页（含左侧导航）。

    会话历史页会去读 `ai.db` —— 换成临时库，免得预览脚本碰用户的真实会话
    （S13 同款做法）。
    """
    import engine.ai as engine_ai
    from engine.ai.store import Store as AIStore
    from presentation.control_center import ControlCenter, reset_instance

    engine_ai.shared_store = lambda *a, **k: AIStore(
        Path(tempfile.mkdtemp(prefix="s17_preview_")) / "preview.db")

    fake_app = types.SimpleNamespace(
        plugin_manager=_StubPluginManager(_StubPlugin(notes)))

    reset_instance()
    cc = ControlCenter(app=fake_app)
    cc.resize(1060, height)
    cc.goto("协同记录")
    if select_first:
        # 选中第一行 → 详情区展开「这一条决定的完整留痕」。
        # 不选的话那块是空的占位提示，图里看不出它长什么样。
        page = next(p for p in cc._pages if p.title == "协同记录")
        page._table.selectRow(0)
        app.processEvents()
    _snap(cc, name, theme_name)


def _snap_key_form(name: str, theme_name: str, *, keyring_mode: bool) -> None:
    """密钥「保存位置」两档的样子。

    密钥库那一档读的是刚种进去的假钥匙（真脱敏）；明文那一档给一份
    带 `api_key` 的旧配置 —— 老用户打开设置时看到的就是这个。
    """
    from data import key_store
    from presentation.ai_config_form import AIConfigForm

    if keyring_mode:
        values = {"ai": {"provider": "openai_compat",
                         "base_url": f"https://{FAKE_ENTRY}/v1",
                         "model": "deepseek-chat",
                         "vision_model": "",
                         "api_key": "",
                         "api_key_ref": key_store.ref_for(FAKE_ENTRY),
                         "request_timeout": 120}}
    else:
        values = {"ai": {"provider": "openai_compat",
                         "base_url": "https://api.siliconflow.cn/v1",
                         "model": "inclusionAI/Ling-flash-2.0",
                         "vision_model": "",
                         "api_key": FAKE_KEY,
                         "api_key_ref": "",
                         "request_timeout": 120}}

    form = AIConfigForm(config=_FakeConfig(values))
    form.resize(640, 470)
    _snap(form, name, theme_name)


def main() -> int:
    notes = _fake_notes()

    for theme_name in ("light", "dark"):
        set_theme(theme_name, persist=False)
        _snap_page(notes, f"decisions_{theme_name}", theme_name, select_first=True)

    set_theme("light", persist=False)
    _snap_page([], "decisions_empty_light", "light")
    _snap_key_form("key_store_light", "light", keyring_mode=True)
    _snap_key_form("key_plain_light", "light", keyring_mode=False)

    print()
    print("RESULT: 请人工确认")
    print("  1. 表格四列（时间 / 决定 / 结论 / 影响范围）都读得通，列宽不挤")
    print("  2. 三条留痕的「影响范围」**互不相同** —— 这正是「记实际结果」的证据：")
    print("     第一条「已开始 45 分钟专注」、第二条「未开始专注（计时已在跑…）」、")
    print("     第三条「不影响本机活动记录」")
    print("  3. 详情区把三段（推荐依据 / 上下文 / 影响范围）都摊开了、**长句自动换行**，")
    print("     等宽字体不乱码 —— S17 第一轮这里被右边缘切掉过，故专门钉了一条用例")
    print("  4. 筛选器「全部 / 采纳 / 忽略」与右上角统计口径一致")
    print("  5. 空状态给的是**下一步怎么做**（去今日页点采纳），不是一句冷冰冰的「无数据」；")
    print("     且空态里**不该**同时出现「完整留痕」卡与可点的「导出证据链」")
    print("     —— 第一轮就是同时出现，S17 抓到后才改的")
    print("  6. 密钥库那一档：状态区写着条目名与**脱敏后**的样子（头 3 尾 4，中段 8 个 •），")
    print("     输入框留空且有 placeholder 说明")
    print("  7. 明文那一档：**状态区是空的**（这是有意的 —— 用户 2026-10-14 要求去掉")
    print("     常驻说明）。所以这张图里**看不到**「会随备份被带走」那句；")
    print("     请改为人工核对「保存位置」控件的 tooltip 与**切换那一刻**的状态文案")
    print("     （`_on_key_mode_changed`）是否写清了代价。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
