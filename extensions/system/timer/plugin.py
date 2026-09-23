"""番茄钟插件"""
from extensions.base_plugin import BasePlugin, MenuAction
from tools.timer_tool import TomatoTimer
from presentation.dialogs import TomatoDialog


class TimerPlugin(BasePlugin):
    def on_load(self, app) -> bool:
        self._timer = TomatoTimer()
        # 把 timer 挂到 app 上，保持向后兼容
        app.timer = self._timer
        return True

    def get_menu_actions(self):
        return [MenuAction("番茄钟", self._open, category="tools")]

    def _open(self):
        parent = self._find_window()
        dialog = TomatoDialog(self._timer, parent)
        dialog.exec()

    def _find_window(self):
        if self.app and self.app.ui_manager and self.app.ui_manager.window:
            return self.app.ui_manager.window
        return None
