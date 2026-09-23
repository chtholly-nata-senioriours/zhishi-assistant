"""便签工具单元测试"""

import sys
import json
import os
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.note_tool import Note, NoteManager
from event_bus import register_event_type

for evt in ("NOTE_CREATED", "NOTE_DELETED", "NOTE_COMPLETED"):
    register_event_type(evt)


def make_manager():
    """创建使用临时文件的便签管理器"""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)  # 关闭文件描述符
    return NoteManager(storage_path=path), Path(path)


def test_create_note():
    """测试创建便签"""
    mgr, tmp = make_manager()
    note = mgr.create_note("测试标题", "测试内容")
    assert note.title == "测试标题"
    assert note.content == "测试内容"
    assert note.completed is False
    assert note.priority == "normal"
    assert note.color == "yellow"
    assert len(note.id) == 8
    print(f"  创建便签: {note.id} - {note.title}")
    tmp.unlink()
    print("✅ 创建便签测试通过")


def test_get_all_notes():
    """测试获取所有便签"""
    mgr, tmp = make_manager()
    assert len(mgr.get_all_notes()) == 0

    mgr.create_note("便签A")
    mgr.create_note("便签B")
    mgr.create_note("便签C")
    assert len(mgr.get_all_notes()) == 3
    tmp.unlink()
    print("✅ 获取所有便签测试通过")


def test_delete_note():
    """测试删除便签"""
    mgr, tmp = make_manager()
    note = mgr.create_note("待删除")
    assert len(mgr.get_all_notes()) == 1

    ok = mgr.delete_note(note.id)
    assert ok is True
    assert len(mgr.get_all_notes()) == 0

    # 删除不存在的ID
    ok = mgr.delete_note("nonexist")
    assert ok is False
    tmp.unlink()
    print("✅ 删除便签测试通过")


def test_complete_note():
    """测试标记完成"""
    mgr, tmp = make_manager()
    note = mgr.create_note("待完成")
    assert note.completed is False

    ok = mgr.complete_note(note.id)
    assert ok is True
    note = mgr.get_note(note.id)
    assert note.completed is True
    tmp.unlink()
    print("✅ 标记完成测试通过")


def test_update_note():
    """测试更新便签"""
    mgr, tmp = make_manager()
    note = mgr.create_note("原标题")
    mgr.update_note(note.id, title="新标题", content="新内容")
    note = mgr.get_note(note.id)
    assert note.title == "新标题"
    assert note.content == "新内容"
    tmp.unlink()
    print("✅ 更新便签测试通过")


def test_filter_notes():
    """测试筛选功能"""
    mgr, tmp = make_manager()
    n1 = mgr.create_note("工作", priority="high", tags=["work"])
    n2 = mgr.create_note("私人", priority="low", tags=["personal"])
    mgr.complete_note(n1.id)

    pending = mgr.get_pending_notes()
    completed = mgr.get_completed_notes()
    assert len(pending) == 1
    assert len(completed) == 1
    assert pending[0].id == n2.id

    # 按标签筛选
    work_notes = mgr.get_notes_by_tag("work")
    assert len(work_notes) == 1
    assert work_notes[0].id == n1.id
    tmp.unlink()
    print("✅ 便签筛选测试通过")


def test_search_notes():
    """测试搜索功能"""
    mgr, tmp = make_manager()
    mgr.create_note("开会", "下午3点会议室")
    mgr.create_note("购物", "买牛奶和面包")

    results = mgr.search_notes("开会")
    assert len(results) == 1

    results = mgr.search_notes("牛奶")
    assert len(results) == 1

    results = mgr.search_notes("不存在")
    assert len(results) == 0
    tmp.unlink()
    print("✅ 搜索便签测试通过")


def test_statistics():
    """测试统计功能"""
    mgr, tmp = make_manager()
    stats = mgr.get_statistics()
    assert stats["total"] == 0
    assert stats["completed"] == 0
    assert stats["pending"] == 0

    mgr.create_note("A")
    mgr.create_note("B", color="blue")
    n3 = mgr.create_note("C", color="blue")
    mgr.complete_note(n3.id)

    stats = mgr.get_statistics()
    assert stats["total"] == 3
    assert stats["completed"] == 1
    assert stats["pending"] == 2
    assert stats["by_color"]["yellow"] == 1
    assert stats["by_color"]["blue"] == 2
    tmp.unlink()
    print("✅ 统计功能测试通过")


def test_persistence():
    """测试持久化（创建后重新加载应恢复数据）"""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    tmp = Path(path)

    # 第一次：创建便签
    mgr1 = NoteManager(storage_path=str(tmp))
    mgr1.create_note("持久化测试")
    mgr1.create_note("第二条")
    assert len(mgr1.get_all_notes()) == 2

    # 第二次：重新加载
    mgr2 = NoteManager(storage_path=str(tmp))
    assert len(mgr2.get_all_notes()) == 2
    assert mgr2.get_all_notes()[0].title in ("持久化测试", "第二条")

    tmp.unlink()
    print("✅ 持久化测试通过")


if __name__ == "__main__":
    test_create_note()
    test_get_all_notes()
    test_delete_note()
    test_complete_note()
    test_update_note()
    test_filter_notes()
    test_search_notes()
    test_statistics()
    test_persistence()
    print("\n所有便签测试通过! ✅")
