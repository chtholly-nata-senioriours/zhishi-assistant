# -*- coding: utf-8 -*-
"""手动归类（应用 → 类别）的契约测试。

分三层，每层守一个「不测就会静默坏掉」的点：

    Store   —— 覆盖表 + **读路径收口**。这是最容易出静默 bug 的地方：
               覆盖只在读取时生效，所以任何一条读路径忘了叠加覆盖，
               都会「不报错、只是数字没变」。实测踩过两次（见下）。
    插件    —— 鸭子类型接口与数据指纹（改了归类必须让缓存建议失效）。
    页面    —— 空态整页自洽、改过的行看得见。

两个真实踩过的坑（各自钉了一个测试）
    ① `totals_by_category` 的 SELECT 只取 `category, seconds`，没有 `app` ——
       覆盖表是按 app 查的，于是它静默返回一份**没覆盖**的数据。
       现在 `_rows()` 里有一道护栏：查询漏了 app 列就直接炸。
    ② `totals_by_app` 在 Python 层重新聚合时把 `auto_category` 丢了 ——
       「应用分类」页的「系统判定」列于是被覆盖后的值污染，
       那一页最该看的对照（系统判成什么 / 你改成了什么）直接消失，
       而汇总行还写着「N 个已手动归类」。目检 S18 抓到的。
"""
import os
import sys
import time
import types
from pathlib import Path

import pytest

# offscreen：无显示环境也能建控件（必须在 QApplication 创建前设置）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from engine.activity import (  # noqa: E402
    CATEGORIES,
    ActivityStore,
    apply_overrides,
)
from engine.activity.category import COMM, FUN, OTHER, STUDY, WORK  # noqa: E402
from extensions.plugin_manager import _import_plugin_class  # noqa: E402

_PLUGIN_NAME = "activity_advisor"
_PLUGIN_DIR = (Path(__file__).resolve().parent.parent
               / "extensions" / "system" / _PLUGIN_NAME)
ActivityAdvisorPlugin = _import_plugin_class(_PLUGIN_DIR, _PLUGIN_NAME)

assert ActivityAdvisorPlugin is not None, "activity_advisor 插件加载失败"

from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402

_qapp = QApplication.instance() or QApplication([])


# ---------------------------------------------------------------- 夹具 / 辅助

@pytest.fixture
def store():
    s = ActivityStore(":memory:")
    yield s
    s.close()


def _seed(store, rows, *, now=None):
    """`rows` 每项 `(app, category, start_offset, end_offset)`。

    偏移是**相对现在**的秒数（负数 = 过去）。必须是近期数据 ——
    `app_totals(days)` / `_data_signature(days)` 都按「近 N 个自然日」过滤，
    种 1970 年的时间戳进去会被整个滤掉，而测试只会看到「表格 0 行」，
    查半天以为是页面坏了。
    """
    base = time.time() if now is None else float(now)
    for app, cat, start, end in rows:
        store.add_segment(app, cat, base + float(start), base + float(end))


def _fake_app(values=None):
    class _Cfg:
        def __init__(self, v):
            self._v = v

        def get(self, key, default=None):
            return self._v.get(key, default)

        def set(self, key, value):
            self._v[key] = value

        def save(self):
            pass

    class _App:
        def __init__(self, v):
            self.config = _Cfg(v)
            self.input_monitor = None
            self.ui_manager = None
            self.timer = None
            self.tray_icon = None

    return _App(values or {})


def _plugin_with_store(store):
    """建一个已接上库的插件（不走 on_load，避免订阅事件总线）。"""
    p = ActivityAdvisorPlugin()
    p.app = _fake_app({"activity.enabled": True})
    p._store = store
    p._enabled = True
    return p


class _PM:
    def __init__(self, plugin=None):
        self._plugin = plugin

    def get_plugin(self, name):
        return self._plugin if name == "activity_advisor" else None

    def get_all_plugins(self):
        return {}


def _category_page(plugin):
    from presentation.control_center import ControlCenter, reset_instance

    reset_instance()
    cc = ControlCenter(app=types.SimpleNamespace(
        plugin_manager=_PM(plugin), config=plugin.app.config))
    return next(p for p in cc._pages if p.title == "应用分类")


# ================================================================
# Store：写入与撤销
# ================================================================

