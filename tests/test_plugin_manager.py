# -*- coding: utf-8 -*-
"""插件卸载 / 恢复的契约测试。

## 为什么必须搭临时目录

卸载**会真的删掉插件目录**（那是「卸载」这个词的全部含义）。如果测试指向
仓库里的 `extensions/`，跑一次测试就把产品自己的插件删了 —— 所以
`PluginManager` 的根目录做成可注入（`base_dir=`），这里一律在 `tmp_path`
下搭一套假插件。

## 三条语义，一条都不能少

    ① 当前会话立刻停用（用户不必重启就看到它没了）
    ② 记入 `plugins.disabled`（重启后不再加载）
    ③ 用户层连目录一起删 / 系统层只停用（程序自带的文件不动）

少 ① 用户会以为没生效；少 ② 下次开机它又回来了；少 ③ 要么删坏安装，
要么留一堆删不掉的「假卸载」。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from data.config_manager import config_manager
from extensions.plugin_manager import PluginManager


def _make_plugin(root: Path, layer: str, name: str) -> Path:
    """在 `root/<layer>/<name>/` 造一个能被加载的最小插件。"""
    directory = root / layer / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        f"description: {name} 的说明\n"
        "version: 9.9.9\n"
        "author: tester\n"
        "---\n",
        encoding="utf-8",
    )
    (directory / "plugin.py").write_text(
        "from extensions.base_plugin import BasePlugin\n"
        "\n"
        "\n"
        "class ProbePlugin(BasePlugin):\n"
        "    def on_load(self, app):\n"
        "        self.loaded = True\n"
        "        return True\n"
        "\n"
        "    def on_unload(self):\n"
        "        self.unloaded = True\n",
        encoding="utf-8",
    )
    return directory


@pytest.fixture(autouse=True)
def _clean_disabled():
    """`plugins.disabled` 是进程级配置，用例之间必须清干净。"""
    config_manager.set("plugins.disabled", [])
    yield
    config_manager.set("plugins.disabled", [])


@pytest.fixture
def plugin_root(tmp_path: Path) -> Path:
    """一套「一内置 + 一用户」的假插件根目录。"""
    root = tmp_path / "extensions"
    _make_plugin(root, "system", "builtin_one")
    _make_plugin(root, "user", "user_one")
    return root


# ================================================================
# 加载与分层
# ================================================================

def test_loading_records_which_layer_each_plugin_came_from(plugin_root):
    """卸载要按层分行为，所以加载时必须记住层 —— 不能事后靠目录猜。"""
    pm = PluginManager(app=None, base_dir=plugin_root)
    pm.discover_and_load()

    assert set(pm.get_all_plugins()) == {"builtin_one", "user_one"}
    assert pm.layer_of("builtin_one") == "system"
    assert pm.layer_of("user_one") == "user"
    assert pm.is_user_installed("user_one") is True
    assert pm.is_user_installed("builtin_one") is False


# ================================================================
# 卸载
# ================================================================

def test_uninstall_stops_it_in_the_current_session(plugin_root):
    """① 当前会话立刻停用 —— 用户不必重启就能看到它从列表里消失。"""
    pm = PluginManager(app=None, base_dir=plugin_root)
    pm.discover_and_load()
    plugin = pm.get_plugin("builtin_one")

    ok, message = pm.uninstall("builtin_one")

    assert ok, message
    assert pm.get_plugin("builtin_one") is None
    assert getattr(plugin, "unloaded", False) is True, "没有调 on_unload"


def test_uninstall_survives_a_restart(plugin_root):
    """② 重启后不再加载 —— 否则用户下次开机又看到它回来了。"""
    pm = PluginManager(app=None, base_dir=plugin_root)
    pm.discover_and_load()
    pm.uninstall("builtin_one")
    assert "builtin_one" in pm.disabled_names()

    restarted = PluginManager(app=None, base_dir=plugin_root)
    restarted.discover_and_load()

    assert "builtin_one" not in restarted.get_all_plugins()
    assert "user_one" in restarted.get_all_plugins(), "误伤了别的插件"


def test_uninstall_deletes_the_directory_only_for_user_plugins(plugin_root):
    """③ 用户层连目录一起删；系统层只停用。

    系统插件的目录在程序安装位置里（打包后是 `_internal/extensions/system/`），
    删了会破坏安装完整性、升级后还会回来 —— 「删了个假的东西」比
    「明确告诉你它只是停用」更糟。
    """
    pm = PluginManager(app=None, base_dir=plugin_root)
    pm.discover_and_load()

    pm.uninstall("builtin_one")
    assert (plugin_root / "system" / "builtin_one").is_dir(), \
        "系统内置插件的目录属于程序本体，不能删"

    pm.uninstall("user_one")
    assert not (plugin_root / "user" / "user_one").exists(), \
        "用户插件卸载必须删掉目录"


def test_uninstall_writes_the_disabled_list_to_disk(plugin_root):
    """名单要落盘 —— 只改内存的话「重启后不加载」就是空话。"""
    pm = PluginManager(app=None, base_dir=plugin_root)
    pm.discover_and_load()
    pm.uninstall("builtin_one")

    path = Path(config_manager.config_dir) / "user_config.json"
    assert path.exists(), f"配置没写盘：{path}"
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert "builtin_one" in on_disk.get("plugins", {}).get("disabled", [])


def test_uninstall_unknown_plugin_is_still_recorded(plugin_root):
    """没加载过的插件（比如上次启动就卸了）也要能进名单，不能报错。"""
    pm = PluginManager(app=None, base_dir=plugin_root)

    ok, message = pm.uninstall("never_seen")

    assert ok, message
    assert "never_seen" in pm.disabled_names()


def test_uninstall_rejects_an_empty_name(plugin_root):
    pm = PluginManager(app=None, base_dir=plugin_root)

    ok, message = pm.uninstall("   ")

    assert ok is False
    assert message


# ================================================================
# 恢复
# ================================================================

def test_restore_brings_it_back_without_a_restart(plugin_root):
    """目录还在 → 恢复后立刻可用（系统插件走的就是这条）。"""
    pm = PluginManager(app=None, base_dir=plugin_root)
    pm.discover_and_load()
    pm.uninstall("builtin_one")
    assert pm.get_plugin("builtin_one") is None

    ok, message = pm.restore("builtin_one")

    assert ok, message
    assert "builtin_one" in pm.get_all_plugins(), "目录还在，恢复就该立刻加载"
    assert "builtin_one" not in pm.disabled_names()


def test_restore_tells_the_truth_when_the_directory_is_gone(plugin_root):
    """用户插件卸载时目录已删 → 恢复要**如实说**，别给一个没反应的按钮。"""
    pm = PluginManager(app=None, base_dir=plugin_root)
    pm.discover_and_load()
    pm.uninstall("user_one")

    ok, message = pm.restore("user_one")

    assert ok, "从名单里移除这一步本身是成功的"
    assert "user_one" not in pm.get_all_plugins()
    assert ("目录" in message) or ("重新" in message), \
        f"没告诉用户目录已经没了：{message}"


def test_restore_of_a_plugin_that_is_not_disabled_fails_cleanly(plugin_root):
    pm = PluginManager(app=None, base_dir=plugin_root)
    pm.discover_and_load()

    ok, message = pm.restore("builtin_one")

    assert ok is False
    assert message


# ================================================================
# 路径安全
# ================================================================

def test_removing_a_directory_outside_the_user_layer_is_refused(plugin_root, tmp_path):
    """**绝不允许删到 `extensions/user/` 之外**。

    目录来自加载时记录的真实路径（不是用插件名拼的），这里再钉一道：
    即使有人传进来一个 user 层之外的目录，也必须拒绝。
    """
    pm = PluginManager(app=None, base_dir=plugin_root)
    outsider = tmp_path / "keep_me"
    outsider.mkdir()
    (outsider / "SKILL.md").write_text("---\nname: keep_me\n---\n", encoding="utf-8")

    removed = pm._remove_plugin_dir("keep_me", outsider)

    assert removed is False
    assert outsider.is_dir(), "user 层之外的目录被删掉了"


def test_the_user_layer_root_itself_is_never_removed(plugin_root):
    """边界：把 user 层根目录本身传进来也要拒绝（父目录不是 user 根）。"""
    pm = PluginManager(app=None, base_dir=plugin_root)
    user_root = plugin_root / "user"
    user_root.mkdir(parents=True, exist_ok=True)

    assert pm._remove_plugin_dir("user", user_root) is False
    assert user_root.is_dir()


# ================================================================
# 控制中心「插件」页
# ================================================================

class _FakeCenter:
    """够 `Page` 用的最小替身。`confirm` 一律返回「确定」，让动作真的执行。"""

    app = None

    def confirm(self, *args, **kwargs) -> bool:
        return True

    def info(self, *args, **kwargs) -> None:
        pass

    def warn(self, *args, **kwargs) -> None:
        pass

    def refresh_status(self) -> None:
        pass


def _plugins_page(pm):
    """造一个插件页。需要 QApplication —— QTableWidget 没有它建不起来。"""
    import types as _types

    from PySide6.QtWidgets import QApplication

    from presentation.control_center import PluginsPage

    QApplication.instance() or QApplication([])
    center = _FakeCenter()
    center.app = _types.SimpleNamespace(plugin_manager=pm)
    return PluginsPage(center, None)


def test_plugins_page_offers_uninstall_for_every_plugin(plugin_root):
    pm = PluginManager(app=None, base_dir=plugin_root)
    pm.discover_and_load()
    page = _plugins_page(pm)

    assert page._table.rowCount() == 2
    for row in range(page._table.rowCount()):
        holder = page._table.cellWidget(row, 4)
        assert holder is not None, f"第 {row} 行没有操作按钮"
        from PySide6.QtWidgets import QPushButton

        button = holder.findChild(QPushButton)
        assert button is not None and button.text() == "卸载"


def test_plugins_page_lists_uninstalled_plugins_and_offers_restore(plugin_root):
    pm = PluginManager(app=None, base_dir=plugin_root)
    pm.discover_and_load()
    pm.uninstall("builtin_one")
    page = _plugins_page(pm)

    assert page._removed_table.rowCount() == 1
    assert page._removed_table.item(0, 0).text() == "builtin_one"
    assert not page._removed_label.isHidden(), "有已卸载插件时该区要出现"
    # 来源要说清 —— 用户得知道「恢复」对它到底有没有用
    assert page._removed_table.item(0, 1).text() == "系统内置"


def test_plugins_page_hides_the_removed_section_when_empty(plugin_root):
    pm = PluginManager(app=None, base_dir=plugin_root)
    pm.discover_and_load()
    page = _plugins_page(pm)

    assert page._removed_table.rowCount() == 0
    assert page._removed_label.isHidden()
    assert page._removed_hint.isHidden()
    assert page._removed_table.isHidden()


def test_plugins_page_uninstall_action_refreshes_both_tables(plugin_root):
    """点「卸载」走页面自己的回调 —— 不手工调 `reload()` 也要立刻反映。"""
    pm = PluginManager(app=None, base_dir=plugin_root)
    pm.discover_and_load()
    page = _plugins_page(pm)

    page._on_uninstall("builtin_one")

    assert pm.get_plugin("builtin_one") is None
    assert page._table.rowCount() == 1
    assert page._removed_table.rowCount() == 1


def test_plugins_page_restore_action_puts_it_back(plugin_root):
    pm = PluginManager(app=None, base_dir=plugin_root)
    pm.discover_and_load()
    pm.uninstall("builtin_one")
    page = _plugins_page(pm)

    page._on_restore("builtin_one")

    assert pm.get_plugin("builtin_one") is not None
    assert page._table.rowCount() == 2
    assert page._removed_table.rowCount() == 0


def test_plugins_page_tolerates_a_manager_without_the_new_api():
    """插件管理器是**鸭子类型**的（预览脚本会塞普通对象进来）。

    缺 `disabled_names()` / `layer_of()` 时，页面应当照常显示已加载列表，
    而不是整个崩掉 —— 这是本次改动引入的新依赖，必须有护栏。
    """
    import types as _types

    class _Bare:
        def get_all_plugins(self):
            return {}

    center = _FakeCenter()
    center.app = _types.SimpleNamespace(plugin_manager=_Bare())

    from PySide6.QtWidgets import QApplication

    from presentation.control_center import PluginsPage

    QApplication.instance() or QApplication([])
    page = PluginsPage(center, None)

    assert page._removed_table.rowCount() == 0
