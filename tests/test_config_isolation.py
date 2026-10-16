# -*- coding: utf-8 -*-
"""测试隔离的回归测试 —— 保证「测试不写用户的数据目录」。

守的是 `tests/conftest.py` **模块级**那行 `os.environ["PET_DEMO_HOME"] = ...`。

## 为什么值得单独测

这条装置失效时**没有任何症状**：测试全绿，用户配置被悄悄重写一遍，
内容还字节相同 —— 只有 mtime 变了。我就是在「全量跑完比对 mtime」时
才发现它的（探针 `_probe_userdir.py`）：

    非 cache 的 mtime 变化: ['user_config.json']
    user_config.json 前: mtime=1791952484.242  sha1=4aac6d27bbfb5c68
    user_config.json 后: mtime=1791952552.462  sha1=4aac6d27bbfb5c68

所以这里断言三层：
① 数据根确实不在用户目录下（机制在）；
② 真存一次配置，用户的文件**字节和 mtime 都没变**（效果在）；
③ 该写的时候还是写（否则「没写」是永真的 —— 装置把功能弄死了也测不出来）。
"""

import copy
import json
import tempfile
from pathlib import Path

from data.config_manager import DEFAULT_CONFIG, ConfigManager
from data.paths import PET_HOME_ENV, pet_home, pet_path


def _real_home() -> Path:
    return Path.home() / ".pet_demo"


def _user_config() -> Path:
    return _real_home() / "user_config.json"


def _fingerprint(p: Path):
    if not p.exists():
        return None
    return (p.stat().st_mtime_ns, p.read_bytes())


def _isolated_manager(config_dir: Path) -> ConfigManager:
    """绕过单例 `__init__`，构造一个指向指定目录的实例。

    （单例在模块 import 时就构造好了，`__init__` 有 `_initialized` 短路，
    所以只能用 `object.__new__`。）
    """
    cm = object.__new__(ConfigManager)
    cm._config_dir = config_dir
    cm._user_config_path = config_dir / "user_config.json"
    cm._default_config_path = Path(__file__).parent.parent / "config.default.json"
    return cm


# ---------------------------------------------------------------- ① 机制在


def test_data_root_is_redirected_away_from_the_user_directory():
    real = _real_home()
    root = pet_home()
    assert root != real, "数据根没被重定向，测试会写进用户的 ~/.pet_demo/"
    assert real not in root.parents, f"重定向目标仍在用户目录下: {root}"


def test_pet_home_honours_the_env_var(monkeypatch):
    """`pet_home()` 每次调用都重读环境变量，不做模块级缓存。

    这条看着像在测实现细节，其实守的是本模块的**整个机制**：
    一旦有人给 `pet_home()` 加上 `@lru_cache` 或模块级常量，
    所有**在设变量之前**就 import 了 `data.paths` 的调用方
    都会拿到 `~/.pet_demo`，重定向静默失效。
    """
    monkeypatch.setenv(PET_HOME_ENV, r"C:\tmp\fake-pet-home")
    assert pet_home() == Path(r"C:\tmp\fake-pet-home")
    assert pet_path("logs", "app.log") == Path(r"C:\tmp\fake-pet-home\logs\app.log")

    monkeypatch.delenv(PET_HOME_ENV)
    assert pet_home() == Path.home() / ".pet_demo"


def test_every_user_data_path_lives_under_the_redirected_root():
    """8 处落点必须**全都**跟着数据根走，漏一个就是一条泄漏通道。

    这是本模块存在的意义 —— 之前每个文件各写一遍
    `Path.home() / ".pet_demo" / ...`，测试没法整体挪走。
    """
    from data.log_manager import log_manager
    from engine.activity.store import default_db_path as activity_db
    from engine.ai.store import default_db_path as ai_db
    from presentation.design.icons import cache_root
    from presentation.control_center import CONFIG_DIR

    root = pet_home()
    real = _real_home()

    candidates = {
        "log_manager._log_dir": Path(log_manager._log_dir),
        "ai.db": ai_db(),
        "activity.db": activity_db(),
        "图标缓存": cache_root(),
        "控制中心 CONFIG_DIR": Path(CONFIG_DIR),
    }

    for label, path in candidates.items():
        assert real not in path.parents and path != real, (
            f"{label} 仍指向用户目录: {path}"
        )
        assert root in path.parents or path == root, (
            f"{label} 没落在重定向后的数据根下: {path}（root={root}）"
        )