class TestStoreWrites:

    def test_set_and_read_back(self, store):
        assert store.set_app_category("chrome.exe", WORK) is True
        assert store.app_categories() == {"chrome.exe": WORK}
        assert store.count_app_categories() == 1

    def test_app_name_is_normalized_on_write(self, store):
        """库里必须只有一种写法 —— 否则「设了不生效」查不出来。"""
        store.set_app_category("  Chrome.EXE ", WORK)
        assert store.app_categories() == {"chrome.exe": WORK}

    @pytest.mark.parametrize("bad", ["摸鱼", "", "work", "工作 ", None, "其他类"])
    def test_category_must_come_from_the_enum(self, store, bad):
        """受限枚举：界面只有五个选项，库里就不该有第六种取值。"""
        assert store.set_app_category("chrome.exe", bad) is False
        assert store.count_app_categories() == 0

    def test_empty_app_is_refused(self, store):
        assert store.set_app_category("   ", WORK) is False
        assert store.set_app_category(None, WORK) is False

    def test_setting_twice_overwrites(self, store):
        store.set_app_category("chrome.exe", WORK)
        store.set_app_category("chrome.exe", FUN)
        assert store.app_categories() == {"chrome.exe": FUN}
        assert store.count_app_categories() == 1

    def test_clear_one_returns_whether_it_existed(self, store):
        store.set_app_category("chrome.exe", WORK)
        assert store.clear_app_category("chrome.exe") is True
        assert store.clear_app_category("chrome.exe") is False
        assert store.app_categories() == {}

    def test_clear_all(self, store):
        store.set_app_category("chrome.exe", WORK)
        store.set_app_category("code.exe", STUDY)
        assert store.clear_app_categories() == 2
        assert store.count_app_categories() == 0


# ================================================================
# Store：覆盖必须在**每一条**读路径上生效
# ================================================================

class TestOverrideAppliesToEveryReadPath:
    """四条读路径逐个断言 —— 只测一条的话，另一条漏了也没人知道。

    这是本项目的老规矩：同一件事有两个实现 = 两个都没验证。
    读路径就是「同一件事的四个入口」。
    """

    def test_segments_since(self, store):
        _seed(store, [("chrome.exe", OTHER, -600, 0)])
        store.set_app_category("chrome.exe", WORK)
        segs = store.segments_since(0)
        assert [s["category"] for s in segs] == [WORK]
        assert segs[0]["auto_category"] == OTHER

    def test_segments_between(self, store):
        _seed(store, [("chrome.exe", OTHER, -600, 0)])
        store.set_app_category("chrome.exe", WORK)
        segs = store.segments_between(0, time.time() + 60)
        assert [s["category"] for s in segs] == [WORK]

    def test_totals_by_app(self, store):
        _seed(store, [("chrome.exe", OTHER, -600, 0)])
        store.set_app_category("chrome.exe", WORK)
        rows = store.totals_by_app(0)
        assert rows[0]["category"] == WORK

    def test_totals_by_category(self, store):
        """这条曾经**静默失效**：SELECT 里漏了 app 列，覆盖查不到键。"""
        _seed(store, [("chrome.exe", OTHER, -600, 0)])
        store.set_app_category("chrome.exe", WORK)
        got = {r["category"]: r["seconds"] for r in store.totals_by_category(0)}
        assert got == {WORK: 600.0}

    def test_read_path_without_app_column_is_refused(self, store):
        """护栏：漏了 app 列的查询必须当场炸，而不是返回没覆盖的数据。

        「改了分类但数字没变」是最难查的一类 bug —— 不报错、不崩。
        """
        _seed(store, [("chrome.exe", OTHER, -600, 0)])
        with pytest.raises(ValueError):
            store._rows("SELECT category, seconds FROM segments")


class TestOriginalObservationIsNotTamperedWith:

    def test_raw_category_column_is_untouched(self, store):
        """`segments.category` 是**系统当时的判定**，是证据 —— 手动归类
        只允许在读路径上叠加，不许 UPDATE 历史行。"""
        _seed(store, [("chrome.exe", OTHER, -600, 0)])
        store.set_app_category("chrome.exe", WORK)
        store.segments_since(0)          # 读一遍，触发覆盖
        raw = store._conn.execute(
            "SELECT app, category FROM segments").fetchall()
        assert [tuple(r) for r in raw] == [("chrome.exe", OTHER)]

    def test_reverting_restores_the_automatic_verdict(self, store):
        """撤销是零代价的 —— 因为原始列从没被改过。"""
        _seed(store, [("chrome.exe", OTHER, -600, 0)])
        store.set_app_category("chrome.exe", WORK)
        assert store.segments_since(0)[0]["category"] == WORK
        store.clear_app_category("chrome.exe")
        assert store.segments_since(0)[0]["category"] == OTHER
        assert "auto_category" not in store.segments_since(0)[0]

    def test_totals_by_app_keeps_the_system_verdict(self, store):
        """回归（目检 S18 抓到）：聚合不能把 `auto_category` 丢掉 ——
        「应用分类」页靠它显示「系统判定」列。"""
        _seed(store, [("chrome.exe", OTHER, -600, 0)])
        store.set_app_category("chrome.exe", WORK)
        row = store.totals_by_app(0)[0]
        assert row["category"] == WORK          # 生效的类别
        assert row["auto_category"] == OTHER    # 系统原本判的

    def test_totals_by_app_has_no_auto_key_when_not_overridden(self, store):
        _seed(store, [("code.exe", WORK, -600, 0)])
        assert "auto_category" not in store.totals_by_app(0)[0]

    def test_clear_keeps_the_user_preferences(self, store):
        """清空行为数据**不该**抹掉归类偏好 —— 那是设置，不是记录。
        抹掉之后用户还得重设一遍，而且他不会知道为什么。"""
        _seed(store, [("chrome.exe", OTHER, -600, 0)])
        store.set_app_category("chrome.exe", WORK)
        store.clear()
        assert store.count() == 0
        assert store.app_categories() == {"chrome.exe": WORK}


