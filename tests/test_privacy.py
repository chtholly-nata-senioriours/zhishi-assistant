# -*- coding: utf-8 -*-
"""`data/privacy.py`（本机数据清单 / 导出 / 清空）与「隐私与数据」页的回归测试。

这份测试守三件事：
    ① **清单是真的**：每一类都落在数据根下（`PET_DEMO_HOME` 重定向后），
       没有一类指向用户真实目录 —— 这是 `paths.py` 那条结构性保证的延伸。
    ② **导出是可用的**：zip 里真有数据、单类导出真的只装那一类、
       数据库走 backup 而不是把 `-wal` 一起塞进去。
    ③ **清空是问过再动的**：有插件借插件、没插件才删文件；
       每条失败都要给出人能看懂的原因，而不是静默成功。

数据根在每个用例里用 `monkeypatch.setenv` 换成自己的临时目录 ——
`pet_home()` 每次调用重读环境变量，正是为了这个（见 `data/paths.py`）。
"""
import os
import sqlite3
import sys
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from data.paths import PET_HOME_ENV
from data.privacy import (
    clear_entry,
    entries,
    export_data,
    find,
    human_size,
    total_size,
)
from presentation.design.widgets import Button


@pytest.fixture
def home(monkeypatch, tmp_path):
    """每个用例一个独立的数据根 —— 用例之间不许互相看见对方的文件。"""
    root = tmp_path / "pet_home"
    root.mkdir()
    monkeypatch.setenv(PET_HOME_ENV, str(root))
    return root


