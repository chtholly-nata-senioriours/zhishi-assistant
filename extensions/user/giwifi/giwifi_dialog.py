# -*- coding: utf-8 -*-
"""GiWiFi 插件对话框 —— 统一玻璃拟态风格

继承桌宠的 GlassDialog 基类（无边框圆角毛玻璃卡片），
使用 glass_widgets 设计规范（SPACING/RADIUS/STATUS_COLOR），
保持原版字段与回调语义：
    - set_online(bool)               ← checker.status_changed
    - on_login_result(ok, msg)       ← 登录完成
    - on_logout_result(ok, msg)      ← 下线完成
    - get_config() → 写回插件配置（保存按钮触发 plugin.save）
"""
import sys
from pathlib import Path

# 拖拽窗口需要访问主程序源码目录中的 presentation 包；
# 打包环境下从 _internal 解析
_APP_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_APP_ROOT), str(_APP_ROOT / "_internal")):
    if Path(_p).exists() and _p not in sys.path:
        sys.path.insert(0, _p)

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
)
from PySide6.QtCore import Qt

from presentation.glass_widgets import (
    GlassTheme, ToggleSwitch, GlassButton, LiquidGlassButton,
    SPACING, RADIUS, STATUS_COLOR,
)

# 统一对话框基类（ dialogs.py 可能尚未打包为可导入路径，做降级处理）
try:
    from presentation.dialogs import GlassDialog
