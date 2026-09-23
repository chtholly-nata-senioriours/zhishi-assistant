#  小小桌宠

> 一个可爱的桌面宠物，能感知你的工作状态，在你专注时安静陪伴，在你休息时活泼互动。  
> 基于 Python + PySide6 (Qt6) 构建，Windows 桌面端。

---

##  功能特性

| 特性 | 说明 |
|------|------|
| **半透明悬浮窗口** | 置顶显示，无边框拖拽，不影响工作 |
| **智能感知** | 监听键盘敲击频率、鼠标活动、检测活跃窗口标题 |
| **状态机驱动** | 空闲 → 放松 → 休眠 → 专注 → 互动，带防抖策略 |
| **精灵图动画** | PNG spritesheet 动画：待机 / 打哈欠 / 睡觉 / 挥手 / 点赞 / 思考 / 开心 / 困惑 |
| **番茄钟** | 25分钟专注 + 5分钟休息，支持暂停/继续，番茄数统计 |
| **便签** | 快速记录待办事项，支持颜色/优先级/标签/搜索/持久化 |
| **快捷启动** | 一键启动常用软件，使用频率排序，支持自定义收藏 |
| **插件系统** | 内置 5 个插件（notes/quick_launch/timer/settings/quit），支持扩展 |
| **右键菜单** | 集成所有插件入口，一键访问 |
| **音效反馈** | 状态切换 / 互动时播放轻音效 |

---

##  项目结构

```
petgame_demo/
├── main.py                        # 程序入口
├── event_bus.py                   # 事件总线（发布-订阅模式）
├── config.default.json             # 默认配置文件
├── requirements.txt               # Python 依赖
├── PetDemo.spec                   # PyInstaller 打包配置
├── installer.iss                  # Inno Setup 安装脚本
├── setup.bat                      # 一键安装脚本
├── unins.bat                      # 卸载脚本
├── 图标.ico                        # 程序图标
├── .gitignore
├── README.md
│
├── sensor/                        # 🔍 感知层
│   ├── input_monitor.py           #   键盘/鼠标监听（pynput）
│   ├── window_monitor.py          #   活跃窗口检测（win32gui）
│   └── time_trigger.py            #   定时触发（整点/30分/5分/自定义）
│
├── engine/                        # 🧠 决策引擎
│   ├── state_machine.py           #   有限状态机（FSM）
│   └── rule_engine.py             #   规则引擎（概率+冷却）
│
├── presentation/                  # 🎨 表现层
│   ├── ui_renderer.py             #   UI 窗口（半透明/拖拽/菜单）
│   ├── anim_controller.py         #   动画控制器（GIF/精灵图/数值动画）
│   ├── pet_model.py               #   宠物模型管理器（多外观）
│   ├── dialogs.py                 #   对话框（番茄钟/便签/快捷启动/设置）
│   └── assets/                    #   资源文件
│       ├── pet.jpg                #     默认宠物图
│       └── models/
│           └── default/           #     默认模型（精灵图 PNG）
│               ├── pet.jpg
│               ├── idle.png       #       待机（4帧）
│               ├── yawn.png       #       打哈欠（2帧）
│               ├── sleep.png      #       睡觉（4帧）
│               ├── wave.png       #       挥手（4帧）
│               ├── happy.png      #       开心（4帧）
│               ├── think.png      #       思考（4帧）
│               ├── thumbs_up.png  #       点赞（4帧）
│               └── confused.png   #       困惑（1帧）
│
├── tools/                         # 🛠️ 工具层
│   ├── timer_tool.py              #   番茄钟计时器
│   ├── note_tool.py               #   便签管理器
│   └── quick_launch.py            #   快捷启动器
│
├── data/                          # 💾 数据层
│   ├── config_manager.py          #   配置管理（默认+用户配置合并）
│   └── log_manager.py             #   日志管理（运行/行为/迁移）
│
├── extensions/                    # 🔌 插件系统
│   ├── base_plugin.py             #   插件基类 + Manifest + MenuAction
│   ├── plugin_manager.py          #   插件管理器（自动发现/加载）
│   ├── system/                    #   系统内置插件
│   │   ├── notes/                 #     便签插件
│   │   ├── quick_launch/          #     快捷启动插件
│   │   ├── timer/                 #     番茄钟插件
│   │   ├── settings/              #     设置插件
│   │   └── quit/                  #     退出插件
│   ├── user/                      #   用户安装（自动加载）
│   └── dev/                       #   开发测试（手动放置）
│
└── tests/                         # 🧪 单元测试
    ├── test_event_bus.py
    ├── test_config_manager.py
    ├── test_state_machine.py
    ├── test_rule_engine.py
    ├── test_note_tool.py
    ├── test_timer_tool.py
    └── test_quick_launch.py
```

---

##  快速开始

### 方法一  新手使用者
```
    双击安装包（无需任何操作）
    点这里安装\小小桌宠_Setup.exe
    → 下一步 → 下一步 → 完成
    → 桌面出现「小小桌宠」快捷方式，双击即运行
```

### 方式二：直接运行打包版

```
dist\小小桌宠Demo\小小桌宠Demo.exe
```

或运行 `setup.bat` 安装到 Program Files，自动创建桌面快捷方式。

