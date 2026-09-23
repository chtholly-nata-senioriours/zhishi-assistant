"""便签插件"""
from extensions.base_plugin import BasePlugin, MenuAction
from tools.note_tool import NoteManager
from presentation.dialogs import NoteDialog


class NotesPlugin(BasePlugin):
    def on_load(self, app) -> bool:
        self._notes = NoteManager()
        app.note_manager = self._notes
        return True

    def get_menu_actions(self):
        return [MenuAction("便签", self._open, category="tools")]

    def _open(self):
        parent = self._find_window()
        dialog = NoteDialog(self._notes, parent)
        dialog.exec()

    def _find_window(self):
        if self.app and self.app.ui_manager and self.app.ui_manager.window:
            return self.app.ui_manager.window
        return None
