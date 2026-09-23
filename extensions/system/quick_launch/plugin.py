"""快捷启动插件"""
from extensions.base_plugin import BasePlugin, MenuAction
from tools.quick_launch import QuickLaunch
from presentation.dialogs import LaunchDialog


class QuickLaunchPlugin(BasePlugin):
    def on_load(self, app) -> bool:
        self._launcher = QuickLaunch()
        app.quick_launch = self._launcher
        return True

    def get_menu_actions(self):
        return [MenuAction("快捷启动", self._open, category="tools")]

    def _open(self):
        parent = self._find_window()
        dialog = LaunchDialog(self._launcher, parent)
        dialog.exec()

    def _find_window(self):
        if self.app and self.app.ui_manager and self.app.ui_manager.window:
            return self.app.ui_manager.window
        return None
