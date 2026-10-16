# 知时助手

> 一个懂你工作节律的 Windows 桌面助手：常驻一枚悬浮球，替你记录时间去向、
> 在合适的时候提醒你休息，也能随时问答、改写、翻译。
> 基于 Python + PySide6 (Qt6) 构建，Windows 桌面端。

产品聚焦在**「时间感知 + AI 助手 + 隐私可控」**三件事上：

- **时间感知** —— 在后台安静地记录前台应用与停留时长，把碎片合并成时段，
  画成一条 24 小时时间轴；分类判定可解释、可手动纠正。
- **AI 助手** —— 三个全局热键随时唤起，问答 / 改写 / 翻译 / 截图提问，
  流式输出、会话可续接。
- **隐私可控** —— 不该记的东西**表里根本没有那一列**；密钥不落配置文件；
  所有数据只存本机，可逐类查看、导出、清空。

---

## 功能特性

| 特性 | 说明 |
|------|------|
| **悬浮球** | 无边框置顶，可拖拽、贴边吸附；球内进度环表达「今日深度工作进度」 |
| **状态感知** | 键盘敲击频率 / 鼠标活动 / 前台窗口 → 空闲 / 放松 / 休眠 / 专注 / 互动 |
| **番茄钟** | 25 分钟专注 + 5 分钟休息，可暂停；悬浮球与托盘环实时显示本轮进度 |
| **活动洞察** | 今日时间构成、7/30 天趋势、AI 生成的作息建议（插件默认关闭） |
| **应用分类** | 五类体系（工作 / 学习 / 沟通 / 娱乐 / 其他）逐条说明判定依据；每个应用都能**手动归类**，且保留「系统判定 vs 你的归类」对照 |
| **人机协同证据链** | 采纳 / 忽略每条建议时自动留痕：推荐依据 + 当时的数据现场 + 影响范围，可逐条核对与导出 |
| **AI 助手** | 全局热键唤起面板：问答 / 改写 / 翻译 / 截图提问；流式输出、会话续接 |
| **系统密钥库** | API Key 存进操作系统凭据库（或 Windows DPAPI），配置里只留引用、不留明文 |
| **隐私与数据** | 一页说清「收集什么、不收集什么、存在哪」，可逐类查看 / 导出 / 清空 |
| **插件系统** | 内置 5 个插件（activity_advisor / ai_assistant / timer / settings / quit） |
| **控制中心** | 左导航 3 组 14 页：今日 / 趋势 / 应用分类 / 协同记录 / 外观 / 行为 / 番茄钟 / AI 服务 / 会话历史 / 预设 / 插件 / 隐私与数据 / 日志 / 关于 |

---

## 项目结构

