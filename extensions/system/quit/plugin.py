"""退出插件"""
from extensions.base_plugin import BasePlugin, MenuAction


class QuitPlugin(BasePlugin):
    def get_menu_actions(self):
        return [MenuAction("退出", self._quit, category="quit")]

    def _quit(self):
        if self.app:
            self.app.stop()
