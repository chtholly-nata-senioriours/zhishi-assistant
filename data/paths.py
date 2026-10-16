# -*- coding: utf-8 -*-
"""用户数据目录的唯一来源。

## 为什么要有这个模块

`~/.pet_demo/` 是**用户数据目录**，散落着配置、日志、便签、快捷启动项、
会话库 `ai.db`、活动库 `activity.db`、图标缓存。在引入本模块之前，
每个模块各自写一遍 `Path.home() / ".pet_demo" / ...` —— 一共 8 处。

这带来一个**结构性**问题：测试没法把它们整体挪走。

    data.config_manager.config_manager 是进程级单例，
    在**模块被 import 的那一刻**就构造好了，并立刻 _load_config() → save()。
    pytest 的 fixture 要到「测试执行时」才跑 —— 那时早就 import 完了。
    于是每一次跑测试，用户的真实 user_config.json 都会被重写一遍
    （实测：mtime 变了，内容字节相同）。

这跟 P2.14 的「测试把日志写进用户目录」是同一类问题，原则也一样：
**测试不许碰用户的运行数据**（见 AGENTS.md §4.9）。

## 修法：把「根」抽出来，允许前置覆盖

`PET_DEMO_HOME` 环境变量一设，所有落点整体换根。关键在于**它可以在 import
之前设** —— `tests/conftest.py` 的**模块级**代码就是这么做的（模块级代码在
测试模块被 import 之前执行，fixture 不行）。

顺带的好处：便携安装 / 多套配置（工作、个人）只要换个环境变量。

> ⚠ 注意：环境变量**不是**「测试专用后门」，它是正式能力。
> 生产路径在没有该变量时**永远是** `~/.pet_demo`。
"""
import os
from pathlib import Path

#: 覆盖用户数据根目录的环境变量名。
PET_HOME_ENV = "PET_DEMO_HOME"

#: 默认目录名（位于用户主目录下）。
DEFAULT_DIR_NAME = ".pet_demo"


def pet_home() -> Path:
    """用户数据根目录。

    优先取 `PET_DEMO_HOME`；未设置时是 `~/.pet_demo`。
    **每次调用都重新读环境变量** —— 不做模块级缓存，
    否则「在 import 之后才设变量」的调用方会拿到旧值（正是我们要防的坑）。
    """
    override = os.environ.get(PET_HOME_ENV)
    if override:
        return Path(override)
    return Path.home() / DEFAULT_DIR_NAME


def pet_path(*parts: str) -> Path:
    """用户数据根目录下的某个路径，如 `pet_path("logs", "app.log")`。"""
    return pet_home().joinpath(*parts)
