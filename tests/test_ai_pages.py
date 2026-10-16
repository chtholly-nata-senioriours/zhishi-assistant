# -*- coding: utf-8 -*-
"""控制中心「会话历史 / 预设」两页 + 预设编辑对话框 + 共享 Store 的回归测试。

守的是三件事：
    1. AI 插件与控制中心**共用同一个 Store** —— 各开各的连接在 WAL 下
       并发写会撞 `database is locked`，而且每开一个连接都要重跑 schema。
    2. 会话页能列出 / 搜索 / 删除 / 清空；没有数据时给空状态而不是白板。
    3. 预设页：内置预设只读，自定义预设可增删改；编辑框对非法输入有校验。

运行:
    python tests/test_ai_pages.py
    pytest tests/test_ai_pages.py -v
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

app = QApplication.instance() or QApplication([])

from engine.ai.prompt import BUILTIN_PRESETS
from engine.ai.store import Store, close_shared_store, shared_store
from engine.ai.types import DeliveryKind, Preset
from presentation.control_center import PresetsPage, SessionsPage
from presentation.dialogs import PresetEditDialog, delivery_label


# ============================================================
# 测试替身
# ============================================================

class FakeCenter:
    """够页面用的最小 center（不建真窗口，测试更快也更隔离）。"""

    def __init__(self, store):
        self.app = None
        self._store = store
        self.warnings: list = []
        self.infos: list = []

    def store(self):
        return self._store

    def confirm(self, *_a, **_k) -> bool:
        return True

    def info(self, title, text=""):
        self.infos.append((title, text))

    def warn(self, title, text=""):
        self.warnings.append((title, text))

    def statusMessage(self, *_a, **_k):
        pass


def _seeded_store(tmp_path) -> Store:
    store = Store(tmp_path / "ai.db")
    store.create_session("s1", "ask", "标题一")
    store.append_message("s1", "user", "你好")
    store.append_message("s1", "assistant", "在的")
    store.create_session("s2", "translate", "标题二")
    store.append_message("s2", "user", "hello")
    store.append_message("s2", "assistant", "你好呀")
    return store


def _row_ids(page) -> set:
    return {
        page._list.item(i).data(Qt.ItemDataRole.UserRole)
        for i in range(page._list.count())
    }


# ============================================================
# 1. 共享 Store
# ============================================================

def test_shared_store_is_a_singleton(tmp_path):
    close_shared_store()
    a = shared_store(tmp_path / "a.db")
    b = shared_store(tmp_path / "b.db")      # 单例已存在 → 路径参数被忽略
    assert a is b

    close_shared_store()
    c = shared_store(tmp_path / "c.db")
    assert c is not a
    close_shared_store()


def test_shared_store_usable_after_close(tmp_path):
    """关掉再取必须是**可用**的新连接（插件卸载后控制中心还要能读）。"""
    close_shared_store()
    shared_store(tmp_path / "a.db")
    close_shared_store()
    store = shared_store(tmp_path / "a.db")
    store.create_session("x", "ask", "t")
    assert len(store.list_sessions()) == 1
    close_shared_store()


# ============================================================
# 2. 会话历史页
# ============================================================

def test_sessions_page_lists_all_sessions(tmp_path):
    store = _seeded_store(tmp_path)
    page = SessionsPage(FakeCenter(store))
    assert page._list.count() == 2
    assert _row_ids(page) == {"s1", "s2"}
    assert not page._list.isHidden()
    assert page._empty_list.isHidden()


def test_sessions_page_shows_messages_of_selected(tmp_path):
    store = _seeded_store(tmp_path)
    page = SessionsPage(FakeCenter(store))

    for i in range(page._list.count()):
        if page._list.item(i).data(Qt.ItemDataRole.UserRole) == "s1":
            page._list.setCurrentRow(i)
            break

    text = page._detail.toPlainText()
    assert "你好" in text and "在的" in text
    assert "用户" in text and "助手" in text
    assert not page._detail.isHidden()


def test_sessions_page_search_filters(tmp_path):
    store = _seeded_store(tmp_path)
    page = SessionsPage(FakeCenter(store))

    page._search.setText("标题二")
    assert _row_ids(page) == {"s2"}

    page._search.setText("translate")      # 也匹配预设 id
    assert _row_ids(page) == {"s2"}

    page._search.setText("不存在的关键字")
    assert page._list.count() == 0
    assert not page._empty_list.isHidden()


def test_sessions_page_empty_state(tmp_path):
    page = SessionsPage(FakeCenter(Store(tmp_path / "empty.db")))
    assert page._list.count() == 0
    assert page._empty_list.isHidden() is False
    assert page._list.isHidden() is True
    assert not page._btn_delete.isEnabled()


def test_sessions_page_delete_and_clear(tmp_path):
    store = _seeded_store(tmp_path)
    page = SessionsPage(FakeCenter(store))

    page._list.setCurrentRow(0)
    page._on_delete()
    assert page._list.count() == 1
    assert len(store.list_sessions()) == 1

    page._on_clear()
    assert page._list.count() == 0
    assert store.list_sessions() == []


def test_sessions_page_survives_broken_store():
    """Store 取不到时页面要降级成空状态，而不是抛异常崩掉控制中心。"""
    page = SessionsPage(FakeCenter(None))
    assert page._list.count() == 0
    assert not page._empty_list.isHidden()


# ============================================================
# 3. 预设页
# ============================================================

def test_presets_page_lists_builtins_as_readonly(tmp_path):
    page = PresetsPage(FakeCenter(Store(tmp_path / "ai.db")))
    assert page._table.rowCount() == len(BUILTIN_PRESETS)

    page._table.setCurrentCell(0, 0)
    assert not page._btn_edit.isEnabled(), "内置预设不该可编辑"
    assert not page._btn_del.isEnabled(), "内置预设不该可删除"


def test_presets_page_custom_crud(tmp_path):
    store = Store(tmp_path / "ai.db")
    page = PresetsPage(FakeCenter(store))
    base = len(BUILTIN_PRESETS)

    preset = Preset(id="custom-1", name="文言文", system_prompt="译成文言",
                    default_delivery=DeliveryKind.REPLACE, description="古风")
    assert page._persist(preset)
    page.reload()
    assert page._table.rowCount() == base + 1

    custom_row = next(i for i, (_p, builtin) in enumerate(page._rows) if not builtin)
    page._table.setCurrentCell(custom_row, 0)
    assert page._btn_edit.isEnabled() and page._btn_del.isEnabled()

    page._on_delete()
    assert page._table.rowCount() == base
    assert store.list_presets() == []


def test_presets_page_persist_fails_gracefully():
    center = FakeCenter(None)
    page = PresetsPage(center)
    ok = page._persist(Preset(id="custom-1", name="x", system_prompt="y"))
    assert ok is False
    assert center.warnings, "保存失败必须给出可见提示，不能静默"


def test_delivery_label_covers_every_kind():
    for kind in DeliveryKind.ALL:
        label = delivery_label(kind)
        assert label and label != kind, f"{kind} 没有中文名"


# ============================================================
# 4. 预设编辑对话框
# ============================================================

def test_preset_dialog_rejects_duplicate_id():
    dlg = PresetEditDialog(None, taken_ids=["ask", "custom-1"])
    dlg._edit_name.setText("测试")
    dlg._edit_prompt.setPlainText("提示词")
    dlg._edit_id.setText("ask")
    dlg._on_ok()
    assert dlg.result() != QDialog.DialogCode.Accepted
    assert "占用" in dlg._err.text()


def test_preset_dialog_rejects_illegal_id():
    dlg = PresetEditDialog(None)
    dlg._edit_name.setText("测试")
    dlg._edit_prompt.setPlainText("提示词")
    dlg._edit_id.setText("非法 ID!")
    dlg._on_ok()
    assert dlg.result() != QDialog.DialogCode.Accepted
    assert "标识" in dlg._err.text()


def test_preset_dialog_rejects_empty_fields():
    dlg = PresetEditDialog(None)
    dlg._edit_name.setText("")
    dlg._edit_prompt.setPlainText("提示词")
    dlg._on_ok()
    assert "名称" in dlg._err.text()

    dlg._edit_name.setText("测试")
    dlg._edit_prompt.setPlainText("   ")
    dlg._on_ok()
    assert "提示词" in dlg._err.text()


def test_preset_dialog_accepts_valid_input():
    dlg = PresetEditDialog(None)
    dlg._edit_name.setText("文言文")
    dlg._edit_id.setText("custom-7")
    dlg._edit_prompt.setPlainText("把用户给的文本翻译成文言文。")
    dlg._edit_desc.setText("古风翻译")
    # 投递方式只提供「当前可用」的那几个 —— 已移除的 replace / paste 不该出现
    offered = [dlg._combo_delivery.itemData(i) for i in range(dlg._combo_delivery.count())]
    assert offered == list(DeliveryKind.AVAILABLE), offered
    assert DeliveryKind.REPLACE not in offered
    assert DeliveryKind.PASTE not in offered

    dlg._combo_delivery.setCurrentIndex(dlg._combo_delivery.findData(DeliveryKind.TTS))
    dlg._on_ok()
    assert dlg.result() == QDialog.DialogCode.Accepted

    p = dlg.result_preset()
    assert p.id == "custom-7"
    assert p.name == "文言文"
    assert p.builtin is False
    assert p.default_delivery == DeliveryKind.TTS


def test_preset_dialog_edit_mode_locks_id():
    """标识是主键，编辑模式下必须锁死 —— 否则会静默产生重复条目。"""
    existing = Preset(id="custom-1", name="旧名", system_prompt="旧提示")
    dlg = PresetEditDialog(None, preset=existing)
    assert dlg._edit_id.text() == "custom-1"
    assert not dlg._edit_id.isEnabled()

    dlg._edit_name.setText("新名")
    dlg._edit_prompt.setPlainText("新提示")
    dlg._on_ok()
    assert dlg.result() == QDialog.DialogCode.Accepted
    assert dlg.result_preset().id == "custom-1"


def test_preset_dialog_auto_ids_skip_taken():
    dlg = PresetEditDialog(None, taken_ids=["custom-1", "custom-2"])
    assert dlg._edit_id.text() == "custom-3"


# ============================================================
# 5. 控制中心整体
# ============================================================

def test_control_center_registers_ai_pages(monkeypatch, tmp_path):
    """导航里必须出现「会话历史」「预设」，且能切过去。"""
    import engine.ai

    monkeypatch.setattr(engine.ai, "shared_store", lambda *a, **k: Store(tmp_path / "ai.db"))

    from presentation.control_center import ControlCenter, reset_instance

    reset_instance()
    win = ControlCenter(app=None)
    try:
        titles = [p.title for p in win._pages]
        assert "会话历史" in titles
        assert "预设" in titles

        win.goto("会话历史")
        assert win.current_page().title == "会话历史"
        win.goto("预设")
        assert win.current_page().title == "预设"
    finally:
        win.close()
        reset_instance()


def test_ai_config_form_hides_the_empty_status_area():
    """没话说时输出区整块收掉。

    那个区固定高 132px，常驻一句「填好后点「测试连接」验证…」既占版面
    又没人看（用户 2026-10-14 明确要求去掉）；但**测试结果仍然要出现**，
    所以是「空则藏、有则显」，不是把这块删掉。
    """
    from data.config_manager import config_manager
    from presentation.ai_config_form import AIConfigForm

    form = AIConfigForm(None, config=config_manager)
    assert form._status.toPlainText() == "", "载入时不该有常驻提示"
    assert form._status.isHidden(), "空的输出区应该整块收掉"

    form.set_status("连接成功")
    assert not form._status.isHidden(), "有结果时必须显示出来"

    form.set_status("")
    assert form._status.isHidden(), "清空后要重新收掉"


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