# ================================================================
# 插件层
# ================================================================

class TestPluginApi:

    def test_app_totals_marks_manual_rows(self, store):
        _seed(store, [("chrome.exe", OTHER, -600, 0), ("code.exe", WORK, -900, -600)])
        store.set_app_category("chrome.exe", WORK)
        p = _plugin_with_store(store)

        rows = {r["app"]: r for r in p.app_totals(7)}
        assert rows["chrome.exe"]["manual"] is True
        assert rows["chrome.exe"]["auto_category"] == OTHER
        assert rows["code.exe"]["manual"] is False

    def test_app_totals_is_empty_without_a_store(self):
        p = ActivityAdvisorPlugin()
        p.app = _fake_app({})
        assert p.app_totals(7) == []
        assert p.app_categories() == {}

    def test_set_and_clear_return_a_human_message(self, store):
        p = _plugin_with_store(store)
        ok, msg = p.set_app_category("chrome.exe", WORK)
        assert ok is True and "chrome.exe" in msg and WORK in msg

        ok, msg = p.clear_app_category("chrome.exe")
        assert ok is True and "自动判定" in msg

    def test_clear_refuses_when_there_was_no_override(self, store):
        p = _plugin_with_store(store)
        ok, msg = p.clear_app_category("chrome.exe")
        assert ok is False and "本来就没有" in msg

    def test_invalid_category_is_refused_with_a_message(self, store):
        p = _plugin_with_store(store)
        ok, msg = p.set_app_category("chrome.exe", "摸鱼")
        assert ok is False and "摸鱼" in msg

    def test_refused_when_collection_is_off(self):
        p = ActivityAdvisorPlugin()
        p.app = _fake_app({})
        ok, msg = p.set_app_category("chrome.exe", WORK)
        assert ok is False and "采集未开启" in msg

    def test_clear_all_counts(self, store):
        _seed(store, [("chrome.exe", OTHER, -600, 0)])
        p = _plugin_with_store(store)
        p.set_app_category("chrome.exe", WORK)
        p.set_app_category("code.exe", STUDY)
        assert p.clear_app_categories() == 2

    def test_data_signature_changes_when_a_category_changes(self, store):
        """改了归类 → 缓存建议必须被判定为**已过期**。

        摘要里有「按类别」那一段、深度工作时长也按类别算，但条数 / 总时长 /
        起止一个都没变 —— 指纹不含归类的话，页面上那份建议就是照着旧分类
        写的，而且不会被标成过期，用户看到一份与他刚做的修改相矛盾的文字。
        """
        _seed(store, [("chrome.exe", OTHER, -600, 0)])
        p = _plugin_with_store(store)
        before = p._data_signature(1)

        p.set_app_category("chrome.exe", WORK)
        after = p._data_signature(1)
        assert before != after

    def test_mixed_categories_report_the_dominant_one(self, store):
        """一个应用可能因为标题变化而落到两个类别上（分类看进程名 + 标题）。

        汇总时要取**占比最大**的那个 —— 取最小的话，一个用了 3 小时的
        编辑器会因为某一段标题里出现了「游戏」而显示成「娱乐」。
        """
        _seed(store, [("code.exe", WORK, -3600, -3000),
                      ("code.exe", FUN, -3000, -2900)])
        assert store.totals_by_app(0)[0]["category"] == WORK

    def test_data_signature_is_stable_without_changes(self, store):
        _seed(store, [("chrome.exe", OTHER, -600, 0)])
        p = _plugin_with_store(store)
        assert p._data_signature(1) == p._data_signature(1)