```
petgame_demo/
├── main.py                        # 程序入口（接线：插件 → UI → 托盘）
├── event_bus.py                   # 事件总线（发布-订阅）
├── config.default.json             # 默认配置（版本号唯一来源）
├── PetDemo.spec                   # PyInstaller 打包配置
├── installer.iss / setup.bat      # Inno Setup 安装脚本 / 一键安装
├── check_project.py                # 快速自检（配置 / 入口 / 数据根 / 模块）
├── dev_bootstrap.py               # 开发运行入口（装配 Lib/ 依赖与 pywin32）
│
├── sensor/                        # 感知层
│   ├── input_monitor.py           #   键盘/鼠标监听（pynput）
│   ├── window_monitor.py          #   前台窗口检测（win32gui，分类转交 engine/activity/category）
│   └── time_trigger.py            #   定时触发
│
├── engine/                        # 决策引擎
│   ├── state_machine.py           #   有限状态机（FSM）
│   ├── rule_engine.py             #   规则引擎（概率 + 冷却）
│   ├── activity/                  #   活动洞察：分类 / 采集 / 聚合 / 建议 / 提醒 / 日程
│   │   ├── category.py            #     五类判定 + explain() 给依据（纯函数，可单测）
│   │   ├── tracker.py             #     瞬时事件 → 活动段（空闲剪裁）
│   │   ├── store.py               #     分段落盘（独立 activity.db）+ 手动归类覆盖表
│   │   ├── timeline.py            #     时间轴与趋势聚合（口径只有这一处）
│   │   ├── summary.py             #     摘要生成（出网内容可单独审阅）
│   │   ├── advice.py / advisor.py #     结构化建议 + 提示词
│   │   ├── decision.py            #     人机协同决策留痕
│   │   ├── schedule.py / idle.py  #     自然日语义 / 系统空闲秒数
│   │   └── reminder.py            #     收工小结时机（一天最多一次 + 免打扰）
│   └── ai/                        #   AI 核心：provider / 会话 / 预设 / 探测 / 流式
│
├── presentation/                  # 表现层
│   ├── ui_renderer.py             #   外壳窗口 ShellWindow（形态无关）+ UIManager
│   ├── forms.py                   #   外观协议 Form 与悬浮球 OrbForm 实现
│   ├── bubble.py                  #   独立顶层气泡窗
│   ├── anim_controller.py         #   动画控制器（数值动画）
│   ├── tray_icon.py               #   托盘图标与进度环
│   ├── control_center.py          #   控制中心主窗口（3 组 14 页）
│   ├── ai_panel.py                #   AI 悬浮面板
│   ├── ai_settings_dialog.py      #   AI 服务设置对话框
│   ├── dialogs.py                 #   预设编辑等对话框
│   └── design/                    #   设计系统：tokens / theme / qss / icons / widgets
│       ├── charts.py              #     图表组件（时间轴 / 排行 / 统计块）
│       ├── advice_card.py         #     建议卡与总结段
│       ├── focus_card.py          #     专注倒计时卡
│       └── ring.py                #     托盘环与球环共用的状态判定
│
├── native/                        # 系统代理层（热键 / 选区 / 截图 / 注入 / 焦点）
├── data/                          # 数据层
│   ├── paths.py                   #   用户数据根的唯一来源（PET_DEMO_HOME 可覆盖）
│   ├── config_manager.py          #   配置管理（默认 + 用户配置合并 / 迁移）
│   ├── log_manager.py             #   日志管理（运行 / 行为 / 迁移）
│   ├── key_store.py               #   系统密钥库（keyring / Windows DPAPI + 脱敏）
│   └── privacy.py                 #   本机数据清单 / 导出 / 清空（隐私页后端）
│
├── tools/                         # 工具层
│   └── timer_tool.py              #   番茄钟计时器（带轮次号，防「停→再开」两倍速）
│
├── extensions/                    # 插件系统
│   ├── base_plugin.py             #   插件基类 + Manifest + MenuAction
│   ├── plugin_manager.py          #   插件管理器（自动发现 / 加载 / 卸载）
│   ├── system/                    #   系统内置插件（5 个）
│   └── user/                      #   用户安装（自动加载）
│
├── tests/                         # 单元测试（27 个文件，856 条用例，另有 1 条按环境跳过）
├── spikes/                        # 验证脚本与目检图（可独立复现，见 spikes/README.md）
└── docs/                          # 设计文档
```

---

## 快速开始

### 方式一：安装包

```
Output\知时助手_Setup.exe
    → 下一步 → 完成
    → 桌面出现「知时助手」快捷方式，双击即运行
```

### 方式二：直接运行打包版

```
dist\知时助手\知时助手.exe
```

