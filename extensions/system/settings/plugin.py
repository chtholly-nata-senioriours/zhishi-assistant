# -*- coding: utf-8 -*-
"""设置插件 —— 「控制中心…」菜单入口。

历史
    以前这个插件弹出一个 `SettingsDialog`（行为 / 番茄钟 / 外观三个选项卡）。
    控制中心（`presentation/control_center.py`）把这些页面和 AI 服务、
    插件列表、日志合并成了应用主窗口，功能是原对话框的超集，
    所以这里改成**只负责打开主窗口**，不再维护第二套设置界面
    （两套界面必然漂移）。

为什么入口在插件里而不是写死在托盘 / 右键菜单
    本项目所有菜单项都由插件提供（`PluginManager.get_menu_actions()`），
    托盘与桌宠右键菜单消费的是同一份列表。写死会让同一个菜单里出现
    两个「控制中心」，也会破坏「新增功能 = 新增插件」的一致心智。
"""
from extensions.base_plugin import BasePlugin, MenuAction
from data.log_manager import log_manager


class SettingsPlugin(BasePlugin):
    """提供「控制中心…」入口。"""

    def get_menu_actions(self):
        return [MenuAction("控制中心…", self._open, category="system")]

    def _open(self):
        try:
            from presentation.control_center import open_control_center

            open_control_center(self.app)
        except Exception as e:  # noqa: BLE001 —— windowed exe 下异常会被静默吞掉
            import traceback

            log_manager.error(f"打开控制中心失败: {e}\n{traceback.format_exc()}")
