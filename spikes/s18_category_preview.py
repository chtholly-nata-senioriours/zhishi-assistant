# -*- coding: utf-8 -*-
"""S18：「应用分类」页目检（v1.9.0）。

为什么必须单独看一眼
    这一页同时承担两件事：**说明分类口径**（五个分类项与各自的判定依据）
    和**纠正判定**（逐应用下拉归类）。规格断言能证明「有几行、选一下写没写库」，
    证明不了：
        · 五条判定依据铺在一张卡里读不读得下去（有没有挤成一团 / 被截断）；
        · 「系统判定」与「你的归类」两列并排时，**改过的行**是否一眼可辨；
        · 下拉框塞进 40px 行高里会不会被裁掉半个箭头；
        · 表体高度是否跟着行数走（行少时不留一大片空白）。
    这四条都只能看图。

两条纪律（沿用 S13 / S15 / S16 / S17）
    ① **假数据也走真实构造路径**：这里用的是**真的 `ActivityAdvisorPlugin`**
       加**真的 `ActivityStore`**（落在临时数据根里），不是手搓 dict 的替身 ——
       替身一旦与真实实现漂移，这张图就开始骗人，而它本来是用来说服人的。
    ② 渲染前提：不设 `QT_QPA_PLATFORM=offscreen`（中文会变豆腐块）；
       必须先 `install(app)` 再 `set_theme()`；快照前 `show()` 且窗口
       **挪到屏幕外**（`move(-4000, -4000)`），不然会在用户桌面上闪一下。

数据安全
    在 import 任何项目模块**之前**把 `PET_DEMO_HOME` 指到新建临时目录，
    所以预览里的 `activity.db` 是空的临时库 —— 不碰用户真实的使用记录。

产物：spikes/results/ui_design/
    app_category_light.png        整页：8 个应用 + 1 个已手动归类（浅色）
    app_category_dark.png         同上（深色）
    app_category_empty_light.png  整页：近 7 天没有记录时的空状态

用法：python dev_bootstrap.py spikes/s18_category_preview.py
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
# ============================================================
_PREVIEW_HOME = Path(tempfile.mkdtemp(prefix="s18_category_home_"))
os.environ["PET_DEMO_HOME"] = str(_PREVIEW_HOME)

from PySide6.QtGui import QColor, QImage                                   # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget                        # noqa: E402

from presentation.design import install, set_theme                         # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "results" / "ui_design"
OUT_DIR.mkdir(parents=True, exist_ok=True)

#: 衬底颜色 —— 与窗口底色拉开，控件的描边 / 圆角 / 留白才看得出来（S13 同款）
_BACKDROP = {"light": "#B9C6DA", "dark": "#3E4859"}

app = QApplication.instance() or QApplication([])
install(app)


# ============================================================
# 种数据：真 store + 真分类器
# ============================================================

#: (应用, 窗口标题, 累计分钟) —— 类别由**真的分类器**算出来，
#: 不手写。这样图上的「系统判定」列就是产品实际会给出的答案。
_FAKE_APPS = (
    ("code.exe", "main.py - myproject - visual studio code", 186),
    ("chrome.exe", "", 94),                       # 浏览器：判不出 → 其他（会被手动改成工作）
    ("winword.exe", "季度复盘.docx - Word", 52),
    ("wechat.exe", "微信", 41),
    ("steam.exe", "steam", 33),
    ("cloudmusic.exe", "网易云音乐", 28),
    ("anki.exe", "anki", 19),
    ("explorer.exe", "下载", 12),
)


def _seed() -> None:
    """把假分段真的写进临时库，并用真的分类器给它们定类别。"""
    from engine.activity import ActivityStore
    from engine.activity.category import classify

    store = ActivityStore(_PREVIEW_HOME / "activity.db")
    now = time.time()
    for i, (proc, title, minutes) in enumerate(_FAKE_APPS):
        category = classify(proc, title)
        # 每 3 个应用摊成两段，段数不为 1 才看得出「汇总」这回事
        half = minutes * 60 / 2
        base = now - (i + 1) * 7200
        store.add_segment(proc, category, base, base + half, key_rate=120)
        store.add_segment(proc, category, base + half + 60, base + half * 2 + 60,
                          key_rate=90)
        print(f"[种数据] {proc:18} 标题={title[:28]!r:32} → 系统判定 {category}")

    # 手动归类一条：Chrome 是「其他」，用户把它改成「工作」——
    # 只有改过一行，图上才看得到「系统判定 / 你的归类」两列的对照。
    store.set_app_category("chrome.exe", "工作")
    print("[种数据] 手动归类 chrome.exe → 工作")
    store.close()


_seed()


# ============================================================
# 测试替身（只替配置与插件管理器；插件本身是真的）
# ============================================================

class _FakeConfig:
    """`ConfigManager` 的最小替身（页面只 get）。"""

    def __init__(self, values):
        self.vals = values

    def get(self, key, default=None):
        cur = self.vals
        for part in key.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur

    def set(self, key, value):        # pragma: no cover —— 预览里不会写配置
        parts = key.split(".")
        cur = self.vals
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = value

    def save(self):                   # pragma: no cover
        pass


class _StubPluginManager:
    def __init__(self, plugin):
        self._plugin = plugin

    def get_plugin(self, name):
        return self._plugin if name == "activity_advisor" else None

    def get_all_plugins(self):
        # 必须返回空：状态栏会去读每个插件的 `manifest`，真插件没 on_load 过
        return {}


def _real_plugin() -> object:
    """构造**真的**活动插件，只把 `_store` 与 `app` 接上。

    不走 `on_load` / `on_ui_ready`：那会去订阅事件总线、起采集线程 ——
    预览不需要，也不该在用户机器上留下运行中的监听。
    """
    from engine.activity import ActivityStore
    from extensions.system.activity_advisor.plugin import ActivityAdvisorPlugin

    plugin = ActivityAdvisorPlugin()
    plugin.app = types.SimpleNamespace(
        config=_FakeConfig({
            "activity": {"enabled": True, "retention_days": 30,
                         "focus_goal_minutes": 240, "nudge_enabled": True,
                         "nudge_hour": 18, "away_seconds": 300,
                         "min_segment_seconds": 5, "exclude_apps": []},
            "ai": {"provider": "openai_compat", "base_url": "",
                   "model": "", "api_key": "", "api_key_ref": ""},
            "tomato": {"work_duration": 45},
        }),
        timer=None, input_monitor=None, tray_icon=None, ui_manager=None,
    )
    plugin._store = ActivityStore(_PREVIEW_HOME / "activity.db")
    plugin._enabled = True
    return plugin


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


def _snap_page(name: str, theme_name: str, *, height: int = 820,
               empty: bool = False) -> None:
    """渲染整页（含左侧导航）。"""
    import engine.ai as engine_ai
    from engine.ai.store import Store as AIStore
    from presentation.control_center import ControlCenter, reset_instance

    # 会话历史页会去读 `ai.db` —— 换成临时库（S13 / S17 同款做法）
    engine_ai.shared_store = lambda *a, **k: AIStore(
        Path(tempfile.mkdtemp(prefix="s18_preview_")) / "preview.db")

    set_theme(theme_name)
    plugin = _real_plugin()
    if empty:
        plugin._store.clear()          # 空态：清掉分段（归类偏好不受影响）

    fake_app = types.SimpleNamespace(
        plugin_manager=_StubPluginManager(plugin),
        config=plugin.app.config,
    )

    reset_instance()
    cc = ControlCenter(app=fake_app)
    cc.resize(1060, height)
    cc.goto("应用分类")
    page = next(p for p in cc._pages if p.title == "应用分类")
    print(f"[{name}] 表格 {page._table.rowCount()} 行，"
          f"表体高 {page._table.height()}px，"
          f"汇总：{page._summary.text()!r}")
    _snap(cc, name, theme_name)


def main() -> int:
    for theme_name in ("light", "dark"):
        _snap_page(f"app_category_{theme_name}", theme_name)
    _snap_page("app_category_empty_light", "light", empty=True, height=700)
    print("完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
