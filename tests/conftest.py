# -*- coding: utf-8 -*-
"""pytest 全局装置。

## 为什么要有这个文件：测试不许碰用户的运行数据

`data.log_manager.log_manager` 是**进程级单例**，默认把日志写进
**用户真实的** `~/.pet_demo/logs/`。只要测试路径上碰到会记日志的代码，
就会往用户的运行日志里写东西 —— 这是真的发生过：

    TrayIcon.refresh_activity() 的降级分支会 log_manager.warning(...)，
    而 tests/test_tray_indicator.py 要构造 TrayIcon，
    于是用户的 app.log 里多出一条测试制造的「读取今日深度工作进度失败: 库坏了」。

日志还是轻的。真正的风险是「测试写进用户数据目录」这个**模式**本身：
今天写日志，明天就可能写到 `user_config.json` / `activity.db`。
所以这里做成**结构性保证**。

## 修法：在 import 之前把整个数据根换掉（2026-10-14 修）

`data.config_manager.config_manager` 也是进程级单例，而它在**模块被 import
的那一刻**就构造好并 `_load_config()`。用 fixture 拦不住 ——
**fixture 要等到测试执行时才跑，那时模块早就 import 完了**。

实测（探针 `_probe_userdir.py`，全量测试前后比对整棵 `~/.pet_demo`）：

    非 cache 的 mtime 变化: ['user_config.json']
    user_config.json 前: mtime=1791952484.242  sha1=4aac6d27bbfb5c68
    user_config.json 后: mtime=1791952552.462  sha1=4aac6d27bbfb5c68
                                            ↑ 内容一样，但每次跑测试都重写一遍

所以重定向必须发生在 **conftest 的模块级代码**里（模块级在测试模块被 import
之前执行，fixture 不行），机制是环境变量 `PET_DEMO_HOME`（见 `data/paths.py`）。

下面那两个 fixture 现在只是**双保险 + 验证**：
即使哪天 conftest 的模块级代码被挪走 / 被绕过，它们也会在会话开始时
把已经构造好的单例再掰回临时目录，并断言确实掰过去了。
"""

import logging
import os
import shutil
import tempfile
from pathlib import Path

import pytest

# ============================================================
# 必须在任何项目模块被 import 之前执行 —— 这段是**模块级**代码，不是 fixture。
# ============================================================

_TEST_HOME = Path(tempfile.mkdtemp(prefix="pet_demo_test_home_"))
os.environ["PET_DEMO_HOME"] = str(_TEST_HOME)


@pytest.fixture(scope="session", autouse=True)
def _isolated_data_home():
    """会话结束时清掉临时数据根。

    （重定向本身在模块级已经做完了，这里只负责收尾与验证。）
    """
    from data.paths import pet_home

    assert pet_home() == _TEST_HOME, (
        f"数据根没被重定向到临时目录：pet_home()={pet_home()}，"
        "测试会写进用户的 ~/.pet_demo/"
    )
    yield _TEST_HOME
    shutil.rmtree(_TEST_HOME, ignore_errors=True)


@pytest.fixture(scope="session", autouse=True)
def _isolate_logs():
    """把 `pet_demo.*` 日志重定向到临时目录（整个会话，自动生效）。

    双保险：`log_manager` 的 handler 是在**它自己 import 时**建的。
    正常路径上 `PET_DEMO_HOME` 已经生效，这里重建一次 handler，
    保证即使 `log_manager` 被更早地 import 过也不会写到用户目录。
    """
    from data.log_manager import log_manager

    tmp = _TEST_HOME / "logs"
    tmp.mkdir(parents=True, exist_ok=True)
    log_manager._log_dir = tmp

    for name in ("app", "behavior", "migration"):
        logger = logging.getLogger(f"pet_demo.{name}")
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:  # noqa: BLE001 —— 关不掉也不该让测试起不来
                pass
        handler = logging.FileHandler(tmp / f"{name}.log", encoding="utf-8")
        logger.addHandler(handler)

    yield tmp


@pytest.fixture(scope="session", autouse=True)
def _isolate_config():
    """把配置目录再掰一次到临时目录（双保险）。

    窗口位置 / 外观形态是**产品行为**要写盘的，测试构造一个 `ShellWindow`
    再拖一下就会触发 `save()`。这里断言单例确实指向临时目录。
    """
    from data.config_manager import config_manager

    if Path(config_manager.config_dir) != _TEST_HOME:
        # 正常不该走到这里；走到了说明 conftest 的模块级重定向没生效。
        config_manager.redirect_for_tests(_TEST_HOME)

    assert Path(config_manager.config_dir) == _TEST_HOME, (
        f"配置目录没被重定向：{config_manager.config_dir}"
    )
    yield _TEST_HOME