# ================================================================
# 页面层
# ================================================================

class TestAppCategoryPage:

    def test_page_is_registered_under_data_group(self):
        from presentation.control_center import NAV_GROUPS

        data = next(items for name, items in NAV_GROUPS if name == "数据")
        assert "应用分类" in [label for _, label, _ in data]

    def test_rules_card_lists_every_category_and_its_basis(self, store):
        """说明卡必须**逐条**列出分类项与判定依据 —— 用户有权知道
        系统凭什么这么判。文案取自 `CATEGORY_RULES`，页面不重写一份。"""
        from engine.activity.category import CATEGORY_RULES

        _seed(store, [("code.exe", WORK, -600, 0)])
        page = _category_page(_plugin_with_store(store))
        from PySide6.QtWidgets import QLabel

        # 分类名在 `FormCard` 的**标签列**（普通 QLabel），判定依据在值列
        # （PageHint）—— 两边都要收，只收一边会漏掉分类名。
        text = " ".join(lbl.text() for lbl in page.findChildren(QLabel))
        for name in CATEGORIES:
            assert name in text, f"说明卡里没有分类项「{name}」"
            assert CATEGORY_RULES[name] in text, f"说明卡里没有「{name}」的判定依据"

    def test_table_lists_apps_with_system_verdict_and_choice(self, store):
        _seed(store, [("chrome.exe", OTHER, -600, 0), ("code.exe", WORK, -900, -600)])
        page = _category_page(_plugin_with_store(store))

        assert page._table.rowCount() == 2
        assert page._table.item(0, 0).text() == "chrome.exe"
        assert page._table.item(0, 1).text() == "10 分钟"
        assert page._table.item(0, 2).text() == OTHER
        assert "2 个应用" in page._summary.text()

    def test_overridden_row_shows_both_verdicts_and_picks_the_category(self, store):
        """改过的行：应用名用强调色（一眼找到），系统判定列显示**原值**，
        下拉选中用户选的那个类别。"""
        from presentation.design.theme import theme

        _seed(store, [("chrome.exe", OTHER, -600, 0)])
        store.set_app_category("chrome.exe", WORK)
        page = _category_page(_plugin_with_store(store))

        name_item = page._table.item(0, 0)
        assert name_item.foreground().color().name() == \
            theme().color("accent").name()
        assert page._table.item(0, 2).text() == OTHER       # 系统判定
        combo = page._table.cellWidget(0, 3).findChild(QComboBox)
        assert combo.currentText() == WORK                  # 你的归类

    def test_untouched_row_sits_on_automatic(self, store):
        _seed(store, [("code.exe", WORK, -600, 0)])
        page = _category_page(_plugin_with_store(store))
        combo = page._table.cellWidget(0, 3).findChild(QComboBox)
        assert combo.currentText() == "自动判定"
        assert page._summary.text().endswith("全部按系统判定。")

    def test_picking_a_category_writes_it_and_refreshes(self, store):
        _seed(store, [("chrome.exe", OTHER, -600, 0)])
        page = _category_page(_plugin_with_store(store))
        combo = page._table.cellWidget(0, 3).findChild(QComboBox)

        combo.setCurrentIndex(combo.findText(FUN))
        combo.activated.emit(combo.currentIndex())          # 模拟用户选择

        assert store.app_categories() == {"chrome.exe": FUN}
        assert "1 个已手动归类" in page._summary.text()
        assert page._table.item(0, 2).text() == OTHER        # 系统判定不变
        # 反馈必须留在状态行上 —— reload() 会把它重置成常驻说明，
        # 所以动作反馈得写在 reload 之后（否则点完等于没反馈）
        assert "已把" in page._status.text() and FUN in page._status.text()

    def test_picking_the_system_verdict_does_not_store_an_override(self, store):
        """选了「正好等于系统判定」的类别 = 不需要覆盖。

        若真写一条覆盖记录，下次刷新时下拉会跳回「自动判定」
        （`apply_overrides` 不认为它与自动判定不同），用户会以为没保存上。
        """
        _seed(store, [("code.exe", WORK, -600, 0)])
        page = _category_page(_plugin_with_store(store))
        combo = page._table.cellWidget(0, 3).findChild(QComboBox)

        combo.setCurrentIndex(combo.findText(WORK))
        combo.activated.emit(combo.currentIndex())

        assert store.app_categories() == {}
        assert "保持系统判定" in page._status.text()

    def test_reset_all_button_is_disabled_without_overrides(self, store):
        _seed(store, [("code.exe", WORK, -600, 0)])
        page = _category_page(_plugin_with_store(store))
        assert page._btn_reset_all.isEnabled() is False

    def test_reset_all_clears_every_override(self, store):
        _seed(store, [("chrome.exe", OTHER, -600, 0)])
        store.set_app_category("chrome.exe", WORK)
        page = _category_page(_plugin_with_store(store))
        assert page._btn_reset_all.isEnabled() is True

        page._btn_reset_all.click()
        assert store.app_categories() == {}
        assert page._table.item(0, 2).text() == OTHER
        assert "已恢复 1 个应用" in page._status.text()

    def test_empty_state_hides_the_whole_toolbar(self, store):
        """空态要**整页自洽**：那一行是「列表工具栏」（汇总 + 恢复按钮），
        没有列表就没有工具栏。留着的话会出现「没有应用可归类，却请你恢复
        归类」的禁用按钮孤零零挂在右边，和下面「还没有可归类的应用」打架。
        （目检 S18 抓到的。）
        """
        page = _category_page(_plugin_with_store(store))
        assert page._table.isHidden() is True
        assert page._toolbar.isHidden() is True
        assert page._empty.isHidden() is False

    def test_toolbar_comes_back_with_data(self, store):
        _seed(store, [("code.exe", WORK, -600, 0)])
        page = _category_page(_plugin_with_store(store))
        assert page._toolbar.isHidden() is False
        assert page._table.isHidden() is False
        assert page._empty.isHidden() is True

    def test_table_height_follows_the_row_count(self, store):
        """行少时不留一大片空白，行多时表内滚动。"""
        _seed(store, [("a.exe", WORK, -600, 0)])
        short = _category_page(_plugin_with_store(store))
        one = short._table.height()

        for i in range(12):
            store.add_segment(f"app{i}.exe", WORK, time.time() - 600, time.time())
        tall = _category_page(_plugin_with_store(store))
        assert tall._table.height() > one
        assert tall._table.height() <= tall._TABLE_MAX

    def test_degrades_without_a_plugin(self):
        from presentation.control_center import ControlCenter, reset_instance

        reset_instance()
        cc = ControlCenter(app=types.SimpleNamespace(
            plugin_manager=_PM(None), config=_fake_app({}).config))
        page = next(p for p in cc._pages if p.title == "应用分类")
        assert page._empty.isHidden() is False
        assert "插件未加载" in page._summary.text()
        assert page._table.isHidden() is True