### 方式三：源码运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 运行（dev_bootstrap 会装配 Lib/ 下的依赖并注册 pywin32 DLL 目录）
python dev_bootstrap.py main.py
```

> **环境要求**：Windows 10 / 11，Python 3.13。
> 源码运行时 `dev_bootstrap.py` 负责把便携依赖目录挂进 `sys.path`，
> 并注册 pywin32 的 DLL 目录 —— 直接 `python main.py` 可能报缺 DLL。

---

## 操作说明

| 操作 | 效果 |
|------|------|
| **拖拽悬浮球** | 移动位置（松手靠近屏幕左右边缘时自动吸附，藏起 1/3） |
| **单击** | 戳一下：球弹一下并发 `PET_CLICKED`（状态机进互动 5 秒） |
| **双击** | 打开控制中心 |
| **右键** | 插件菜单（番茄钟 / 设置 / 退出） |
| **Alt+Q / Alt+T / Alt+S** | 唤起 AI：问答 / 翻译 / 截图提问 |
| **托盘图标** | 进度环 = 今日深度工作进度；菜单可开始专注、查看今日 |

---

## 应用怎么分类

分类**按「行为类型」划分，不按场景** —— 场景（上班 / 在家）判不出来，行为判得出来。
所以钉钉、飞书算「沟通」而不是「工作」：它们本身是沟通工具，至于聊的是不是公事，
代码无从得知，硬猜一个「工作」才是撒谎。判不出来的一律进「其他」，**不猜**。

| 分类 | 判定依据 |
|------|----------|
| **工作** | 生产力工具（编辑器 / IDE / Office / 设计 / 终端 / 数据库 / 远程），或标题命中工作站点与流程词 |
| **学习** | 学习工具（词典 / 文献 / 记忆卡 / 阅读器），或标题命中课程、题库、论文、开发文档站 |
| **沟通** | 即时通讯、邮件与会议客户端（微信 / 钉钉 / 飞书 / Slack / Teams / Zoom / Outlook…） |
| **娱乐** | 游戏平台与游戏本体、影音播放器与音乐客户端，或标题命中视频、短视频、直播、社交娱乐站点 |
| **其他** | 以上都不命中，**或同时命中两个方向 —— 判不出就不猜**。浏览器停在空白页时也在这里 |

判定分三层，越靠前越可信：

1. **进程名**（精确匹配）：`code.exe` → 工作，`steam.exe` → 娱乐。
   **浏览器除外** —— `chrome.exe` 只是容器，不代表在做什么。
2. **标题**（英文按**词边界**匹配、中文按子串）：`vs code` 命中「工作」，
   `decode` **不会**（早期版本用裸子串匹配，把含 `digital` / `knowledge` / `password`
   的网页全判成了工作，现已修正并逐条钉了回归用例）。
3. 都没有信号 → **其他**。

每次判定都会附上**依据**（命中了哪个词），而依据只回命中的词 ——
`activity.db` 里没有窗口标题这一列，依据也不会开后门。

### 手动纠正

判定不可能全对，所以**每个应用都能被你改**：控制中心 →「应用分类」页，
表格里逐应用显示「停留时长 / 系统判定 / 你的归类」，下拉即可改，
改过的行用强调色标出。你的归类与系统判定**分开存**（原始记录不被篡改），
所以随时可以「恢复自动判定」，而「系统当初判成什么」永远查得到。

> **深度工作** = 工作 + 学习。看两小时网课在悬浮球进度环上不该是 0。

---

## 隐私与数据

所有数据只保存在**本机** `~/.pet_demo/`（可用环境变量 `PET_DEMO_HOME` 整体改根）：

| 数据 | 文件 | 内容 |
|------|------|------|
| 设置与偏好 | `user_config.json` | AI 服务地址、模型、界面与采集开关（**密钥默认不在这里**） |
| 系统密钥库 | 操作系统凭据库，或 `secure_keys.bin` | API Key（按当前用户加密，配置里只留一个引用） |
| AI 会话历史 | `ai.db` | 提问、回答与预设 |
| 活动记录 | `activity.db` | **只有**前台应用名、类别、停留时长、敲击次数；另有「决策留痕」表与「应用分类」偏好表 |
| 运行日志 | `logs/` | 排障用 |
| 界面缓存 | `cache/` | 图标缓存，删了自动重建 |

- **不采集**：窗口标题、按键内容、剪贴板、截图（`activity.db` 里根本没有 title 列，有测试钉住）。
  决策留痕的上下文也**只放聚合数字**（条数 / 总时长 / 起止 / 是否过期），
  用白名单过滤 —— 认不出的键直接丢掉。
- **会出网**：只有你主动发起的 AI 提问，发送到你在「AI 服务」页自己填写的地址。
- **可自决**：控制中心「隐私与数据」页可逐类**查看大小 / 导出 zip / 清空**。
  导出走 sqlite 的 backup API，不会漏掉还留在 WAL 里的最近几轮对话。
- **活动采集默认关闭**：不开启就不订阅事件、不落任何数据。

### 密钥怎么存

「AI 服务」页的**保存位置**有两档，密钥本身**不进配置文件**（默认档）：

1. **系统密钥库（推荐）** —— 装了 `keyring` 就用操作系统的凭据管理器
   （Windows 凭据管理器 / macOS 钥匙串 / Linux Secret Service）；
   没装则走 **Windows DPAPI 加密文件**（`secure_keys.bin`）。
   两者都由操作系统按**当前用户**隔离，别的用户、别的进程读不到。
   配置里只写 `"api_key_ref": "keyring:<条目名>"`。
2. **配置文件（明文）** —— 给老用户与无密钥库机器的退路，界面上写明了代价
   （会随备份与「导出全部数据」被带走）。

读取一律走 `resolve_api_key()`（全项目唯一读密钥的地方）；日志、状态栏里
只出现**脱敏**后的值（头 3 尾 4、总长度固定）。

---

## 配置说明

配置文件保存在 `~/.pet_demo/user_config.json`，首次启动时自动从默认配置生成；
程序只在「磁盘与内存不一致」时才写盘。完整节结构见 `config.default.json`：

```jsonc
{
  "version": "1.9.0",
  "window":    { "center": [100, 200], "opacity": 0.8, "always_on_top": true },
  "appearance": { "orb_size": 52, "theme": "default" },
  "behavior":  { "idle_threshold": 30, "sleep_threshold": 300, "focus_threshold": 60 },
  "tomato":    { "work_duration": 25, "break_duration": 5 },
  "ai":        { "provider": "openai_compat", "base_url": "...",
                 "api_key": "", "api_key_ref": "keyring:api.example.com" },
  "activity":  { "enabled": false, "retention_days": 30, "focus_goal_minutes": 240 }
}
```

| 配置节 | 关键项 | 说明 |
|---|---|---|
| `window` | `center` | 悬浮球位置，以**中心点**保存，下次启动自动恢复 |
| `appearance` | `theme` | `default` / `light` / `dark`；`orb_size` 悬浮球直径 |
| `behavior` | `idle_threshold` 等 | 空闲 / 休眠 / 专注判定的秒数阈值 |
| `tomato` | `work_duration` / `break_duration` | 番茄钟时长（分钟） |
| `ai` | `base_url` / `api_key_ref` | 兼容 OpenAI 接口的服务地址与密钥引用 |
| `activity` | `enabled` | **默认 false**：不开启就不订阅事件、不落任何数据 |
| | `retention_days` | 活动记录保留天数（超期清理） |
| | `focus_goal_minutes` | 每日深度工作目标，进度环按它算比例 |

环境变量 `PET_DEMO_HOME` 可整体改写数据根目录（测试与多份配置隔离都用它）。

---

## 打包发布

```bash
# 打包（输出到 dist\知时助手\，约 3–4 分钟）
PYTHONPATH="Lib;Lib/site-packages;Lib/packtools" \
  python dev_bootstrap.py -m PyInstaller PetDemo.spec --noconfirm --clean