### 方式三：源码运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 运行
python main.py
```

---

## 🎮 操作说明

| 操作 | 效果 |
|------|------|
| **左键拖拽** | 移动桌宠位置 |
| **右键点击** | 打开菜单（番茄钟 / 便签 / 快捷启动 / 设置 / 退出） |
| **键盘高频输入** | 桌宠进入专注状态 → 点赞动画 |
| **无操作 30 秒** | 进入放松状态 → 打哈欠动画 |
| **无操作 5 分钟** | 进入休眠状态 → 睡觉动画 |
| **点击桌宠** | 进入互动状态 → 挥手动画 + 问候音效 |

---

##  配置说明

配置文件保存在 `~/.pet_demo/user_config.json`，首次启动时自动从默认配置生成。

```json
{
  "version": "1.0.0",
  "window": {
    "position": [100, 200],       // 窗口位置（像素）
    "size": [200, 200],           // 窗口大小
    "opacity": 0.9,               // 透明度 0~1
    "always_on_top": true,        // 是否置顶
    "show_on_startup": true       // 启动时自动显示
  },
  "behavior": {
    "idle_threshold": 30,         // 进入放松的闲置秒数
    "sleep_threshold": 300,       // 进入休眠的闲置秒数
    "focus_threshold": 60,        // 进入专注的按键频率（次/30秒）
    "focus_debounce": 15,         // 退出专注的防抖秒数
    "state_switch_cooldown": 1,   // 状态切换冷却秒数
    "sound_enabled": true,
    "volume": 0.5
  },
  "tomato": {
    "work_duration": 25,          // 工作时长（分钟）
    "break_duration": 5,          // 休息时长（分钟）
    "long_break_duration": 15,    // 长休息时长
    "long_break_interval": 4,     // 几个番茄后长休息
    "auto_start_break": false
  },
  "quick_launch": {
    "items": [                    // 快捷启动项列表
      {"name": "Chrome", "command": "start chrome", "category": "浏览器"},
      ...
    ]
  },
  "appearance": {
    "pet_name": "小宠",
    "pet_model": "default",
    "animation_speed": 1.0
  },
  "notification": {
    "enabled": true,
    "rest_reminder_interval": 60
  }
}
```

---

##  打包发布

```bash
# 安装 PyInstaller（已安装可跳过）
pip install pyinstaller

# 打包（输出到 dist\小小桌宠Demo\）
python -m PyInstaller PetDemo.spec

# 可选：用 Inno Setup 编译安装包
# 右键 installer.iss → Compile → Output\小小桌宠_Setup.exe
```

---

##  自定义宠物模型

在 `presentation/assets/models/` 下创建新目录（如 `my_pet/`），放入以下文件：

| 文件 | 格式 | 说明 |
|------|------|------|
| `pet.jpg` / `pet.png` | 单张图片 | 默认显示图（必需） |
| `idle.png` | 精灵图 | 待机动画 |
| `yawn.png` | 精灵图 | 打哈欠 |
| `sleep.png` | 精灵图 | 睡觉 |
| `wave.png` | 精灵图 | 挥手 |
| `happy.png` | 精灵图 | 开心 |
| `think.png` | 精灵图 | 思考 |
| `thumbs_up.png` | 精灵图 | 点赞 |
| `confused.png` | 单张/GIF | 困惑 |

**精灵图规范**：水平排列多帧 PNG，宽度 ≥ 高度 × 1.5，程序自动检测帧数（优先匹配 4/2/3/5/6/8 帧）。也可以在 `appearance.pet_model` 配置中切换模型。

---

##  测试

```bash
# 运行单个测试
python tests/test_event_bus.py
python tests/test_state_machine.py
python tests/test_rule_engine.py
python tests/test_config_manager.py
python tests/test_note_tool.py
python tests/test_timer_tool.py
python tests/test_quick_launch.py
```

---

##  架构概览

```
用户交互 → 感知层（input/window/time）
              ↓ 事件总线（EventBus）
         决策引擎（状态机 + 规则引擎）
              ↓ 事件总线（EventBus）
         表现层（UI + 动画 + 音效）
              ↓
         插件层（番茄钟 / 便签 / 快捷启动 / 设置）
```

- **感知层**: 收集键盘/鼠标/窗口/时间信号 → 发布事件
- **决策引擎**: 状态机管理空闲/放松/休眠/专注/互动切换；规则引擎按概率+冷却触发动效
- **表现层**: 跨线程安全的 Qt 动画播放（Signal + QueuedConnection）
- **插件系统**: 基于 SKILL.md 自动发现，plugin.py 动态加载，右键菜单集成

---

##  技术栈

| 技术 | 用途 |
|------|------|
| Python 3.13 | 主开发语言 |
| PySide6 (Qt6) | 跨平台 GUI 框架 |
| pynput | 键盘/鼠标全局监听 |
| pywin32 | Windows 窗口 API（活跃窗口检测） |
| PyInstaller | 打包为独立 exe |
| Inno Setup | 安装包制作 |
| pytest | 单元测试 |

---

##  许可

MIT License

---

> ** 提示**: 桌宠位置会保存在配置中，下次启动时自动恢复。  
> 如果桌面上看不见桌宠，检查它是不是跑到了屏幕外面，或查看 `~/.pet_demo/user_config.json` 中的 `window.position`。