def _write(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _make_db(path: Path, table: str = "sessions") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (id TEXT)")
    conn.execute(f"INSERT INTO {table} (id) VALUES ('a-row')")
    conn.commit()
    conn.close()


# ================================================================
# ① 清单是真的
# ================================================================

def test_every_entry_lives_under_the_data_root(home):
    """6 类数据必须**全都**落在数据根下 —— 漏一类就是一条「说了却没管」的账。"""
    for entry in entries():
        for p in entry.paths:
            assert home in p.parents or p == home, f"{entry.key} 指向数据根外：{p}"


def test_entries_cover_the_known_files(home):
    """磁盘上真实存在的每类数据都要被列出来，包括旧版本遗留。"""
    _write(home / "user_config.json")
    _make_db(home / "ai.db")
    _make_db(home / "activity.db")
    _write(home / "notes.json")
    _write(home / "logs" / "app.log", "hello")
    _write(home / "cache" / "icons" / "a.svg")

    keys = [e.key for e in entries()]
    assert keys == ["config", "ai_sessions", "activity", "logs", "cache", "legacy"]
    for entry in entries():
        assert entry.size() > 0, f"{entry.key} 明明有文件却算成 0"


def test_human_size_uses_the_same_unit_everywhere():
    """各处显示大小必须一个口径 —— 页面与导出提示各算各的就会互相矛盾。"""
    assert human_size(0) == "0 B"
    assert human_size(1023) == "1023 B"
    assert human_size(1024) == "1.0 KB"
    assert human_size(1024 * 1024 * 3) == "3.0 MB"


def test_total_size_is_the_sum_of_entries(home):
    _write(home / "user_config.json", "12345")
    _write(home / "logs" / "app.log", "123")
    assert total_size() == 8


# ================================================================
# ② 导出是可用的
# ================================================================

def test_export_all_packs_everything_plus_a_readme(home, tmp_path):
    dest = tmp_path / "out"
    dest.mkdir()
    _write(home / "user_config.json", "{}")
    _make_db(home / "ai.db")
    _write(home / "logs" / "app.log", "line")

    ok, message, zip_path = export_data(dest)
    assert ok, message
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        assert "user_config.json" in names
        assert "ai.db" in names
        assert "logs/app.log" in names
        assert "README.txt" in names
        assert "README.txt" in names
        # 旁车不该原样进去 —— 它会被 backup 合并掉
        assert "ai.db-wal" not in names


def test_exported_db_is_a_usable_copy_not_a_raw_dump(home, tmp_path):
    """zip 里的 ai.db 必须能被 sqlite 打开、且真有那行数据。"""
    dest = tmp_path / "out"
    dest.mkdir()
    _make_db(home / "ai.db")
    _write(home / "ai.db-wal", "junk")

    ok, _, zip_path = export_data(dest)
    assert ok
    extracted = tmp_path / "ai.db"
    with zipfile.ZipFile(zip_path) as zf:
        zf.extract("ai.db", tmp_path)
    conn = sqlite3.connect(str(extracted))
    try:
        assert conn.execute("SELECT id FROM sessions").fetchall() == [("a-row",)]
    finally:
        conn.close()


def test_exported_db_includes_data_that_only_lives_in_the_wal(home, tmp_path):
    """导出必须拿到**只在 WAL 里**的那些行。

    为什么专门造这个场景
        WAL 模式下刚提交的数据在 `-wal` 里，主库文件还是旧的。导出时
        **只原样拷主库**就会丢掉它们 —— 用户以为导走了全部历史，
    实际缺了最近几轮对话，而这种缺失没有任何报错。
    （`_backup_db` 走 sqlite 的 backup API 正是为了这个；
     反向验证：把 backup 改成恒失败，本用例当场打红。）
    """
    dest = tmp_path / "out"
    dest.mkdir()
    db = home / "ai.db"

    conn = sqlite3.connect(str(db))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE sessions (id TEXT)")
        conn.commit()
        conn.execute("INSERT INTO sessions VALUES ('only-in-wal')")
        conn.commit()
        # 趁连接还开着（没有 checkpoint，数据只住在 -wal 里）导出
        ok, message, zip_path = export_data(dest)
    finally:
        conn.close()
    assert ok, message

    extracted = tmp_path / "extracted"
    extracted.mkdir(exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        assert "ai.db-wal" not in zf.namelist()
        zf.extract("ai.db", extracted)
    copy = sqlite3.connect(str(extracted / "ai.db"))
    try:
        assert copy.execute("SELECT id FROM sessions").fetchall() == [("only-in-wal",)]
    finally:
        copy.close()


def test_export_subset_only_packs_that_entry(home, tmp_path):
    """单类导出只装那一类 —— 用户点「设置与偏好」时不想连带拿到会话库。"""
    dest = tmp_path / "out"
    dest.mkdir()
    _write(home / "user_config.json", "{}")
    _make_db(home / "ai.db")
    _write(home / "logs" / "app.log", "line")

    ok, message, zip_path = export_data(dest, ("config",))
    assert ok, message
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
    assert names == {"user_config.json", "README.txt"}


def test_export_of_an_empty_entry_says_so_instead_of_writing_a_zip(home, tmp_path):
    dest = tmp_path / "out"
    dest.mkdir()
    ok, message, zip_path = export_data(dest, ("legacy",))
    assert not ok
    assert "还没有数据" in message
    assert zip_path is None
    assert list(dest.iterdir()) == [], "失败时不该留下半截 zip"


def test_export_to_a_missing_folder_reports_it(home, tmp_path):
    ok, message, _ = export_data(tmp_path / "nope")
    assert not ok
    assert "目标目录" in message


# ================================================================
# ③ 清空是问过再动的
# ================================================================

def test_clear_activity_prefers_the_plugins_live_handle(home):
    """插件还持着连接时走它的 `clear_data()`，不删文件 —— 否则 Windows 上
    只会得到一个 PermissionError，而用户看到的是「点了没反应」。"""
    _make_db(home / "activity.db")
    (home / "activity.db-wal").write_bytes(b"wal")
    (home / "activity.db-shm").write_bytes(b"shm")
    before = (home / "activity.db").read_bytes()

    class _Plugin:
        def clear_data(self):
            return 7

    class _App:
        plugin_manager = type("PM", (), {"get_plugin": staticmethod(
            lambda name: _Plugin() if name == "activity_advisor" else None)})()

    ok, message = clear_entry("activity", _App())
    assert ok, message
    assert "7 条分段" in message
    assert (home / "activity.db").read_bytes() == before, "走了插件 API 就不该再删库文件"
    assert not (home / "activity.db-wal").exists(), "旁车要一起清掉"
    assert not (home / "activity.db-shm").exists(), "旁车要一起清掉"


def test_clear_activity_without_plugin_deletes_the_files(home):
    _make_db(home / "activity.db")
    _write(home / "activity.db-wal", "junk")
    ok, message = clear_entry("activity", None)
    assert ok, message
    assert not (home / "activity.db").exists()
    assert not (home / "activity.db-wal").exists(), "旁车要跟着一起走"


def test_clear_legacy_removes_the_old_notes_and_quick_launch(home):
    _write(home / "notes.json", "[]")
    _write(home / "quick_launch.json", "[]")
    ok, message = clear_entry("legacy", None)
    assert ok, message
    assert not (home / "notes.json").exists()
    assert not (home / "quick_launch.json").exists()


def test_clear_logs_empties_but_keeps_the_files(home, monkeypatch):
    """日志是**清空**不是删除 —— 文件的 handler 还开着，删了会让后续写入失效。

    这里把 `log_manager._log_dir` 一并指到用例的数据根：生产里它默认就是
    `pet_path("logs")`（与清单同一个来源），只有测试把根换走了才需要显式对齐。
    """
    from data.log_manager import log_manager

    monkeypatch.setattr(log_manager, "_log_dir", home / "logs")
    _write(home / "logs" / "app.log", "line\n" * 10)
    ok, message = clear_entry("logs", None)
    assert ok, message
    assert (home / "logs" / "app.log").exists()
    assert (home / "logs" / "app.log").read_text(encoding="utf-8") == ""


def test_clear_cache_removes_the_directory(home):
    _write(home / "cache" / "icons" / "a.svg")
    ok, message = clear_entry("cache", None)
    assert ok, message
    assert not (home / "cache").exists()


def test_clear_ai_sessions_closes_the_shared_store_first(home):
    """共享单例持着连接 —— 不先关就删，只会撞权限。"""
    from engine.ai import store as ai_store

    _make_db(home / "ai.db")
    ai_store.shared_store(home / "ai.db")       # 占住连接
    ok, message = clear_entry("ai_sessions", None)
    assert ok, message
    assert not (home / "ai.db").exists()
    # 关掉之后要能原样重建 —— 用户重启后会话历史是空的，不是坏的
    again = ai_store.shared_store(home / "ai.db")
    assert (home / "ai.db").exists()
    ai_store.close_shared_store()


def test_clear_unknown_key_is_refused_with_a_reason():
    ok, message = clear_entry("no-such-thing", None)
    assert not ok
    assert "no-such-thing" in message


# ================================================================
# ④ 页面：该问就问，该禁就禁
# ================================================================


class _FakeCenter:
    app = None

    def __init__(self):
        self.confirmed = False
        self.infos = []
        self.warnings = []

    def confirm(self, title, text):
        self._last = (title, text)
        return self.confirmed

    def info(self, title, text):
        self.infos.append((title, text))

    def warn(self, title, text):
        self.warnings.append((title, text))

    def refresh_status(self):
        pass


def _privacy_page(home, center=None):
    from presentation.control_center import PrivacyPage

    return PrivacyPage(center or _FakeCenter(), None)


def _buttons(page, row: int):
    cell = page._table.cellWidget(row, 3)
    return {b.text(): b for b in cell.findChildren(Button)}


def test_page_lists_every_entry(home):
    page = _privacy_page(home)
    assert page._table.rowCount() == len(entries())
    labels = [page._table.item(r, 0).text() for r in range(page._table.rowCount())]
    assert labels == [e.label for e in entries()]


def test_page_mentions_the_data_root_in_the_total_line(home):
    """「存在哪」必须写在页面上 —— 只说「本机」不说路径，用户还是找不到。"""
    page = _privacy_page(home)
    assert str(home) in page._lbl_total.text()


def test_empty_entries_have_their_buttons_disabled(home):
    """没有数据的类别不许让用户点「导出 / 清空」—— 点了只会弹一个错误框。"""
    page = _privacy_page(home)
    for row in range(page._table.rowCount()):
        assert not _buttons(page, row)["导出"].isEnabled()
        assert not _buttons(page, row)["清空"].isEnabled()


def test_buttons_wake_up_once_there_is_data(home):
    _write(home / "user_config.json", "{}")
    page = _privacy_page(home)
    buttons = _buttons(page, 0)
    assert buttons["导出"].isEnabled()
    assert buttons["清空"].isEnabled()
    assert page._table.item(0, 1).text() == "2 B"


def test_clear_asks_before_touching_anything(home, monkeypatch):
    """取消确认 → 一个字节都不该动。"""
    _write(home / "user_config.json", "keep-me")
    center = _FakeCenter()          # confirmed = False
    page = _privacy_page(home, center)

    entry = find("config")
    page._on_clear(entry)
    assert center._last[0].startswith("清空")
    assert "不能撤销" in center._last[1]
    assert (home / "user_config.json").read_text(encoding="utf-8") == "keep-me"


def test_clear_after_confirm_reports_what_happened(home, monkeypatch):
    _write(home / "user_config.json", "{}")
    from data.config_manager import config_manager

    snapshot = dict(config_manager._config)
    try:
        center = _FakeCenter()
        center.confirmed = True
        page = _privacy_page(home, center)
        page._on_clear(find("config"))
        assert center.infos and center.infos[-1][0] == "已清空"
        assert "恢复默认设置" in center.infos[-1][1]
    finally:
        # 别把共享配置单例的默认重置留给后面的用例
        config_manager._config = snapshot
