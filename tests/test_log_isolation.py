# -*- coding: utf-8 -*-
"""测试隔离的回归测试 —— 保证「测试不写用户的运行日志」。

守的是 `tests/conftest.py` 里那个会话级装置。为什么值得单独测：

`data.log_manager.log_manager` 是**进程级单例**，默认写 `~/.pet_demo/logs/`。
它平时很安静，所以「装置哪天被删掉 / 没生效」不会有任何症状 ——
直到某天用户的 app.log 里出现一条测试制造的「库坏了」。
（这不是假设，`tests/test_tray_indicator.py` 构造 TrayIcon 时真的写过一条。）

所以这两条断言：① 目录确实被换掉了；② 真写一条日志，它**只**出现在临时目录里。
第 ② 条同时确认 logger 没被弄死 —— 否则「没写进用户日志」是永真的。
"""
import logging
from pathlib import Path

MARKER = "测试制造的日志标记-绝不该出现在用户的 app.log 里"


def _real_log_dir() -> Path:
    return Path.home() / ".pet_demo" / "logs"


def _flush():
    for name in ("app", "behavior", "migration"):
        for handler in logging.getLogger(f"pet_demo.{name}").handlers:
            handler.flush()


def test_log_dir_is_redirected_away_from_the_user_directory():
    from data.log_manager import log_manager

    real = _real_log_dir()
    redirected = Path(log_manager._log_dir)
    assert redirected != real, "日志目录没被重定向，测试会写进用户的 ~/.pet_demo/logs/"
    assert real not in redirected.parents, f"重定向目标仍在用户目录下: {redirected}"


def test_a_logged_line_lands_in_the_temp_dir_not_the_users_log():
    from data.log_manager import log_manager

    real_log = _real_log_dir() / "app.log"
    before = real_log.read_text(encoding="utf-8", errors="ignore") if real_log.exists() else ""

    log_manager.warning(MARKER)
    _flush()

    after = real_log.read_text(encoding="utf-8", errors="ignore") if real_log.exists() else ""
    assert MARKER not in after, "测试往用户真实的 app.log 里写了东西"
    assert before.count(MARKER) == 0, "marker 是本文件独有，不该预先出现在用户日志里"

    temp_log = Path(log_manager._log_dir) / "app.log"
    assert temp_log.exists(), "重定向后的日志文件都没生成 —— logger 可能已经死了"
    assert MARKER in temp_log.read_text(encoding="utf-8", errors="ignore"), (
        "日志根本没落到任何地方 —— 那「没写进用户日志」是永真的，这条断言没有意义"
    )