# 发版核查三件套（不可互相替代）
PYTHONPATH="Lib;Lib/site-packages;Lib/packtools" \
  python dev_bootstrap.py spikes/pyz_check.py      # ① PYZ 里该在的符号 / 不该在的旧符号
python dev_bootstrap.py spikes/leak_check.py       # ② zip 逐条目查密钥泄漏
python dev_bootstrap.py spikes/exe_window_check.py # ③ exe 真的跑起来了、窗口真的在

# 冒烟（存活 16s + 版本行 + 完整启动序列 + 零 ERROR）
python dev_bootstrap.py spikes/smoke_exe.py

# 刷新发布目录与版本号
python dev_bootstrap.py spikes/_refresh_release.py
```

安装包用 Inno Setup 编译：右键 `installer.iss` → Compile → `Output\知时助手_Setup.exe`。

> ⚠ 顺序不能颠倒：`leak_check.py` 必须在 `_refresh_release.py` **之后**跑
> —— 它只认发布目录 `dist/知时助手-v<版本>-win64`，先跑会失败在「目录不存在」。

---

## 测试

```bash
# 全量（不带 tests 路径会把第三方测试收进来 → 崩溃）
rm -rf .pytest_tmp && python dev_bootstrap.py -m pytest tests -q --basetemp=.pytest_tmp

# 单文件
python dev_bootstrap.py -m pytest tests/test_category.py -q
```

测试全部跑在**临时数据根**下（`tests/conftest.py` 在 import 前设 `PET_DEMO_HOME`），
不会碰你真实的 `~/.pet_demo/`。

除单元测试外，`spikes/` 下还有一批**可独立复现**的验证脚本与目检图：
端到端链路验证（假 Provider + 合成按键）、真实 API 连通性自检、
发版核查、以及各页面的界面目检图（浅深两套）。
索引见 `spikes/README.md`。

---

## 架构概览

```
用户交互 → 感知层（input / window / time）
              ↓ EventBus
         决策引擎（状态机 + 规则引擎 + 活动分析 + AI 编排）
              ↓ EventBus
         表现层（外壳 + 悬浮球 + 托盘 + 控制中心）
              ↓
         插件层（activity_advisor / ai_assistant / timer / settings / quit）
```

- **分层依赖严格单向向上**：`native`（系统代理）→ `engine`（决策与 AI）→
  `presentation`（交互）→ `data`（数据）。核心分析层**零界面依赖**，可脱离 Qt 单测。
- **感知层**：收集键盘 / 鼠标 / 窗口 / 时间信号 → 发布事件。
- **决策引擎**：状态机管五种状态切换；规则引擎按概率 + 冷却触发反馈；
  活动分析层负责「行为 → 分类 → 摘要 → 提示词」这一段纯逻辑。
- **表现层**：`ShellWindow`（外壳，管拖拽 / 位置 / 菜单 / 气泡）+ `Form`（外观）分层，
  换形态不动窗口行为；托盘环与球环共用同一套状态判定。
- **插件系统**：按清单自动发现，支持包加载、异步事件投递与 `on_ui_ready`
  生命周期钩子，可单独启用 / 卸载 / 恢复。

---

## 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.13 | 主开发语言 |
| PySide6 (Qt6) | 跨平台 GUI 框架 |
| pynput | 键盘 / 鼠标全局监听 |
| pywin32 | Windows 窗口 API（前台窗口检测、热键） |
| SQLite | 会话历史与活动记录（WAL 模式） |
| PyInstaller | 打包为独立 exe |
| Inno Setup | 安装包制作 |
| pytest | 单元测试 |

---

## 许可

MIT License

---

> **提示**：悬浮球位置以**中心点**保存在配置里，下次启动自动恢复。
> 如果桌面上看不见它，检查是不是被拖到了屏幕外面，
> 或查看 `~/.pet_demo/user_config.json` 中的 `window.center`。
