# -*- coding: utf-8 -*-
"""系统密钥库（P1-5）—— API Key 安全存取的契约测试。

守的是四件事：
    1. **不落地明文**：密钥进系统密钥库，配置文件与磁盘上都不出现它。
    2. **动态读取**：`resolve_api_key()` 是唯一读密钥的地方；引用存在就
       从密钥库取，取不到才回退明文（老用户）。
    3. **权限隔离**：条目名有白名单（挡路径穿越），DPAPI 按当前用户加密。
    4. **脱敏**：`mask()` 只露头尾且**总长度固定** —— 真实长度本身就是信息。

⚠ 这些用例会真的调用 Windows DPAPI（`CryptProtectData`）—— 这是刻意的：
   mock 掉加密等于没测「存进去的东西不是明文」。

运行:
    python tests/test_key_store.py
    pytest tests/test_key_store.py -v
"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from data import key_store  # noqa: E402
from data.paths import pet_home  # noqa: E402

#: 一把形状真实的假钥匙（不是真 key，仅用于断言「它没有出现在明文里」）。
SECRET = "sk-testonly-0123456789abcdef0123456789abcdef"


# ============================================================
# 测试替身
# ============================================================

class FakeConfig:
    """`ConfigManager` 的最小替身：点号路径读写 + 真的落盘（要断言磁盘内容）。

    ⚠ 构造时**深拷贝**入参：`dict(values)` 是浅拷贝，`values["ai"]` 会和调用方
      共享同一个 dict —— 一次 `set("ai.api_key", ...)` 就把模块级的 `_BASE`
      改掉了，后面的用例于是拿到一份被别人改过的配置。
      （这不是假设：初版就踩了，三个用例因为执行顺序而红/绿不一。）
    """

    def __init__(self, path: Path, values=None):
        self.path = Path(path)
        self.vals = json.loads(json.dumps(values or {}))
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
        self.path.write_text(json.dumps(self.vals, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        return True


# ============================================================
# ① 脱敏
# ============================================================

class TestMask:

    def test_keeps_only_head_and_tail(self):
        masked = key_store.mask(SECRET)
        # 用**精确常量**而不是 startswith / endswith：`raw[:8] + raw[-4:]`
        # 那种「多露一段、还完全不遮」的实现同样满足 startswith / endswith，
        # 只有逐字符相等才拦得住「头露多了」。
        assert masked == SECRET[:3] + "•" * 8 + SECRET[-4:]
        assert "•" in masked, "中段必须是遮罩字符，不能是原文"
        assert SECRET not in masked
        assert SECRET[3:-4] not in masked, "中间那段一个字符都不许露"

    def test_length_is_not_leaked(self):
        """长度固定 —— 露出真实长度等于告诉别人试错空间有多大。"""
        short = key_store.mask("sk-abcdefghij")
        long = key_store.mask("sk-" + "x" * 200)
        assert len(short) == len(long) == len(key_store.mask(SECRET))
        # 连「固定成多少」也钉住：头 3 + 遮罩 8 + 尾 4。
        # 写死这个数字是有意的 —— 它是安全参数，改它就该顺手改测试。
        assert len(short) == 3 + 8 + 4

    def test_short_secret_is_fully_hidden(self):
        masked = key_store.mask("sk-123")
        # 精确常量：短密钥走的是「全遮」分支，而不是「头尾拼接恰好把整串露完」
        assert masked == "•" * 8
        assert "1" not in masked and "s" not in masked

    def test_empty_says_so_instead_of_returning_empty(self):
        # 界面上「--」会被读成「加载失败」，而这里想说的是「还没有密钥」
        assert key_store.mask("") == "（未设置）"
        assert key_store.mask(None) == "（未设置）"


# ============================================================
# ② 条目名
# ============================================================

class TestEntryName:

    def test_host_from_base_url(self):
        assert key_store.entry_for_base_url("https://api.deepseek.com/v1") == "api.deepseek.com"
        assert key_store.entry_for_base_url("http://localhost:11434/v1") == "localhost"
        assert key_store.entry_for_base_url("api.siliconflow.cn/v1") == "api.siliconflow.cn"

    def test_unparsable_falls_back_to_default(self):
        for raw in ("", "   ", "///", "!!!", None):
            assert key_store.entry_for_base_url(raw) == "default"

    def test_ref_round_trip(self):
        assert key_store.ref_for("api.deepseek.com") == "keyring:api.deepseek.com"
        assert key_store.entry_of("keyring:api.deepseek.com") == "api.deepseek.com"
        # 裸名字也认（读路径上要宽容），写路径由 `store_key` 再校验一次
        assert key_store.entry_of("api.deepseek.com") == "api.deepseek.com"

    def test_entry_names_cannot_escape_the_store(self):
        for bad in ("../evil", "a/b", "a\\b", "", "x" * 65, ".hidden", "-lead"):
            assert not key_store.valid_entry(bad), bad

    def test_store_refuses_a_bad_entry_name(self):
        ok, message = key_store.store_key("../evil", SECRET)
        assert not ok and "不合法" in message


# ============================================================
# ③ 存取：真的过一遍系统密钥库
# ============================================================

class TestStoreAndLoad:

    def test_a_backend_is_available_on_windows(self):
        """本机（Windows）至少要有一个后端 —— 两个都没有就等于没有这个功能。"""
        if os.name == "nt":
            assert key_store.available(), key_store.status()
            assert key_store.backend_name() in ("keyring", "dpapi")

    def test_round_trip(self):
        ok, message = key_store.store_key("unit.test", SECRET)
        assert ok, message
        assert key_store.load_key("unit.test") == SECRET
        assert key_store.load_key("keyring:unit.test") == SECRET
        assert key_store.has_key("unit.test") is True

    def test_secret_is_not_plaintext_on_disk(self):
        """**最关键的一条**：磁盘上找不到明文密钥。

        这条是「不落地明文」这个承诺的唯一客观判据 ——
        mock 掉加密、或只断言「读回来一样」，都测不出它。
        """
        assert key_store.backend_name() == "dpapi", (
            "本机装了 keyring 时这条断言不适用（密钥由系统保管，不在数据根里）")
        key_store.store_key("unit.disk", SECRET)
        blob = (pet_home() / key_store.DPAPI_FILE).read_bytes()
        assert SECRET.encode("utf-8") not in blob
        assert b"sk-testonly" not in blob

    def test_missing_entry_gives_empty_string(self):
        assert key_store.load_key("nope.missing") == ""
        assert key_store.load_key("") == ""
        assert key_store.has_key("nope.missing") is False

    def test_overwrite_replaces_the_value(self):
        key_store.store_key("unit.over", "sk-first-000000000000")
        key_store.store_key("unit.over", SECRET)
        assert key_store.load_key("unit.over") == SECRET

    def test_delete_is_idempotent(self):
        key_store.store_key("unit.del", SECRET)
        ok, _ = key_store.delete_key("unit.del")
        assert ok
        assert key_store.load_key("unit.del") == ""
        ok, _ = key_store.delete_key("unit.del")      # 再删一次不算错
        assert ok

    def test_other_entries_survive_a_delete(self):
        key_store.store_key("unit.keep", SECRET)
        key_store.store_key("unit.gone", "sk-other-000000000000")
        key_store.delete_key("unit.gone")
        assert key_store.load_key("unit.keep") == SECRET

    def test_empty_secret_is_refused(self):
        ok, message = key_store.store_key("unit.empty", "")
        assert not ok and "空" in message


# ============================================================
# ④ 动态读取：唯一入口
# ============================================================

class TestResolveApiKey:

    def test_ref_wins_over_plaintext(self):
        from engine.ai import resolve_api_key

        key_store.store_key("unit.resolve", SECRET)
        cfg = FakeConfig(pet_home() / "x.json", {
            "ai": {"api_key_ref": "keyring:unit.resolve", "api_key": "sk-plain-should-lose"}
        })
        assert resolve_api_key(cfg) == SECRET

    def test_plaintext_is_the_legacy_fallback(self):
        from engine.ai import resolve_api_key

        cfg = FakeConfig(pet_home() / "x.json", {"ai": {"api_key": "sk-legacy"}})
        assert resolve_api_key(cfg) == "sk-legacy"

    def test_missing_keyring_entry_falls_back_to_plaintext(self):
        """引用存在但取不到 → 回退明文（老配置），而不是返回空。"""
        from engine.ai import resolve_api_key

        cfg = FakeConfig(pet_home() / "x.json", {
            "ai": {"api_key_ref": "keyring:unit.absent", "api_key": "sk-legacy"}})
        assert resolve_api_key(cfg) == "sk-legacy"

    def test_nothing_configured_gives_empty(self):
        from engine.ai import resolve_api_key

        assert resolve_api_key(FakeConfig(pet_home() / "x.json", {})) == ""


# ============================================================
# ⑤ 配置表单：三种走向
# ============================================================

def _form(tmp_path, values):
    from presentation.ai_config_form import AIConfigForm

    cfg = FakeConfig(tmp_path / "user_config.json", values)
    form = AIConfigForm(None, config=cfg)
    return form, cfg


_BASE = {
    "ai": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "vision_model": "",
        "api_key": "",
        "api_key_ref": "",
        "request_timeout": 60,
    }
}


class TestConfigFormKeyring:

    def test_default_mode_prefers_the_system_store(self, tmp_path):
        form, _ = _form(tmp_path, _BASE)
        assert form._key_mode.index() == 0, "默认应当是「系统密钥库」"

    def test_saving_a_new_key_stores_it_outside_the_config(self, tmp_path):
        form, cfg = _form(tmp_path, _BASE)
        form._key_edit.setText(SECRET)
        assert form.save() is True

        entry = key_store.entry_for_base_url("https://api.deepseek.com/v1")
        assert key_store.load_key(entry) == SECRET
        assert cfg.get("ai.api_key") == "", "密钥库模式下配置里不许留明文"
        assert cfg.get("ai.api_key_ref") == f"keyring:{entry}"
        on_disk = (tmp_path / "user_config.json").read_text(encoding="utf-8")
        assert SECRET not in on_disk, "配置文件里出现了明文密钥"

    def test_plaintext_mode_still_works_and_clears_the_ref(self, tmp_path):
        key_store.store_key("api.deepseek.com", "sk-old-from-store")
        values = json.loads(json.dumps(_BASE))
        values["ai"]["api_key_ref"] = "keyring:api.deepseek.com"

        form, cfg = _form(tmp_path, values)
        assert form._key_mode.index() == 0
        form._key_mode.set_index(1)
        form._key_edit.setText(SECRET)
        assert form.save() is True

        assert cfg.get("ai.api_key") == SECRET
        assert cfg.get("ai.api_key_ref") == "", "留着旧引用会优先读到密钥库，用户以为改了却没生效"

    def test_empty_field_in_keyring_mode_does_not_wipe_the_stored_key(self, tmp_path):
        key_store.store_key("api.deepseek.com", SECRET)
        values = json.loads(json.dumps(_BASE))
        values["ai"]["api_key_ref"] = "keyring:api.deepseek.com"
        form, cfg = _form(tmp_path, values)

        assert form._key_edit.text() == "", "密钥库里的钥匙不该被回填进输入框"
        assert form.save() is True
        assert key_store.load_key("api.deepseek.com") == SECRET
        assert cfg.get("ai.api_key") == ""

    def test_plaintext_key_is_migrated_when_switching_mode(self, tmp_path):
        """老用户的明文密钥：只切一下保存位置就能搬进密钥库。"""
        values = json.loads(json.dumps(_BASE))
        values["ai"]["api_key"] = "sk-legacy-plaintext-key"
        form, cfg = _form(tmp_path, values)
        assert form._key_mode.index() == 1

        form._key_mode.set_index(0)
        assert form.save() is True

        entry = key_store.entry_for_base_url("https://api.deepseek.com/v1")
        assert key_store.load_key(entry) == "sk-legacy-plaintext-key"
        assert cfg.get("ai.api_key") == ""
        on_disk = (tmp_path / "user_config.json").read_text(encoding="utf-8")
        assert "sk-legacy-plaintext-key" not in on_disk

    def test_keyring_mode_without_any_key_refuses_to_save(self, tmp_path):
        form, cfg = _form(tmp_path, _BASE)
        form._key_edit.setText("")
        assert form.save() is False
        assert "还没有密钥" in form._status.toPlainText()
        assert cfg.saved == 0

    def test_switching_the_mode_counts_as_an_unsaved_change(self, tmp_path):
        """只切保存位置也是改动 —— 否则「搬到密钥库」这一步永远提示不了未保存。"""
        values = json.loads(json.dumps(_BASE))
        values["ai"]["api_key"] = "sk-legacy"
        form, _ = _form(tmp_path, values)
        assert form.has_unsaved_changes() is False
        form._key_mode.set_index(0)
        assert form.has_unsaved_changes() is True

    def test_probe_uses_the_stored_key_when_the_field_is_empty(self, tmp_path):
        """留空 = 不修改。此时「测试连接」要用密钥库里那一把，不能拿空串去测。"""
        key_store.store_key("api.deepseek.com", SECRET)
        values = json.loads(json.dumps(_BASE))
        values["ai"]["api_key_ref"] = "keyring:api.deepseek.com"
        form, _ = _form(tmp_path, values)
        assert form.collect()["api_key"] == SECRET

    def test_saving_does_not_log_the_secret(self, tmp_path, caplog):
        import logging

        form, _ = _form(tmp_path, _BASE)
        form._key_edit.setText(SECRET)
        with caplog.at_level(logging.DEBUG):
            assert form.save() is True
        assert SECRET not in caplog.text
        # 但「密钥放在哪」要记 —— 排查「为什么读不到 key」时这是唯一的线索
        assert "系统密钥库" in caplog.text


# ============================================================
# ⑥ 隐私页如实说明密钥存在哪
# ============================================================

class TestPrivacyNote:

    def test_note_follows_the_real_config(self, monkeypatch):
        from data import privacy
        from data.config_manager import config_manager

        monkeypatch.setattr(config_manager, "get",
                            lambda key, default=None: {
                                "ai.api_key_ref": "keyring:api.deepseek.com",
                                "ai.api_key": "",
                            }.get(key, default))
        assert "系统密钥库" in privacy._key_storage_note()

        monkeypatch.setattr(config_manager, "get",
                            lambda key, default=None: {
                                "ai.api_key_ref": "",
                                "ai.api_key": "sk-plain",
                            }.get(key, default))
        note = privacy._key_storage_note()
        assert "明文" in note and "搬进系统密钥库" in note

        monkeypatch.setattr(config_manager, "get",
                            lambda key, default=None: {"ai.api_key_ref": "",
                                                       "ai.api_key": ""}.get(key, default))
        assert privacy._key_storage_note() == ""

    def test_config_entry_carries_the_note(self, monkeypatch):
        from data import privacy
        from data.config_manager import config_manager

        monkeypatch.setattr(config_manager, "get",
                            lambda key, default=None: {
                                "ai.api_key_ref": "keyring:x", "ai.api_key": ""}.get(key, default))
        entry = next(e for e in privacy.entries() if e.key == "config")
        assert "系统密钥库" in entry.detail