# ================================================================
# 深度工作口径（工作 + 学习）
# ================================================================

class TestFocusIncludesStudy:

    def test_study_counts_as_deep_work(self):
        """看两小时网课在进度环上不该是 0。"""
        from engine.activity import focus_seconds, longest_focus_seconds

        segs = [
            {"app": "chrome.exe", "category": STUDY, "seconds": 3600.0},
            {"app": "chrome.exe", "category": FUN, "seconds": 600.0},
            {"app": "code.exe", "category": WORK, "seconds": 1800.0},
        ]
        assert focus_seconds(segs) == 5400.0
        assert longest_focus_seconds(segs) == 3600.0

    def test_fun_and_comm_are_not_focus(self):
        from engine.activity import focus_seconds

        segs = [
            {"app": "steam.exe", "category": FUN, "seconds": 3600.0},
            {"app": "wechat.exe", "category": COMM, "seconds": 600.0},
            {"app": "explorer.exe", "category": OTHER, "seconds": 600.0},
        ]
        assert focus_seconds(segs) == 0.0

    def test_daily_totals_counts_study_as_focus(self):
        """趋势页柱状图的「深度工作」走同一口径（三处，一处都不能漏）。"""
        from engine.activity import daily_totals

        now = time.time()
        segs = [{"app": "chrome.exe", "category": STUDY,
                 "start_at": now - 600, "end_at": now, "seconds": 600.0}]
        assert daily_totals(segs, days=1, now=now)[0]["focus"] == 600.0

    def test_the_two_aggregators_share_one_definition(self):
        """页面上的「深度工作」与摘要里的「最长连续专注」必须同口径 ——
        以前两处各自写死 `"工作"`，改一处就会互相矛盾。"""
        from engine.activity import focus_seconds, longest_focus_seconds
        from engine.activity.category import FOCUS_CATEGORIES

        for cat in CATEGORIES:
            segs = [{"app": "x.exe", "category": cat, "seconds": 600.0}]
            counted = focus_seconds(segs) > 0
            assert counted == (cat in FOCUS_CATEGORIES)
            assert (longest_focus_seconds(segs) > 0) == counted
