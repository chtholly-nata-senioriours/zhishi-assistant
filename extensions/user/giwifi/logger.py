# -*- coding: utf-8 -*-
"""giwifi 插件日志 —— 与原版 logger.py 同接口，落点改为桌宠数据目录。

原版把 giwifi.log 写在 exe 同目录；插件化后无独立数据目录权限约定，
改写到 ~/.pet_demo/giwifi.log，接口保持 log(msg) 不变，
login_worker.py / network_checker.py 的 `from logger import log` 零改动。
"""
import os
from datetime import datetime

_LOG_DIR = os.path.join(os.path.expanduser("~"), ".pet_demo")
try:
    os.makedirs(_LOG_DIR, exist_ok=True)
except Exception:
    _LOG_DIR = os.path.dirname(os.path.abspath(__file__))

LOG_FILE = os.path.join(_LOG_DIR, "giwifi.log")


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