except Exception:
    from presentation.glass_widgets import (
        GlassTheme, apply_dialog_style, paint_dialog_background,
    )
    from PySide6.QtGui import QMouseEvent

    class GlassDialog(QDialog):  # type: ignore[no-redef]
        """降级基类：仅应用统一样式（无标题拖拽）"""

        def __init__(self, parent=None, dark: bool = False, title: str = ""):
            super().__init__(parent)
            self._theme = apply_dialog_style(self, dark=dark)
            self.setWindowTitle(title)

        def paintEvent(self, event):
            paint_dialog_background(self, self._theme)

        def make_title_label(self, text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setFont(self._theme.font_bold)
            lbl.setStyleSheet(f"font-size: 16px; color: {self._theme.color('text').name()};")
            return lbl

        def make_section_label(self, text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setFont(self._theme.font_bold)
            lbl.setStyleSheet(f"color: {self._theme.color('text_sec').name()};")
            return lbl

        def make_status_label(self, text: str, color_key: str = "info") -> QLabel:
            color = STATUS_COLOR.get(color_key, STATUS_COLOR["info"])
            lbl = QLabel(f'<span style="color:{color};">●</span> {text}')
            lbl.setFont(self._theme.font_bold)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            return lbl

from config import save_config  # 插件目录内的原版 config（plugin.py 已挂 sys.path）


class GiwifiDialog(GlassDialog):
    """校园网 GiWiFi 状态/账号面板（统一玻璃拟态风格）"""

    def __init__(self, plugin, parent=None):
        super().__init__(parent, title="校园网 GiWiFi")
        self._plugin = plugin
        self.setFixedWidth(360)
        self._build_ui()
        self._load_config()

    # ----- UI -----
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING["xl"], SPACING["lg"], SPACING["xl"], SPACING["lg"])
        layout.setSpacing(SPACING["md"])

        layout.addWidget(self.make_title_bar("校园网 GiWiFi"))
        layout.addSpacing(SPACING["xs"])

        # 状态行（语义色圆点）
        self._status_label = self.make_status_label("检测中…", "info")
        layout.addWidget(self._status_label)

        # 在线时长
        self._duration_label = QLabel("")
        self._duration_label.setStyleSheet(
            f"color: {self._theme.color('text_ter').name()};")
        layout.addWidget(self._duration_label)

        # 账号 / 密码（带文字标签提示）
        form = QVBoxLayout()
        form.setSpacing(SPACING["xs"])

        lbl_user = QLabel("校园网账号")
        lbl_user.setStyleSheet(f"color: {self._theme.color('text_sec').name()};")
        form.addWidget(lbl_user)
        self._edit_user = QLineEdit()
        self._edit_user.setPlaceholderText("请输入学号 / 账号")
        form.addWidget(self._edit_user)

        lbl_pass = QLabel("密码")
        lbl_pass.setStyleSheet(f"color: {self._theme.color('text_sec').name()};")
        form.addWidget(lbl_pass)
        self._edit_pass = QLineEdit()
        self._edit_pass.setPlaceholderText("请输入密码")
        self._edit_pass.setEchoMode(QLineEdit.EchoMode.Password)
        form.addWidget(self._edit_pass)

        layout.addLayout(form)

        # 开关
        self._sw_auto_login = ToggleSwitch("断网自动重连", theme=self._theme)
        layout.addWidget(self._sw_auto_login)

        # 按钮（液态玻璃胶囊：登录=主按钮，下线=危险红玻璃）
        btn_row = QHBoxLayout()
        btn_row.setSpacing(SPACING["sm"])
        self._btn_login = LiquidGlassButton("登 录", primary=True, theme=self._theme)
        self._btn_logout = LiquidGlassButton("下 线", theme=self._theme)
        self._btn_logout.set_danger(True)
        self._btn_save = GlassButton("保存配置", primary=False, theme=self._theme)
        self._btn_login.clicked.connect(self._on_login)
        self._btn_logout.clicked.connect(self._on_logout)
        self._btn_save.clicked.connect(self._on_save)
        btn_row.addWidget(self._btn_login)
        btn_row.addWidget(self._btn_logout)
        layout.addWidget(self._btn_save)
        layout.addLayout(btn_row)

        # 结果提示
        self._msg_label = QLabel("")
        self._msg_label.setWordWrap(True)
        layout.addWidget(self._msg_label)

    def _load_config(self):
        cfg = self._plugin._config
        self._edit_user.setText(cfg.get("username", ""))
        self._edit_pass.setText(cfg.get("password", ""))
        self._sw_auto_login.setChecked(bool(cfg.get("auto_login", True)))

    # ----- 状态回调（plugin 调用，保持原版命名语义）-----
    def set_online(self, online):
        if online is None:
            self._status_label.setText("检测中…")
            return
        if online:
            self._status_label.setText("● 在线")
            self._status_label.setStyleSheet("color: #34C759;")
            dur = self._plugin and _duration_text(self._plugin)
            self._duration_label.setText(dur or "")
        else:
            self._status_label.setText("○ 离线 / 未认证")
            self._status_label.setStyleSheet("color: #FF3B30;")
            self._duration_label.setText("")

    def on_login_result(self, ok: bool, msg: str):
        self._msg_label.setText(("✅ " if ok else "❌ ") + msg)
        if ok:
            self.set_online(True)

    def on_logout_result(self, ok: bool, msg: str):
        self._msg_label.setText(("✅ " if ok else "❌ ") + msg)
        if ok:
            self.set_online(False)

    # ----- 按钮 -----
    def _on_login(self):
        user = self._edit_user.text().strip()
        pwd = self._edit_pass.text()
        if not user or not pwd:
            QMessageBox.warning(self, "校园网", "请先填写账号和密码")
            return
        self._btn_login.setEnabled(False)
        self._msg_label.setText("登录中…")
        self._plugin.manual_login(user, pwd)

    def _on_logout(self):
        self._btn_logout.setEnabled(False)
        self._plugin.manual_logout()

    def _on_save(self):
        cfg = self._plugin._config
        cfg["username"] = self._edit_user.text().strip()
        cfg["password"] = self._edit_pass.text()
        cfg["auto_login"] = self._sw_auto_login.isChecked()
        save_config(cfg)
        self._msg_label.setText("配置已保存")


def _duration_text(plugin) -> str:
    """在线时长（原版 get_online_duration 语义：需 logout_url）"""
    try:
        from login_worker import get_online_duration
        dur = get_online_duration(getattr(plugin, "_logout_url", None))
        return f"本次在线时长: {dur}" if dur != "未知" else ""
    except Exception:
        return ""
