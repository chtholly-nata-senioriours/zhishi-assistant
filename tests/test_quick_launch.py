"""快捷启动工具单元测试"""

import sys
import os
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.quick_launch import QuickLaunch
from event_bus import register_event_type

register_event_type("QUICK_LAUNCH")


def make_launcher():
    """创建使用临时文件的快捷启动管理器"""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    return QuickLaunch(storage_path=path), Path(path)


def test_default_items_loaded():
    """测试默认启动项加载"""
    launcher, tmp = make_launcher()
    items = launcher.get_all_items()
    # 默认10项，但如果是新文件则加载 DEFAULT_ITEMS
    assert len(items) > 0
    print(f"  默认启动项: {len(items)} 个")
    tmp.unlink()
    print("✅ 默认启动项加载测试通过")


def test_add_item():
    """测试添加启动项"""
    launcher, tmp = make_launcher()
    item = launcher.add_item("测试应用", "notepad", category="工具")
    assert item.name == "测试应用"
    assert item.command == "notepad"
    assert item.category == "工具"
    assert item.run_count == 0
    assert item.enabled is True
    tmp.unlink()
    print("✅ 添加启动项测试通过")


def test_remove_item():
    """测试移除启动项"""
    launcher, tmp = make_launcher()
    item = launcher.add_item("待删除", "calc")
    assert len(launcher.get_all_items()) > 0

    ok = launcher.remove_item(item.id)
    assert ok is True

    # 移除不存在的
    ok = launcher.remove_item("nonexist")
    assert ok is False
    tmp.unlink()
    print("✅ 移除启动项测试通过")


def test_launch_increments_count():
    """测试启动增加计数"""
    launcher, tmp = make_launcher()
    item = launcher.add_item("测试", "echo hello", category="工具")
    count_before = item.run_count

    # 启动（这条命令应该成功）
    ok = launcher.launch(item.id)
    assert ok is True

    item = launcher.get_item(item.id)
    assert item.run_count == count_before + 1
    assert item.last_run != ""
    tmp.unlink()
    print("✅ 启动计数测试通过")


def test_get_categories():
    """测试获取分类列表"""
    launcher, tmp = make_launcher()
    launcher.add_item("A", "a", category="工具")
    launcher.add_item("B", "b", category="浏览器")
    launcher.add_item("C", "c", category="工具")

    cats = launcher.get_categories()
    assert "工具" in cats
    assert "浏览器" in cats
    tmp.unlink()
    print("✅ 分类查询测试通过")


def test_filter_by_category():
    """测试按分类筛选"""
    launcher, tmp = make_launcher()
    # 清除默认项，避免干扰
    for item in launcher.get_all_items():
        launcher.remove_item(item.id)
    launcher.add_item("A", "a", category="工具")
    launcher.add_item("B", "b", category="浏览器")

    tools = launcher.get_items_by_category("工具")
    assert len(tools) == 1
    assert tools[0].name == "A"

    browsers = launcher.get_items_by_category("浏览器")
    assert len(browsers) == 1
    tmp.unlink()
    print("✅ 分类筛选测试通过")


def test_search():
    """测试搜索"""
    launcher, tmp = make_launcher()
    # 清除默认项
    for item in launcher.get_all_items():
        launcher.remove_item(item.id)
    launcher.add_item("Chrome浏览器", "start chrome", category="浏览器")
    launcher.add_item("记事本", "notepad", category="工具")

    # 搜索名称
    results = launcher.search("Chrome")
    assert len(results) == 1
    assert results[0].name == "Chrome浏览器"

    # 搜索不存在的
    results = launcher.search("不存在的")
    assert len(results) == 0
    tmp.unlink()
    print("✅ 搜索测试通过")


def test_update_item():
    """测试更新启动项"""
    launcher, tmp = make_launcher()
    item = launcher.add_item("原名", "cmd")
    launcher.update_item(item.id, name="新名", command="powershell")
    item = launcher.get_item(item.id)
    assert item.name == "新名"
    assert item.command == "powershell"
    tmp.unlink()
    print("✅ 更新启动项测试通过")


def test_favorites():
    """测试常用启动项"""
    launcher, tmp = make_launcher()
    a = launcher.add_item("A", "echo a")
    b = launcher.add_item("B", "echo b")
    c = launcher.add_item("C", "echo c")

    # 模拟使用次数
    launcher.launch(a.id)
    launcher.launch(a.id)
    launcher.launch(a.id)
    launcher.launch(b.id)
    launcher.launch(b.id)

    favorites = launcher.get_favorites(limit=2)
    assert len(favorites) == 2
    assert favorites[0].name == "A"  # 使用最多
    assert favorites[1].name == "B"
    tmp.unlink()
    print("✅ 常用启动项测试通过")


if __name__ == "__main__":
    test_default_items_loaded()
    test_add_item()
    test_remove_item()
    test_launch_increments_count()
    test_get_categories()
    test_filter_by_category()
    test_search()
    test_update_item()
    test_favorites()
    print("\n所有快捷启动测试通过! ✅")
