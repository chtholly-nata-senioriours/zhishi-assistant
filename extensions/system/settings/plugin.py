"""设置插件"""
from extensions.base_plugin import BasePlugin, MenuAction
from presentation.dialogs import SettingsDialog


class SettingsPlugin(BasePlugin):
    def get_menu_actions(self):
        return [MenuAction("设置", self._open, category="system")]

    def _open(self):
        parent = self._find_window()
        dialog = SettingsDialog(parent)
        dialog.exec()

    def _find_window(self):
        if self.app and self.app.ui_manager and self.app.ui_manager.window:
            return self.app.ui_manager.window
        return None
