# -*- coding: utf-8 -*-
"""giwifi 插件配置 —— 与原版 config.py 逻辑一致（JSON + Base64 密码混淆）。

唯一差异：存储路径由"exe/源码同目录"改为 ~/.pet_demo/giwifi_config.json，
避免插件写自身目录（Program Files 下无写权限）。读写逻辑、字段、
编码方式均保持原版不变。
"""
import json
import base64
import os

_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".pet_demo")
try:
    os.makedirs(_CONFIG_DIR, exist_ok=True)
except Exception:
    _CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(_CONFIG_DIR, "giwifi_config.json")

DEFAULT_CONFIG = {
    "username": "",
    "password": "",
    "portal_url": "http://172.27.253.230/gportal/web/login",
    "wlanacname": "SDZYY",
    "check_interval": 10,
    "auto_login": True,       # 断网自动重连（原版由 UI 开关驱动，插件内同名语义）
    "notify": True,
}


def _encode(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("utf-8")


def _decode(text: str) -> str:
    return base64.b64decode(text.encode("utf-8")).decode("utf-8")


def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return DEFAULT_CONFIG.copy()
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    config = DEFAULT_CONFIG.copy()
    config.update(data)
    if config.get("password"):
        try:
            config["password"] = _decode(config["password"])
        except Exception:
            pass
    return config


def save_config(config: dict):
    data = config.copy()
    if data.get("password"):
        data["password"] = _encode(data["password"])
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