# ---------------------------------------------------------------- ② 效果在


def test_saving_config_does_not_touch_the_users_file():
    """真存一次配置，用户的 `user_config.json` 必须**连 mtime 都没动**。"""
    from data.config_manager import config_manager

    real = _user_config()
    before = _fingerprint(real)

    config_manager.set("window.center", [123, 456])
    config_manager.save()

    after = _fingerprint(real)
    assert before == after, (
        "测试改动了用户真实的 user_config.json"
        f"（before={before}，after={after}）"
    )

    # 同时确认这一笔确实落到了临时目录 —— 否则「没写用户文件」是永真的
    assert config_manager.get("window.center") == [123, 456]
    assert json.loads(
        config_manager._user_config_path.read_text(encoding="utf-8")
    )["window"]["center"] == [123, 456], "配置根本没落盘 —— 断言①没有意义"


# ---------------------------------------------------------------- ③ 该写还得写


def test_loading_an_identical_file_does_not_rewrite_it():
    """磁盘内容与内存一致时**不重写**（修掉「import 就写盘」的那一刀）。

    这条断言是「无谓写入」的守门员：`_load_config()` 无条件 `save()` 的话，
    本模块**被 import 的那一刻**就会重写用户的配置 —— 而 pytest 的 fixture
    要到测试执行时才跑，拦不住 import。所以修法有两层：
    ① 环境变量前置换根（结构性）；② 这一层「一致就不写」（不写就没有伤害）。
    """
    with tempfile.TemporaryDirectory() as td:
        cfg_file = Path(td) / "user_config.json"
        cfg_file.write_text(
            json.dumps(copy.deepcopy(DEFAULT_CONFIG), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        before = _fingerprint(cfg_file)

        _isolated_manager(Path(td))._load_config()

        assert _fingerprint(cfg_file) == before, "内容一致却被重写了（mtime 会无谓变动）"


def test_loading_a_stale_file_still_materialises_new_defaults():
    """反向：文件里缺了新版的默认节，必须补写进去。

    没有这条，「不重写」可以靠「干脆永不 save」作弊过关 ——
    而永不 save 会让升级后新增的配置项永远不出现在用户文件里。
    """
    with tempfile.TemporaryDirectory() as td:
        cfg_file = Path(td) / "user_config.json"
        stale = copy.deepcopy(DEFAULT_CONFIG)
        del stale["appearance"]                      # 假装是旧版本写的文件
        stale["window"]["opacity"] = 0.42            # 用户自己的设置
        cfg_file.write_text(json.dumps(stale, ensure_ascii=False), encoding="utf-8")

        cm = _isolated_manager(Path(td))
        cm._load_config()

        on_disk = json.loads(cfg_file.read_text(encoding="utf-8"))
        assert "appearance" in on_disk, "新版默认节没被补写进用户文件"
        assert on_disk["appearance"]["orb_size"] == DEFAULT_CONFIG["appearance"]["orb_size"]
        assert on_disk["window"]["opacity"] == 0.42, "补写时把用户设置弄丢了"


def test_default_config_constant_is_not_mutated_by_config_manager():
    """`set()` 不能改到模块级 `DEFAULT_CONFIG`。

    历史隐患：`DEFAULT_CONFIG.copy()` 是**浅拷贝**，嵌套节与常量共享同一个
    dict。于是 `config_manager.set("window.center", ...)` 会顺手改掉
    `DEFAULT_CONFIG["window"]` —— 而它是「重置为默认」和版本迁移的基准。
    """
    with tempfile.TemporaryDirectory() as td:
        cm = _isolated_manager(Path(td))
        cm._load_config()
        snapshot = copy.deepcopy(DEFAULT_CONFIG)

        cm.set("window.center", [7, 7])
        cm.set("appearance.orb_size", 88)
        cm.reset_to_default()

        assert DEFAULT_CONFIG == snapshot, "DEFAULT_CONFIG 被 set()/reset 改动了"
