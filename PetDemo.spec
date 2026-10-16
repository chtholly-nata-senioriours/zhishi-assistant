# -*- mode: python ; coding: utf-8 -*-

# T4：hiddenimports 自动化（修复 C4 —— 手工维护必然漏）
# 见 build_hiddenimports.py 与 docs/执行框架.md §5 T4。
# 若 PyInstaller 报找不到该模块，说明 spec 所在目录不在 sys.path，
# 退化为手工列表也可（但请同步补 build_hiddenimports.py 的 SCAN_DIRS）。
import os
import sys

try:
    _SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))  # PyInstaller 注入的全局变量
except NameError:  # 非 PyInstaller 环境（如语法自检）
    _SPEC_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, _SPEC_DIR)

from build_hiddenimports import scan_hiddenimports  # noqa: E402

block_cipher = None

# 静态可发现之外的第三方依赖（保持手工，因为扫描只覆盖本项目目录）
BASE_IMPORTS = [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'pynput',
    'pynput.keyboard',
    'pynput.mouse',
    'win32gui',
    'win32process',
    'win32api',
    'win32con',
    # 插件延迟导入的 presentation 模块。
    # P2.1 起 `presentation` 已纳入 build_hiddenimports.SCAN_DIRS，会被自动扫到；
    # 这里仍显式保留，是为了让「AI 链路的依赖清单」在 spec 里一眼可见
    # （scan 结果会去重，重复无害）。
    'presentation.dialogs',
    'presentation.glass_widgets',
    'presentation.ai_panel',
    'presentation.ai_settings_dialog',
    'presentation.markdown_view',
    'presentation.overlay_select',
    # P2.6 新增：应用级主题源 + 窗口层级行为。
    # 面板/对话框用相对导入引用它们，静态扫描能看到（扫描数 54 → 56），
    # 这里显式列出是为了让「UI 设计系统的依赖」在 spec 里一眼可见。
    'presentation.theme',
    'presentation.window_behavior',
    # P2.7 新增：设计系统（tokens/theme/qss/icons/widgets）+ 控制中心 + AI 配置表单。
    # 扫描已覆盖（扫描数 56 → 64），显式列出同样是为了让依赖清单可见。
    'presentation.design',
    'presentation.design.tokens',
    'presentation.design.theme',
    'presentation.design.qss',
    'presentation.design.icons',
    'presentation.design.widgets',
    'presentation.control_center',
    'presentation.ai_config_form',
    # AI 链路的第三方依赖（engine/ai + ai_assistant 插件）
    'requests',
    'requests.adapters',
    'urllib3',
    'charset_normalizer',
    'idna',
    'certifi',
    # giwifi 插件依赖（login_worker 函数内动态 import Crypto）
    'Crypto',
    'Crypto.Cipher',
    'Crypto.Cipher.AES',
    'Crypto.Cipher._raw_cbc',
    'Crypto.Hash.SHA256',
    'Crypto.Util.Padding',
]

# 扫描 engine/ native/ tools/ extensions/ 得到的模块列表
_SCANNED = scan_hiddenimports()
# 去重但保持顺序，避免与 BASE_IMPORTS 重复
hiddenimports = list(dict.fromkeys(BASE_IMPORTS + _SCANNED))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('extensions', 'extensions'),
        ('tools', 'tools'),
        # T4：AI 链路的两层必须随包分发（插件按文件路径动态加载，静态分析看不到）
        ('native', 'native'),
        ('engine', 'engine'),
        ('config.default.json', '.'),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='知时助手',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='图标.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='知时助手',
)
