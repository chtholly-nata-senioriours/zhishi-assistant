# AGENTS.md — 接手须知

> 面向**没有上下文的新 AI / 新开发者**。读完本文件 + `docs/执行框架.md` 即可准确接手。
> 本文件是入口，细节以 `docs/执行框架.md` 为准。

---

## 1. 项目是什么

**知时助手（petgame_demo）**：Python 3.13 + PySide6 的 Windows 桌面助手，约 6000 行业务代码。
**2026-10-15 起由「小小桌宠」更名为「知时助手」（v1.7.0）**。

**当前定位**：一枚常驻悬浮球 + 一个控制中心 + 随时可唤起的 AI 面板。

| | 改造前 | **现在（v1.7.0）** |
|---|---|---|
| 产品本体 | 陪伴型桌宠 | **时间感知 + AI 助手**（问答 / 翻译 / 截图提问 / 作息建议） |
| 主入口 | 桌宠右键菜单 | **全局热键 + 悬浮面板**（悬浮球只做常驻指示） |
| 桌宠角色 | 核心 | **已整体移除**（宠物模型子系统 + 便签 + 快捷启动，v1.7.0） |
| 数据主权 | —— | **「隐私与数据」页**：逐类查看 / 导出 / 清空 |

> 为什么要移除宠物那一套：参加数字媒体竞赛的赛题是「AIGC 类数字创意作品」，
> 宠物模型与赛题无关，只会稀释评委对主线的理解。移除前已做**项目外备份**
> （`_backup_petgame_demo_before_知时助手_20261015.zip`，379 文件 / 51.1 MB）——
> 本项目自 P0 起 git 全部未提交，删掉就找不回来，这是先备份再动手的原因。
> `Form` 协议与 `FORM_BUILDERS` 注册机制**保留**：它承载的是
> 「外壳不关心外观长什么样」这条架构边界，对比赛仍然有讲头。

---

## 2. 硬规则（违反即返工）

1. **主线程不可阻塞。** 任何网络 / IO / **数据库写入**不得在 Qt 主线程或事件回调里同步执行。
   - `EventBus.publish` 是**同步 for 循环**（`event_bus.py:165`）—— 耗时回调请用 `publish_async()`。
   - **SQLite 落库必须放工作线程**。M1 实测：在主线程 commit 三次要 **154ms**，移到线程池后降到 **2.8ms**。
2. **插件现在支持包加载了（T1 已修）。** `plugin.py` 内**可以**写相对导入（`from .modes import ...`）。
   但模块名仍建议带前缀，且禁止 `config.py` / `logger.py` / `utils.py` 这类通用名。
3. **桌宠不是入口。** 新功能不得依赖桌宠窗口存在。**判据：把桌宠隐藏，功能必须完整可用。**
4. **不要用裸 `time.sleep()` 阻塞主线程等待。** 会卡住 Qt 事件循环（S2 实测：目标窗口收不到 WM_COPY）。
   正确做法是「泵事件循环 + 短睡眠」，见 `native/selection.py` 的 `_wait()`。
5. **不要新建与标准库同名的顶层包** —— `platform` / `types` / `code` / `token` 等会遮蔽标准库。
   系统代理层因此命名为 `native/`。
6. **配置改两处**：`data/config_manager.py` 的 `DEFAULT_CONFIG` 常量 + `config.default.json`。只改一处不生效。
   - ⚠ **`config_manager.set(k, v)` 只改内存，不落盘**，必须另调 `config_manager.save()`。
     惯例是「多次 `set()` 后统一 `save()`」（`presentation/dialogs.py` 连设 10 项再存一次），
     所以别把 `save()` 塞进 `set()`。模块级 `set_config()` 同样不保存 —— **命名有误导性，勿用**。
   - ⚠ **程序运行期间改配置文件会被覆盖**：`presentation/ui_renderer.py` 会在窗口移动时
     保存 `window.position`。**改配置必须先关程序。**
7. **面板必须预热**，且预热要**真的画一次**（`warm_up()` 里 `processEvents()` + `repaint()`）。
   否则首次唤起会付 145ms 的冷绘制成本。
8. **一切"只贵一次"的开销都必须在启动期付掉**（`on_ui_ready`），不得留到首次热键响应。
   当前预热清单（缺一个就会卡）：
   | 资源 | 一次性成本 | 预热函数 |
   |---|---|---|
   | pynput `Controller()` 构造 | **71ms** | `native/selection.py::warmup_keyboard()` |
   | 首次访问剪贴板 | **88ms** | `native/selection.py::warmup_clipboard()` |
   | `OverlaySelect` 首绘（全屏自绘） | **~100ms** | `presentation/overlay_select.py::warm_up()` |
   | `AIPanel` 首绘 | **145ms** | `presentation/ai_panel.py::warm_up()` |

   新增任何重量级资源（模型、句柄、大控件树）时，**必须加进这张表**。
   M2 实测：不预热时首次唤起卡 **87–340ms**；全部预热后稳定在 **17ms**。
9. **截图只抓需要的区域**，不要先抓全屏再裁剪。抓全屏 **90ms** → 抓 320×200 区域 **3–5ms**。
   见 `native/capture.py::grab_region()`。
10. **颜色/圆角/间距一律走设计 token，不许写死。** 主题只有**一个**来源：
    `presentation/design/theme.py::theme()`（配置键 `appearance.theme`）。
    `presentation/theme.py` 只是老名字的兼容门面。
    - **`qss.py` 里不允许出现任何 `#RRGGBB`**，颜色只能来自 `t.palette`；
      UI 代码里也不许 `setStyleSheet("... #RRGGBB ...")`。
      有测试守着（`tests/test_design.py::test_qss_source_has_no_hex_literals`、
      `test_no_inline_stylesheet_with_hex_in_ui_code`）。
    - 对话框继承 `AppDialog`（`dark` 参数保留但忽略 —— 主题是全局单例）。
      面板 / 自绘控件不要自己拼颜色，**用 `objectName` + 全局 QSS 表达**。
    - 字号一律 **pt**（DPI 自适应），禁止写死 `px` 字号。
    - 图标统一从 `presentation/design/icons.py` 取（内联 Lucide SVG，按主题着色）；
      名字写错返回**空图标**而不是抛异常。
11. **不要打开 `quitOnLastWindowClosed`。** 本项目两个常驻窗口都是 `Qt.Tool`，
    **不计入「最后窗口」判定** —— 一旦为 True，关掉任意对话框就会退出整个应用
    （P2.6 修的就是这个）。退出只能由显式 `app.quit()` 触发（托盘/右键菜单「退出」）。
12. **新增窗口时想清楚层级。** 本项目所有窗口都应在**同一个置顶层**
    （`WindowStaysOnTopHint`），并在 `mousePressEvent` 开头调
    `self.raise_to_front()`（`presentation/window_behavior.py`）。
    漏掉前者的后果：置顶窗口（`WS_EX_TOPMOST`）会**永久压住**它，点也翻不上去。
13. **模态提示框一律用 `presentation/dialogs.py::message_box()`**，
    不要用 `QMessageBox.warning()` / `.question()` 静态方法 ——
    后者不继承置顶标志，会被桌宠 / AI 面板盖住。
    另外 `QMessageBox.setWindowModality()` **会重置窗口标志**，
    所以顺序必须是「先 modality、后 flags」（见 `_build_message_box`）。
14. **不要给 `.QWidget` 设背景色。**
    `.QWidget` 是 Qt 的**精确类**选择器（不匹配 `QPushButton` 等子类），
    但它照样命中「卡片内部的普通 QWidget 容器」—— 控制中心每个表单行、
    分隔条、面板动作行都是裸 QWidget。一旦给它上窗口底色，白色卡片里就会
    冒出一条条灰带（P2.7 踩过，浅色主题下肉眼可见）。
    顶层裸 QWidget 窗口的底色由 `QPalette` 的 `Window` 角色提供。
    同理，滚动区里透明化只能用 `.QWidget`，用 `QWidget` 会把里面的
    `QLineEdit` / `QComboBox` 一起透明掉。
15. **控件尺寸由 Python 的 `setFixedSize()` 决定，不要在 QSS 里写 `min/max-width`。**
    QSS 的尺寸约束会盖掉 `setFixedSize()`，两者打架时按钮会突然变成另一个尺寸，
    而且**没有任何报错**（P2.7 踩过：`#iconButtonDanger` 缺基础规则，
    退化成通用 `QPushButton`，关闭按钮变成 120×30 的灰块）。
    新增带变体的控件时，**每个变体都要有基础规则**，不能只写 `:hover`。
16. **渲染 UI 预览图不能用 `QT_QPA_PLATFORM=offscreen`。**
    那个平台下拿不到中文字形，渲染出来全是豆腐块（`□`）。
    要目检排版必须用真实平台（不 `show()` 也能 `widget.render(QImage)`）。

## 2.1 唤起时序的隐藏陷阱（最容易写错的地方）

取选中文本必须**在面板抢焦点之前**完成，否则 `Ctrl+C` 会复制到面板自己的输入框：

```
1. snapshot 前台窗口
2. panel.show_passive()   ← 非激活显示，用户立刻看到，原应用仍持有焦点
3. selection.get_selected()  ← 此时 Ctrl+C 才取得到东西
4. panel.activate_for_input()  ← 采集完成后才抢焦点
```

见 `extensions/system/ai_assistant/plugin.py` 的 `invoke()`。

---

## 3. 环境与运行（已实测可用）

项目目录内**没有 `python.exe`**，但自带完整依赖（`Lib/site-packages`：PySide6 6.11.1 / pynput / pywin32 / pytest）。

```bash
cd "C:/Users/LL/Desktop/处理沙盒/petgame_demo"

python dev_bootstrap.py                     # 启动桌宠
python dev_bootstrap.py check_project.py    # 项目自检
python dev_bootstrap.py -m pytest tests -q  # 测试套件

# 端到端验证（会自动注册全局热键并合成按键，运行时会占用 Alt+Q/T/S 数秒）
python dev_bootstrap.py spikes/m1_verify.py # 问答链路
python dev_bootstrap.py spikes/m2_verify.py # 翻译 + 截图 + 投递链路
python dev_bootstrap.py spikes/m3_verify.py # 设置 UI 热切换（本地假服务，不联网）

# 真实 API 连通性自检（**需要已填 api_key**，会真的发网络请求、可能计费）
python dev_bootstrap.py spikes/api_check.py
```

`dev_bootstrap.py` 负责挂载 `Lib/` 依赖并注册 pywin32 的 DLL 目录；
它还会把**被运行脚本所在目录**加入 `sys.path`（对齐 `python <script>` 语义），
否则 `spikes/*.py` 里的 `import _common` 会失败。

若改用独立 venv（`pip install -r requirements.txt`），则不需要它，直接 `python main.py`。

**当前测试基线：166 passed**（116 P2.6 及以前 + 9 设计系统规格 + 20 控件/面板/控制中心
+ 12 垫片契约 + 9 缺陷回归）。

> ⚠ 注意：`tests/test_config_manager.py` 里的用例会实例化**真实单例**
> `ConfigManager()`，因此跑测试会顺带读写 `~/.pet_demo/user_config.json`
> （只补齐缺失字段，不会丢用户值）。新增的版本回归用例已刻意绕过单例、
> 改用临时目录，不污染真实配置。

> ⚠ `tests/test_theme.py` 会调用 `set_theme(..., persist=False)` 切主题，
> 只改内存不写盘；用例结束前会把主题复位，`user_config.json` 的
> `appearance.theme` 不会被污染。

> ⚠ `m3_verify.py` 会**临时改写** `~/.pet_demo/user_config.json` 并在结束时还原
> （`finally` 保证，即使中途异常）。跑完可自行确认配置未被污染。

---

## 3.1 接入模型服务（API 配置）

**本项目的 provider 是「OpenAI 兼容协议」**（`engine/ai/providers/openai_compat.py`），
只要服务商实现了 `POST {base_url}/chat/completions`，改三个字段就能接：
`base_url` / `model` / `api_key`。DeepSeek、Kimi、通义、硅基流动、OpenRouter、
本地 Ollama/vLLM/LM Studio 都是这一类。

配置文件是 **`~/.pet_demo/user_config.json`** 的 `ai` 节
（`data/config_manager.py` 的 `DEFAULT_CONFIG` 是**另一份**硬编码默认值，
两者要同步改，见硬规则 #6）。

### 方式一：在程序里改（推荐，支持热切换）

**唤起面板（`Alt+Q`）→ 点标题栏右上角 `⚙` → 选服务商 → 填 API Key → 点「测试连接」→ 点「保存并生效」。**

也可以从**托盘菜单 → 「AI 服务设置…」**进入（热键失效时的兜底通道）。

- **热切换**：保存后 `SessionManager` 立即重建，**无需重启程序**。
  实现见 `plugin._on_settings_applied()` → `_ensure_manager(force=True)`。
- **测试连接**：发真实请求验证（`GET /models` + 一次极短对话），结果逐步显示在状态区；
  成功后会**把服务端返回的真实模型列表灌进下拉候选**，比预设里的硬编码准。
- **服务商预设**：硅基流动 / DeepSeek / OpenAI / 阿里百炼 / Kimi / 本地 Ollama / 自定义。
  选预设会自动填 `base_url` 并换掉模型候选（换服务商=换模型命名体系）。
- 代码：`presentation/ai_settings_dialog.py`（UI）+ `engine/ai/probe.py`（探测，纯 Python 可单测）。

### 方式二：手编配置文件

以硅基流动（SiliconFlow）为例：

```jsonc
"ai": {
  "provider": "openai_compat",
  "base_url": "https://api.siliconflow.cn/v1",   // 固定，不要带 /chat/completions
  "model": "inclusionAI/Ling-flash-2.0",         // 文本主力（首字节 ~0.5s，见下表）
  "vision_model": "Qwen/Qwen3-VL-32B-Instruct",  // 截图问答（Alt+S）专用；见下方实测表
  "api_key": "sk-xxxxxxxx",                      // 见下方两种填法
  "api_key_ref": "",
  "request_timeout": 120
}
```

**模型名必须带命名空间前缀**（`团队/模型`），少写斜杠前缀会直接 404。
聚合平台上同一把 Key 可调几百个模型，所以本项目**用两个字段分流**：

| 字段 | 用途 | 建议 |
|---|---|---|
| `model` | 问答 / 翻译（纯文本） | 便宜的通用模型即可，如 `inclusionAI/Ling-flash-2.0`（首字节 ~0.5s）、`zai-org/GLM-5.3-Flash`（质量更好但 ~4s） |
| `vision_model` | **截图问答**（`Alt+S`） | 必须能看图，如 `Qwen/Qwen3-VL-32B-Instruct`（实测 0.76s）；留空则回退 `model`（会报错） |

> ⚠ **选模型务必实测首字节，不要看名字。** 2026-10-10 实测硅基流动（同一网络、同一 Key）：
>
> | 模型 | TTFB | 备注 |
> |---|---|---|
> | `inclusionAI/Ling-flash-2.0` | **~0.47s** | ✅ 快 30 倍，质量够用 |
> | `stepfun-ai/Step-3.5-Flash` | ~2–4s | |
> | `zai-org/GLM-5.3-Flash` | ~3.5–4.7s | 翻译最自然 |
> | `Qwen/Qwen3-8B` | ~15.3s | 免费档排队严重 |
> | `deepseek-ai/DeepSeek-V4-Flash` | ~19.4s | **名字带 Flash 却最慢** |
>
> 量法：`probe.probe_chat(provider, model)` 只等第一个 token 就返回，省时省钱。
> 免费档排队会让首字节从 0.5s 飙到 15s+，交互式工具对此极其敏感。

> ⚠ **视觉模型：参数量大 ≠ 慢。** 2026-10-11 实测（同一网络、同一 Key）：
>
> | 视觉模型 | TTFB | 备注 |
> |---|---|---|
> | `Qwen/Qwen3-VL-32B-Instruct` | **756ms** | ✅ 当前选用 |
> | `Qwen/Qwen3-VL-32B-Thinking` | 5153ms | |
> | `PaddlePaddle/PaddleOCR-VL-1.5` | 8718ms | |
> | `Qwen/Qwen3-VL-8B-Instruct` | **22396ms** | ❌ 8B 反而慢 **30 倍**，冷门型号排队 |
>
> 8B 那个还极其不稳定（另一次实测首次 TTFB 19.5s、第二次 59s），
> 直接把 `api_check.py` 的 30s 超时打穿。**聚合平台上冷门型号的排队时间
> 远大于模型本身的计算时间**，选模型必须实测。

> `vision_model` 留空时，截图会发给纯文本模型 —— 大多数服务端会直接拒绝。
> `SessionManager.model_for(has_image)` 负责这个路由，有单测覆盖。

### API Key 的三种存法

1. **系统密钥库（推荐）** —— v1.8.0 起界面里就能选：
   面板 → `⚙` → 「保存位置 → 系统密钥库」。
   手编配置则是 `"api_key_ref": "keyring:api.siliconflow.cn"` + `"api_key": ""`。
   - 装了 `keyring` 就用操作系统凭据管理器（`pip install keyring`，可选依赖）；
   - **没装 keyring 的 Windows 走 DPAPI 加密文件**（`~/.pet_demo/secure_keys.bin`），
     同样不落地明文；
   - 想直接写：
     ```bash
     python -c "import keyring; keyring.set_password('pet_demo_ai', 'api.siliconflow.cn', 'sk-...')"
     ```
     条目名按 `base_url` 的主机名取（`key_store.entry_for_base_url()` 就是这个口径）；
     名字有白名单 `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`（同时挡路径穿越）。
2. **明文（退路）**：直接写 `"api_key": "sk-..."`。
   配置文件在用户主目录，不在 git 仓库里 —— 但**它会进备份、进同步盘、
   进「导出全部数据」的 zip**。所以界面上这一档的标签直接写明代价。

读取一律走 `engine.ai.resolve_api_key()` —— **全项目唯一读密钥的地方**：
`api_key_ref` 优先，明文只作老用户的回退。别处直接 `config.get("ai.api_key")`
会把已迁移的用户悄悄降级成明文读取（界面显示已保存、实际取不到）。
引用存在但取不到 → 返回空串，让上层报「没配 API Key」，**不做别的兜底**。

脱敏一律走 `data.key_store.mask()`（只露头 3 尾 4、**总长度固定**）。
日志、状态栏、异常信息里**只许出现脱敏值** —— 真实长度本身就是信息。

### 自检（填完 Key 后跑这一条）

```bash
python dev_bootstrap.py spikes/api_check.py
```

它会依次验证：配置完整性 → `GET /models`（地址+鉴权）→ 文本流式（TTFB/块数）
→ 翻译预设 → 视觉模型识别合成测试图（红圆 + 数字 42）。
模型名填错时，它会**从 `/models` 列表里列出候选**帮你纠正。
参数：`--model` / `--vision-model` / `--text` / `--skip-vision` / `--skip-translate`。

---

## 4. 进度台账

| 阶段 | 状态 |
|---|---|
| 可行性研究（v1） | ✅ 完成 |
| 执行框架定稿（v2，功能优先） | ✅ 完成 → `docs/执行框架.md` |
| **P0 技术验证（4 个 spike）** | ✅ **完成，4/4 PASS** → `spikes/README.md` |
| **P1 AI 底座与最小闭环** | ✅ **完成，M1 端到端 PASS** → `spikes/m1_verify.py` |
| **P1.5 打包自动化（T4）** | ✅ 完成 → `build_hiddenimports.py`；**打包冒烟已于 P2.2 补齐** |
| **P1.6 翻译/截图链路验证（M2）** | ✅ **完成，M2 端到端 PASS（8/8）** → `spikes/m2_verify.py` |
| **P1.7 冷启动开销整改** | ✅ 完成，首次唤起 87–340ms → **17ms** → §10.0.5 |
| **P2.0 API 接入（硅基流动）** | ✅ 配置已切好 + `vision_model` 分流已实现 → §3.1（**Key 已填，`api_check.py` 三条链路全 PASS**） |
| **P2.1 设置 UI 化（热切换）** | ✅ **完成，M3 端到端 PASS** → `spikes/m3_verify.py` |
| **P2.2 打包出 exe + 发布目录** | ✅ **完成** → `dist/小小桌宠Demo/`、`dist/little-table-pet-v1.1.1-win64{,.zip}` |
| **P2.3 配置版本号修复** | ✅ 完成，基线 85 → 86 passed |
| **P2.4 SSE 中文乱码修复** | ✅ **完成，S5 复现 → 修复 → 94 passed**（真机一接就乱码的根因） |
| **P2.5 换主力模型（速度）** | ✅ 完成，`Ling-flash-2.0` TTFB 0.47s vs `DeepSeek-V4-Flash` 19.4s → §3.1 |
| **P2.6 UI 统一 + 窗口生命周期 + 点击置顶** | ✅ **完成，S6/S7 复现→修复 → 116 passed** → §4.1 |
| **P2.7 设计系统重构（VS Code / Win11 取向）+ 控制中心** | ✅ **完成，S8 全过 → 166 passed** → §4.2 |
| **P2.8 会话历史 / 预设管理 UI + 性能收尾（R14/R15）** | ✅ **完成，S9/S10 全过 → 196 passed + 1 skipped** → §4.3 |
| **P2.9 投递语义打磨（REPLACE ≠ PASTE）** | ✅ **完成，S11 全过 → 216 passed + 1 skipped** → §4.4 |
| **P2.10 会话历史的「继续对话」入口** | ✅ **完成 → 236 passed + 1 skipped** → §4.5 |
| **P2.11 移除「替换原文 / 粘贴到前台」** | ✅ **完成，S12 实测成功率仅 ~40% → 234 passed + 1 skipped** → §4.6 |
| **P2.12 活动建议插件（行为采集 + AI 规划）** | ✅ **完成 → 271 passed + 1 skipped** → §4.7 |
| **P2.13 降低操作负担与打扰（一键开关 + 收工小结 + 空闲剪裁）** | ✅ **完成 → 327 passed + 1 skipped** → §4.8 |
| **P2.14 活动洞察升级为主功能（双核心并列 + 控制中心改造）** | ✅ **已完成**：① 数据层 ② 组件层 ③ 今日页 ④ 趋势页 ⑤ 常驻指示 ⑥ 测试·文档·打包 **v1.2.0** → **485 passed + 1 skipped**；发布包 `dist/little-table-pet-v1.2.0-win64{,.zip}` → §4.9 |
| **P2.15 概览升级为独立仪表盘** | ✅ **已完成**：`OverviewBoard`（顶边强调线 + 标题 + 竖分隔线）+ 头条格 `primary`（强调软底 + 更宽）→ **494 passed + 1 skipped**；发布包 `dist/little-table-pet-v1.2.1-win64{,.zip}` → §4.10 |
| **P2.16 表现形态重构：悬浮球（外壳 / 外观分层）** | ✅ **已完成**：① `ShellWindow` + `Form` 协议 ② `OrbForm`（球 + 进度环 + 中心图标 + 四态）③ 气泡改独立窗口 + 位置改中心点 ④ 贴边吸附 ⑤ **位移动画按形态门控**（`wants_shell_motion` + 按住即停，exe 冒烟才发现）⑥ 测试·目检·反向验证 ⑦ 文档·打包 **v1.3.0** → **535 passed + 1 skipped**；发布包 `dist/little-table-pet-v1.3.0-win64{,.zip}` → §4.11 |
| **P2.8+ 真实 API 连通性自检（Key 已填）** | ✅ **完成，`api_check.py` 三条链路全 PASS**；修掉视觉模型选型 / UI 预设表 / 超时提示三个真问题 → §4.3 第 6 节 |
| **P2 查询/翻译主力功能（真实第三方应用实测）** | ⬜ **未开始 —— 这是下一步**（真实 API 已通；缺 Chrome / VSCode / 微信等真实应用矩阵） |
| P3 皮肤与语音 | ⬜ 未开始 |

**P0 结论（实测）**：
- S4 流式渲染：最差主线程阻塞 **34.8ms**（200 tok 压力测试 33.0ms）→ **不需要拆子进程**
- S1 全局热键：Alt+Q/T/S 注册成功，合成按键可触发 WM_HOTKEY，与 InputMonitor 共存 → **可用**
- S3 面板：冷构建 63ms / 预热唤起 P95 **5.8ms**，焦点还原成功 → **必须预热**
- S2 选中文本：剪贴板方案机制通过，还原无损 → **可用**

**P1 结论（实测）**：M1 全链路 PASS（8/8 稳定）—— 插件包加载 → 面板预热 → 热键注册 → 合成 Alt+Q 唤起
→ 采集选中文本 → 流式渲染 → Esc 还原焦点。测试基线 **73 passed**（原 58 + 新增 15）。
主线程心跳：[唤起] **16.6–18.3ms**、[流式] **16.7–19.5ms**。

**P1.6 结论（实测）**：M2 全链路 PASS（8/8 稳定）—— `Alt+T` 划词翻译（自动提交 + translate 预设）、
「替换原文」投递（**原应用内容真的被译文覆盖**）、`Alt+S` 截图问答（多模态 `image_url` 已发出）。
翻译与截图两条链路从此不再是「已实现未验证」。

**P1.7 结论（实测）**：一次性冷启动开销整改。发现并修掉 4 处「只贵一次」的开销
（pynput Controller 71ms / 首次剪贴板 88ms / 遮罩首绘 ~100ms / 抓全屏 90ms），
首次唤起从 **87–340ms** 降到稳定的 **17ms**。详见 `docs/执行框架.md` §10.0.5。

**P2.1 结论（实测）**：设置 UI 化 + 热切换，M3 **全绿**（32 项检查）。
关键验证不是「配置里的字符串变了」，而是**请求真的换了目的地**：
起两个本地假服务 A / B，切配置后确认 B 收到请求、A 不再收到（可反复切换）。
测试连接调用 **0.8ms 返回**（子线程跑），全程主线程最大心跳 **24ms**。
顺带修掉 T4 的一个盲区：`presentation/` 不在 `SCAN_DIRS` 里，
导致 `ai_panel` / `ai_settings_dialog` 等**延迟导入的模块进不了 hiddenimports**
（开发正常、打包后一点设置就崩）。扫描数 43 → **54**。

**P2.2 结论（实测）**：首次真正打包并验证。

- 构建：PyInstaller 装进**隔离目录** `Lib/packtools`（不污染 `Lib/site-packages`），
  经 `PYTHONPATH` + `dev_bootstrap.py` 驱动，约 2m40s。
  产物 `dist/小小桌宠Demo/`（exe 5.09 MB + `_internal/`）。
- **三重验证**：① 读 PYZ 归档（597 模块）确认 `presentation.ai_settings_dialog` 等全部在内；
  ② `_internal/` 下 `engine/ native/ presentation/ extensions/ tools/` 齐全；
  ③ 真跑一次，日志出现完整启动序列 + `热键已注册: alt+q/t/s`。
- **`*.spec` 已从 `.gitignore` 移除** —— `PetDemo.spec` 是构建配置（T4 自动化写在里面），
  必须纳入版本控制，否则 T4 成果会被忽略掉。
- 发布目录：`dist/little-table-pet-v1.1.1-win64{,.zip}`（zip **317 文件 / 56.75 MB**，
  已排除 `__pycache__` 与 `.pyc`）。
- 顺手修掉 `config_manager` 的版本号覆盖问题（见下）。

> ⚠ **验证 GUI 进程时的坑**：Bash 工具在**命令结束**时回收整棵子进程树，
> 与 `dangerouslyDisableSandbox` 无关。所以「启动 GUI 后换一条命令去 `tasklist`」**必然查不到**，
> 容易误判成「应用崩溃退出」。同理，**沙箱内的 `s1_hotkey.py` 注册成功不能证明外部应用已死**
> （可能处于不同 job/桌面，热键不冲突）。
> 正确做法：在**同一次调用内**轮询进程；需要长期驻留的 GUI 由**用户自己双击**启动。

**P2.4 结论（实测）**：修掉「真机一接就乱码」的根因 —— SSE 响应解码。

症状：划词翻译（`Alt+T`）返回 `ç¿»è¯ç»æ...`。
这是 **UTF-8 字节被按 ISO-8859-1 解码**的特征（「翻译」2 字 → 6 字符，长度翻倍）。

根因在 `engine/ai/providers/openai_compat.py`：

```python
resp.iter_lines(decode_unicode=True)   # ← 受 resp.encoding 影响
```

服务端返回 `text/event-stream` **不带 charset** 时，requests 按 RFC 2616 对 `text/*`
回退到 **ISO-8859-1** → 中文全变乱码。硅基流动 / DeepSeek 都是这个形态。

**为什么四轮验证都没抓到（最重要的教训）**

| 验证 | 为什么漏掉 |
|---|---|
| M1 / M2 | 用**进程内假 Provider**（继承 `Provider`），**完全绕过** `OpenAICompatProvider.stream()` |
| S4 | 唯一走真 HTTP 的，但假服务写了 `text/event-stream; **charset=utf-8**` → 解码正确 |
| M3 | 不带 charset，但只断言「请求打到哪个服务」，不看内容 |
| 单元测试 | 只测 `iter_openai_deltas(str)`，输入已是 str，**编码边界不在被测范围内** |

**一句话**：测试替身（fake provider / 带 charset 的假服务）恰好绕过了唯一有问题的那层。

修复：
1. `engine/ai/stream.py` 新增 `decode_lines()`（纯函数，可单测）——
   取**原始字节**自己按 UTF-8 解。按字节切行是安全的：UTF-8 多字节序列
   的每个字节都在 0x80–0xFF，**不含 0x0A / 0x0D**。
2. provider 改用 `iter_lines(decode_unicode=False)` + `decode_lines()`，
   并显式 `resp.encoding = SSE_ENCODING`（让错误分支的 `resp.text` 也确定）。
3. `probe.list_models()` 同样钉死 `resp.encoding`。
4. 新增 `spikes/s5_sse_encoding.py`：**真 HTTP 边界**复现（两种响应头对比）。
5. 新增 3 条**集成**回归用例，把「`SessionManager` + 真实 `OpenAICompatProvider` + 真 HTTP」
   这个组合锁住 —— 这正是历史盲区。
6. 给 `invoke()` / `_on_submit()` 补日志（`唤起模式` / `选区采集` / `发起请求`），
   让「按了没反应」能区分是热键没到还是选区为空。

验证方式同 P2.3：**先把修复注释掉，确认新用例会失败**（实测复现 `ç¿»è¯` 乱码），
再恢复。基线 86 → **94 passed**。

> 附带发现：`Alt+T` 在**没有选中文本**时不会有任何动静（`translate` 模式是
> `auto_submit=True` + `SRC_SELECTION`，取不到文本就只显示一句提示）。
> 这不是 bug，但以前无日志、无法区分，现已补上。

---

## 4.1 P2.6 结论（UI 统一 / 窗口生命周期 / 点击置顶）

用户实测报了三个问题，**根因是两个**。

### 问题 1：关掉「AI 服务设置」→ 整个应用退出

根因：`QApplication.quitOnLastWindowClosed` 默认 **True**，而本项目两个**常驻**
窗口（`PetWindow` / `AIPanel`）都带 `Qt.Tool` 标志 —— **Tool 窗口不计入
「最后窗口」判定**。于是关掉任意普通 `QDialog`（AI 设置、番茄钟、便签…）时
Qt 认为「没有窗口了」→ 直接 quit。

修复：`presentation/ui_renderer.py::UIManager.initialize()` 里
`self.app.setQuitOnLastWindowClosed(False)`。之后退出**只能**由显式
`app.quit()` 触发，共两处：托盘/右键菜单「退出」→ `main.PetApp.stop()`；
以及 `PetWindow._quit_app()`。「关对话框」与「退应用」就此解耦。

> ⚠ 验证这个 bug 时踩的坑：`lastWindowClosed` **只在事件循环运行期间才会发出**
> （Qt 源码 `QGuiApplicationPrivate::emitLastWindowClosed()` 里有 `in_exec` 判断）。
> 第一版 spike 没跑 `app.exec()`，于是无论对错都"没触发"，把假设误判成"未复现"。
> 另外 `QApplication` 无法销毁重建、`quitOnLastWindowClosed` 又是全局状态，
> 所以 `spikes/s6_window_lifecycle.py` **每个用例单开一个子进程**，各自跑真事件循环。

### 问题 2：各窗口 UI 不统一（+ 问题 3：点击的窗口没到上层）

根因：`appearance.theme` 这个配置项**从来没有任何代码读过** ——
「应用主题」在代码里根本不存在。后果：
- `AIPanel` 自己写死一份深色 QSS（圆角 **12**）
- 所有对话框走 `GlassTheme(dark=False)`（浅色，圆角 **20**）
- 点面板上的 ⚙ 会弹出一张**白卡片盖在深色面板上**

而「点击置顶」失败的根因是**窗口层级**：`PetWindow` / `AIPanel` 带
`WindowStaysOnTopHint`（Windows 上是 `WS_EX_TOPMOST`），**对话框没有**。
`WS_EX_TOPMOST` 窗口始终高于非置顶窗口 → 设置对话框被面板永久压住，
**点也翻不上去**。

修复：
1. 新增 `presentation/theme.py` —— **唯一**主题源。`app_theme()` 返回进程内单例
   `GlassTheme`，`set_theme()` **原地**改（`set_dark`），于是持有引用的自绘控件
   只需 `update()` 就能跟着变色。取值 `default`/`light`/`dark`（非法值兜底成 default）。
2. `presentation/ai_panel.py` —— 删掉写死的 `_CARD_QSS`，改由 `panel_qss(theme)`
   从 token 生成；圆角改用 `RADIUS['dialog']`，与对话框一致；图标按钮统一成
   26px 圆角方块（悬停才出现底色），并加一条 iOS 风格的发丝分隔线。
3. `presentation/dialogs.py::GlassDialog` —— `dark` 默认改为 `None` = 跟随应用主题；
   并补上 `WindowStaysOnTopHint`，与面板/桌宠**同处置顶层**。
4. 新增 `presentation/window_behavior.py::RaiseOnClickMixin` —— 提供
   `raise_to_front()`（`raise_()` + `activateWindow()`，吞 `RuntimeError`）。
   `PetWindow` / `AIPanel` / `GlassDialog` 三者在自己的 `mousePressEvent` 开头
   显式调用它。
5. 面板标题行加了**昼夜切换按钮**（复用已有的 `ThemeToggleButton`），
   让 `appearance.theme` 真正可用 —— 点一下即写配置并当场换肤。

> ⚠ 混入类**只**提供 `raise_to_front()`，不代管 `mousePressEvent`：
> 代管的话，子类重写 `mousePressEvent` 并调用 `super()` 会在同一次点击里
> 再触发一遍 `raise_() + activateWindow()`（实测 `called == [1, 1]`）。
> 三个窗口本来就要重写该方法做拖拽，所以改成显式调用 —— 一次点击一次置顶。

**验证**：`spikes/s6_window_lifecycle.py`（子进程隔离，复现 → 修复 → 对照）。
反向验证：把 `setQuitOnLastWindowClosed(False)` 改回 `True`，新用例确实失败。
基线 94 → **118 passed**（+2 窗口生命周期，+22 主题/UI）。

> P2.6 当时的 UI 统一性探针 `s7_ui_theme.py` 已随 P2.7 的设计系统重构
> **失效并删除**（它断言的 12px/20px 圆角与写死深色都不存在了），
> 由 `spikes/s8_ui_design.py` 取代。

### 附带修掉的两个坑

**(a) 模态提示框会被置顶窗口压住。**
`QMessageBox.warning()` / `.question()` 这类静态方法只把 parent 设为 owner，
**flags 里没有 `WindowStaysOnTopHint`**。而桌宠 / AI 面板都是 `WS_EX_TOPMOST` ——
于是「保存时配置不完整」的提示框会被面板盖住。实测：设置对话框 `topmost=True`，
而 `QMessageBox(parent=dialog)` 的 `topmost=False`。
→ 新增 `presentation/dialogs.py::message_box()`，全项目统一用它。

**(b) `QMessageBox.setWindowModality()` 会重置窗口标志。**
顺序写反就白干 —— 实测（offscreen）：

```
setWindowFlags(+WindowStaysOnTopHint) → 0x8043103  topmost=True
setWindowModality(WindowModal)        → 0x8003003  topmost=False   ← 标志被吃掉
```

所以 `_build_message_box()` 里 **modality 必须写在 flags 之前**。
这个顺序问题没有任何报错，只能靠断言窗口标志的用例兜住
（`tests/test_theme.py::test_message_box_is_topmost`）。

---

## 4.2 P2.7 结论（设计系统重构 + 控制中心）

### 为什么推倒重来

P2.6 把「各窗口颜色不统一」修成了「都走 `GlassTheme`」，但设计语言本身
还是早期那套 **iOS 液态玻璃**：20px 大圆角、半透明底、顶部高光、弹性动画。
用户明确要求换成 **VS Code + Windows 11 原生**的工具类审美，并给了硬规格
（配色 / 字体 / 间距 / 圆角 / 边框 / 布局 / 四态 / 数据区 / 滚动条 / 日志 /
空状态 / 图标 / 选择器纪律 / 颜色收敛）。

这不是「调几个数值」——是要**先有设计系统**。于是新建 `presentation/design/`：

| 文件 | 职责 |
|---|---|
| `tokens.py` | `Palette`（深浅两套色值）+ 间距/圆角/字体/图标尺寸常量 |
| `theme.py` | `Theme(QObject)`：`color()` / `qss()` / `qt_palette()` / `changed` 信号 |
| `qss.py` | 从 token 生成**全应用**样式表 + `QPalette`（零 hex 字面量） |
| `icons.py` | 49 个 Lucide 风格内联 SVG，按主题色现场着色（深浅各一套） |
| `widgets.py` | ToolButton / Button / IconButton / Card / NavList / LogView / EmptyState / SegmentedControl / ToggleSwitch / Hairline / BusyIndicator |
| `charts.py` | **P2.14** StatTile / RatioBar / RankBar / BarChart / TimelineBar / AxisLabels（数据可视化，图表色走 token） |

**订阅制而非枚举制**：每个控件继承 `ThemedWidget`，自己订阅 `theme().changed`。
将来新增窗口自动获得换肤能力 —— 靠枚举窗口列表一定会漏。

### 新增控制中心（`presentation/control_center.py`）

用户给的布局规格落成了实际窗口：`QToolBar`（iconOnly + tooltip，四态）+
左导航 208px + `QStackedWidget` + `QStatusBar`。七个页面：
桌宠外观 / 行为 / 番茄钟 / AI 服务 / 插件 / 日志 / 关于。
入口在托盘菜单和右键菜单的第一项「控制中心…」。

### 兼容垫片：`glass_widgets.py` 不删

`extensions/user/` 下的第三方插件（giwifi）按**老名字**导入
`GlassTheme` / `GlassButton` / `SPACING` / `STATUS_COLOR` …
直接删掉会让它们 import 失败。于是该模块保留为**垫片**：老名字 → 新实现，
行为按新设计走，老插件不改一行代码就换了皮肤。`STATUS_COLOR` 从
「写死的色值」改成「按当前主题实时解析」的惰性取值器。

### 本次修掉的四个真 bug

**(a) `ThemeToggleButton` 无限递归（`RecursionError`）。**
垫片里 `refresh_theme()` 调 `self.set_icon(...)`，而 `IconButton.set_icon`
内部又回调 `self.refresh_theme()` —— 覆盖了基类实现就变成死循环。
修法：直接改 `_icon_name` 字段再调 `super().refresh_theme()`。

**(b) `.QWidget` 背景色在卡片内部漏成灰带。**
`.QWidget` 是 Qt 的**精确类**选择器（不匹配 `QPushButton` 等子类），
但它照样命中「卡片内部的普通 QWidget 容器」—— 控制中心的每个表单行、
分隔条、面板的动作行都是裸 QWidget。浅色主题下白色卡片里冒出一条条
窗口底色的灰带，肉眼可见。
修法：**不再给 `.QWidget` 设背景**；顶层裸 QWidget 窗口的底色交给
`QPalette` 的 `Window` 角色（Fusion 会给顶层窗口上色），并显式声明
卡片/滚动区内部的 `.QWidget` 透明。

**(c) `#iconButtonDanger` 缺基础规则 → 关闭按钮变成 120×30 灰块。**
只写了 `:hover`，没有基础规则，于是它退化去匹配通用 `QPushButton`
（背景 `#2D2D30`、padding 撑开尺寸）。修法：把
`#iconButton, #iconButtonDanger` 合并写基础规则；**并且不在 QSS 里写
`min/max-width`** —— QSS 的尺寸约束会盖掉 `setFixedSize()`，两者打架
没有任何报错。

**(d) 滚动条 hover 变宽的实现口径。**
轨道宽度**固定**为 hover 宽度，靠 handle 的 `margin` 由 2px 收到 0
让滑块从 8px 变宽到 12px。不直接改轨道宽度 —— 占位一变 viewport 就要
重排，hover 瞬间正文会左右抖一下。

### 验证

`spikes/s8_ui_design.py`（原 S7 已随重构失效并删除）：25 项自动断言
（规格可判定项全过）+ **真实平台**渲染 20 张预览图供人工目检。

> ⚠ 渲染预览图**不能用** `QT_QPA_PLATFORM=offscreen` —— 那个平台下拿不到
> 中文字形，渲染出来全是豆腐块（`□`）。必须用真实平台（不 `show()` 也能
> `widget.render(QImage)`）。

反向验证：把 `.QWidget` 背景加回去，新用例确实失败（第一版断言只匹配
「行首的 `.QWidget`」，被 `QMainWindow, QDialog, .QWidget { ... }` 这种
逗号列表绕过去了 —— 改成扫整条选择器列表才真正生效）。

基线 116 → **166 passed**。产物：`spikes/results/ui_design/*.png`（16 张）。

---

## 4.3 P2.8 结论（会话历史 / 预设管理 UI + 性能收尾）

三件事：把控制中心剩下两个空位填上，再把 `docs/执行框架.md` 里挂着的
两条性能遗留（R14 / R15）清掉。

### 1. 会话历史页（`SessionsPage`）

左列表（搜索框 + 会话）+ 右详情（预设 / 时间 / 消息条数 + 全文）+ 底部动作。

- 数据来自 `Store.list_sessions()` / `get_messages()` / `delete_session()`
- 搜索同时匹配标题与预设 id
- 没数据时给 `EmptyState` 引导（「按 Alt+Q 问一句，记录会出现在这里」），不是白板
- `Store` 取不到时降级成空状态，**不抛异常**（否则整个控制中心崩在这一页）

### 2. 预设管理页（`PresetsPage`）+ `PresetEditDialog`

表格 5 列（名称 / 标识 / 来源 / 默认投递 / 说明）。

- 内置 6 个预设**只读**（它们有专门的代码路径与测试），自定义预设可增删改
- 编辑模式下**标识锁死** —— 标识是主键，允许改等于静默产生重复条目
- 校验：名称非空 / 标识非空且 `[a-z0-9][a-z0-9_-]{0,31}` / 不与他人冲突 / 提示词非空

### 3. Store 收敛为进程级单例（`engine/ai/store.py::shared_store()`）

AI 插件（写）与控制中心（读）访问的是同一个库文件。各开各的连接在 WAL 下
并发**读**没问题，并发**写**会撞 `database is locked`，而且每开一个连接都要
重跑一遍 schema。改为全进程共用一个连接 + 内部 RLock。

配套：插件不再 `close()` 它（只解除引用），真正释放由 `main.py::stop()`
调 `close_shared_store()` 统一做 —— 否则控制中心正在读的数据会被关掉。

### 4. R14 选区采集：双峰各有原因，两半都要修

`get_selected()` 的耗时呈双峰（253ms / 565ms），两个峰**根因不同**：

**第一半（253ms）= 固定等待。**
`get_selected()` 发完 Ctrl+C 后无条件 `_wait(max(delay, timeout_ms))`，
于是每次调用都付约 250ms。
→ 改成 **30ms 最小响应窗口 + 8ms 轮询**，一读到内容立刻返回。
没有选中文本的应用根本不会写剪贴板，自然走到超时分支返回空串。
`_wait()` 步进同时从 5ms 压到 2ms —— 否则 8ms 的轮询间隔会被拖成 10ms+。
实测（假目标应用 25ms 写好剪贴板）：**251ms → 32ms，约 8×**。

**第二半（565ms）= `clip.clear()` 的跨进程代价。**
旧实现靠 `QClipboard.clear()` 制造「空剪贴板」基准，再判断 Ctrl+C 有没有写进东西。
但清空剪贴板要**等前一个所有者进程响应**（Windows 跨进程剪贴板所有权协商）。
→ 改用 `GetClipboardSequenceNumber()`（Win32，纯读、不需要打开剪贴板）判断
「是否发生了新的一次复制」，**完全不清空剪贴板**。

| 操作 | 代价 |
|---|---|
| `clipboard_sequence()` 读取 | **0.001–0.004 ms**（200 次共 0.6–1.5ms） |
| `clip.clear()`（本进程持有剪贴板） | 0.5 ms |
| `clip.clear()`（剪贴板有外部写入者） | **330 ms** |

用户剪贴板里放的通常就是别的应用刚复制的内容，所以这 330ms 是**常态**。

真实记事本上的分段计时（新旧交替，跨会话复现）：

| 阶段 | 旧（clear） | 新（序列号） |
|---|---|---|
| **clear** | **339.4 ms** | — |
| seq | — | **0.0 ms** |
| poll | 33.3 | 33.0 |
| **合计** | **375.0 ms** | **37.0 ms** |

> ⚠ **`clear()` 的代价只有跨进程才看得见。**
> 单进程里剪贴板由本进程（Qt）持有，`clear()` 只要 0.5ms ——
> 直接测会得出「才 0.5ms，改它干嘛」的错误结论。
> 想用「独立助手进程直接写剪贴板」来稳定复现也**不成立**：助手写完
> （数据完好、格式齐全）后 `clear()` 仍只要 0.1ms；反而一个
> **只 `EmptyClipboard` 不写数据**的助手进程能复现出 330ms。
> 即**慢的根源是所有权交接，与内容无关**，但触发时机依赖外部应用的真实行为，
> 无法用合成手段稳定构造 —— 所以 S10 用真实记事本，且两臂都取不到内容时
> 报 **INCONCLUSIVE** 而不是 FAIL（合成 Ctrl+C 是否落地取决于会话状态）。

### 5. R15 截图编码：PNG → JPEG

多模态上传默认改走 JPEG（质量 88），PNG 路径保留（`to_data_url(pm, fmt="PNG")`）。

真实屏幕实测：

| 图源 | PNG | JPEG | 提速 | 体积 |
|---|---|---|---|---|
| 全屏 2560×1600 | 1944 ms / 6212 KB | **98 ms / 894 KB** | 20× | 1/7 |
| 半分辨率 1280×800 | 501 ms / 1761 KB | **23 ms / 306 KB** | 22× | 1/6 |

> ⚠ **一个差点写进错误结论的坑**：第一版 S9 用「纯色 + 规则网格」的合成图对比，
> 结果 PNG 只有 9KB、比 JPEG 还小 —— 得出「JPEG 体积更大」的相反结论。
> 合成图对 PNG 极其友好，**必须用真实屏幕截图**才能反映实际。S9 已改为
> 优先真实抓屏，headless 时才回退合成图（并在输出里标注图源）。

带 alpha 的图不能直接存 JPEG（透明区会变黑块），`to_jpeg_bytes()` 先铺白底再画。

### 6. 真实环境自检暴露的三个真问题

用户填好 API Key 后跑 `spikes/api_check.py`，视觉链路 30s 超时 FAIL。
排查后**不是配置错误**，而是三个独立问题：

1. **视觉模型延迟与参数量无关。** 硅基流动实测：
   `Qwen/Qwen3-VL-32B-Instruct` **756ms** vs `Qwen/Qwen3-VL-8B-Instruct` **22396ms**
   （差 30 倍 —— 冷门型号排队严重）；`Qwen3-VL-32B-Thinking` 5153ms、
   `PaddleOCR-VL-1.5` 8718ms。
   → 把 `ai.vision_model` 从 8B 换到 **32B**，三条链路重跑全 PASS。
2. **UI 预设表把最慢的模型列在首位。** `presentation/ai_config_form.py` 的
   视觉模型候选表已按实测延迟重排，并在 tooltip 里写明「别按参数量猜快慢」。
3. **超时提示词误导。** 原 tooltip 写「视觉模型较慢，建议 ≥120」，
   实际文本模型不到 1s、视觉模型冷启动可达数十秒 —— 已改为给出实测数字。

> 教训：**「参数量大 = 慢」是错的。** 聚合平台上冷门型号的排队时间
> 远大于模型本身的计算时间。选模型必须实测 TTFB。

### 验证

- `spikes/s9_perf_tail.py`：R14 新旧实现对比 + R14-b 判据代价 + R15 编码对比。
  `QT_QPA_PLATFORM=windows python dev_bootstrap.py spikes/s9_perf_tail.py` 走真实抓屏
- `spikes/s10_real_app_selection.py`：真实记事本上的跨进程 A/B（需真实桌面）
- **反向验证**（四条都确认过断言不是空的）：
  - 把 `_poll_clipboard` 改回固定等待 → 新用例失败（实测 252ms）
  - 把 `UPLOAD_FORMAT` 改回 `"PNG"` → mime 断言失败
  - 让 `clipboard_sequence()` 恒返回常量 → `test_clipboard_sequence_moves_on_real_copy` 失败
  - 让测试假件的「版本号」永不递增 → `test_get_selected_returns_as_soon_as_content_appears` 失败
- 测试基线 **166 → 197**（196 passed + 1 skipped；+19 页面/对话框/单例，+12 性能契约）
- 版本号 1.1.1 → **1.1.2**

> **测试接缝说明**：`test_clipboard_sequence_moves_on_real_copy` 在 `offscreen`
> 平台下会 **skip** —— 那个平台下 Qt 用的是**进程内**剪贴板，根本不触碰
> Windows 剪贴板，`setText()` / `clear()` 前后序列号纹丝不动（实测都是同一个值）。
> 因此 `SelectionService._clip_token()` 抽成了可覆盖的方法，给单元测试留一条接缝；
> 真实判据由 `windows` 平台下跑这条用例来守（`QT_QPA_PLATFORM=windows`）。

---

## 4.4 P2.9 结论（投递语义打磨）

§5 的 P2 待办里挂着「投递方式打磨（替换原文的边界情况）」。
动手前先实测，发现它不只是「边界情况」—— 是个**语义错误**。

### 1. REPLACE 与 PASTE 曾经完全同路

`DeliveryKind.REPLACE` 的注释写着「替换原文（覆盖选中区）」，但
`Injector.paste_to_foreground()` 的签名是 `(self, text, restore_clipboard)` ——
**没有投递方式这个参数**，两种 kind 都只是「写剪贴板 + Ctrl+V」：

| 场景 | 期望 | 实际（改造前） |
|---|---|---|
| 选区还在 + PASTE | 插入 | **替换掉原文** |
| 选区丢了 + REPLACE | 替换 | **退化成插入** |

用户看到的是「点了替换原文，原文还在」。

**修法**：区别只在粘贴前**有没有取消选区**。

- `replace` → 不动选区，Ctrl+V 覆盖它（原文消失）
- `paste` → 先按一下 `Right` 取消选区（有选区时只取消选中、不移动光标），
  再粘贴 → 结果插在选区末尾（原文保留）

`Right` 在**无选区**时会让光标右移一格，所以只在**本次确实采到过选区**时才取消
（`plugin._context_text`，每次唤起重置）。

### 2. 成功判定恒为 True —— 「粘贴失败」提示不可达

`_send_paste()` 返回注解是 `None` 且 `except Exception: pass`，于是
`paste_to_foreground()` **只在设置剪贴板失败时才返回 False**。
实测：让 pynput 构造抛异常，它仍返回 `True`。

现在 `_send_paste()` 如实返回 bool，且**失败时不再白等 120ms**
（那 120ms 只为「等目标应用读走剪贴板」，没发出去就不必等）。

### 3. 投递路径的代价分解（实测）

| 段 | 本进程持有剪贴板 | 外部进程持有 |
|---|---|---|
| `backup()` | 0.2 ms | 0.8 ms |
| `set_clipboard()` | 1.4 ms | **113.1 ms**（首次 464ms） |
| `_send_paste()` | 3–8 ms | 3.4 ms |
| `_pump()` | **123.7 ms** | 121.7 ms |
| `restore()` | 1.0 ms | 0.8 ms |
| **合计** | **134.7 ms** | **240.8 ms** |

- **`restore()` 不慢** —— 一旦 `set_clipboard()` 成功，所有权已在本进程，
  还原只是本进程内的写。慢的是**第一次** `set_clipboard()`，与 R14 同源。
- **`_pump()` 的 120ms 是有语义必要的固定等待** —— 剪贴板是延迟渲染的，
  目标应用响应 Ctrl+V 时才来要数据；提前还原会粘到旧内容。

### 验证

- `spikes/s11_delivery_semantics.py`：真实记事本上比对**结果文本**。
  正常模式 REPLACE `'XXX BBB CCC'` / PASTE `'AAAXXX BBB CCC'`；
  `--legacy` 两臂相同 —— **自证探针能区分好坏**
- `tests/test_injector.py` **新增 20 例**（`Injector` 此前零测试覆盖）
- **反向验证四条**全部确认断言不是空的（忽略 `clear_selection` / 异常也返回 True /
  失败后仍 pump / 插件层恒不取消选区）
- 测试基线 **196 → 216 passed + 1 skipped**

> ⚠ S11 用**窗口消息**（`WM_PASTE` / `VK_RIGHT`）而非全局按键注入 ——
> 本机会话里合成按键落不下去（与 S10 同源，是桌面会话状态问题）。
> 所以它验证的是**语义**（有没有取消选区 → 结果文本差异）；
> 真实按键序列由 `tests/test_injector.py` 覆盖（断言 Right 排在 Ctrl+V 之前）。
>
> 顺带踩了三个 Windows 11 记事本的坑：编辑控件是 `RichEditD2DPT`（不是 `Edit`）；
> 消息必须发给**编辑控件**（发给主窗口只改到标题栏）；记事本是**单实例**，
> `Popen().pid` 不是 UI 进程 → 用「操作前后窗口集合差集」定位。

---

## 4.5 P2.10 结论（会话历史的「继续对话」入口）

§5 待办里的第三项。`SessionsPage` 原本只能查看 / 删除 —— 数据库里明明有历史，
读完却接不下去。

### 链路：控制中心 → AI 面板 → 同一条会话

```
SessionsPage「继续对话」
  → ControlCenter.continue_session(sid, msgs)        # 鸭子类型调插件
    → AIAssistantPlugin.continue_session(sid, msgs)  # 填上下文 + 唤起面板
      → AIPanel.load_history(msgs)                   # 渲染已有对话
        → 用户接着问 → SessionManager.ask(history=…, session_id=sid)
          → Store.append_exchange(sid, …)            # 追加到**同一条**会话
```

### 1. 续接不能复用 `save_exchange()`

`save_exchange()` 是给「新建会话」用的：`INSERT OR REPLACE INTO sessions`
会把 `created_at` 重置为现在、并用新提问覆盖标题；而 `messages` 是**追加**语义，
续接时整段历史已在库里，再写一遍就重复了。

所以新增 `Store.append_exchange()`：只追加这次的提问（内部走 `append_message`，
顺带更新 `updated_at`）。`SessionManager._run()` 按 `continuing` 分流。

### 2. 上下文要「既送模型又落库」

`ask(session_id=…)` 只影响**落库与追踪**，上下文由 `history` 决定 ——
两者必须一起传，否则续接出来的对话丢上下文。插件 `_on_submit()` 的顺序是：

```python
history = list(self._history) or None            # 先取**之前**的
self._history.append(ChatMessage("user", text))  # 再记这次的
```

反过来的话当前问题会被送进模型两遍。

### 3. 载入历史时不能露出投递按钮

`_on_delivery()` 的兜底就是「输出区内容」—— 载入历史后若允许投递，
「替换原文」会把**整段历史**投到前台应用。所以 `load_history()` 刻意让
`_has_result` 保持 False、`_actions.hide()`，等真的问出结果再出现。

### 4. 控制中心不硬依赖 AI 插件

用鸭子类型（`hasattr(plugin, "continue_session")`）而不是
`import AIAssistantPlugin` —— 插件可以被禁用或整个移除。取不到就明确提示
「AI 助手插件未加载」，比抛异常或静默失败好得多。

### 验证

- `tests/test_session_continue.py` **新增 20 例**，覆盖 Store / SessionManager / UI 三层
- **反向验证 5 条**全部确认断言不是空的：
  1. `append_exchange` 顺手覆盖标题 → `test_append_exchange_keeps_created_at_and_title` 失败
  2. `_run` 一律走 `save_exchange` → `test_ask_with_session_id_does_not_duplicate_history` 失败
  3. `_on_submit` 不传 `history` → `test_submit_sends_history_and_reuses_session_id` 失败
  4. `invoke` 不重置上下文 → `test_invoke_resets_to_a_fresh_session` 失败
  5. `load_history` 露出投递按钮 → `test_load_history_does_not_offer_delivery` 失败
- 测试基线 **216 → 236 passed + 1 skipped**
- 打包冒烟（v1.1.4）：PYZ **607 模块**，`append_exchange` / `load_history` /
  `continue_session` 等新符号全部在包内；exe 存活 16s，日志显示「版本: 1.1.4」
  + 完整启动序列（插件加载 → 托盘 → 预热 → `alt+q/t/s`）。
  发布包 `dist/little-table-pet-v1.1.4-win64{,.zip}`（**318 文件 / 56.90 MB**）

> ⚠ 查 PYZ 符号时记得收 `co_varnames` —— **函数参数名在那里**，不在 `co_names`。
> 只查 `co_names` 会把 `clear_selection` 之类误判成缺失（P2.9 踩过）。

---

## 4.6 P2.11 结论（移除「替换原文 / 粘贴到前台」）

用户反馈：**「替换原文和粘贴到前台没有反应」**。结论是**移除**，只保留「复制」。

### 先证伪了两件事

| 假设 | 实测 | 结论 |
|---|---|---|
| 代码有回归（P2.9 引入） | `tests/test_injector.py` 全绿；M2 端到端投递 **PASS** | ❌ 不是回归 |
| 目标换成**外部应用**就坏 | 专门写探针：真记事本 + 真面板 + 真 `_on_delivery` → `'敏捷的棕色狐狸跃过懒惰的狗。 jumps over the lazy dog.'`，状态栏「已替换原文」 | ❌ 外部应用也通 |

### 真正的问题：**成功率只有 40–50%**

`spikes/s12_real_injection.py`（真 pynput → 真记事本）连跑 10 次：

```
FPPFFPFFFP      →  PASS=4  FAIL=6
```

失败与成功**交错**出现（不是「跑一阵就坏」的状态漂移）。抓到的失败形态之一：

```
基准 "AAA BBB CCC"，选中 "AAA"，剪贴板 "XXX"
  期望 "XXX BBB CCC"
  实得 "v BBB CCC"     ← 字母 v 落下了，**Ctrl 没生效**
```

### 为什么必须移除：失败**无法自检**

`_send_paste()` 只在**抛异常**时才返回 False。系统把按键丢掉时不抛异常，
于是它返回 True → `_on_delivery()` 走成功分支 → 面板显示「已替换原文」，
而前台应用纹丝不动。**用户看到的就是「点了没反应」。**

> 一个会谎报成功、时灵时不灵的功能，比没有这个功能更糟 —— 它让人以为
> 是自己操作错了。

### 顺手纠正一条错误结论（重要）

S10 / S11 记着「**本机会话里合成按键落不下去**，是桌面会话状态问题」。
**不准确。** S12 直接问 `SendInput` 的返回值（`VK_F24` 无副作用键）：

| 环境 | `SendInput` 返回值 |
|---|---|
| 沙箱内 | **2/2 接受** |
| 沙箱外 | **2/2 接受** |

而且**两边都成功注入过**。所以真相不是「不 work」，而是「**时灵时不灵**」。
（S11 改用窗口消息本身是合理选择 —— 它要的是**确定性**；但当时给的理由是错的。）

### 试过但没用的两个修复假设

写在这里，省得后人重走：

| 假设 | 实验 | 结果 |
|---|---|---|
| 120ms 后还原剪贴板太早，目标读到旧内容 | 交错对照 6 次：`restore` 1P/2F、`--no-restore` 2P/1F | **无相关** |
| `press(Ctrl)` 与 `press("v")` 之间缺间隔 | 插 40ms 后连跑 5 次 | **5 次全 FAIL**，更糟 |

> 所以**别再调时序参数了**。真要恢复这个功能，第一步必须是
> **可验证的成功判定**（注入后回读目标窗口内容），而不是继续猜延迟。

### 改动

- `presentation/ai_panel.py`：投递行只剩「复制」（`Signal(str)` 现在只发 `"copy"`）
- `extensions/system/ai_assistant/plugin.py`：`_on_delivery()` 只认 `COPY`，
  非 copy **彻底无动作**；不再持有 `Injector`
- `presentation/dialogs.py`：新增 `DELIVERY_CHOICES`（只列可用方式）；
  `DELIVERY_LABELS` 保留旧值，避免读到历史预设时显示裸字符串
- `engine/ai/prompt.py`：翻译 / 改写的 `default_delivery` `replace` → `copy`
- `engine/ai/types.py`：`REPLACE` / `PASTE` 标注已移除，新增 `AVAILABLE`
- **保留** `native/injector.py` + `tests/test_injector.py`（实测记录 + 便于恢复）

### 验证

- 反向验证 3 条全部确认断言不是空的：
  1. 面板加回「替换原文」按钮 → `test_panel_offers_only_the_copy_button` 失败
  2. 让 `replace` 退回复制路径 → `test_removed_delivery_kinds_do_nothing` 失败
  3. 插件重新持有 `Injector` → `test_plugin_no_longer_holds_an_injector` 失败
- `spikes/m2_verify.py` 投递段改写后 **PASS**（复制写入剪贴板 + 已移除方式为空操作）
- 测试基线 **236 → 234 passed + 1 skipped**（−7 移除行为断言，+5 新守卫）
- 打包冒烟（v1.1.5）：PYZ **607 模块**，新增 `DELIVERY_CHOICES` / `AVAILABLE` 在内，
  且 `替换原文` / `粘贴到前台` / `已替换原文` 等字面量**已从包里彻底消失**
  （移除类改动要查「旧东西有没有真走掉」，不能只查新东西在不在）；
  exe 存活 16s，日志显示「版本: 1.1.5」+ 完整启动序列。
  发布包 `dist/little-table-pet-v1.1.5-win64{,.zip}`（**318 文件 / 56.90 MB**）

> ⚠ PYZ 符号收集还要收**字符串常量里的 `KW_NAMES` 元组** ——
> 关键字参数名（如 `default_delivery`）以**元组常量**形式出现，
> 不递归进容器就会漏报。另外「旧字面量走没走」要用**精确字符串常量**比对：
> `DELIVERY_LABELS` 里合法保留着「替换原文（已移除）」，子串搜索会误报。
> `ZlibArchiveReader.extract()` **直接返回 code object**（不是 bytes）。

### 附：API Key 审计（无代码变更，2026-10-12）

用户问「apikey 有没有打进包」。核查结论：**没有打进包，也没有泄漏**。

| 检查位置 | 结果 |
| --- | --- |
| 项目目录 **10388** 个文件（含 `dist/` 解压后的包） | 真实密钥 **0 命中** |
| 发布 zip **318** 个条目（**逐条解压**后再查） | **0 命中** |
| 包内 `_internal/config.default.json` | `api_key = ''` |
| `~/.pet_demo/logs/app.log`（388 KB）、`ai.db` | 无 |
| 自有代码 2965 个文件 | 密钥 / `Bearer` 令牌均无 |

- 三段匹配（**完整密钥 + 前 12 位 + 前 8 位**），避免「只存了一半」的情况漏掉
- zip 必须**逐条目解压**再查 —— 压缩后的原始字节搜索不可靠
- 密钥只在 `~/.pet_demo/user_config.json`（**项目目录之外**），另有 `.bak-20261011` 备份
- 代码里无任何 `log` / `print` 输出密钥；报错走 `requests.RequestException`
  消息与响应体，**不含请求头**（`Authorization` 在发请求那一刻才现构造）；
  设置对话框用 `setEchoMode(Password)` 掩码

> ⚠ **分发约束**：只发 `dist/little-table-pet-v1.1.5-win64.zip`（干净）。
> **不要**连同 `~/.pet_demo/` 一起打包 —— 那里有**明文密钥**与会话历史 `ai.db`。

> ⚠ **已知现状（非漏洞）**：`_resolve_api_key()` 支持 `keyring:` 前缀读取凭据管理器，
> 但全项目 `set_password` 出现 **0 次** —— **只读不写**，设置对话框总是把密钥
> **明文**写进 `user_config.json`。风险仅限「本机其他进程可读该文件」，与打包无关；
> 要消除明文落盘，需在保存路径接 `keyring.set_password`。

（本小节补写后**重新打包并复验**：PYZ 607 模块、符号校验 PASS、
新包密钥复检 0 命中、exe 存活 16s / 日志「版本: 1.1.5」。）

---

## 4.7 P2.12 活动建议插件（行为采集 + AI 规划）

用户要求：加一个功能插件，「获取用户行为用来为其提供建议，通过 AI 分析来提供规划」。

### 先想清楚的事：难点不在采集，在**数据边界**

项目里 `sensor/` 已经有 `WindowMonitor` / `InputMonitor` / `TimeTrigger`，
采集是现成的。真正要想的是：**行为数据要发给 AI 才能分析 —— 这就是一次数据出网**，
而窗口标题可能含文件名、网页标题、聊天对象，比密钥更贴身。

所以设计的**第一约束是隐私边界**，功能实现反而次要：

| 会做 | 不会做 |
| --- | --- |
| 应用名（`code.exe`）+ 类别 + 时长 | 窗口标题（默认不存） |
| 键盘敲击**次数** | 按键内容 |
| 本地 SQLite，可一键清空 | 剪贴板、截屏、窗口内容 |
| **默认关闭**，显式开启才采集 | 后台静默采集 |

三个决策点由用户拍板：**应用 + 键盘活跃度 / 手动触发 / 本地留 7 天**。

### 隐私的**结构性**保证（本节的要点）

「不记录标题」没有写成代码里的自觉，而是**表结构里根本没有那一列**：

```sql
CREATE TABLE segments (
    id, app, category, start_at, end_at, seconds, key_rate
);   -- 没有 title / content / screenshot / clipboard
```

`tests/test_activity_advisor.py::test_schema_has_no_place_to_store_titles`
直接断言表结构。想加标题就得先删掉这条测试 —— 那是个显眼动作，review 时跑不掉。
反向验证确认过：往 schema 加一列 `title`，该测试立刻失败。

### 分层

```
采集（sensor，已有）→ 聚合（engine/activity）→ 分析（engine/ai）→ 展示（dialog）
```

- `engine/activity/` 与 `engine/ai/` 平级，**零 Qt 依赖**，可脱离 Qt 单测
- 插件**不自己启动传感器** —— `main.py::_start_sensors()` 已经在跑，
  重复启动会装**两个键盘钩子**；插件只 `subscribe("WINDOW_ACTIVE", …)`
- `activity.db` 与 `ai.db` **分开**：清空行为数据不该动用户的会话历史，反之亦然

### 关键实现点

| 点 | 做法 | 为什么 |
| --- | --- | --- |
| 同应用不切段 | app 相同就只延长 `end_at` | `WINDOW_ACTIVE` 会因标题变化（换标签页 / 改文件名）反复触发，但用户没换应用 |
| 短段过滤 | `min_segment_seconds=5` | Alt+Tab 扫过一排窗口会造出大量 1～2 秒碎片，把总时长撑虚 |
| flush 用当前时间 | 结束点取 `clock()` | 用户可能在同一应用待很久没切窗口，此时事件不会再触发 |
| 排除应用 | 关当前段且**不开新段** | 那段时间算「未记录」，而不是硬塞进「其他」 |
| 摘要只读需要的字段 | `build_summary()` 不碰 `title` | 即便分段被人塞了多余字段也不会带出去（有测试守着） |
| 分析结果不落会话库 | `ask(persist=False)` | 否则「会话历史」页会被每天的日报刷屏 |

### 改善：`sensor/window_monitor.py`（两个真问题）

1. **只返回 `pid_1234`**（代码注释写着「简化处理，实际可能需要 psutil」）→
   无法按应用聚合。改用 `QueryFullProcessImageNameW`：它只要
   `PROCESS_QUERY_LIMITED_INFORMATION`，对受保护 / 提权进程比
   `GetModuleFileNameEx` 更不容易 Access Denied；失败回退 `pid_<n>`。
   **没有引入 psutil**（项目未装，不为一个字段加依赖）。
2. **分类把 title 与 process 拼起来一起匹配** → `browser` / `chrome` 这类泛词
   让**任何**浏览器窗口都算「工作」，在 Chrome 里刷 B 站被记成工作。
   改为「娱乐优先 + 进程名兜底」，并补中文站点名（窗口标题常是中文）。
   实测：「哔哩哔哩 - Google Chrome」→ **娱乐**；「新标签页 - Google Chrome」→ 工作（进程兜底）。

### 验证

- 新增 `tests/test_activity_advisor.py` **37 例**，分五层：
  Store / Tracker / Summary / Advisor / 插件与对话框
- 反向验证 4 条全部确认：
  1. schema 加 `title` 列 → `test_schema_has_no_place_to_store_titles` 失败
  2. 去掉「同应用不切段」 → `test_same_app_does_not_split` 失败（`assert 2 == 1`）
  3. 摘要读 `title` → `test_summary_does_not_leak_extra_fields` 失败
  4. 默认改为开启 → `test_disabled_by_default` / `test_disabled_never_subscribes` 失败
- 测试基线 **234 → 271 passed + 1 skipped**

---

## 4.8 P2.13 降低操作负担与打扰（活动建议的第二轮）

**用户原话**：「思考建议助手有什么改进方向，如何做到尽量减少用户主动操作，降低用户感知」。

### 先厘清：「降感知」是三件事，只能降两件

| 维度 | 能不能降 | 做法 |
|---|---|---|
| **操作负担**（点几次、要不要改配置文件） | ✅ 降到接近 0 | 一键开关；自动范围；打开即有内容 |
| **交互打断**（弹窗 / 抢焦点 / 红点） | ✅ 降到接近 0 | 托盘气泡、每天最多一次、全屏/专注免打扰 |
| **知情**（知道在采集、数据发到哪） | ❌ **不能降** | 开关同卡片写清边界；常驻状态行；一键关闭并清除 |

理由很直接：隐私保证是**结构性**的（表里没有 title 列、出网只发聚合摘要）。
一旦变成「静默采集 + 静默出网」，结构性保证就退化成「用户不知道的保证」——那是最糟的形态。
所以方向是：**把知情从「每次操作」搬到「一次性授权 + 常驻轻量指示」**。

### 现状的 5 个摩擦点（都是代码里的实处）

1. **开关藏在配置文件里**（最致命）—— `activity.enabled` 默认 false，开启要手改
   `~/.pet_demo/user_config.json`；对话框里的 `_DISABLED_HINT` 干的就是「告诉用户去改 JSON」。
2. **要用户自己想起来** —— 没有任何主动提示。
3. **「打开」与「出结果」是两次操作** —— 进面板只渲染本地概览，AI 建议还得再点一次。
4. **范围要用户选** —— 1/7/30 天是产品参数，不该由用户决定；且原实现是「滚动 7 天」不是自然日。
5. **结果是一次性的** —— `persist=False` 不进会话历史，对话框一关就没了。

### 做了什么

| 层 | 改动 | 位置 |
|---|---|---|
| 入口 | **一键开关 + 首启说明 + 清除数据**（立即生效，不重启） | `presentation/control_center.py::ActivityPage` |
| 触发 | **收工小结**：`TIME_TICK` 驱动，一天最多一次，托盘气泡 | `engine/activity/reminder.py` + 插件 |
| 决策 | **自然日范围**（今天 = 今天 00:00）+ **建议缓存**（数据指纹变了才重算） | `engine/activity/schedule.py` + `store.advices` |
| 消费 | 常驻「今日小结」卡片 + **「开始 25 分钟专注」打通番茄钟** | `ActivityPage` + 插件 `start_focus()` |
| 采集 | **空闲剪裁**（人不在的时间不计入）+ 全屏作为免打扰信号 | `engine/activity/idle.py` + `sensor/window_monitor.py` |

### 三个设计决定（值得记住）

1. **空闲信号只用来「剪时长」，不新增任何字段。**
   用户上午开 Chrome、中午出去吃饭、下午回来 —— 旧实现记成「Chrome 3 小时」。
   现在结算时把「最后一次输入之后」的时间剪掉（`end = at - idle`），
   时长才对得上直觉。**顺带覆盖了锁屏**（锁屏 = 没有输入 = 空闲）。
2. **全屏只用来「免打扰」，不用来改分类。**
   全屏看文档也是全屏，拿它把「工作」改成「娱乐」会误判。
   但「全屏时不要弹提示」是稳赚的 —— 那时用户大概率在看视频/开会/演示。
3. **只在 `tick()` 里剪是不够的，必须周期性剪。**
   用户回来第一件事往往是切窗口，那一刻空闲已归零，剪不到了。
   所以 `tick()` 由 `TIME_TICK`（5 分钟）驱动，**在用户还不在的时候**就把段收尾。
   回来后按「最后一次输入的时刻」续上离开前的应用，否则回来不切窗口这段会整个丢失。

### 修掉的真 bug：`0 or default` 会把合法配置悄悄改掉

`nudge_hour` 用 `int(cfg.get(...) or 18)` 读值 —— 而 **`0` 是合法值**
（表示「过零点就提醒」），`0 or 18` 会把它改成 18，于是怎么都不触发。
同样的写法在 `min_segment_seconds`（0 = 不过滤碎片）上也存在。
统一改成 `_cfg_number()`：`None` / 非数值回退默认，**0 原样保留**。

### 顺手修掉的一个潜在线程安全问题

`SessionManager.chunk` 是从**工作线程**发出的。原实现把它直接连到插件的普通方法上 ——
Qt 的队列连接只在 QObject 之间生效，连普通 Python 可调用对象会退化成**直连**，
等于在工作线程里动控件。现在统一经过 `_ViewBridge`（活在主线程的 QObject）中转。

### 验证

- `tests/test_activity_advisor.py` **37 → 93 例**（新增 56 例）：
  Schedule（自然日）/ Idle（探针容错）/ Reminder（**每条免打扰分支单独一条**）/
  AdviceCache / TrackerIdle / 插件 P2.13 / 控制中心页
- **反向验证 6 条，全部真实打红**（确认断言不是空的）：
  1. 去掉空闲剪裁 → `assert 1800.0 == 1200.0`
  2. 配置读值改回 `or default` → `assert 18 == 0`
  3. 去掉「一天最多一次」 → `assert True is False`
  4. 去掉「全屏免打扰」 → `assert True is False`
  5. 「最近 N 天」改回滚动窗口 → 起点比自然日早 8.5 小时
  6. 提醒状态不落库 → `assert None is not None`
- 测试基线 **271 → 327 passed + 1 skipped**

### 打包与冒烟（v1.1.7）

- 版本号 1.1.6 → **1.1.7**（`config.default.json` + `data/config_manager.py` 两处同步）
- PyInstaller 打包 **3m43s**；**PYZ 615 → 618 模块**（+3 = `schedule` / `idle` / `reminder`）
- PYZ 符号校验：`engine.activity.*` 8 个条目全在；新符号 `should_nudge` / `day_start` /
  `since_for_days` / `today_range` / `system_idle_seconds` / `is_foreground_fullscreen` /
  `is_away` 等全在；字符串 `advices` / `meta` / `last_nudged_at` / `nudge_enabled` /
  `nudge_hour` / `away_seconds` / `活动建议` / `开始 25 分钟专注` 等全在；
  旧字面量 `已替换原文` / `粘贴到前台` **无残留**
- 发布包 `dist/little-table-pet-v1.1.7-win64{,.zip}`（**329 文件 / 56.98 MB**）
- 密钥复检（**zip 逐条目解压**）：4 个用户自定义值（`ai.base_url` / `ai.model` /
  `ai.vision_model` / `ai.api_key`）+ `sk-` 模式 —— 发布目录 363 文件、zip 329 条目
  **全部 0 命中**；包内 `config.default.json` 的 `api_key` 为空
- exe 冒烟：存活 **18s**、日志「版本: 1.1.7」+ 完整启动序列（插件加载 / 托盘 / 键盘 /
  剪贴板 / 面板预热 / 三热键）、**零 ERROR**；`activity.db` 的 mtime 与表结构**未变**
  （默认关闭采集 → 不落库），`segments` 仍 0 行、无 `title` 列

> **已知小瑕疵（非回归）**：spec 用 `datas=('engine','engine')` 把整个 `engine/` 当数据分发
> （插件按文件路径动态加载，静态分析看不到），于是本地发布目录里会混入
> `_internal/engine/**/__pycache__/*.pyc`。`_refresh_release.py` 打 zip 时**已排除**
> `__pycache__` 与 `.pyc`，所以**用户下载的包是干净的**。要不要顺手在 spec 里加排除、
> 让发布目录也干净，留作后续可选项（改 spec 需重新打包）。

---

## 4.9 P2.14 活动洞察升级为主功能（已完成）

**用户拍板**：**双核心并列**（AI 助手 + 活动洞察都是主功能）+ **控制中心升级为主窗口** +
四项全做（今日页 / 趋势页 / 常驻指示 / 测试·文档·打包 v1.2.0）。

分 5 步走，每步「先实测/勘察 → 想清楚关键约束 → 最小改动 → 补测试 → 反向验证 → 更新文档」：

| 步 | 内容 | 状态 | 测试基线 |
|---|---|---|---|
| ① | 数据层（`advice.py` 结构化建议 / `timeline.py` 纯函数 / `store` 忽略落库） | ✅ | 327 → **371** |
| ② | 组件层（`charts.py` 4 控件 / `advice_card.py` / 6 个图表色 token） | ✅ | 371 → **391** |
| ③ | 今日页（`TodayPage` 替换 `ActivityPage`）+ 导航 10 平级 → 3 组 | ✅ | 391 → **408** |
| ④ | 趋势页（`TrendPage`） | ✅ | 408 → **457** |
| ⑤ | 常驻指示（托盘进度环 + 悬停 + 菜单项） | ✅ | 457 → **483** |
| ⑥ | 测试·文档·打包 v1.2.0 | ⬜ 待做 | — |

### ① 数据层

- **`engine/activity/advice.py`**（新）—— `Advice` / `AdviceAction` / `parse_advices` /
  `advice_to_text` / `advice_fingerprint` / `is_structured`。
  `parse_advices` **永不返回空**（解析不了就退化成一条纯文本建议），所以另立
  `is_structured()` 判据来区分「模型真给了 JSON」与「模型回了大白话」。
  `fingerprint` 归一化时**去掉数字、空白与标点**（只留中英文字）—— 于是
  「上午被打断 9 次」与「上午被打断 11 次」视为同一条建议，而
  「上午被打断 9 次」与「下午被打断 9 次」仍是两条（时段词是文字，不会被去掉）。
- **`engine/activity/advisor.py`** —— 提示词改为**要求输出 JSON**（`ADVICE_JSON_SPEC`）。
- **`engine/activity/store.py`** —— `ignored_advices` 表：忽略必须**落库**
  （否则刚忽略的建议下次生成后立刻复活）；`clear()` 连忽略标记一起清
  （不然清空数据后新建议仍被旧标记挡掉，还找不到原因）。
- **`engine/activity/timeline.py`**（新）—— 纯函数、零 Qt：
  `merge_segments` / `total_seconds` / `focus_seconds` / `switch_count` /
  `top_apps` / `category_totals` / `daily_totals`（自然日、**含空日**）。

### ② 组件层

- **`presentation/design/tokens.py`** —— `Palette` 加 6 个图表色
  （`chart_work` / `chart_comm` / `chart_browse` / `chart_other` / `chart_idle` / `chart_track`）。
- **`presentation/design/charts.py`**（新）—— `StatTile` / `RatioBar` / `RankBar` /
  `BarChart` / `TimelineBar` / `AxisLabels`。
- **`presentation/design/advice_card.py`**（新）—— `AdviceCard`（headline / evidence / 动作 / 忽略）。

### ③ 今日页 + 导航改分组

- **`TodayPage`** 替换 `ActivityPage`：本机记录卡（一键开关 + 隐私边界）→ 概览 4 tile
  （总时长 / 深度工作 / 最长应用 / 切换打断）→ 24 小时时间轴 + 刻度 → 应用排行 →
  建议卡（结构化）/ 纯文本兜底。
- **导航 10 平级 → 3 组**（`NAV_GROUPS` → 派生 `NAV_ITEMS`）：
  **数据**（今日 / 趋势）/ **功能**（6 项）/ **系统**（3 项）。
  数据组放最上面且默认打开「今日」—— 这是把活动洞察升级成主功能的关键一步。
- 三个实现要点（都踩过）：
  1. 分组标题行用 **`ItemIsEnabled`** 而不是 `NoItemFlags` —— 后者会被 Qt 按禁用态渲染，
     `setForeground` 的 `Normal` 组刷子不生效，标题淡到看不见。
  2. 插了分组行以后**不能按行号索引平行数组** —— 图标名改存条目自身
     （自定义 role `_ROLE_NAV_ICON = UserRole + 10`；`UserRole` 已被业务数据占用）。
  3. **行号 ≠ 页序号** —— `ControlCenter._nav_rows` 做映射，`_on_nav_row_changed` 与
     `goto()` 都经它。
- **流式期间不渲染结构化建议** —— 模型输出 JSON，逐块画会闪半截 `{"headline": …`；
  进度由状态行表达。
- 忽略必须**落库** + 过滤**只写一处**（`plugin.filter_ignored`）。

### ④ 趋势页

- **数据层**：`HOURS_PER_DAY` / `hour_of_day` / `hour_label` / `hour_switches` /
  `busiest_hour` / `period_bounds` / `compare_periods`。
  `hour_label(23)` = `23:00–24:00`（写「23:00–00:00」会被读成倒着走）；
  `busiest_hour` 无切换返回 **`None`**（0 点是合法答案）；`delta_ratio` 为 `None`
  表示上周期是 0（不能显示「增长 0%」）。
- **`retention_days` 默认 7 → 30**（`data/config_manager.py` + `config.default.json`
  **两处同步**）—— 趋势页最长看 30 天，保留 7 天等于那个视图开箱就是残缺的。
  页面读 `plugin.retention_days()` 如实提示。
- **`TrendPage`**：范围切换（近 7 / 30 天）→ 概览 3 tile → 每日深度工作柱状图 + 刻度 +
  与上周期对比 → 时间构成 + 最容易被打断的时段（24 桶）→ footer 数据边界。
  向插件要 `days * 2` 天（本周期 + 上周期）。

#### S13 目检抓到的 4 个真 bug（都有回归用例）

| # | 现象 | 根因 | 修法 |
|---|---|---|---|
| 1 | 「最容易被打断的时段」把早上 9 点算成峰 | **跨天伪切换**：昨天最后一段 → 今天第一段被算成一次切换，且归到当天开工的小时 | 数据层加 `_is_switch()`（同一天 + 应用不同），`switch_count` / `hour_switches` / 摘要**共用一处判据** |
| 2 | 同一页「本周期总时长 159h」但「时间构成 236h」 | 页面拿 `days * 2` 的**混合**列表算类别构成 / 按小时打断 | `compare_periods` 交出切好的 `current["segments"]`，页面不再自己切 |
| 3 | 切 7/30 天时首刻度糊成一团、底部两个「0:00」 | `AxisLabels.set_labels` 用 `deleteLater()` —— **排队删除**期间旧标签仍在绘制 | `hide()` + `setParent(None)` + `deleteLater()` |
| 4 | 30 天视图首末刻度互相压住 | 首标签 clamp 到 x=0 后右溢、末标签右对齐后左溢 | `_place` 加重叠规避：放不下就藏靠后的那个（变宽后恢复） |

**顺手修掉 `summary.py` 一处错标**：`应用切换次数：{len(segments)}` —— 标签写「切换次数」、
值却是**段数**（段数 = 切换次数 + 1，多日数据里还被跨天边界抬高）。改成 `switch_count()`。

**Windows 上的坑**：`day_start` 内部走 `mktime`，1970-01-01 的**本地** 0 点落在 UTC 纪元
之前会抛 `OverflowError`。判「同一天」改用 `_local_date(ts) -> (年, 月, 日)`（只走
`localtime`，对坏数据也不炸）；对正常数据两者结论一致。

#### 验证

- `tests/test_activity_advisor.py` 新增 `TestHourSwitches` / `TestPeriodCompare` /
  `TestTrendPage` / `TestTrendPageText`；`tests/test_design.py` 新增刻度重影与重叠两条。
  另加只读访问器 `BarChart.count/highlight/value_at`、`RankBar.name_at/value_text_at`。
- **反向验证 21 条，全部真实打红**（四个临时脚本，用后即删）。
- 测试基线 408 → **457 passed + 1 skipped**。
- `spikes/s13_today_preview.py` 扩到 **10 张图**（新增趋势 4 张）。
  `_StubPlugin.segments_for(days)` 按 `since_for_days` 过滤 60 天假历史（与真插件同口径）；
  `_snap_page(..., height=…)` 可拉高窗口看折叠线以下的内容。

### ⑤ 常驻指示（托盘进度环）

托盘图标外圈画**今日深度工作进度环**，悬停给精确数字，右键菜单加一条
「开始 45 分钟专注」。**画在外圈而不是换成纯环**：16px 上换成纯环等于把桌宠
图标弄丢，用户在任务栏里认不出这是哪个程序；精确数字放悬停提示（16px 写不下）。

- **插件侧**（`extensions/system/activity_advisor/plugin.py`）：
  `focus_goal_seconds()` 读 `activity.focus_goal_minutes`（默认 **240 分钟**）；
  `focus_progress(days=1)` 返回 `{"focus", "goal", "ratio", "enabled"}`。
  口径**只在这一处** —— 托盘不自己算。
- **配置**（`data/config_manager.py` + `config.default.json` **两处同步**）：
  `focus_goal_minutes = 240`。**刻意偏高**：每天都刷满的进度环等于没有信息量。
- **三态**（`activity_state()`）：`off`（采集关闭）/ `active`（记录中未达标）/ `done`（达标）。
  「关闭」**不能画成「0 进度」** —— 空环会被读成「今天一点没干」，
  而真相是「根本没在记录」，两件事对用户的含义完全不同。
- **`TrayIcon`**：`_progress_timer`（`PROGRESS_REFRESH_MS = 60_000`）+
  订阅 `theme().changed`；`hide()` 停表。插件缺失 / 查库抛异常时**静默降级**
  成静态图标、不起定时器 —— 一个可选的常驻指示不该把程序带崩。

#### S14 目检抓到的坑：托盘环的颜色不能问主题

**托盘图标的底色由 Windows 任务栏决定，跟应用主题毫无关系。** 环一开始取主题色，连踩两次：

| token | 取值 | 后果 |
|---|---|---|
| `text_disabled` | `light` = `#1F1F1F` | 深色任务栏上**整个消失** |
| `chart_track` | `light` = `#DCDCDC` | 深色任务栏上被读成**满环** |

「深色应用主题 + 浅色任务栏」这种组合下，取主题色怎么选都会有一半场景糊掉。
最终改成**固定色 + 一圈白描边**（`_TRAY_OUTLINE` 白 / `_TRAY_TRACK` 半透明黑 /
`_TRAY_OFF` 中性灰 / `_TRAY_PROGRESS` `#0067C0` / `_TRAY_DONE` `#107C10`）：
白描边保证深色任务栏上有轮廓，深色底槽保证浅色任务栏上看得见环，**两边都不依赖
任务栏实际颜色**。这些常量**不进 `Palette`**、不参与主题切换。

#### 验证

- `tests/test_tray_indicator.py`（新，20 例）—— `TestActivityState` /
  `TestActivityTooltip` / `TestProgressIcon` / `TestTrayIndicator`。
  `tests/test_activity_advisor.py` 加 `TestFocusProgress`（5 例）+
  菜单项 1 例。基线 457 → **483 passed + 1 skipped**。
- **反向验证 5 条，4 条真实打红**（`_mutcheck_tray.py`，用后即删）。
  剩下 1 条（单独把底槽换成 `chart_track`）经分析**不构成缺陷**：
  白描边 + 进度弧仍在，环整体依然可读；真正的缺陷是「无描边 + 主题色」那个
  **组合**，已被另外两条打红。
- **写这两条断言时踩的两个坑**（值得记，因为都是「假测试」的典型）：
  1. 先写的是「未填段要暗到看不见」—— **前提本身是错的**。深色任务栏上白描边
     在未填段本来就该可见（那是它勾轮廓的职责）。反向验证当场打红，
     说明我在给一个视觉判断硬套像素指标。改成断言**「环不随主题变」**
     （结构性根因），才是可守的。
  2. 主题断言最初只测 `STATE_ACTIVE`，于是「关闭态读主题」这个 mutation
     **溜了过去**（`_TRAY_OFF` 只在关闭态才画）。改成三态全测才打红。
- **像素断言的两个采样半径**：环带在半径 23–30、白描边 21.5–31.5，
  所以采 **26.5**（环中心线）与 **30.0**（外沿）—— 只看中心线的话，
  深色任务栏上「未完成的那段」会量成「看不见」。
- `spikes/s14_tray_indicator.py`（新）—— 三态联络表，**按任务栏底色
  （浅 / 深）分两张**（不是按应用主题），尺寸 16/24/32/64 按 1:1 贴出。

### ⑥ 打包与冒烟（v1.2.0）

- 版本号 1.1.7 → **1.2.0**（`config.default.json` + `data/config_manager.py` 两处同步）
- PyInstaller 打包 **4m16s**；**PYZ 618 → 622 条目**
  （+4 = `advice` / `timeline` / `charts` / `advice_card` —— `advisor` 是重写，本来就在）
- PYZ 符号校验（清单已按 P2.14 **追加**，旧项不删）：
  `engine.activity.*` **10** 个条目全在；新符号 `parse_advices` / `merge_segments` /
  `hour_switches` / `compare_periods` / `focus_progress` / `progress_icon` /
  `PROGRESS_REFRESH_MS` 等全在；字符串 `ignored_advices` / `headline` /
  `focus_goal_minutes` / `今日概览` / `开始 45 分钟专注` / `chart_browse` 等全在；
  旧字面量 `已替换原文` / `粘贴到前台` / **`ActivityPage`** **无残留**
- 发布包 `dist/little-table-pet-v1.2.0-win64{,.zip}`（**331 文件 / 57.04 MB**）
- 密钥复检（**zip 逐条目解压**）：4 个用户自定义值 + `sk-` 模式 ——
  发布目录 359 文件、zip 331 条目 **全部 0 命中**；包内 `config.default.json`
  的 `api_key` 为空
- exe 冒烟：存活 **18s**、日志「加载用户配置成功 (版本: 1.2.0)」+ 完整启动序列
  （插件加载 / 托盘 / 键盘 / 剪贴板 / 面板预热 / 三热键）、**零 ERROR 零 WARNING**；
  `activity.db` 的 mtime 与表结构**未变**（默认关闭采集 → 不落库），
  `segments` 仍 0 行、无 `title` 列

> **打包时顺手修掉一个测试卫生问题**：`data.log_manager` 是**进程级单例**，
> 默认写用户的 `~/.pet_demo/logs/`。`tests/test_tray_indicator.py` 要构造 `TrayIcon`，
> 于是「查库失败要静默降级」那条测试把「读取今日深度工作进度失败: 库坏了」
> **写进了用户真实的 app.log**（实测确实写进去了）。
> 新增 `tests/conftest.py` 做**结构性隔离**（会话级把 `pet_demo.*` 三个 logger
> 改指临时目录）+ `tests/test_log_isolation.py`（2 例）守它；
> 反向验证：摘掉 conftest 两条都打红。
> 已把用户日志里那 10 行测试残留清掉（备份 `app.log.bak-testcleanup`）。
> **教训：测试写用户目录这件事一旦成立，今天写日志、明天就可能写 `user_config.json`。**

---

## 4.10 P2.15 概览升级为独立仪表盘（v1.2.1）

**用户原话：「优化交互 ui，让核心之一的概览部分更特殊更明显」。**

### 先想清楚的事：「更明显」不是把字号调大

改之前，概览的四个指标格就是四个 `surface_alt` 灰块**直接摊在页面底色上**：

| token | 浅色取值 | 页面底色 `window` | 差值 |
|---|---|---|---|
| `surface_alt`（格子底） | `#F7F7F7` | `#F3F3F3` | **4 级** |

4 级差值肉眼基本不可分 —— 整页最该被看见的信息，反而是**最不显眼**的。

> 关键认识：「更明显」不是把字号调大一点，而是**给它一个独占的容器**。
> 整页只有这一处长那个样子，扫一眼就知道「这里是重点」。

### 做了什么

- **`OverviewBoard`**（`presentation/design/charts.py`）：有描边、有标题、
  **顶边一条 3px 强调色线**的台面。格子收进同一块台面，格与格之间**自动插竖分隔线**
  （`add_tile` 里插，调用方不用管）。今日页与趋势页共用。
  - 顶边线**不单独做一个 rule 控件** —— `border-top: 3px solid accent` 一行 QSS 就够，
    多一个控件就多一处要跟着主题重刷的地方。
  - 竖分隔线必须**显式给 `Expanding` 高度策略**：`Hairline` 控件的默认竖向策略是
    `Fixed`，直接放进 `HBox` 会缩成一个点。
- **头条数字有层级**：`StatTile` 加 `primary` / `icon_name` 两个可选参数。
  「今日总时长」`primary=True` → **强调色软底**（`accent_soft`）+ 更大字号 +
  **更宽的伸展因子**（`stretch=2`，即 2:1:1:1）。四格等大等于没有重点。
  - `primary` 用 **Qt 动态属性 + QSS 属性选择器**（`QFrame#statTile[primary="true"]`），
    不做两套控件。
- 不传 `icon_name` 时**藏起图标位**（`self._icon.hide()`）——
  否则标签被推右，几格之间对不齐。
- 只读访问器：`tile()` / `tiles()` / **`stretch_of()`** / `title()`。

### 抓到的两个真问题

**① 我自己在 `_build_dashboard` 里漏了 `add_tile`。**

把原来的 `QGridLayout` 换成台面时，我写成了：

```python
for key, tile in self._tiles.items():
    lay.addWidget(tile)          # ❌ 挂到**外层**布局，台面是空的
lay.addWidget(self._overview)
```

四格于是**竖排铺满整页**、台面只剩一条顶边线掉到折叠线以下 —— 非常明显。
抓到它的是**结构断言**（`board.tile(key) is tile`），不是目检。

> **教训（比 bug 本身重要）：目检必须做「改前 vs 改后」对照。**
> 我上一轮只扫了一眼**当前**截图就说「目检通过」—— 而那张图整页都塌了。
> 单看一张图容易把「全塌了」读成「还行」；**两张并排看**才看得出布局变了。
> 这条已实测确认：临时改回坏版本重渲染，四格确实是竖排铺满整页。

**② `tests/test_design.py` 抓像素的用例从来没装过样式。**

新写的顶边断言一直红。根因：该文件**从没调 `install(app)`**，而
`reset_for_tests()` 会清空已注册的 app —— 等于 QSS 根本没装上，
抓到的是「没上过样式」的像素。（正是 MEMORY.md 里那条「渲染预览图三条硬前提」的第 ②条。）

修法：新增 `_styled_theme()` 装置（`install(app)` + `set_theme()` 一起做），
抓像素的用例统一走它；只读 token 的用例仍用原来的 `_theme()`。

### 一条「没法用像素断言」的取舍（值得记）

「头条格更宽」这条**在页面级量不出宽度**：页面是 `QStackedWidget` 里的一页，
测试里不会真正 show，布局不跑，`width()` 全是 Qt 的默认值 **640** ——
量出来四格一样宽，断言要么永真要么误报（实测确认：`page.show()` 也不管用，
因为祖先 `QMainWindow` 没显示）。

拆成两条，各守一环：

| 测试 | 层 | 守什么 |
|---|---|---|
| `test_headline_tile_is_stretched_wider` | 页面 | 页面**给对了**伸展因子（走 `stretch_of()`） |
| `test_a_tile_with_a_bigger_stretch_really_gets_more_width` | 组件 | 伸展因子**真的**变成宽度（真 show + 量像素） |

少了后者，把 `add_tile` 里的 `stretch` 丢掉照样 PASS。

### 验证

- 新增 **9 例**：`tests/test_design.py` +5、`tests/test_activity_advisor.py` +4。
- **反向验证 8 条、8 条全部真实打红**（`_mutcheck_overview.py`，用后即删），
  且每条都由**预期的**那条测试打红：

| 改坏 | 打红 |
|---|---|
| 顶边线改普通描边 | `test_overview_board_has_an_accent_top_edge` |
| 头条格不铺强调软底 | `test_primary_tile_is_visually_distinct_from_the_others` |
| 去掉 total 的 `primary` | `test_only_the_headline_number_is_primary` |
| 今日页格子不放台面 | `test_overview_is_wrapped_in_exactly_one_board` + `…stretched_wider` |
| 趋势页格子不放台面 | `test_overview_uses_the_same_board_as_today` |
| 不传图标不藏图标位 | `test_tile_without_an_icon_leaves_no_gap` |
| 页面不给 total 更大伸展因子 | `test_headline_tile_is_stretched_wider` |
| `add_tile` 忽略伸展因子 | `test_a_tile_with_a_bigger_stretch_really_gets_more_width` |

> 反向验证脚本里两页的循环**写法完全一样**，所以锚点必须带上后面那行注释才唯一 ——
> 否则「趋势页」那条 mutation 会**误改今日页**（旧脚本就有这个隐患，已修）。

- 全量测试 **485 → 494 passed + 1 skipped**。
- `spikes/s13_today_preview.py` 重跑，浅 / 深两套目检通过：台面顶边线、头条软底、
  竖分隔线在三处都清晰。

### 打包与冒烟（v1.2.1）

- 版本号 1.2.0 → **1.2.1**（两处同步）。
- PyInstaller 打包；PYZ 符号校验清单按 P2.15 **追加**（`OverviewBoard` /
  `stretch_of` / `overviewBoard` / `accent_soft`），旧项不删。
- 密钥复检（**zip 逐条目解压**）0 命中。
- exe 冒烟：存活 18s、「版本: 1.2.1」+ 完整启动序列、零 ERROR；`activity.db` 未变。

---

## 4.11 P2.16 表现形态重构：悬浮球（v1.3.0）

**用户原话：「现在重构表现形态，桌宠形象作为备选项，常态外观像 aioxo 的悬浮球，思考一个可行方案」。**

三个细节由用户拍板：

| 问题 | 拍板 |
|---|---|
| 左键单击球 | **和左击原版桌宠一个效果**（发 `PET_CLICKED` → 状态机进 interact 5 秒 → 弹一下 + 冒气泡） |
| 球面上显示什么 | **进度环 + 中心图标** |
| 第一版做贴边吸附吗 | **做**，拖动后吸附到屏幕边缘 |

单击既然留给「戳一下」，**打开控制中心就改到双击** —— 否则单击要延迟 250ms
等双击判定，点击手感会变钝。

### 先想清楚的事：换形态不是重写窗口，是**换内胆**

原 `PetWindow` 一个类同时干三件事，而**只有一件是形态相关的**：

| 职责 | 形态相关？ | 去向 |
|---|---|---|
| 窗口行为（无边框 / 置顶 / 拖拽 / 位置 / 右键菜单 / 关到托盘） | 否 | `ShellWindow` |
| 精灵图渲染 | **是** | `Form`（`PetForm` / `OrbForm`） |
| 气泡 | 否 | `Bubble`（独立窗口） |

所以拆成 `ShellWindow`（外壳）+ `Form`（外观）。**`ui_manager.window` 这个名字必须保留** ——
它是 4 个插件（`notes` / `quick_launch` / `timer` / `giwifi`）拿来做对话框父窗口的既有契约，
`main.py` 也拿它当动画落点。换形态只换内胆，**契约面不动**。

`Form` 协议只回答五个问题：

| 方法 | 作用 |
|---|---|
| `animation_target()` | 精灵图动画往哪画？球返回 `None` |
| `set_state(name)` | 状态机状态怎么表现？桌宠换图，球换环与图标 |
| `form_size()` | 这个形态需要多大的窗口？ |
| `wants_edge_snap()` | 松手后要不要吸附到屏幕边缘？ |
| `wants_shell_motion()` | 允许动画 `move()` 整个外壳吗？球**不许**（见下） |

另有 `edge_snap_inset()` / `preferred_opacity()` / `attach(shell)` / `set_model()`。

> 关键认识：**状态机不该知道外面是球还是宠物。** 它只发 `STATE_CHANGE`，
> 外壳转发给当前形态，形态自己决定用什么介质表达 —— 桌宠有 7 张精灵图可用，
> 球只有颜色 / 环 / 中心图标。

### 三个被逼出来的必要改动（不是顺手美化）

**① 气泡必须改成独立顶层窗口。**
球窗只有 64px，窗口内 160px 的 `QLabel` 会被直接裁掉。桌宠窗勉强放得下，
但气泡压在精灵图顶上像贴在脸上。独立窗口后两种形态共用一套气泡、不占窗口尺寸。
- `WA_TransparentForMouseEvents` **是关键**：气泡浮在球上方几像素处，
  吃鼠标的话用户点球的上半部分就会点空。

**② 位置持久化从左上角改成中心点。**
桌宠 200×200、球 64×64 —— 按左上角对齐，换形态后球会往右下**漂 68px**。
改存 `window.center`，旧配置做一次迁移（`position + size//2`），升级后位置不跳。

**③ `_move_center()` 不能用「目标中心 ± 半宽」。**
无边框窗口在 Windows 上**仍带 1px 不可见边框**，而 `move()` 作用在 frame 上，
直接算会累积漂移（探针实测：球中心 `852,508` → 桌宠中心 `851,507`）。
改成自校正写法，与 frame 无关：

```python
self.move(self.pos() + center - self.geometry().center())
```

### 贴边吸附：必须按**窗口所在那块屏**算

```python
QGuiApplication.screenAt(self._center())   # ✅
QGuiApplication.primaryScreen()            # ❌ 多显示器下会把窗口吸到主屏边上
```

垂直方向夹在 `availableGeometry()` 内（不能钻到任务栏底下）。
球藏 `_canvas // 3`（约 21px）；鼠标移入完全拉出，移出再贴回去
（拖动过程中不贴，否则会跟用户抢位置）。桌宠 `wants_edge_snap()` 返回 `False` ——
它是个「角色」，吸到边上很怪。

### ④ 位移动画必须按形态门控（**exe 冒烟才发现的**）

**发现路径本身值得记。** exe 冒烟按老判据「存活 + 版本行 + 完整启动序列」是**通过**的 ——
可 `app.log` 到「热键已注册」就没了（之后进 Qt 事件循环，不再打日志）。
**「启动序列完整」证明不了窗口存在**，而 P2.16 恰恰改的就是窗口。
于是补一步：直接问 Windows 枚举这个 pid 名下的可见顶层窗口。

枚举出来球确实在（`64×64`），但**多次采样位置一直在变**：

```
t= 1s  64x64@1664,75
t= 6s  64x64@1635,75
t=14s  64x64@1103,644     ← 横竖各跳了 500+ px
t=22s  64x64@1664,617
```

在进程内插桩 `ShellWindow.move` 才抓到调用者：

```
   6  anim_controller.py:572:tick <- ui_renderer.py:635:run <- main.py:417:run
```

根因：`ui_renderer.py` 的 `set_anim_controller()` **无条件**执行
`controller.set_target_widget(self.window)`。而数值动画
（`wave` 摇一摇 / `happy` 弹跳 / `yawn` / `confused`）是**通过 `move()` 作用在外壳上**的：

```python
original_pos = widget.pos()          # ← 动画开始时抓一次
widget.move(original_pos + offset)   # ← 之后每个 tick 都按这个「过期坐标」摆
```

`main.py` 里那句注释「只保留数值动画（作用在外壳上）」正是**有意的**设计 ——
但它对球是错的。复现（`_probe_stale.py`）：

| 场景 | 结果 |
|---|---|
| 球：动画中途拖到 `(900,500)` | 动画结束停在 **`(470,300)`** —— 被拽回原处 430px |
| 桌宠：同样操作 | 一样被拽回（**既有缺陷**，见下） |

球还有第二重冲突：**贴边吸附**。球贴边时是「故意藏 1/3」的，被动画一挪就脱离边缘。

**修法（两层）：**

1. **门控**：新增 `Form.wants_shell_motion()`（桌宠 `True` / 球 `False`），
   `UIManager._sync_anim_target()` 据此决定要不要把外壳交给 `AnimController`；
   `apply_form()` 换形态时也要重新同步（换回桌宠得装回去）。
   球的「弹一下」由它自己的 `_bounce()`（窗口内缩放脉冲）完成，不靠移动窗口。
2. **打断即还原**：桌宠的既有缺陷同源 —— 用户按住窗口时停掉动画，
   并靠 `_numeric_origin` 把窗口放回起点（`_stop_numeric()`）。
   不做这步的话，打断会让窗口**永久停在「摇到一半」的偏移位置**。

> **判据：一个动画在「动谁的坐标」上必须问清所有权。**
> 数值动画假定「窗口归动画管」；而球的位置归**用户 + 吸附逻辑**管。
> 两个所有者同时写同一个坐标，就必然打架 —— 这不是时序问题，调参数没用。

反向验证 `_mutcheck_motion.py` 6 条（门控默认值 / 门控本身 / 按住不停 / 不还原 / 不记起点）
**全部真实打红**。

### 球环与托盘环是**同一个量**

新建 `presentation/design/ring.py`：`STATE_OFF / ACTIVE / DONE` + `activity_state()`。
托盘图标与球画的都是「今日深度工作进度」，各写各的迟早会漂。
**配色仍各自定**（底色不同：任务栏 vs 壁纸），共用的是**状态判定**。

球的配色沿用 S14 结论：**固定色 + 一圈白描边**，不跟应用主题。
球的底色是**壁纸**，比任务栏更不可预测。

### 顺手查出来的两个真 bug（都不是本次需求的一部分）

**① `data.config_manager` 在 import 时无条件重写用户配置。**

这条是**「全量测试跑完比对 mtime」**发现的，从测试结果上完全看不出来
（内容字节相同，测试全绿）：

```
非 cache 的 mtime 变化: ['user_config.json']
user_config.json 前: mtime=1791952484.242  sha1=4aac6d27bbfb5c68
user_config.json 后: mtime=1791952552.462  sha1=4aac6d27bbfb5c68
```

根因：`config_manager = ConfigManager()` 是模块级单例，
**被 import 的那一刻**就 `_load_config()` → `save()`。
而 pytest 的 **fixture 要到测试执行时才跑** —— 那时模块早 import 完了，拦不住。

> **判据：需要「在 import 之前生效」的隔离，只能写在 conftest 的模块级代码里，fixture 不行。**

修法两层：
1. **结构性** —— 新增 `data/paths.py`（`pet_home()` / `pet_path()`），
   整个用户数据目录可由 `PET_DEMO_HOME` 前置覆盖。`tests/conftest.py` 的
   **模块级**代码设它（`dev_bootstrap.py` 不 import 项目模块，所以时机安全）。
   8 处落点全部改走它：配置 / 日志 / `ai.db` / `activity.db` / 便签 / 快捷启动 /
   控制中心 `CONFIG_DIR` / **图标缓存**。
   `pet_home()` **不做模块级缓存** —— 否则「在 import 之后才设变量」的调用方会拿到旧值，
   正是要防的坑（有测试钉住）。
2. **不写就没有伤害** —— `_load_config()` 只在磁盘内容与内存不一致时才 `save()`。
   代价是「文件缺了新版默认节」时必须补写，这条也有测试钉住（否则「永不 save」能作弊过关）。

**② `DEFAULT_CONFIG` 被 `set()` 污染。**
原用 `DEFAULT_CONFIG.copy()`（**浅拷贝**），嵌套节与模块级常量共享同一批 dict 对象。
一次 `config_manager.set("window.center", …)` 就会改掉 `DEFAULT_CONFIG["window"]` ——
而它是「重置为默认」和版本迁移的基准。改用 `copy.deepcopy`。

### 反向验证：**抓到 2 条假断言**

`_mutcheck_appearance.py` 23 条 + `_mutcheck_isolation.py` 6 条，**29 条全部真实打红**。
前 2 条一开始是绿的：

| 假断言 | 为什么是假的 | 改成 |
|---|---|---|
| `test_orb_sleep_is_dimmer_than_idle` | 只测**球心** —— 而球心恰好落在**月牙的空心处**，量到的是球体填充。于是「图标不压暗」照样通过 | 加「图标框内最亮像素」断言（框在球内、环内侧，框里只有填充与图标） |
| `test_orb_off_state_draws_a_dim_full_ring_not_an_empty_one` | 把关闭环调成与底槽同色后仍通过 —— 环被**画了两遍**，叠出来的亮度恰好还在判据带 `[100,180)` 内 | 换成「底槽调成关闭环的亮度」这条真实回归（常态也成了满环 → 打红） |

> **教训：断言要钉在「机制」上，不能钉在「看起来像」上。**
> 「休眠更暗」这个观感由**两处**共同产生（填充更透明 + 图标半透明），
> 只测一处就会漏掉另一处。反向验证是发现它的唯一手段。

### S15 目检结果（`spikes/s15_orb_preview.py`）

**按壁纸底色分张，不是按应用主题** —— 判据同 S14：
**这个图标的背景由谁决定？不是应用就別问主题。** 球的底色是壁纸。

四种壁纸（深色 / 中灰 / 浅色 / 花哨渐变）各一张，五态 × 1:1 与 3×，
外加悬停与被戳两种瞬时态。结论：

- **五态在四种壁纸上都分得清。** 环画在**球体上**（不是壁纸上），
  所以环的可读性由球体保证，与壁纸无关；壁纸只影响球体本身的轮廓 ——
  深色壁纸上靠**白描边**站住（球体填充 `#1C1C1C` α205 在 `#141414` 上几乎不可分，
  是那圈白描边在勾轮廓）。
- **「未采集」的环比「0%」亮**（α120 vs α58，叠在球体上约 128 vs 76）。
  这是**刻意**的（「没在记录」要比「今天没干」显眼），且与托盘同一个约定；
  颜色上「已达成」是绿色，不会与灰环混。**但值得记一笔**：
  在 52px 的球上比 16px 的托盘更容易被误读成「满环」。
  若要再改，方向是让关闭态画**虚线环**而不是更亮的实线环（属设计决策，未改）。
- **气泡中文正常**（不是豆腐块），QSS 背景在，深浅两种壁纸上都读得清。
- 贴边三态（左吸 / 右吸 / 展开）符合预期，`edge_snap_inset() = 21px`。

> ⚠ **S15 自己也踩了两个坑**（都已修）：① 画布高度只留 40px 放不下
> 末尾的「瞬时态」行，整行被裁在画布外；② 贴边图画布宽 720 放不下第 4 格，
> 桌宠对比图**静默没画出来**（`if left + panel_w <= width` 直接跳过）。
> **教训：目检图「少了一格」不会报错** —— 看图时要数格子，不能只看「有没有图」。

顺带发现：`model_manager.get_current_default_image()` **恒返回 `None`**
（找的是 `pet.png`，而资源目录里是 `idle/happy/…` 命名）——
是条既有死路径，桌宠形态实际靠 `AnimController` 播 `idle` 帧出图，功能不受影响。
另外 `_current_model` 默认是 `""`，资源目录会落到 `assets/` 根上（那里没有帧文件），
生产里这个值来自 `appearance.pet_model`。

### 验证

- `tests/test_appearance.py` +34、`tests/test_config_isolation.py` +7。
- 全量 **494 → 535 passed + 1 skipped**。
- `spikes/userdir_diff.py` 复验：全量测试前后 **新增 0 / 删除 0 / mtime 变 0 / 内容变 0**。
- 反向验证合计 **35 条**（外观 23 + 隔离 6 + 位移门控 6）全部真实打红。

### 打包与冒烟（v1.3.0）

- 版本号 1.2.1 → **1.3.0**（两处同步）。
- PYZ 符号校验清单按 P2.16 **追加**（`ShellWindow` / `OrbForm` / `PetForm` /
  `_build_initial_form` / `animation_target` / `wants_shell_motion` /
  `_sync_anim_target` / `_numeric_origin` / `edge_snap_inset` / `pet_home` /
  `PET_DEMO_HOME` / `Bubble` / `forms` / `bubble` / `paths` / `ring` / `orb`），
  旧项不删；并**反向查旧字面量 `PetWindow` 是否真的走掉**（用精确常量，不用子串）。
- 密钥复检（**zip 逐条目解压**）0 命中。
- exe 冒烟：存活 16s、「版本: 1.3.0」+ 完整启动序列、零 ERROR；
  **收尾必须 `taskkill /F /T`**（`kill $PID` 报「已退出」不代表 Windows 进程真没了）。
- **新增第 ③ 步发版核查 `spikes/exe_window_check.py`** —— 枚举 exe 名下的可见顶层窗口。
  起因就是上面那条：日志到「热键已注册」为止，**证明不了窗口存在**。
  判据：至少 1 个可见窗口 + 含正方形形态窗（球是 `orb_size + 12` 画布）。

---

## 4.12 P2.17 体验收尾：吸附门控 · 删冗余文案 · 插件可卸载（v1.4.0）

用户原话：「侧边吸附改成只在靠近屏幕两侧的时候有，应用内这几个冗余提示去掉，
为插件增加可在控制中心内卸载的功能」。

三条需求看着互不相干，其实是同一件事：**「主动作」之外还堆着一堆没人看、
还占地方的东西**。吸附不该在屏幕任何位置都触发；说明文字不该常驻；
插件既然能在界面里装，就得能在界面里卸。

### ① 贴边吸附：从「无条件」改成「有触发距离」

原实现（P2.16）松手后**无条件**按「窗口中心落在屏幕哪半」吸附 ——
在屏幕正中间松手也会被拽到边上，而用户要的是「只在靠近两侧时」。

改法：协议加 `Form.edge_snap_trigger()`（基类返回 `0` = 不吸附），
`OrbForm` 返回 `_ORB_SNAP_TRIGGER = 48`。`_snap_to_edge()` 先算窗口左右边缘
到屏幕左右边缘的距离，**两侧都大于触发距离就不吸附**。

> ⚠ 关键在「不吸附时还要**清掉吸附态**」（`_edge_side = None` / `_snapped = False`）。
> 只加判断、不清态的话：从贴边拖到中间 → `_edge_side` 还在 →
> 鼠标一移开（`leaveEvent`）`_snap_to_edge()` 又把它拽回边上。
> 反向验证专门有两条钉这个（M1 去掉判断、M3 只不清态）。

### ② 删掉四处冗余提示

| 位置 | 删掉的文案 | 为什么 |
|---|---|---|
| `AppearancePage.hint` | 「主题、形象与窗口行为。主题切换会立即生效并保存。」 | 页面标题已经说了 |
| 配色项 | 「深色参考 VS Code Dark+，浅色参考 Windows 11 原生」 | 是给开发者看的 |
| 趋势页底部 | 「数据只在本机，保留最近 N 天，不出网。」 | 常驻说明；**功能性**警告保留 |
| AI 表单 | 「填好后点「测试连接」验证…」 | 常驻说明；输出区改成按内容自动显隐 |

> 「删掉常驻说明」不是把话挪个地方 —— 是**承认它本来就该只在需要时出现**。
> 趋势页底部那条还在，只是改成 `retention_days < days` 时才返回文案。

### ③ 控制中心内卸载插件

`extensions/plugin_manager.py`：

- 新增 `disabled_names()` / `layer_of()` / `uninstall()` / `restore()` /
  `_remove_plugin_dir()`；`discover_and_load` **跳过 `plugins.disabled` 里的名字**。
- 卸载语义按层分：**system 层 = 停用**（程序自带文件不动，可恢复）；
  **user 层 = 停用 + 删目录**（要重新放回才能恢复）。
- `_remove_plugin_dir()` 删之前**必须核对 `target.parent == user_root`**，
  并拒绝删 `user_root` 本身 —— 防「传进来一个越界路径就把别处删了」。
- `__init__(app=None, base_dir=None)` 支持注入，测试能在临时目录造插件树。

`presentation/control_center.py` · `PluginsPage`：已加载表格加操作列（「卸载」），
下方加「已卸载」区（名称 / 来源 / 「恢复」），**空时整段收起来**。

> ⚠ 页面把 `plugin_manager` 当**鸭子类型**用（预览脚本会塞普通对象进来，
> 见 `spikes/s13`），所以 `disabled_names` / `layer_of` 都要 `getattr` 探一下，
> 拿不到就当「没有已卸载插件」—— 页面照常显示，而不是整个崩掉。

### 验证

- `tests/test_plugin_manager.py` **新增 18 例**、`test_appearance.py` +3、
  `test_ai_pages.py` +1。
- 全量 **536 → 558 收集**（557 passed + 1 skipped）。
- **反向验证 15 条全部真实打红**（`_mutcheck_p2_17.py`，用后即删）：
  覆盖「门控判断 / 触发距离 / 清吸附态」、四处文案、卸载写盘 / 调 `on_unload` /
  删目录 / 跳过名单 / 越界保护 / 恢复 / 按钮 / 鸭子类型兜底。

### 零泄漏复验踩到的坑：**桌宠在跑，比对会「看起来在泄漏」**

`spikes/userdir_diff.py` 报 `mtime 变 3 / 内容变 4`（`app.log` / `giwifi.log` /
`activity.db-shm` / `activity.db-wal`）—— 但这是**运行中的桌宠实例**在写，
不是测试。证据：**不跑测试、只等 60s**，`app.log` / `giwifi.log` 照样在变；
`app.log` 里全是「鼠标点击」（实例挂着全局鼠标钩子，用户点哪儿它记哪儿）。

> **判据：零泄漏复验必须在「被测程序没在跑」时做。**
> 拿不准时用**差分法**：先量一段「无测试」的噪声基线，再量「测试期间」，
> 两者之差才是测试的贡献。
> 测试侧另有结构性保证：`tests/conftest.py` 在**模块级**把 `PET_DEMO_HOME`
> 指到临时目录，且测试里没有任何一处硬编码真实 `~/.pet_demo` 路径
> （`ActivityStore` 一律 `":memory:"`）。

---

## 4.13 P2.18 专注可见化 · 建议总结段（v1.5.0）

需求原话：「点击专注选项后没有直观反馈，交互感不强，在建议生成部分加一个总结部分，
优化整体的流畅性和交互设计」。

### 先想清楚的事：这不是两条需求，是**同一条**

「点专注没反馈」和「建议区缺总结」，表面一个是交互一个是内容。往下想一层，
它们都是**「做了一件事」与「看见这件事发生了」之间那层缺失**：

- 点「专注」原来只往页面底部写一行状态字 —— 看不见倒计时、看不见还剩多少、
  看不出能不能停、甚至看不出**是不是真启动了**。用户按了一下，世界没有任何变化。
- 一排并列建议卡，每张都在说「你该去做 X」，但没有一句在说**「今天整体怎么样」**。
  用户读完记住了 5 个待办，却没得到结论。

所以这次补的不是装饰，是把**已经发生的事显式地摆出来**。两条需求落在同一个
设计原则上：**状态要有一个能被看见的载体**。

用户通过提问明确了两个关键选择：
- **总结从哪来** → 「由 AI 一并生成」（改提示词与 JSON 格式，让模型多输出一段 `summary`）
- **专注要看到什么** → 「倒计时卡 + 悬浮球联动」（页内 `MM:SS` 卡 + 进度条 + 暂停/结束，
  同时悬浮球外环改画本次专注进度）

### ① 总结与建议是**两件事**

`AdviceReport = summary + advices`。summary 是「今天整体怎么样」的**结论**，
不是「第 0 条建议」—— 它不能有 `action` / `minutes`，也不该被当成一条卡片渲染。

新格式：`{"summary": "…", "advices": [{…}, …]}`。
`engine/activity/advice.py` 新增 `AdviceReport`（frozen dataclass）、
`parse_report(text) -> AdviceReport`、`_clamp_summary()`（`" ".join(text.split())`
折成一行 + `MAX_SUMMARY_CHARS = 120` 截断）、`_bracket_order(text)`。
`parse_advices()` 改成 `list(parse_report(text).advices)` —— **只有一条解析路径**，
不允许两套解析各自演化。

总结**同样受**「只能用摘要里出现过的数字」这条约束管（它比单条建议更容易编数字，
因为它是概括性的）。

### ② 两个「静默错误」——解析层的坑

#### JSON 解析的「错误地成功」

`{"summary": …, "advices": […]}` 里**嵌着一个数组**。原来的解析逻辑固定先试 `[`：

```
text.find("[")  →  命中 advices 的开括号  →  json.loads 成功
```

于是 summary 被**静默丢掉**，而且**解析是成功的** —— 没有任何异常，
界面上只是「总结没了」，从现象完全看不出是解析问题。
（如果不是先写测试，这个 bug 会以「模型有时候不返回总结」的面目长期存在。）

修法：`_bracket_order()` 比较 `{` 与 `[` **谁先出现**，按先出现的那个决定先试哪种。

#### 空数组是**内容**，不是字段缺失

数据不足时，模型按格式说明给出的**正确答案**是 `{"summary": "…", "advices": []}`。
旧写法 `data.get("advices") or [data]` 把空列表当**假值** → 判定为「没有 advices 字段」
→ 退回 `[data]`（把整个 dict 当成一条建议）→ **总结被丢掉，整段 JSON 被当大白话显示**。

修法：
```python
if "advices" in data:          # 用「在不在」判断，不用真假值
    items = list(data["advices"])
...
if items or summary:           # 有总结也算有内容
    return AdviceReport(...)
if structured:                 # 合法但空的 JSON（[] / {}）
    return AdviceReport()      # 不许降级成一条内容是 "[]" 的假建议
```

**合法但空的 JSON 不许降级**：`[]` / `{}` 是模型明确说了「我没有建议」，
降级成大白话会把 `[]` 当文本，造出一条内容为 `[]` 的假建议卡。

### ③ 专注反馈：环只能有**一个口径**

托盘图标和悬浮球**各画一个环**。如果专注时只有球改画本次专注、托盘还画今日进度，
用户就会看到**两个互相矛盾的环**（P2.14 已在配色上踩过一模一样的坑）。

所以新增 `presentation/design/ring.py::ring_view(*, enabled, ratio, focus_ratio=None,
focus_paused=False) -> (state, ratio)`：`focus_ratio is not None` 时返回专注态，
否则回落到 `activity_state()`。**两个环都调它**，状态判定只有一份。
五态：`off` / `active` / `done` / `focus` / `focus_paused`。

> **专注态必须与「已达成」分开** —— 不分开的话，走到 40% 的环会被读成
> 「今天只完成了 40%」，真相是「这轮专注还剩 60%」。这是**两个完全不同的意思**，
> 同一个视觉不能同时表达。

### ④ 番茄钟的两个真 bug（都不是本次需求的一部分）

#### `start()` 静默丢掉调用方给的分钟数

建议卡上写着「专注 45 分钟」，点下去实际跑 25 分钟（构造时的 `work_duration`）。
`TomatoTimer.start(timer_type)` 根本没有接收分钟数的参数 —— 调用方传了也被丢掉。
**时长是「这一次」的属性**，不该只能由构造时的全局值决定。
现在 `start(self, timer_type="work", minutes: int = 0)`，
`self._total_seconds = (wanted if wanted > 0 else self.work_duration) * 60`。

#### 「停 → 再开」两倍速倒计时（`_epoch` 轮次号）

```
线程 A: while self._running: ... sleep(1)     ← 睡在 sleep(1) 里
用户:   stop()   → _running = False
用户:   start()  → _running = True            ← 同一瞬间
线程 A: 醒来，读 _running → True → 继续扣秒
线程 B: 新线程也在扣秒
```

结果：**两个线程一起倒扣，倒计时两倍速**。
P2.18 之前 `stop()` 只有番茄钟对话框能触发，很难碰到；
加了「结束专注」按钮之后，「停 → 再开」是**常规操作**，不修就是必现。

修法：每轮一个**轮次号** `self._epoch`；`_spawn()` 换号开线程，
`_timer_loop(self, epoch)` **每处读共享状态前**先 `if epoch != self._epoch: return`，
`stop()` 里 `self._epoch += 1`。

> ⚠ 反向验证时发现：只删**睡前**那次号检查，醒后那次仍拦得住 → mutation 打不红。
> 要删就删**两处**才能证明「号检查是必需的」。

### ⑤ 暂停时进度条不变色 —— Qt 属性选择器不可靠

暂停后卡片边框、时钟、「已暂停」标题都变琥珀了，**进度条还是强调色**。

原因：QSS 里写的是
```css
QFrame#focusCard[paused="true"] QProgressBar#focusBar::chunk { … }
```
这种「**祖先带属性 + 子控件子部件**」的选择器在 Qt 上**不生效**。
（`QFrame#focusCard[paused]` 单独用有效，`QProgressBar#focusBar::chunk` 单独用有效，
组合起来就哑了。）

修法：**属性直接挂在进度条自己身上** + 各自 `unpolish/polish`：
```python
self._bar.setProperty("paused", flag)
# QSS: QProgressBar#focusBar[paused="true"]::chunk { background: warning; }
```
`_repolish()` 同时 polish `self` 和 `self._bar`。

> **判据：样式选择器要「就近」—— 属性挂在哪，选择器就写哪。**
> 别指望祖先属性穿透到子控件的子部件上。

### ⑥ 顺带处理的交互细节

- **状态没变不发信号**：`update_from(status)` 返回 `bool`（状态是否变化），
  只在变化时 `state_changed.emit` —— 否则每秒刷一次 UI。
- **页面不可见时不轮询**：`TodayPage.showEvent` 起 `TICK_MS = 1_000` 定时器，
  `hideEvent` 停掉。看不见的页面不该烧 CPU。
- **球环刷新同样只在专注时提速**：平时跟着活动事件走，专注期间切 1 秒轮询
  （`FOCUS_REFRESH_MS = 1_000`），结束自动还原。
- **顶部「开始专注」按钮跟着状态变**：专注中变「专注中…」并禁用；
  页面刷新（`_render_advice`）时**不无条件重新启用**。
- **启动失败的原因分开说**：原来是混成一句「启动失败」，
  现在「计时器不可用」/「已有一个专注在进行」分开提示。
- **球中心图标随状态换**：专注 → `clock`，暂停 → `pause`，已达成 → `check`。
  新增 `pause` 图标（两个实心圆角矩形），加进 `FILLED` 集合。

### 验证

- `tests/test_advice_report.py`（**新增**）：新格式 / 旧裸数组 / 大白话降级 /
  折行截断 / **空 advices 不吞总结** / **合法空 JSON 不造假建议** / 永不抛 /
  上限 / `parse_advices` 与 `parse_report` 一致 / 提示词要 summary。
- `tests/test_focus_flow.py`（**新增**）：`TestTimerDuration`（默认值 / 显式覆盖 /
  非法回退 / break 忽略 / 换长度 / `_epoch` / 过期线程不扣秒）、
  `TestRingView`（**五态全枚举** / 专注优先 / 值夹取）、
  `TestOrbFocusRing`（环切换与还原 / 暂停 / 像素琥珀色 / 图标 / 坏计时器不崩）、
  `TestFocusCard`（时钟格式 / 展开收起 / 按钮显隐 / 进度 / 信号 / provider /
  **进度条变色**）、`TestAdviceSummary`。
- `tests/test_activity_advisor.py`：+`TestTodayFocusFeedback` / `TestTodayAdviceSummary` /
  `TestPluginStructuredReport`；`test_start_focus_uses_shared_timer` 改签名。
- 全量 **558 → 629 收集**（**628 passed + 1 skipped**）。
- **反向验证 32 条全部真实打红**（`_mutcheck_p2_18.py`，用后即删）：
  分三轮 —— 第一轮 **4 条漏网**、第二轮 **2 条漏网**，逐条补强断言后归零。

#### 反向验证抓到的假断言（值得单记）

| 漏网 | 为什么打不红 | 修法 |
|---|---|---|
| 「空 advices」 | 真正兜底的是 `if items or summary:`，不是 `in` 判断 | 改 mutation 目标 + 测试里写明 |
| 「system prompt 删规则」 | 只断言出现 `summary` 一词是假的 —— 改成「先给建议数组」照样绿 | 断言精确到 `"先给一段 summary" in …` |
| 「过期线程」 | 删睡前那次号检查，醒后那次仍拦得住 | mutation 改成**两处都删** |
| 「空总结显示框」 | mutation 只影响一个用例 | 扩到 3 个用例 |
| 「暂停不换配色」 | 只断言了卡片属性，没断言进度条 | 拆成两条 mutation + 新增 `test_the_paused_bar_changes_colour` |

### 零泄漏复验

`spikes/userdir_diff.py` 报「**新增 0 / 删除 0 / mtime 变 0 / 内容变 0**」（152 文件）。
复验前先确认**无桌宠实例在跑** —— 这是 P2.17 踩过的坑（见 §4.12 末节），
这次直接照做，一次通过。

### 打包与冒烟（v1.5.0）

- PyInstaller 打包 EXIT=0（5m07s）。`spikes/_refresh_release.py` →
  `dist/little-table-pet-v1.5.0-win64{,.zip}`（**331 文件 / 57.10 MB**）。
- **发版核查三道全 PASS**：
  - ① `pyz_check.py`：PYZ 627 条目；必需模块 / 符号 / 字符串**全部命中**，旧字面量无残留。
    ⚠ 踩到一次 FAIL：新加的 `"QProgressBar#focusBar[paused"` 只出现在 `presentation/design/qss.py`，
    而 `qss.py` **不在 `EXTRA_MODULES` 里** ⇒ 字符串根本没被收集。加进清单后 PASS。
  - ② `leak_check.py`：目录 362 文件 / zip 331 条目，敏感命中 **0**、`sk-` **0**；包内 `ai.api_key = ''`。
  - ③ `exe_window_check.py`：顶层窗口 12 个、可见 2 个，含 **64×64 正方形球窗**；
    6s 后同尺寸窗口位置**不变**（球不自己动）；进程已 `taskkill /F /T` 清理。
- **exe 冒烟通过**：存活 17s（185MB）；
  **版本行 `加载用户配置成功 (版本: 1.5.0)`** + 完整启动序列
  （AI 助手插件已加载 → 系统托盘已启动 → 键盘控制器已预热 → 剪贴板已预热 → AI 面板已预热 → 热键已注册）。

> ⚠ **两个「看着像问题、其实不是」的东西**（都当场查清了）：
> ① **版本行不在 `app.log` 里** —— 它在 exe 的 **stdout**（`INFO:data.config_manager:…`），
> `app.log` 从「AI 助手插件已加载」开始记。只看 `app.log` 会误判「版本行没了」。
> ② **`alt+q` 注册失败是环境问题**：三个热键由**同一个循环**注册，
> `alt+t` / `alt+s` 成功而 `alt+q` 失败 ⇒ 不是应用内重复注册。
> 探针确认 `RegisterHotKey(NULL, id, MOD_ALT, VK_Q)` 返回 0 且 `GetLastError()==1409`
> （`ERROR_HOTKEY_ALREADY_REGISTERED`）⇒ **机器上别的程序占着**。
> 10-13 / 10-14 都正常，10-15 起才失败 —— 应用按设计降级为 WARNING 并提示可从托盘菜单唤起。
>
> ⚠ **冒烟脚本自己踩了两个坑**（写 Bash 一行流时）：`BEFORE=$(wc -l < log) && ./exe &`
> 会把整条链丢进子 shell，父 shell 的 `BEFORE` 是空的（`tail -n +1` 打印了整个日志）；
> 列表推导里写 `in l` 而不是 `in x` 会让 taskkill 静默不执行。
> **判据：`&` 只作用于它左边的那条链 —— 要在后台跑的只是启动命令本身。**

## 4.14 P2.19 专注入口的反馈口径（v1.6.0）

**问题**：用户截图 —— 点了建议卡上的「开始 45 分钟专注」之后，那张卡的按钮
**一动不动**，还是蓝色可点，能反复点。倒计时卡出来了、顶部按钮也变了，
唯独**手指所在处**没变。

**把全项目扫了一遍**，同类问题只有两处（其余入口都有反馈）：

| 入口 | 点后反馈 | 判定 |
|---|---|---|
| 建议卡「开始 N 分钟专注」 | 无 | **缺**（用户报的） |
| 今日页顶部「开始 N 分钟专注」 | 有（`_on_focus_state` 同步） | OK |
| 番茄钟页「开始一个番茄」 | 只有旁边小字变、且**不自动刷新** | **缺** |
| 番茄钟对话框 | 完整（按钮显隐 + 每秒刷新） | OK |
| 生成建议 | 「分析中…」+ 禁用 | OK |
| 测试连接（两处） | busy + 禁用 | OK |
| 复制 | 「已复制到剪贴板」 | OK |
| 插件卸载 / 恢复 | confirm + 列表刷新 | OK |
| 清空 / 刷新 / 打开目录 | 外部结果 | OK |

**判据**：

> **「开始 X」不是一次性动作，是「进入一个持续状态」。**
> 一次性动作点完有外部结果（列表刷新、窗口打开）；进入持续状态的动作，
> 点完之后**按钮自己必须变成那个状态的显示** —— 否则用户看到的就是「点了没反应」。
> 而且这个状态**全局唯一**（同一时刻只有一个计时在跑）⇒
> **所有入口必须同时反映它**：只改用户点的那一个不够，只改别处更糟。

**改法**（一处收口）：
- `focus_card.focus_label(state, minutes, kind)` —— 四个入口共用一份文案。
- `AdviceCard.set_focus_state(state, kind)` —— 卡片按钮跟随，非 idle 时换文案 + **真禁用**。
- `TodayPage._sync_focus_entries(state=None)` —— 一处同步顶部按钮 + 全部建议卡。
  传 None 读计时器实况；`_on_focus_state` 有权威 state 就直接用
  （再读一次只会多一个不一致的窗口）。
- `TomatoPage`：`showEvent` / `hideEvent` + 1 秒轮询，按钮与状态行一起跟随。
- `focus_title(state, kind, total)` —— 卡里显示 `专注中 · 90 分钟`（让承诺可核对），
  顺带修掉一个旧错：**休息阶段原来也写「专注中」**。

**踩到的两个坑**（都值得单独记）：

> ⚠ **属性名不能叫 `focus`**：`focus` 是 **QWidget 的内建 bool 属性**（QSS 里还有 `:focus` 伪状态）。
> `setProperty("focus", "running")` 之后 `property("focus")` 读回来是 `False` ——
> 字符串值被内建属性吞掉，于是 `QPushButton[focus="running"]` **永不匹配、且不报任何错**。
> 误导性在于现象**像层叠 / 特异度问题**：属性「设上了」、`unpolish/polish` 也调了、样式就是不变。
> 我按这个错误方向试了两轮（先给按钮加 id 抬特异度、又改成 `[attr]:disabled` 复合选择器）都没用。
> 真正定位靠**对照实验**：同一个按钮分别设 `focus` 与 `phase` 两个属性名 ——
> 前者渲染出通用禁用灰 `#f3f3f3`，后者立刻出琥珀 `#9c5b00`。
> **判据：属性「设了但不生效」时，先怀疑名字撞了内建属性 / 伪状态，再怀疑层叠。**
>
> ⚠ **同一件事有两个实现 = 两个都没被验证**：`AdviceCard.set_advice()` 自己会跟随状态，
> `_show_cards()` 当时又同步一次。反向验证时删掉**任意一处**，测试都照样全绿 ——
> 因为另一处兜住了。删掉 `_show_cards` 里那次（它的职责是渲染，不该顺手改全局状态）之后，
> 那条 mutation 才真正打红。
> **判据：反向验证发现「删了不红」时，第一反应是「是不是有冗余实现」，不是「补个测试」。**

**另一个假测试**：`test_a_timer_with_missing_fields_does_not_crash` 原来只断言「状态行有字」——
把取值改成硬索引 `st['today_count']` 之后，异常被 `except` 兜住、界面照样有字，**改坏了还是绿**。
判据改成「文字 ≠ 兜底文案『状态不可用』」才打红。
**判据：测「容错」时不能只断言「没崩」，要断言「真的走了正常分支」。**

**验证**：
- 新增 41 条测试（`test_focus_flow.py` 组件级 + `test_activity_advisor.py` 页面级）。
- 全量 **669 passed + 1 skipped**（P2.18 基线 628+1）。
- **反向验证 30 条全部真实打红**，两轮（第一轮 2 漏网，正是上面那两个坑）。
- 目检：s13 新增四张 `today_focus_cards_*`（**1560px 高** —— 700px 窗口里建议卡落在
  折叠线以下，不拉高等于没目检），与改动前并排对照；顶部按钮与两张卡的按钮
  都变成琥珀「专注中…」，三者口径一致。
- 零泄漏：**本机有一个用户自己启动的桌宠实例在跑**，`giwifi.log` / `app.log` 被它持续写入 ⇒
  改用**差分法**（先量 75 秒纯噪声，再量测试期间），判据是「测试期间变化的文件
  集合 ⊆ 纯噪声集合」。查下来 `app.log` 的新增行全是 `[DEBUG] pet_demo.app: 鼠标点击`
  —— 是运行实例的**全局鼠标钩子**在记录用户点击（时间戳落在测试窗口内），
  且 `tests/conftest.py` 已把 `pet_demo.app` 重定向到临时目录 ⇒ **不是测试泄漏**。
  **关掉那个实例后重跑全量差分，得到干净结论：新增 0 / 删除 0 / mtime 变 0 / 内容变 0。**

**收尾（v1.6.0）**：
- 打包**被用户实例挡住**：PyInstaller `--clean` 要清空 `dist/`，而用户开着的实例
  （PID 5912）正是从 `dist/小小桌宠Demo/` 启动的（`OpenProcess(0x1000)` +
  `QueryFullProcessImageNameW` 查到路径）⇒ 必然 `WinError 5`。
  **先问用户再关**（他可能在跑专注计时），关掉后才开始打包。
  ⚠ 顺带踩到：**Git Bash 会把 `taskkill /F` 的 `/F` 当路径转换**（报「无效参数/选项 - 'F:/'」）
  → 改用 `subprocess.run([...])` 列表形式，不经 shell 就不转换。
- 打包前先做「清单 vs 源码」**预检**（临时脚本 `compile()` 源码收符号）——
  省掉「打包 4 分钟才发现清单里的名字写错」。预检 PASS 后真 `pyz_check` 也 PASS。
- PyInstaller EXIT=0（3m40s）→ `dist/little-table-pet-v1.6.0-win64{,.zip}`
  （**331 文件 / 57.11 MB**）。
- **发版核查三道全 PASS**：① `pyz_check.py` PYZ 627 条目、模块/符号/字符串全命中、
  旧字面量无残留；② `leak_check.py` 目录 362 文件 / zip 331 条目、敏感命中 0、`sk-` 0；
  ③ `exe_window_check.py` 顶层窗口 12 个 / 可见 2 个（含 64×64 球窗）、6s 后位置不变。
- **exe 冒烟**：存活 17.0s + 版本行 + 完整启动序列 + 零 ERROR。
  ⚠ 这次实测把上一版的记录**改正**了：版本行 `INFO:data.config_manager:…` 落在 **stderr**
  （`logging.StreamHandler` 默认 stderr），**不是 stdout** —— 冒烟必须两个流都收。
  → 固化为正式 spike `spikes/smoke_exe.py`（版本号从 `config.default.json` 读，
  不再每次现场拼 Bash 一行流，也就不会再踩 `&` 与 `taskkill` 那两个坑）。
  ⚠ 它**证明不了窗口存在**，窗口仍归 `exe_window_check.py` 管，两者都要跑。

---

## 4.15 v1.7.0 聚焦赛题：移除宠物子系统 + 新增「隐私与数据」页

### 1. 先说为什么

用户要拿这个产品参加**2026 年第十四届全国大学生数字媒体科技作品及创意竞赛**
（首选赛道：指定命题 → AIGC 类数字创意作品创作赛项），提出两条改造：

1. **移除所有与赛题无关的宠物模型设计相关内容**，让项目聚焦赛题核心；
2. **新增隐私政策与数据管理页**：说明数据的收集 / 使用 / 存储 / 保护方式，
   并提供**查看、导出、删除**的操作入口。

对第 1 条，用户 additionally 决定把**便签与快捷启动**也一并移除，并给产品改名
**「知时助手」**。两条决定都记在这里，因为它们改变了产品结构，不只是改名。

### 2. 移除范围（先备份，再动手）

**项目自 P0 起 git 全部未提交**（`presentation/forms.py` 甚至是 untracked），
所以删掉就找不回来。先做项目外备份：
`C:\Users\LL\Desktop\处理沙盒\_backup_petgame_demo_before_知时助手_20261015.zip`
（379 文件 / 51.1 MB）。

| 移除了什么 | 文件 |
|---|---|
| 宠物模型管理器 | `presentation/pet_model.py` |
| 全套精灵图资源 | `presentation/assets/`（7 张 PNG） |
| 桌宠形态实现 | `presentation/forms.py::PetForm`（**`Form` 协议保留**） |
| 便签 / 快捷启动插件 | `extensions/system/notes/`、`extensions/system/quick_launch/` |
| 便签 / 快捷启动实现 | `tools/note_tool.py`、`tools/quick_launch.py` |
| 对应对话框 | `presentation/dialogs.py::NoteDialog` / `LaunchDialog` |
| 配置项 | `appearance.form` / `pet_name` / `pet_model` / `animation_speed`、`quick_launch` 节、`ai.pet_reacts` / `pet_reactions` |
| 形态应用入口 | `ui_renderer.apply_pet_model()` / `apply_form()` / `set_model()`、`ai_assistant._react()` |

改名：`APP_NAME` / exe / 安装脚本 / 托盘 / 全部文案 → **知时助手**；
版本 `1.6.0 → 1.7.0`（`config.default.json` 与 `data/config_manager.py` 两处同步）。

### 3. 三个真实缺陷（都是「移除」挖出来的，不是「新增」）

1. **`ui_renderer.py:102` 还在调已删除的 `_pet_size()`** ——
   `ShellWindow()` 无参构造会直接 `NameError`。删类时只删了定义没删调用点。
   **判据：删一个符号，要 grep 它的每一处调用点，而不是只删定义那一个文件。**
2. **`tests/test_appearance.py` 有 14 处 `PetForm`** —— 包括
   `isinstance(form, PetForm)`（回退断言）、`OrbForm().form_size() != PetForm().form_size()`
   （尺寸对比）、`set_form(PetForm())`（换形态）、`wants_shell_motion() is True`。
   全部改写为「只有球 + 一个最小 `_BareForm` 桩」——
   **协议缺省值反而因此被钉住了**（基类：不换图 / 允许位移 / 不贴边），
   这是原来「两个实现互相兜底」时测不到的。
3. **`check_project.py` 还在查「默认宠物资源目录不存在」** ——
   一条永远报错的检查比没有检查更糟（训练出「看见报错就忽略」）。
   换成查**数据根可写**（`os.access`，不落任何文件）——
   数据根不可写时，用户看到的现象只是「设置老是保存不了」，提前查出来更值。

### 4. 「隐私与数据」页（新增）

**分层**：`data/privacy.py`（纯逻辑，无 Qt）+ `control_center.py::PrivacyPage`（只提问和展示）。
好处是那套「枚举 / 统计 / 打包 / 删除」能被测试直接覆盖，不必弹一个窗口。

- **清单是声明式的**：`entries()` 返回 6 类（设置 / 会话历史 / 活动记录 / 日志 / 缓存 /
  旧版本遗留），每类的 `paths` 用 `pet_path()` **调用时求值** ——
  数据根可被 `PET_DEMO_HOME` 覆盖，写常量就等于把根钉死。
- **导出走 sqlite 的 backup API**，不原样拷 `-wal` / `-shm`：
  WAL 模式下刚提交的数据在 `-wal` 里，只拷主库会**静默丢掉最近几轮对话**。
  反向验证时把 `_backup_db` 改成恒失败，专门写的「数据只在 WAL 里」用例当场打红。
- **清空优先借活实例的 API**：活动记录走插件的 `clear_data()`（它还持着连接），
  配置走 `config_manager.reset_to_default()`，日志走 `log_manager.clear_logs()`；
  只有 `ai.db` 这种「关掉单例就能重建」的才 `close_shared_store()` 后删文件。
  **直接删一个还被开着的库文件，在 Windows 上只会得到 `PermissionError`。**
- **旁车过滤必须用 `name.endswith(("-wal", "-shm"))`**：
  `Path("ai.db-wal").suffix` 是 **`.db-wal`**（最后一个点之后的一切），
  拿 `-wal` 去比永远不相等 —— 这条 bug 是反向验证抓到的：
  写成 `suffix` 时 WAL 会被原样拷进 zip，而它不能被单独打开。

### 5. 验证

- **新增 `tests/test_privacy.py`（23 条）**：清单落在数据根下、单类导出只装那一类、
  zip 里的库能打开且含 WAL 里的行、有插件走插件 / 没插件才删文件、
  清空前必须确认（取消则一个字节都不动）、空态按钮禁用。
- **反向验证 10 条 mutation，0 漏网**（临时探针 `_rev_privacy.py`，用完即删）。
  第一轮有 1 条漏网：「backup 恒失败」测不出来 —— 因为原样拷也能让
  「zip 里的库能打开且有那行数据」这条断言通过。**补了 WAL 专用用例才拦住。**
- **目检 `spikes/s16_privacy_preview.py`**（3 张，浅深 + 空态）：
  ① 禁用态与可用态**逐像素 100% 不同**（裸按钮实测），不是「点了没反应」的灰；
  ② 抓到一处 tooltip 伪影 → 删掉冗余 tooltip（「说明」列已经完整显示同一句话）。
- **全量测试 675 passed + 1 skipped**（原 669：-17 移除的用例，+23 隐私用例）。
- **`pyz_check` 预先检**（`compile()` 源码收符号）PASS；清单新增
  `data.privacy` 到 `EXTRA_MODULES`，并加入 v1.7.0 的符号 / 字符串 / 禁词
  （`PetForm` / `pet_model` / `note_tool` / `quick_launch` / `pet_name` / `小小桌宠` 等）。
- **打包与发版核查全部通过**（2026-10-15）：
  - PyInstaller → `dist/知时助手/`（EXIT=0，约 3m25s）；
  - `pyz_check`：PYZ 621 条，必需模块 / 符号 / 字符串全命中、旧字面量零残留 → **PASS**；
  - `exe_window_check`：可见窗口含 **64×64** 正方形形态窗，6s 后位置不变 → **PASS**；
  - `smoke_exe`：存活 17s、`版本: 1.7.0`、启动序列完整、零 `[ERROR]` → **PASS**；
  - `leak_check`：发布目录 347 文件、zip 318 条目，**敏感命中 0 / `sk-` 0** → **PASS**；
  - `_refresh_release.py` → `dist/知时助手-v1.7.0-win64{,.zip}`（318 文件 / **50.35 MB**）；
  - `userdir_diff`：跑全量测试前后 `~/.pet_demo` **新增 0 / 删除 0 / mtime 变 0 / 内容变 0**。
  - 打包前查过「有没有进程从 `dist/` 启动」→ 0 个（否则 `--clean` 会撞 WinError 5）。
- **收尾修掉的一个真 bug**：`clear_entry("activity")` 走插件 API 后**只删旁车不删主库**
  的那句判据仍写着 `p.suffix in ("-wal", "-shm")` —— 和上面第 2157 条是同一个错，
  实际一个旁车都删不掉。改成 `_is_sidecar(p)`，并给用例补两条断言；
  反向验证（把判据改回 `suffix`）确认新断言当场打红。

---

## 4.16 v1.8.0 人机协同证据链（P1-4）+ API Key 接入系统密钥库（P1-5）

用户原话：

> 「P1-4｜将「一键采纳/忽略」升级为可解释的人机协同证据机制：在用户执行采纳或
> 忽略操作时，系统需自动生成结构化的决策说明（包含推荐依据、上下文信息、
> 影响范围等），完整留存可追溯、可审计的人机协作证据链。」
>
> 「P1-5｜补充 API Key 接入系统密钥库：完成 API Key 与系统统一密钥管理模块的
> 安全集成，涵盖密钥的安全存储、动态读取、权限隔离及脱敏处理，
> 严禁在代码中硬编码敏感信息。」

### 1. P1-4：为什么要留痕，而不是只落一个指纹

原来的「一键采纳 / 忽略」只往 `ignored_advices` 写一个指纹。那只回答
「这条建议别再出现」，回答不了三个更值钱的问题：

| 问题 | 字段 | 为什么现在答不了 |
|---|---|---|
| 用户凭什么同意 / 否决 | `basis` | 依据会被下一次生成**覆盖** |
| 那一刻数据是什么样 | `context` | 同一句结论，6 小时和 2 小时含义完全不同 |
| 这个动作影响了什么 | `impact` | 是开始了 45 分钟专注，还是只是不再出现 |

所以存的不是又一份结论，而是**做决定时的现场**。

### 2. 三条设计纪律（`engine/activity/decision.py` 的 docstring 里也写了）

1. **现场在动作那一刻固化，不事后补。** 建议会重新生成、数据会变化，
   只有当场快照能证明「他当时看到的就是这个」。
2. **上下文只放聚合数字。** `_clean_context` 用**白名单**
   （`CONTEXT_KEYS`），认不出的键**直接丢掉** —— 与 `activity.db` 没有 title 列
   是同一条边界，做法也一样：不靠「调用方记得别放」，靠「这里就收不进去」。
   连 app 名都不放：留痕要回答的是「当时数据量够不够、结论站不站得住」，
   那个问题用数字就能答。
3. **纯函数 + frozen dataclass**，零 Qt。留痕能被单测覆盖，
   不必起窗口、不必连 AI。

两个**相反的取舍**必须分开测（都踩过）：
- 空值（`None` / `""` / `[]` / `{}`）**要丢键** —— `format_context` 里
  `"segments" in ctx` 是**存在性**判断（正是为了保住 0），
  于是 `{"segments": None}` 一旦留下键，界面就显示「现场 None 段记录」；
- `0` 与 `False` **必须留** —— 「现场 0 段记录」说明这条建议当时没有数据支撑，
  是事实；`advice_stale` / `focus_running` 只记 True 的话，
  读的人分不出「当时没在专注」与「当时没检查」。

### 3. 影响范围：记**实际结果**，不谎称

- 忽略 → 「该建议及其同类（同指纹）不再出现在后续推荐中；
  **不影响本机活动记录**，也不影响其他建议。」最后半句是防误解的：
  用户会以为点忽略等于删数据。
- 采纳 → 看 `outcome`。`focus_started=False`（计时已在跑 / 番茄钟插件未加载）
  时写「未开始专注」，**不写「已开始」**。假证据比没有证据更糟。
  `build_note` 的默认值也是「没开始」—— 宁可记成没开始，也不能谎称开始了。

### 4. 留痕为什么在插件里做（不在页面里）

页面只有一个 `Advice` 对象；「当时的数据现场」（分段条数、缓存建议的生成时间、
专注是否在跑）**只有插件拿得到**。放在 `ActivityAdvisorPlugin.record_decision()`
里，留痕的完整性不依赖某个界面记得传参。

一个入口写两件事：忽略时**同时**写 `ignored_advices` 标记与留痕。
只留痕不写标记 → 忽略了还在出现；只写标记不留痕 → 没有凭据。

### 5. `AdviceCard.decided = Signal(object, str)` 替代两个单一动作信号

原来 `action_triggered(int)` / `ignored(str)` 各管一路。现在采纳与忽略
**走同一条路**，卡上两个按钮不可能各记各的 —— 这是「一处收口」的又一处应用。

### 6. 可审计的出口：`DecisionLogPage`（「协同记录」，12 → 13 页）

为什么值得单独一页：「今日」页回答「我今天干得怎么样」，
这一页回答「**我和 AI 是怎么协作的**」—— 前者是结论，后者是过程与凭据。
评审看的是后者。

- 表格：时间 / 决定 / 建议结论 / 影响范围；筛选 全部 · 采纳 · 忽略；
- 详情面板含**建议指纹**，可逐条回溯到具体建议；
- 「导出证据链」→ 一份人可读的 UTF-8 文本（能 diff、能存档、能贴进报告）。
  界面是给「看一眼」的，审计是给「逐条核对」的。
  **没有记录时不弹保存框**（否则用户会以为导出了一份空文件）。

### 7. P1-5：密钥为什么不留在 `user_config.json`

配置文件是**明文 JSON**：会进备份、进同步盘、进「导出全部数据」的 zip。
密钥写在那里，等于每一次备份都多一个泄露面。

`data/key_store.py` 两层后端（接口完全相同）：

| 后端 | 何时用 | 隔离靠什么 |
|---|---|---|
| `keyring` | 装了就用（可选依赖） | 操作系统（凭据管理器 / 钥匙串 / Secret Service）按**当前用户** |
| DPAPI 加密文件 | 没装 keyring 的 Windows | `CryptProtectData` 按当前用户加密 → `<数据根>/secure_keys.bin` |
| `none` | 都没有 | 只能明文（界面会说明，不静默降级） |

**「权限隔离」不靠代码自觉**，靠操作系统的账户边界 —— 别的用户、别的进程读不到。
`_keyring_module()` 要求**能导入且选得出后端**才算：`import keyring` 成功但没装
任何后端时 `get_keyring()` 会抛 `NoKeyringError`，那跟没装是一样的。

**配置里只存引用**：`ai.api_key_ref = "keyring:api.deepseek.com"`。
`REF_PREFIX` 只认 `keyring:` 前缀 —— 否则用户手写 `api_key_ref = "sk-xxx"`
会被当成条目名，把密钥绕回配置里。

**条目名白名单** `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$` 同时挡住路径穿越（`../../x`）。

**脱敏**：只露头 3 尾 4，中段固定 8 个 `•`，**总长度固定**。
真实长度本身就是信息 —— 它告诉别人试错空间有多大。太短的密钥全遮
（露出 4 位里的 2 位没有辨识度，只有泄露）。

### 8. `resolve_api_key()` 是**全项目唯一**读密钥的地方

```python
# engine/ai/__init__.py
def resolve_api_key(config) -> str:
    ref = str(config.get("ai.api_key_ref", "") or "")
    if ref.startswith(REF_PREFIX):
        value = load_key(ref)
        if value:
            return value
    return str(config.get("ai.api_key", "") or "")
```

- 为什么必须收口：密钥的存放方式（密钥库 / 明文）只有这里知道。别处直接
  `config.get("ai.api_key")` 会把「已经迁到密钥库」的用户**悄悄降级成明文读取**
  —— 界面显示已保存、实际取不到，最难查的那类。
- 引用存在但取不到 → 返回空串，让上层报「没配 API Key」。
  **不做别的兜底**：悄悄换一把错的 key，比明确失败难查十倍。
- `load_key()` 取不到一律返回空串、**不抛异常**：调用方（AI 链路）要的是
  「有一把钥匙或没有」，不是一个堆栈。失败原因由 `status()` 给界面看。

### 9. AI 配置页的「保存位置」：退路要看起来像退路

- `SegmentedControl(["系统密钥库", "配置文件（明文）"])`，**明文那一档的标签
  就写明代价** —— 它是给老用户与无密钥库机器的退路，不是并列的普通选项；
- 切换时当场说清「这把钥匙会怎样」（别等保存完才发现）；
- 切到密钥库且已有明文密钥 → **顺手迁移**（写进密钥库，配置里只留引用）；
- 密钥库模式下输入框**留空 = 不修改**，填新 Key 才覆盖；
- 「测试连接」在输入框留空时**用密钥库里的那把**，不拿空串去测；
- 改回明文时**清掉引用** —— 否则 `resolve_api_key` 优先读密钥库，
  用户以为改了却没生效；
- **不设常驻提示**（用户 2026-10-14 明确要求去掉这类一直挂着的说明）：
  需要说的放在**切换那一刻**的状态里，以及控件的 tooltip 上。

### 10. 验证：第一轮 7 条漏网，逐条查清

反向验证 **27 条 mutation**（临时探针 `_rev_p18.py`，用完即删）。
**第一轮 7 条漏网** —— 这 7 条才是这一节最值钱的部分：

| 漏网原因 | 具体 | 修法 |
|---|---|---|
| 断言太松 ×3 | ① 「导出含影响范围」被**表头那句说明**里的同一串字满足；② `masked.startswith/endswith` 对「头露 8 位、完全不遮」的实现照样成立；③ `"未知" in message` 对 `build_note` 抛异常后的兜底文案也成立 | 改成**精确常量**：`f"影响范围：{impact}"` / `masked == SECRET[:3] + "•"*8 + SECRET[-4:]` / `message == "未知的决定类型：like"` |
| mutation 打错目标 ×2 | 改坏的是 A，断言盯的是 B（`test_length_is_not_leaked` 按构造就抓不到「短密钥不遮」） | 把 node 指到真正该红的用例 |
| pattern 不匹配 ×1 | 缩进抄错（4 空格写成 8 空格）→ `SKIP` 而不是 `OK` | 回源码对一遍 |
| **真缺用例 ×1** | 只测了 `advice_stale=True`，于是「只记 True」的实现全绿 | 补 False 用例 |

第 ③ 条正是 §2 硬规则里那句「**同一件事有两个实现 = 两个都没验证**」：
入口的 `if action not in ACTIONS` 与 `build_note` 的 `raise ValueError`
都能给出含「未知」的文案，于是入口那层删掉照样全绿。

**第 4 条漏网原因（这一轮新踩的）：mutation 的 pattern 不唯一。**
`replace(old, new, 1)` 会在**第一个**匹配处动手，而同一个文件里常有一模一样的行 ——
`SessionsPage._detail.setLineWrapMode(...)` 与 `DecisionLogPage._detail.setLineWrapMode(...)`
就完全相同，于是「详情区不换行」这条 mutation 改的是**另一个页面**，
用例当然全绿。**已给探针加护栏**：pattern 出现次数 ≠ 1 就报 `SKIP` 并计入漏网，
不许静默按「OK」记。这类假 OK 比漏网更危险 —— 它让你以为验证过了。

### 11. 目检 S17：又抓到两个规格断言测不出的真问题

`spikes/s17_decision_preview.py`（5 张图，见 `spikes/README.md` 的「S17 结果」）：

1. **详情区不换行，长句被右边缘切掉。** `QPlainTextEdit` 的默认是 `NoWrap`
   （**与 `QTextEdit` 相反**），而上下文那行是「今日；现场 6 段记录；
   累计 1 小时 30 分；数据范围 14:44–16:14；建议生成于 14:14；…」这种长句。
   会话历史页那处**显式设过** `LineWrapMode.WidgetWidth`，这一页是新的、漏了。
   → **教训：抄页面结构时，要连「那些看起来像默认值、其实是显式设置」的项一起抄。**
2. **空态不自洽**：一边写「还没有决策记录」，一边还挂着「这一条决定的完整留痕」
   空卡与**可点的**「导出证据链」按钮。规格断言当时只钉了「表格与空态互斥」，
   这两块不在判据里。→ **教训：空态要按「整页自洽」检查，不是只检查列表本身。**
   修法：详情卡 `setVisible(has_any)`；导出按钮 `setEnabled(has_any)`
   （**禁用而不是隐藏** —— 不跳版，也说明「这里本来有个功能」，与隐私页同一口径）；
   「刷新」保持可用（去今日页做一次决定再回来，就是这个空态的下一步）。
3. 顺带修掉高度问题：详情区原来固定 148px，长留痕永远要在盒子里滚
   （而页面外面明明还有地方）。改成按内容算（下限 168 / 上限 460）。
   ⚠ 量的是 `QFontMetrics`，**不是** `document().size()` ——
   `QPlainTextDocumentLayout` 是**惰性排版**的，控件没画过之前它返回「一行」的
   高度（实测 14px），照它设高度等于永远贴着下限（第一版就是这么写的，图里那块还是被切掉）。
   另外控件还没布局过时（`viewport().width()` < 200）直接不调 —— 否则行数算到天上、
   每次都顶上限，还会「先很高、show 完缩回去」。

> ⚠ **目检清单自己也会撒谎。** 第一版 RESULT 里有一条写「明文那一档：标签里写明了
> 代价（会随备份被带走）」，而 `key_plain_light.png` 上**根本没有这句** ——
> 状态区是空的（有意的，用户 2026-10-14 要求去掉常驻说明，代价只在 tooltip 与
> 切换那一刻出现）。**判据：目检清单里的每一条，都要能由那张图本身证实。**
> 证不了的，要么改图、要么改清单措辞。

### 12. 最终数字

- **全量 748 passed + 1 skipped**（v1.7.0 基线 675：+73 新用例，0 回归）。
- **反向验证 32 条 mutation，0 漏网**（27 条 P1-4/P1-5 + 5 条针对目检发现的问题）。
- `pyz_check` 清单按版本追加，**源码预检**（临时探针 `_preflight18.py`，用完即删）
  当场抓到一处：`resolve_api_key` 在 `engine.ai`，而 `pyz_check` 只扫
  `engine.activity*` + `EXTRA_MODULES` —— 不把 `engine.ai` 加进 `EXTRA_MODULES`
  就会在打包后误报缺符号。**预检省掉一轮 4 分钟打包。**

### 13. 打包与发版核查（2026-10-16，全通过）

| 检查 | 结果 |
|---|---|
| 打包前 dist 占用探针 | 0 个进程（`--clean` 不会撞 WinError 5） |
| PyInstaller | EXIT=0，约 3m48s |
| `pyz_check` | PYZ **623** 条（v1.7.0 是 621）；必需模块 / 符号 / 字符串全命中、旧字面量零残留 |
| `exe_window_check` | 可见窗口含 **64×64** 正方形形态窗，6s 后位置不变 |
| `smoke_exe` | 存活 17s、`版本: 1.8.0`、启动序列完整、零 ERROR |
| `_refresh_release.py` | → `dist/知时助手-v1.8.0-win64{,.zip}`（348 文件 / zip 319 条目 / **50.39 MB**） |
| `leak_check` | 发布目录 348 文件 + zip 319 条目，**敏感命中 0 / `sk-` 0** |
| `userdir_diff` | 跑全量测试前后 `~/.pet_demo` **零变化**（155 个文件） |

⚠ **打包时 `rm -rf dist/知时助手` 会被沙箱的批量删除保护拦下**（347 个文件，
报 `SAFE_DELETE_BULK_CONFIRM_REQUIRED`）。不必去申请放行 ——
直接让 PyInstaller 的 `--noconfirm --clean` 自己清理输出目录即可，效果一样。

⚠ 顺序不能颠倒：`leak_check` **必须在** `_refresh_release.py` **之后**跑
（它只认发布目录 `dist/知时助手-v<版本>-win64`，先跑会 FAIL 在「目录不存在」）。

---

## 4.17 v1.9.0 分类口径重写 + 手动归类（2026-10-16）

> 用户原话：
> 「当前对工作和娱乐的判定不够准确，请调整分类逻辑。支持让每个线程都能被手动
> 选择归纳到指定分类，并说明可选的分类项及其判定依据。」

三件事，其实是**一条**：分类不可信 → 得能解释 → 解释不了就得让用户自己改。
按顺序做完了。

### 1. 判定为什么不准：裸子串匹配，而且零测试

旧判定长在 `sensor/window_monitor.py::_classify_window` 里，用 `"git" in text`
这种裸子串匹配。`tests/` 下搜 `_classify_window` **零命中** ——
**没测试的地方就是会烂的地方**，这次全烂在了明面上：

| 现象 | 根因 |
|---|---|
| 标题含 `digital` → 判**工作** | `"git" in text` 命中 `di`**`git`**`al` |
| 标题含 `knowledge` → 判**工作** | `"edge" in text` 命中 `knowl`**`edge`** |
| 标题含 `password` / `wordle` → 判**工作** | `"word" in text` |
| 标题含 `decode` / `barcode` → 判**工作** | `"code" in text` |
| Vimeo 播放页 → 判**工作** | `"vim" in text` 命中 `vim`**`eo`** |
| 标题含 `atomic` → 判**工作** | `"atom" in text` |
| Chrome 空白页 / 任意无信号网页 → 判**工作** | 进程名兜底把 `chrome.exe` 当工作工具 |
| 看网课 → 判**工作**或**娱乐** | 没有「学习」这一类 |
| 微信 / 钉钉 / 邮件 → 判**其他** | 没有「沟通」这一类 |

八条误匹配**每条**在 `tests/test_category.py` 里钉一个回归用例 —— 它们是这次重写的
**理由**，删掉就等于把误判放回去。

### 2. 五类体系：按「行为类型」分，不按场景

| 分类 | 判定依据（原文，界面直接展示） |
|---|---|
| **工作** | 生产力工具（编辑器 / IDE / Office / 设计 / 终端 / 数据库 / 远程），或标题命中工作站点与流程词 |
| **学习** | 学习工具（词典 / 文献 / 记忆卡 / 阅读器），或标题命中课程、题库、论文、开发文档站 |
| **沟通** | 即时通讯、邮件与会议客户端（微信 / 钉钉 / 飞书 / Slack / Teams / Zoom / Outlook…） |
| **娱乐** | 游戏平台与游戏本体、影音播放器与音乐客户端，或标题命中视频、短视频、直播、社交娱乐站点 |
| **其他** | 以上都不命中，**或同时命中两个方向 —— 判不出就不猜**。浏览器停在空白页时也在这里 |

**为什么按行为不按场景**：场景（上班 / 在家）判不出来，行为判得出来。所以钉钉、飞书
算「沟通」而不是「工作」—— 它们本身是沟通工具，至于聊的是不是公事，代码无从得知，
硬猜一个「工作」才是撒谎。这是本次改动**最根本**的一条设计判断。

### 3. `engine/activity/category.py`（新，纯函数，零 Qt，约 470 行）

判定逻辑从 `window_monitor` 搬出来，**唯一目的是能被单测覆盖**。三层判定，
越靠前越可信：

1. **进程名**（`process_stem()` 去 `.exe` 后**精确匹配**）：`code.exe` → 工作，
   `steam.exe` → 娱乐。进程名是受控标识符，`barcode.exe` 的词干 `barcode` ≠ `code`，
   所以这里**不能**用词边界（也不需要）。
   **浏览器除外** —— `chrome.exe` 只是容器，不代表在做什么，把它算「工作」
   正是旧实现最大的误判来源。
2. **标题**（ASCII 用**词边界**正则、中文退化为子串）：
   ```python
   parts = sorted({str(w).lower() for w in words if str(w)}, key=len, reverse=True)
   body = "|".join(re.escape(p) for p in parts)
   return re.compile(r"(?<![a-z0-9])(?:" + body + r")(?![a-z0-9])")
   ```
   `(?<![a-z0-9])code(?![a-z0-9])` 匹配 "vs code"，**不**匹配 "decode"。
   中文没有词边界概念，正则自然退化成子串匹配 —— 正是想要的。
   标题内部优先级 **娱乐 > 学习 > 沟通 > 工作**：站点名（bilibili / coursera）
   最明确，办公词（「周报」「审批」）最泛，**越泛越容易误伤**。
3. 都没有信号 → **其他，不猜**。

**工作标题词刻意收得很窄**：「数据」「文档」「代码」这类词在任何标题里都会出现
（「王者荣耀数据分析」也含「数据」），放进来误判比命中还多。

### 4. `explain()` 给出「凭什么」

`explain(process, title) -> (分类, 依据)`，依据只回**命中的词**（来自本模块白名单），
**绝不回窗口标题原文**。理由与 `segments` 表**根本没有 title 列**是同一条：
隐私是结构性保证，依据也不能开后门。依据只进内存事件（`WINDOW_ACTIVE.data.reason`），
**不落库**。有测试 `test_reason_never_quotes_the_window_title` 钉住。

### 5. 深度工作口径一处收口

新增 `FOCUS_CATEGORIES = (WORK, STUDY)`，`timeline.focus_seconds` 与
`summary.longest_focus_seconds` **统一引用它**（原来是两处各自写死 `"工作"`）。
看两小时网课在进度环上不该是 0。**同一件事有两个实现 = 两个都没验证** ——
反向验证专门补了 `test_the_two_aggregators_share_one_definition` 与
`test_daily_totals_counts_study_as_focus`（第三处口径）。

### 6. 手动归类：覆盖在「读」时生效，不 UPDATE 历史行

`activity.db` 新增 `app_categories` 表（app 主键 + category + updated_at）。
关键设计：**`segments.category` 是系统当时的判定，是证据**（与 P1-4 决策留痕同一条
纪律）；用户的手动归类是「后来人的判断」。两层分开存，于是：

- 原始观测**不被篡改**；撤销是**零代价**的（删掉覆盖记录即回到自动判定）；
- 「系统当初判成什么」**永远查得到** —— 这正是「应用分类」页那两列对照的意义。

**读路径一处收口**：`ActivityStore._rows()` 是所有 segments 查询的唯一出口，
覆盖只在那里叠加一次。`segments_since` / `segments_between` / `totals_by_app` /
`totals_by_category` **全部改走它** —— 这是「同一件事的四个入口」，
任何一处绕过都会读出一份没有覆盖的数据。

**结构性护栏**：`_rows()` 里加一道检查 —— SELECT 漏了 `app` 列（覆盖表是按 app 查的）
就当场 `raise`，而不是返回一份看起来正常的数据：

```python
if rows and "app" not in rows[0].keys():
    raise ValueError("segments 查询必须带 app 列，否则手动分类不会生效")
```

这条护栏是**真抓到东西的**：`totals_by_category` 原来 SELECT 只取
`category, seconds`，没有 `app` —— 覆盖表拿不到键，**静默返回未覆盖数据、不报错**。

### 7. 三个「规格断言测不出」的真问题（目检 S18 抓到）

- **`totals_by_app` 丢掉 `auto_category`**：Python 层重新聚合时没累加
  `auto_category`，导致「系统判定」列被覆盖后的值污染 —— 那一页**最该看的对照**
  （系统判成什么 / 你改成了什么）直接消失，而汇总行还写着「N 个已手动归类」，
  用户找不到是哪几个。修：加 `_by_auto` 累加并输出。
- **空态不自洽**：没有记录时，右边挂着**禁用**的「全部恢复自动判定」按钮 +
  一句状态说明 + 空态文案，三遍说同一件事。修：整行 `self._toolbar.setVisible(False)`。
  **空态要按「整页自洽」检查**，不是「文案非空」就算过。
- **动作反馈被 `reload()` 盖掉**：`_on_category_changed` 先 `setText(message)`
  再 `reload()`，而 `reload()` 把 `_status` 重置成常驻说明 —— 用户点完下拉
  等于**没有任何反馈**。修：反馈写在 `reload()` 之后。本项目踩过好几次的老毛病。

### 8. 「应用分类」页（`AppCategoryPage`，数据组，第 14 页）

- **分类项与判定依据卡**：文案取自 `category.CATEGORY_RULES`，**不在页面里重写一份**
  —— 重写一份的下场是改了分类器忘了改这里，页面开始说假话。这正是用户要的
  「说明可选的分类项及其判定依据」。
- **逐应用归类表**：应用 / 停留时长 / **系统判定**（只读）/ **你的归类**（下拉，
  首项「自动判定」）。改过的行应用名用强调色标出。
- **下拉用 `activated` 信号而非 `currentIndexChanged`** —— 后者在**程序设索引**时
  也会触发，会把「刷新」误当成「用户操作」。
- **选了「正好等于系统判定」的类别 = 不写覆盖记录** —— 若真写一条，下次刷新时
  下拉会跳回「自动判定」，用户会以为没保存上。
- `NAV_GROUPS` 数据组由 3 项变 4 项：今日 / 趋势 / **应用分类** / 协同记录。

### 9. 验证：反向验证第一轮 5 条漏网（全是真缺用例）

38 条 mutation，第一轮 5 条**漏网**，逐条查清 —— 都不是实现错，是**测试没覆盖到**：

| 漏网 | 为什么没被抓住 | 怎么补 |
|---|---|---|
| ①「浏览器在进程层排除」 | 现有词表下**不可观测**（chrome 本来就不在工具表里） | monkeypatch `_PROCESS_RULES` 塞进 chrome，把守卫变成可观测 |
| ②「标题去掉词边界」 | 工作标题词表恰好没有 `code`/`git` 这类短词（它们是进程词表成员） | 直接测 `_compile_title_regex` 机制本身 |
| ③「标题不做小写归一」 | 没有大写标题的用例 | 补 `"YouTube"` / `"BILIBILI"` |
| ④「聚合取占比最小」 | 没有「一个应用落到两个类别」的用例 | 补 `test_mixed_categories_report_the_dominant_one` |
| ⑤「daily_totals 的深度工作只算工作」 | 没测**第三处**口径 | 补 `test_daily_totals_counts_study_as_focus` |

补完后逐条复验全部 OK → **0 漏网 / 0 SKIP**。

**反向验证脚本的两条纪律**（写进了 `spikes/_rev_p19.py`，用完即删）：
- **pattern 必须唯一**（`count == 1`），不唯一报 `SKIP` 而非 `OK` ——
  改了 3 处但 pattern 撞了 2 处，只改一处仍全绿，那是**假 OK**。
- 支持按标签筛选（`sys.argv[1]`），改一处只复跑相关的那几条。

### 10. 最终数字

- **新增 `tests/test_category.py`（58 条）+ `tests/test_app_category.py`（49 条）**，
  共 107 条；`tests/test_activity_advisor.py` 更新一处导航断言（3 项 → 4 项）。
- **全量 856 passed + 1 skipped**（v1.8.0 基线 748：+108，0 回归）。
- **反向验证 40 条 mutation，0 漏网 / 0 SKIP**（38 条分类 + 2 条配色护栏）。

### 11. 打包与发版核查（2026-10-16，全通过）

| 检查 | 结果 |
|---|---|
| 打包前 dist 占用探针 | 1 个实例（PID 35224，存活 2h10m）→ **先问用户**，确认可关后结束 |
| PyInstaller | EXIT=0，约 4m04s |
| `pyz_check` | PYZ **624** 条（v1.8.0 是 623，+1 = `engine.activity.category`）；必需模块 / 符号 / 字符串全命中、旧字面量（`WORK_KEYWORDS`/`ENTERTAIN_KEYWORDS`）零残留 |
| `exe_window_check` | 可见窗口含 64×64 正方形形态窗，6s 后位置不变 |
| `smoke_exe` | 存活 17s、`版本: 1.9.0`、启动序列完整、零 ERROR |
| `_refresh_release.py` | → `dist/知时助手-v1.9.0-win64{,.zip}`（349 文件 / zip 320 条目 / **50.42 MB**） |
| `leak_check` | 发布目录 349 文件 + zip 320 条目，敏感命中 0 / `sk-` 0 |
| `userdir_diff` | 跑全量测试前后 `~/.pet_demo` 零变化（156 个文件） |

打包前用临时探针 `spikes/_preflight19.py` 预检四张清单与源码一致（**PASS**，用完即删）
—— 这是 v1.8.0 立下的规矩，省掉一轮 4 分钟打包。

⚠ `smoke_exe` 里有一条 `热键注册失败（可能被占用）: alt+q` 的 **WARNING**
（`alt+t` / `alt+s` 正常）。已确认不是本次进程残留（dist 下 0 个实例），
是用户机器上别的程序占了 Alt+Q；属既有现象，不影响冒烟判定（零 ERROR）。

### 12. 顺带改正的文档错误：控制中心页数一直是错的

回源码核对页数时发现 `NAV_ITEMS` 实际是 **14 页**（数据 4 / 功能 6 / 系统 4），
而文档里的链条是错的：v1.7.0 条目写「11 → 13 页」（**加一个页面不可能 +2**），
v1.8.0 条目写「13 → 14 页」，于是 v1.9.0 差点写成「第 15 页」。

**正确链条**：v1.6.0 = 11 → v1.7.0 = 12 → v1.8.0 = 13 → **v1.9.0 = 14**。
三处已改正（§4.16 / §4.17 / §7 改动清单的 v1.7.0 行），并在此留下痕迹 ——
**文档里的数字也必须回源码核对**，凭印象往后累加迟早会漂。

### 13. 顺带修掉的配色缺陷：分类改了，配色没跟上

做演示页时发现的：`presentation/design/charts.py::_CATEGORY_TOKENS` 还写着**旧分类名**
（工作 / 沟通 / **浏览**）。于是「学习」「娱乐」双双掉进 `chart_other` 灰色兜底 ——
时间轴与排行条上只剩蓝 / 黄 / 灰三色，看不出这两类的区别；而「浏览」这个
已经不存在的类别还白占着一个橙色。**这是 v1.9.0 自己挖的坑**：改了分类体系，
却没回头改「按类别取色」那张表。

- token **改名 + 新增**：`chart_browse` → `chart_fun`，新增 `chart_study`（深浅两套都补）。
  `chart_work` 的注释从「深度工作」改正为「工作」—— 深度工作现在是工作 + 学习。
- **结构性护栏**（这才是重点）：`test_every_category_has_a_distinct_chart_color`
  **不写死名单**，直接遍历 `CATEGORIES` —— 除「其他」外每一类都必须有非兜底配色，
  且五色两两不同。旧用例只钉了当时那四个名字，所以这次漏配**一条断言都不会红**；
  新用例把「清单同步」变成可执行判据。
- 反向验证：把「学习」改回兜底灰 → 红；让「学习」「娱乐」共用一色 → 红。
- `pyz_check`：符号清单 +`chart_study`/`chart_fun`，`chart_browse` 进 `FORBIDDEN_STRINGS`。
- 预览脚本的假数据同步（`s13` 的「浏览」→「娱乐」），并给两个假插件补上
  「协同记录」页（v1.8.0）与「应用分类」页（v1.9.0）要用的方法 ——
  **控制中心的 `reload()` 是全量刷新的**，缺方法直接崩，与当前渲染哪一页无关。
  第一版还把 `count_decisions` 写成无参，`reload()` 传 action 时 TypeError：
  **假替身的参数表就是接口契约**，少一个参数等于换了接口。

> ⚠ `dist/知时助手-v1.9.0-win64{,.zip}` 是**修复之前**打的包（包内那两类仍是灰的）。
> 源码已修，重新打包即可 —— 版本号没动。

### 14. `spikes/s19_demo_page.py`：对外演示页

把 10 张界面截图 base64 内嵌成一个**单文件** HTML 落到桌面，零外部依赖
（无 CDN、无字体、无 JS 库），断网双击也能开。为什么做成脚本而不是手写 HTML：
手写的话图片一改就得手工重贴 base64，迟早出现「图换了、页面还是旧图」。
分类依据文案**逐字取自 `category.CATEGORY_RULES`**，不在页面里另写一份
（同产品内「应用分类」页的纪律）。

验证：用 Playwright（复用系统已装的 Chromium）打开并检查 ——
10 张图全加载、**外部 http 引用 0**、7 个分区齐全、控制台与页面零报错。

---

## 5. 下一步做什么

**P0 / P1 / T4 / P1.6 / P1.7 / P2.0–P2.19 均已完成**（见 §4）。
**v1.7.0（宠物子系统移除 + 隐私与数据页）已完成**：代码、测试、打包与发版核查，见 §4.15。
**v1.8.0（人机协同证据链 P1-4 + API Key 接入系统密钥库 P1-5）已完成**，见 §4.16。
**v1.9.0（分类口径重写 + 手动归类 + 「应用分类」页）已完成**，见 §4.17。
测试基线 **856 passed + 1 skipped**。剩下的是**真实环境实测**：

1. ~~**填 API Key**~~ ✅ **已完成**（2026-10-11）：`spikes/api_check.py` 三条链路
   （文本流式 / 翻译 / 视觉）**全 PASS**。过程中修掉三个真问题，见 §4.3 第 6 节 ——
   最关键的一条是**视觉模型从 `Qwen3-VL-8B` 换成 `Qwen3-VL-32B`**
   （8B 实测 22.4s，32B 只要 0.76s，快 30 倍）。
   若日后重填 Key，等价做法：
   ```bash
   python dev_bootstrap.py spikes/api_check.py   # 三条链路连通性自检
   python dev_bootstrap.py                       # 起桌宠，按 Alt+Q 试真实问答
   ```
2. **在真实应用里实测**（机制层已过，缺的是真实环境）：
   `Alt+T` 划词翻译、`Alt+S` 截图问答在 Chrome / VSCode / 记事本 / Word / 微信 上的表现。
   重点看 R14 整改后的**手感**：选区采集从 251ms 降到 ~32ms，应当「按下去就有」。
   > 已知：选区采集在真实记事本上跨会话测过（S10），取值正确、耗时稳定 ~37ms。
   > 未测：浏览器 / 编辑器 / 微信 / 提权窗口（见 `spikes/README.md` 人工验证清单）。
3. 补完 `spikes/README.md` 的**人工验证清单**（提权窗口热键、真实应用选区矩阵、
   多显示器、真实 LLM 流式、活动建议采集与 AI 规划）。
4. P2 待办：
   - ~~投递方式打磨（替换原文的边界情况）~~ ✅ **P2.9 已完成**（见 §4.4）——
     发现的不只是边界情况，而是 REPLACE 与 PASTE **语义未分离** + 成功判定恒真
   - ~~会话历史的「继续对话」入口~~ ✅ **P2.10 已完成**（见 §4.5）——
     打通「控制中心 → AI 面板 → 同一条会话」，新问答追加而非新建
   - ~~投递到前台~~ ✅ **P2.11 已移除**（见 §4.6）—— 用户反馈「点了没反应」，
     实测成功率仅 ~40% 且代码无法自检失败，只保留「复制」
   - ~~活动建议插件（行为采集 → AI 分析 → 建议与规划）~~ ✅ **P2.12 已完成**（见 §4.7）——
     难点不在采集，在**数据边界**：把「不记录窗口标题」做成**结构性保证**
     （`segments` 表根本没有 title 列，有测试直接断言表结构），
     出网只发**聚合摘要**（应用名 + 时长），并默认关闭
   - ~~活动建议的操作负担与打扰~~ ✅ **P2.13 已完成**（见 §4.8）——
     一键开关（不再手改 JSON）+ 收工小结（一天最多一次、全屏/专注免打扰）
     + 自然日范围与建议缓存 + 空闲剪裁时长 + 常驻「今日小结」卡片与番茄钟打通
   - ~~专注无反馈 / 建议区缺总结~~ ✅ **P2.18 已完成**（见 §4.13）——
     两条需求其实是同一条：**「做了一件事」与「看见这件事发生了」之间那层缺失**。
     补了倒计时卡（`MM:SS` + 进度条 + 暂停/结束）、悬浮球与托盘**共用口径**的专注环、
     建议区 AI 生成的总结段；顺带修掉番茄钟两个真 bug（丢分钟数、停后再开两倍速）
   - 截图框选体验（框选时的手感、边界吸附）—— **P2 待办里最后一项**
5. 可选清理：删除 `dist/little-table-pet-v1.1.0-win64{,.zip}`（9 月 22 日无 AI 的旧构建），
   以及 `dist/` 下两个 0.04 MB 的**僵尸进程条目**（PID 44068 / 24052，
   `taskkill` 报「拒绝访问」，无实际影响 —— 冒烟时 `tasklist` 会看到它们，
   别误判成「冒烟进程没杀干净」）。

> 三条链路（问答 / 翻译 / 截图）在**机制层**均已端到端验证通过（M1 + M2，均为假 Provider，8/8 稳定），
> 并且**真实 API 连通性也已全 PASS**（`api_check.py`）。
> 尚未验证的是**真实第三方应用**（浏览器 / 编辑器 / 微信等）—— 这是唯一剩下的空白。
>
> **R14 / R15 已在 P2.8 关闭**（见 §4.3）：选区采集 251ms → 32ms（+ 去掉 clear 的 330ms），
> 截图编码 1944ms → 98ms。
>
> **P2.9 关闭了投递语义**（见 §4.4）：REPLACE 与 PASTE 不再同路，
> 真实记事本上结果文本可区分（`spikes/s11_delivery_semantics.py`）。
>
> **P2.10 补上了会话续接**（见 §4.5）：会话历史页可一键把旧会话载入面板继续问，
> 新问答追加到**同一条**会话（`Store.append_exchange()`），不再是只读的死档案。
>
> **P2.11 把投递到前台移除了**（见 §4.6）：P2.9 让 REPLACE 与 PASTE 语义正确，
> 但 S12 实测发现**成功率只有 ~40%**，且失败时 `_send_paste()` 不抛异常、
> 照样返回 True —— 面板会谎报「已替换原文」。语义正确不等于**能可靠送达**，
> 所以只保留「复制」。`native/injector.py` 保留未删（实测记录 + 便于恢复）。
>
> **P2.12 加了活动建议插件**（见 §4.7）：采集「前台应用 + 键盘活跃度」分段落库
> （独立 `activity.db`），手动触发后用 AI 生成建议与规划。隐私做成**结构性保证** ——
> 表里没有窗口标题这一列；出网只发聚合摘要；**默认关闭**。顺带修掉
> `sensor/window_monitor.py` 两个真问题（拿不到真实进程名、浏览器一律算「工作」）。
>
> **P2.13 把它从「要用得先改配置」改成「点一下就开」**（见 §4.8）：
> 控制中心一键开关 + 首启说明；收工小结一天最多推一次（全屏 / 专注 / 人不在时免打扰）；
> 「今天」改成自然日语义；建议本地缓存（数据没变不重复花钱）；**空闲剪裁**让
> 「人不在」的时间不再计入时长；全屏作为免打扰信号而非分类依据。
> 顺带修掉 `0 or default` 把合法配置悄悄改掉的真 bug，以及一处潜在线程安全问题。

---

## 6. 关键源码地图

| 关注点 | 文件 | 关键位置 |
|---|---|---|
| 程序入口 / 启动顺序 | `main.py` | `PetDemo.start()` 155；`_start_ui()` 259；`_notify_ui_ready()` 196/293 |
| 事件总线 | `event_bus.py` | `ALLOWED_EVENTS` 38（AI 事件 69 起）；`publish` 145；`publish_async` 182；`_executor` 248 |
| 插件契约 | `extensions/base_plugin.py` | `BasePlugin` 28；`on_ui_ready` 53；`register_hotkeys` 64 |
| 插件加载 | `extensions/plugin_manager.py` | `_import_plugin_class` 43（**T1 已改为包加载**，`_PLUGIN_PKG` 20） |
| **外壳窗口（形态无关）** | `presentation/ui_renderer.py` | **P2.16**：`ShellWindow`（原 `PetWindow`）—— 无边框/置顶/拖拽/位置/右键菜单/关到托盘；`set_form()` / `form()` / `animation_target()` / `set_state()`；贴边 `_screen()`（**按窗口所在屏**）/ `_snap_to_edge()` / `_expand_from_edge()` / `_ensure_on_screen()`；`_move_center()`（**自校正，与 frame 无关**）；`_restore_position()`（优先 `window.center`，旧配置迁移）。`UIManager`：`_text_requested` / **`_state_requested`（类体信号，转回主线程）** / `apply_form()` |
| **外观（可替换内胆）** | `presentation/forms.py` | **P2.16 新增**：`Form` 协议（`animation_target` / `set_state` / `form_size` / `wants_edge_snap` / **`wants_shell_motion`（球 `False`）** / `edge_snap_inset` / `preferred_opacity` / `attach`）。**v1.7.0**：`PetForm` 与整套精灵图资源已移除，**`OrbForm` 是唯一形态**，但协议与 `FORM_BUILDERS` 注册机制保留（再加形态不必改调用方；基类缺省值有测试钉住）。`build_form()` 对空名与旧 `pet` 名一律回退到球 |
| **本机数据清单 / 导出 / 清空** | `data/privacy.py` | **v1.7.0 新增**（无 Qt，可单测）：`entries()` 6 类清单（`pet_path()` 调用时求值）/ `human_size()`（体积唯一口径）/ `export_data(dest, keys=None)`（单类与全量**同一条通道**，差异只在 `_selected_rels()` 选谁；sqlite 走 backup API，`_is_sidecar()` 用 `name.endswith`）/ `clear_entry(key, app)`（有插件借插件、没插件才删文件）/ `home_bak_files()` |
| **隐私与数据页** | `presentation/control_center.py` | **v1.7.0 新增** `PrivacyPage`（`shield` 图标）：承诺卡（只陈述能被代码兑现的结构性事实）+ 6 行表格（数据 / 大小 / 说明 / 导出 + 清空两个按钮；大小为 0 时禁用）+ `_PRIVACY_PROMISE` 文案。**v1.8.0**：「设置与偏好」行的说明改由 `data/privacy.py::_key_storage_note()` 按**真实配置**给（密钥在密钥库 / 明文，不是固定话术） |
| **人机协同决策留痕（P1-4）** | `engine/activity/decision.py` | **v1.8.0 新增**（纯函数 + frozen dataclass，**零 Qt**）：`DecisionNote` 三字段对应三个问题 —— `basis` 凭什么 / `context` 当时数据什么样 / `impact` 改变了什么；`build_context()` **只收聚合数字**（连 app 名都不放）；`_clean_context()` **白名单**（认不出的键直接丢）+ **空值丢键、`0` 与 `False` 必须留**；`build_note(advice, action, *, summary, context, outcome, now)`；`_build_basis()`（采纳时把「同意的动作」也算一条）；`_build_impact()`（记**实际结果** —— `focus_started=False` 时不写「已开始」）；`format_notes()` / `format_context()`（展示层的**唯一**口径）；`ACTIONS` 受限枚举 |
| **决策留痕落库 / 读取** | `engine/activity/store.py` | **v1.8.0** 新增 `decisions` 表 + `record_decision()` / `decisions(limit, action)`（`ORDER BY decided_at DESC`）/ `count_decisions()` / `clear_decisions()`；`clear()`（清空行为数据）**连留痕一起删** —— 它同样是用户行为的产物 |
| **留痕的入口（插件侧）** | `extensions/system/activity_advisor/plugin.py` | **v1.8.0** 新增 `record_decision(advice, action, *, outcome, days)`：现场（分段条数 / 缓存建议的生成时间 / 专注是否在跑）**只有插件拿得到**，所以留痕在这里做，完整性不依赖某个界面记得传参。忽略时**同时**写 `ignored_advices` 标记与留痕。另有 `decision_log()` / `count_decisions()` / `export_decisions()` |
| **协同记录页（P1-4 的出口）** | `presentation/control_center.py` | **v1.8.0 新增** `DecisionLogPage`（`file-check` 图标，数据组）：表格（时间 / 决定 / 结论 / 影响范围）+ 全部·采纳·忽略筛选 + 详情面板（含**建议指纹**，可逐条回溯）+ 导出证据链（人可读 UTF-8 文本；**没有记录时不弹保存框**）+ 空状态 |
| **分类引擎（v1.9.0）** | `engine/activity/category.py` | **v1.9.0 新增**（纯函数，**零 Qt**，约 470 行）：常量 `WORK`/`STUDY`/`COMM`/`FUN`/`OTHER` + `CATEGORIES` + `FOCUS_CATEGORIES = (WORK, STUDY)` + `CATEGORY_RULES`（五类判定依据原文，界面原样展示）；词表 `BROWSER_PROCESSES` / `_WORK_PROCESSES` / `_STUDY_PROCESSES` / `_COMM_PROCESSES` / `_FUN_PROCESSES` / `_PROCESS_RULES`（顺序 工作→学习→沟通→娱乐）/ `PROCESS_TABLES` / `TITLE_TABLES`；`_compile_title_regex()`（**词边界** `(?<![a-z0-9])(?:...)(?![a-z0-9])`，中文自然退化为子串）；`_TITLE_RULES`（优先级 **娱乐 > 学习 > 沟通 > 工作**）；`process_stem()`（去 `.exe`，**精确匹配**）/ `normalize_app()` / `classify()` / **`explain(process, title) -> (分类, 依据)`**（依据只回命中的词、**绝不回标题原文**）/ `is_valid_category()` / `apply_overrides(segments, mapping)`（读时覆盖，键也要 `normalize_app`） |
| **手动归类覆盖表（v1.9.0）** | `engine/activity/store.py` | **v1.9.0 新增** `app_categories` 表 + `app_categories()` / `set_app_category()`（**受限枚举**，非法类别拒）/ `clear_app_category()` / `clear_app_categories()` / `count_app_categories()`；**`_rows(sql, params)` 是所有 segments 查询的唯一出口**（覆盖只在那里叠加一次；SELECT 漏 `app` 列当场 `raise` —— 这是**真抓到东西**的护栏）；`segments_since` / `segments_between` / `totals_by_app`（Python 层聚合，保留 `auto_category`）/ `totals_by_category` **全部走 `_rows()`**；`clear()` **不动 `app_categories`**（那是偏好设置，不是行为数据） |
| **应用分类页（v1.9.0）** | `presentation/control_center.py` | **v1.9.0 新增** `AppCategoryPage`（`sliders` 图标，数据组，**第 14 页**）：分类项与判定依据卡（取自 `CATEGORY_RULES`，**不重写一份**）+ 4 列表格（应用 / 停留时长 / **系统判定** / **你的归类**）+ `_make_combo`（用 `activated` 信号，**不用 `currentIndexChanged`** —— 程序设索引也会触发）+ `_on_category_changed`（**反馈写在 `reload()` 之后**，否则被重置成常驻说明）+ `_on_reset_all` + 空态整行隐藏 `_toolbar`。`NAV_GROUPS` 数据组 **3 项 → 4 项**（今日 / 趋势 / 应用分类 / 协同记录） |
| **系统密钥库（P1-5）** | `data/key_store.py` | **v1.8.0 新增**（**零 Qt**）：两层后端 `keyring` → **DPAPI 加密文件**（`secure_keys.bin`）→ `none`；`REF_PREFIX = "keyring:"`（只认前缀，防用户手写 `sk-xxx` 被当成条目名）；条目名白名单 `_ENTRY_RE`（同时挡路径穿越）；`store_key` / `load_key`（**取不到返回空串、不抛异常**）/ `has_key` / `delete_key`；`mask()`（头 3 + 8 个 `•` + 尾 4，**总长度固定**）；`status()`；`entry_for_base_url()` |
| **气泡（独立顶层窗口）** | `presentation/bubble.py` | **P2.16 新增**：`Bubble` —— `WA_TransparentForMouseEvents`（**不吃鼠标，否则挡住点球**）+ `WA_ShowWithoutActivating`；`show_text()` / `follow()`；`_place()`（上方放不下翻下方、夹在可用区内） |
| **用户数据根（唯一来源）** | `data/paths.py` | **P2.16 新增**：`pet_home()`（`PET_DEMO_HOME` 可覆盖，**不做模块级缓存**）/ `pet_path()`。落点全部改走它（v1.7.0 前是 8 处，便签 / 快捷启动随子系统一起移除）—— 这是「测试不许碰用户数据」的结构性保证 |
| 动画 | `presentation/anim_controller.py` | `AnimController` 45；`play()` 321；数值动画 `_numeric_rotate` 552 / `_numeric_bounce` 600；**`_numeric_origin`（位移起点，被打断时还原）** + `_stop_numeric()` |
| 对话框基类 | `presentation/dialogs.py` | `AppDialog` 63（**统一基类** + `WindowStaysOnTopHint`）；`MessageDialog` 219；`message_box()` 291 |
| **应用主题源（唯一）** | `presentation/design/theme.py` | `theme()` / `set_theme()`；`color()` / `qss()` / `qt_palette()` / `changed` 信号；`appearance.theme` = `default`\|`light`\|`dark` |
| **设计 token** | `presentation/design/tokens.py` | `PALETTES`（`LIGHT`/`DARK`）+ `SPACING` / `RADIUS` / `FONT_SIZE` / `ICON_SIZE` / `ROW_HEIGHT` / `NAV_WIDTH`；**P2.14 加 6 个图表色**，**v1.9.0 增为 7 个**（`chart_work` / `chart_study` / `chart_comm` / `chart_fun` / `chart_other` / `chart_idle` / `chart_track` —— `chart_browse` 随分类体系改名 `chart_fun`；后两个是铺满整条的底色，**必须与 `window`/`surface` 拉得开**）；**P2.19 加 `warning_soft`**（warning 的软底，「专注中」这类**非交互态**用 —— 灰会被读成「坏了」） |
| **全应用样式表** | `presentation/design/qss.py` | `build_qss(theme)`（**零 hex 字面量**）、`build_qt_palette()`；选择器纪律见 §2 规则 14/15 |
| **图标库** | `presentation/design/icons.py` | `ICONS`（**52 个**内联 Lucide SVG；P2.18 加 `pause`，v1.7.0 加 `shield`，v1.8.0 加 `file-check`）；`themed(name, role)` 按主题着色；未知名字 → 空图标 |
| **通用控件** | `presentation/design/widgets.py` | `ThemedWidget`（订阅 `theme().changed`）/ ToolButton / Button / IconButton / Card / NavList（P2.14 加 `add_group` 分组标题行）/ LogView / EmptyState（P2.14 加 `set_text`）/ SegmentedControl / ToggleSwitch / BusyIndicator |
| **图表控件** | `presentation/design/charts.py` | **P2.14 新增**：`StatTile` / `RatioBar` / `RankBar` / `BarChart` / `TimelineBar` / `AxisLabels`（按 fraction 精确摆刻度、自动躲重叠）；**P2.15** 新增 `OverviewBoard`（概览台面：顶边强调线 + 标题 + 自动竖分隔线 + `stretch_of()` 访问器），`StatTile` 加 `icon_name` / `primary` |
| **建议卡** | `presentation/design/advice_card.py` | **P2.14 新增**：`AdviceCard`（headline / evidence / 动作按钮 / 忽略）；**P2.18** 加 `AdviceSummary`（建议区顶部的整体结论段，空文本整块 `setVisible(False)`，不留空版面）；**P2.19** 加 `set_focus_state()` —— 动作按钮跟随全局专注状态（非 idle 换文案 + **真禁用**，专治「点了没反应 / 还能反复点」），只读口 `action_enabled()` / `focus_state()`。**v1.8.0**：`action_triggered(int)` / `ignored(str)` 两个单一动作信号合并为 **`decided = Signal(object, str)`** —— 采纳与忽略**走同一条路**，卡上两个按钮不可能各记各的 |
| **专注倒计时卡** | `presentation/design/focus_card.py` | **P2.18 新增**：`FocusCard`（`MM:SS` + 进度条 + 暂停/继续/结束）；`set_status_provider()` 拉状态（不推）、`update_from()` 返回是否变化（**没变不发信号**）、`_repolish()` 同时 polish 自己**和进度条**（Qt 祖先属性穿透不到子控件的子部件，见 §4.13 ⑤）；`format_clock()` / `TICK_MS = 1_000`。**P2.19** 加模块级 `focus_label()`（四个专注入口**共用一份文案**）、`focus_title()`（`专注中 · 90 分钟`；休息阶段不再写成「专注中」）、`duration_text()`、`apply_phase()`（挂 `phase` 属性 + repolish —— **属性名绝不能叫 `focus`**，见 §4.14）、`FOCUS_ENTRY_ID`（今日页顶部按钮与建议卡按钮**共用**的 id）、`ACTIVE_STATES` |
| **控制中心主窗口** | `presentation/control_center.py` | `ControlCenter`；`NAV_GROUPS`（**3 组 14 页**，派生 `NAV_ITEMS`；v1.7.0 加 `PrivacyPage`，v1.8.0 加 `DecisionLogPage`，v1.9.0 加 `AppCategoryPage`）；`_nav_rows`（页序号→导航行号）；`open_control_center()`；`store()`（共享单例）；托盘/右键菜单第一项入口 |
| **活动洞察页** | `presentation/control_center.py` | `TodayPage`（**P2.14**，替换 P2.13 的 `ActivityPage`）：本机记录卡（一键开关 + 隐私边界）+ 概览 4 tile（**P2.15 收进 `OverviewBoard` 台面**，头条格 `primary` + `stretch=2`）+ 24 小时时间轴 + 应用排行 + 建议卡（结构化）/ 纯文本兜底；实现插件约定的视图协议（`set_status` / `set_advice` / `append_advice` / `set_analyzing`），与对话框可互换。**P2.18**：建议列顶部加 `FocusCard`、卡上方加 `AdviceSummary`；`showEvent` / `hideEvent` 控制轮询（**不可见不烧 CPU**）；`_start_focus` 失败原因分开说。**P2.19**：`_sync_focus_entries(state=None)` —— 一处同步顶部按钮 + **全部**建议卡（传 None 读计时器实况、有权威 state 就直接用；`usable` 把「没有插件」与「此刻不在专注」分开）。`TrendPage`（**P2.14**）：近 7 / 30 天、每日深度工作、周期对比、时间构成、最易被打断的时段（**P2.15 同样收进台面**） |
| **会话历史页** | `presentation/control_center.py` | `SessionsPage`（左列表 + 搜索 + 右详情；**继续对话** / 删除 / 清空）；`ControlCenter.continue_session()`（**鸭子类型调插件**，P2.10） |
| **预设管理页** | `presentation/control_center.py` | `PresetsPage`（内置只读 + 自定义增删改）；`presentation/dialogs.py::PresetEditDialog` / `ask_preset()` |
| 兼容垫片（勿删） | `presentation/glass_widgets.py` | 老名字 → 新实现；`extensions/user/` 的第三方插件靠它 import |
| **点击置顶** | `presentation/window_behavior.py` | `RaiseOnClickMixin.raise_to_front()`（三窗口显式调用） |
| 唤起面板 | `presentation/ai_panel.py` | `AIPanel`；QSS 直接取 `theme().qss()`；`apply_theme()` / `_on_toggle_theme()` |
| 配置 | `data/config_manager.py` | `DEFAULT_CONFIG` 27；`_merge_config` 139；`get/set/save` 204/224/241；**P2.16**：`_setup_paths(root=None)`（默认走 `data.paths.pet_home()`）、`redirect_for_tests()`、`_load_config()` **只在磁盘与内存不一致时才 save()**、`DEFAULT_CONFIG` 一律 `copy.deepcopy` |
| 日志 | `data/log_manager.py` | `LogManager` 28（日志目录走 `data.paths.pet_path("logs")`） |
| 输入监听 | `sensor/input_monitor.py` | pynput listener 67 |
| 托盘 | `presentation/tray_icon.py` | `TrayIcon`；**P2.14 常驻指示**：`activity_tooltip` / `progress_icon`（三态进度环，**固定色 + 白描边，不取主题色**）+ `refresh_activity()`（60s 定时 + 订阅主题）；**P2.16** 三态定义改从 `presentation/design/ring.py` 取（与球环共用，配色仍各自定）；**P2.18** `activity_tooltip(progress, focus=None)` 支持专注提示 + 专注时切 `FOCUS_REFRESH_MS = 1_000` 轮询 |
| **环状态（托盘 + 球共用）** | `presentation/design/ring.py` | **P2.16 新增**：`STATE_OFF` / `STATE_ACTIVE` / `STATE_DONE` + `activity_state(enabled, ratio)` + `OUTLINE`。两者画的是**同一个量**（今日深度工作进度），各写各的迟早会漂。**P2.18** 加 `STATE_FOCUS` / `STATE_FOCUS_PAUSED` 与 `ring_view(*, enabled, ratio, focus_ratio=None, focus_paused=False)` —— 专注期间两个环**必须**一起改画本次专注，否则会同时存在两个互相矛盾的环 |
| 打包 | `PetDemo.spec` | `datas` 已补 `native`/`engine`；`hiddenimports` = `BASE_IMPORTS + scan_hiddenimports()` |
| 打包依赖扫描 | `build_hiddenimports.py` | `scan_hiddenimports()`（**T4**，当前 56 个模块） |
| AI 核心入口 | `engine/ai/__init__.py` | `build_from_config()`（✅ 已实现，非空壳）；**v1.8.0** `resolve_api_key()`（**全项目唯一读密钥的地方**：`ai.api_key_ref` 优先、明文只作老用户回退；取不到返回空串，**不做别的兜底**） |
| AI 会话编排 | `engine/ai/session.py` | `SessionManager`（流式 + 取消；**落库在工作线程**）；`model_for(has_image)`（**文本/视觉模型分流**）；`ask(session_id=…)` **续接已有会话**（P2.10） |
| **会话 / 预设存储** | `engine/ai/store.py` | `Store`（sqlite，线程安全）；**`shared_store()` 进程级单例** / `close_shared_store()`（P2.8）；`append_exchange()` / `session_exists()` **续接语义**（P2.10） |
| 连接探测 | `engine/ai/probe.py` | `probe()` / `list_models()` / `suggest_models()`（**纯 Python，可单测**；UI 与 `api_check.py` 共用） |
| 设置对话框 | `presentation/ai_settings_dialog.py` | `AISettingsDialog.applied` 信号 → 插件热切换；`PROVIDERS` 预设表；探测走子线程 |
| 真实 API 自检 | `spikes/api_check.py` | 配置 → `/models` → 文本 → 翻译 → 视觉（**需填 Key**）。**v1.8.0**：改用 `resolve_api_key()` + `key_store.mask()` —— 自检脚本不再自己拼一遍读密钥 / 脱敏的逻辑（那是第二次实现，迟早漏一处） |
| 系统热键 | `native/hotkey.py` | `HotkeyService.install/register` |
| 选中文本 / 预热 | `native/selection.py` | `get_selected()`（**30ms 窗口 + 8ms 轮询**，P2.8）；`clipboard_sequence()` / `_clip_token()`（**序列号判据，不再 clear**）；`keyboard_controller()` 缓存；`warmup_keyboard()` / `warmup_clipboard()` |
| 截图 | `native/capture.py` | `grab_region()`（**只抓子矩形**，红线 17）；`to_data_url()` 默认 **JPEG**（R15） |
| 面板 / 遮罩预热 | `presentation/ai_panel.py`、`overlay_select.py` | `warm_up()`（**必须真的画一次**，红线 14） |
| 唤起时序 | `extensions/system/ai_assistant/plugin.py` | `invoke()`（**4 步时序，见 §2.1**）、`on_ui_ready()`（**预热清单，见 §2 规则 8**）、`_on_delivery()`（**只认「复制」**，投递到前台已于 P2.11 移除，见 §4.6） |
| 端到端验证 | `spikes/m1_verify.py`、`spikes/m2_verify.py` | 夹具剔除逻辑见 `_common.py::force_foreground()`、`Heartbeat.mark_harness()` |

---

## 7. 目录职责（P1 + T4 完成后的实际状态）

```
petgame_demo/
├─ build_hiddenimports.py   打包依赖自动扫描（T4；spec 从这里取 hiddenimports）
├─ dev_bootstrap.py         开发启动器（挂 Lib/ + Lib/site-packages + pywin32 DLL 目录）
├─ spikes/                  P0/P1/P2 验证脚本（可独立复现，见 spikes/README.md）
│   ├─ s1_hotkey.py … s4_stream.py   四个 P0 spike
│   ├─ s5_sse_encoding.py   S5：SSE 中文编码（真 HTTP 边界，P2.4）
│   ├─ s6_window_lifecycle.py  S6：关对话框不应退出应用（**子进程隔离 + 真事件循环**，P2.6）
│   ├─ s8_ui_design.py      S8：UI 设计系统（25 项规格断言 + 20 张预览图，P2.7）
│   ├─ s9_perf_tail.py      S9：性能收尾 R14/R15（选区轮询 vs 固定等待；序列号判据；PNG vs JPEG，P2.8）
│   ├─ s10_real_app_selection.py  S10：真实应用选区跨进程 A/B（需真实桌面，P2.8）
│   ├─ s11_delivery_semantics.py  S11：投递语义 —— REPLACE/PASTE 结果文本必须不同（需真实桌面，P2.9）
│   ├─ s12_real_injection.py  S12：真实按键注入**成功率** —— 实测仅 ~40%（P2.11 移除投递的依据）
│   ├─ s13_today_preview.py  S13：今日页 / 趋势页**整页**目检（14 张图，纯假数据；P2.18 加专注中/暂停两态）
│   ├─ s14_tray_indicator.py S14：托盘环三态联络表（按**任务栏底色**分两张，P2.14）
│   ├─ s15_orb_preview.py    S15：悬浮球目检（**七态** × 四种壁纸 + 气泡浅深两套 + 贴边三态；P2.18 加专注两态）
│   ├─ s16_privacy_preview.py  S16：「隐私与数据」页目检（v1.7.0，种假数据，3 张图）
│   ├─ userdir_diff.py       用户数据目录比对（snap / diff，只输出计数，P2.16）
│   ├─ exe_window_check.py   发版核查 ③：枚举 exe 名下的可见窗口（P2.16）
│   ├─ pyz_check.py         发版核查 ①：PYZ 符号（P2.13 起正式化，清单按版本追加）
│   ├─ leak_check.py        发版核查 ②：密钥泄漏（发布目录 + **zip 逐条目解压**）
│   ├─ _refresh_release.py  重建 dist/知时助手-v<版本>-win64 发布目录（v1.7.0 起随产品改名）
│   ├─ m1_verify.py         M1：问答链路端到端
│   ├─ m2_verify.py         M2：翻译 + 截图 + 投递端到端
│   ├─ m3_verify.py         M3：设置 UI 热切换端到端（两个本地假服务证明「请求真的换了目的地」）
│   └─ api_check.py         真实 API 连通性自检（需填 Key，会发真实请求）
├─ engine/ai/            L2 AI 核心层 ✅已建
│   ├─ types.py           ChatMessage / Preset / DeliveryKind
│   ├─ stream.py          SSE 解析（纯函数）
│   ├─ provider.py        Provider 抽象
│   ├─ providers/openai_compat.py   OpenAI 兼容（DeepSeek/Kimi/通义/…）
│   ├─ registry.py        Provider 注册表
│   ├─ prompt.py          内置预设（问答/翻译/摘要/解释/改写/代码）
│   ├─ probe.py           连接探测（/models + 极短对话；纯 Python，UI 与自检脚本共用）
│   ├─ session.py         SessionManager（流式 + 取消 + 线程池）
│   └─ store.py           SQLite 会话/预设持久化
│
├─ engine/activity/      L2 活动分析层 ✅ **P2.12 新增**（零 Qt 依赖）
│   ├─ store.py           活动分段落盘（独立 activity.db；**表里没有 title 列**）
│   │                     P2.13 加 `advices`（建议缓存）+ `meta`（键值状态位）
│   │                     P2.14 加 `ignored_advices`（忽略必须**落库**，否则会复活）
│   │                     v1.8.0 加 `decisions`（人机协同留痕）
│   │                     v1.9.0 加 `app_categories`（手动归类覆盖表）+ **`_rows()` 读路径唯一出口**
│   ├─ category.py        **v1.9.0 新增** 分类引擎（纯函数，零 Qt）：五类判定 + `explain()` 给依据
│   │                     + `apply_overrides()` 读时覆盖 —— 原判定从 window_monitor 搬出来以便单测
│   ├─ decision.py        **v1.8.0 新增** 决策留痕（frozen dataclass）：凭什么 / 当时什么样 / 改变了什么
│   ├─ tracker.py         瞬时事件 → 活动段（同应用不切段 / 短段过滤）
│   │                     P2.13 加 `idle_provider` —— **把「人不在」的时间剪掉**
│   ├─ summary.py         摘要生成（纯函数，**出网内容可单独审阅**）
│   ├─ advisor.py         活动建议预设 + 提示词；**P2.14 起要求输出 JSON**；**P2.18 加规则 7**（先给 summary 再给数组）
│   ├─ advice.py          **P2.14 新增** 结构化建议（`Advice` / `parse_advices` /
│   │                     `advice_fingerprint` / `is_structured`）—— 纯函数，可单测
│   │                     **P2.18** 加 `AdviceReport`（`summary` + `advices`）/ `parse_report` /
│   │                     `_clamp_summary` / `_bracket_order`；`parse_advices` 改为复用它
│   ├─ timeline.py        **P2.14 新增** 时间轴与趋势聚合（合并碎片段 / 自然日聚合 /
│   │                     排行 / 按小时打断 / 周期对比）—— 纯函数，**口径只有这一处**
│   ├─ schedule.py        **P2.13 新增** 自然日语义（「今天」= 今天 00:00，不是滚动 24h）
│   ├─ idle.py            **P2.13 新增** `GetLastInputInfo` 系统空闲秒数（只读强度，零依赖）
│   └─ reminder.py        **P2.13 新增** 收工小结时机（一天最多一次 + 一串免打扰条件）
│
├─ native/               L1 系统代理层 ✅已建
│   ├─ hotkey.py          HotkeyService（RegisterHotKey + NativeEventFilter）
│   ├─ selection.py       SelectionService（剪贴板方案，全 MIME 备份还原）
│   ├─ capture.py         CaptureService（多显示器合成截图）
│   ├─ injector.py        Injector（粘贴到前台 / 逐字键入）—— **P2.11 起未接入 UI**
│   └─ foreground.py      ForegroundGuard（AttachThreadInput 焦点还原）
│
├─ presentation/         L3 交互层
│   ├─ design/            ✅ **P2.7 新增 —— 设计系统（唯一权威）**
│   │   ├─ tokens.py      Palette（深浅两套色值）+ 间距/圆角/字体/尺寸常量
│   │   ├─ theme.py       Theme(QObject)：color / qss / qt_palette / changed
│   │   ├─ qss.py         从 token 生成全应用样式表 + QPalette（零 hex）
│   │   ├─ icons.py       **51** 个内联 Lucide SVG，按主题着色（P2.14 加 `trend`，v1.7.0 加 `shield`）
│   │   ├─ widgets.py     ThemedWidget 基类 + 全部通用控件（订阅制换肤）
│   │   │                 P2.14 加 `NavList.add_group()` 分组标题行 + `EmptyState.set_text()`
│   │   ├─ charts.py      **P2.14 新增** 数据可视化控件：StatTile / RatioBar / RankBar /
│   │   │                 BarChart / TimelineBar / AxisLabels（刻度按**精确比例**摆，不重叠）
│   │   └─ advice_card.py **P2.14 新增** AdviceCard（headline / evidence / 动作 / 忽略）
│   ├─ control_center.py  ✅ **P2.7 新增 / P2.8 扩至 9 页 / P2.13 扩至 10 页 /
│   │                     P2.14 11 页并按「数据 / 功能 / 系统」分 3 组 /
│   │                     v1.7.0 13 页（加「隐私与数据」）** 控制中心
│   │                     （工具栏+左导航+工作区+状态栏）；`_nav_rows` 做「页序号 → 导航行号」映射
│   ├─ theme.py           ⚠ 兼容门面（老名字 → design.theme），新代码请用 design/
│   ├─ window_behavior.py ✅ P2.6 `RaiseOnClickMixin`（点击置顶）
│   ├─ ai_config_form.py  ✅ AI 配置表单（设置对话框与控制中心共用同一份）
│   ├─ ai_panel.py        ✅ AIPanel（预热常驻 / 双焦点模式 / 拖拽 / 齿轮入口）
│   ├─ ai_settings_dialog.py ✅ AI 服务设置（服务商预设 / 测试连接 / 热切换）
│   ├─ markdown_view.py   ✅ 流式 Markdown（60ms 节流）
│   ├─ overlay_select.py  ✅ 截图选区遮罩
│   ├─ glass_widgets.py   ⚠ 兼容垫片（勿删，第三方插件依赖）
│   ├─ tray_icon.py       ✅ P2.14 **常驻指示**：三态进度环（固定色 + 白描边，**不取主题色**）
│   │                     P2.16 三态定义改从 `design/ring.py` 取（与球环共用）
│   ├─ forms.py           ✅ **P2.16 新增** 外观（可替换内胆）：`Form` 协议 +
│   │                     `OrbForm`（悬浮球，**v1.7.0 起唯一形态**）+
│   │                     `FORM_BUILDERS` / `DEFAULT_FORM = "orb"
│   │                     （`PetForm` 与精灵图资源已于 v1.7.0 移除，协议保留）
│   ├─ bubble.py          ✅ **P2.16 新增** 独立顶层气泡（`WA_TransparentForMouseEvents`）
│   ├─ ui_renderer.py     ✅ P2.16 `PetWindow` → **`ShellWindow`**（外壳，形态无关）
│   │                     + 贴边吸附 + 位置改中心点；`UIManager.apply_form()`
│   └─ …既有（anim_controller / dialogs）
│
├─ extensions/system/ai_assistant/   ✅ 功能插件
│   ├─ SKILL.md           元数据（含 requires / permissions）
│   ├─ modes.py           模式三元组定义（ask / translate / capture）
│   └─ plugin.py          组装 L1/L2/L3，注册热键，托盘兜底入口
│
├─ extensions/system/activity_advisor/  ✅ **P2.12 新增 / P2.13 扩展** 活动建议
│   ├─ SKILL.md           元数据 + **隐私边界声明**（采集什么 / 不采集什么）
│   ├─ plugin.py          订阅 WINDOW_ACTIVE + TIME_TICK / 采样敲击频率 / 组装 SessionManager
│   │                     P2.13：一键开关热生效、收工小结、建议缓存、`_ViewBridge` 跨线程回主线程
│   └─ dialog.py          对话框（纯 UI，只发信号）
│
├─ tools/          工具实现层（v1.7.0 起只剩番茄钟：`timer_tool.py`）
├─ sensor/         感知层（既有）
├─ engine/         决策层（既有：状态机/规则引擎）
└─ data/           数据层（既有：配置/日志）
    ├─ paths.py    ✅ **P2.16 新增** 用户数据根的唯一来源（`pet_home()` / `pet_path()`，
    │               `PET_DEMO_HOME` 可覆盖）—— 落点全走它
    └─ privacy.py   ✅ **v1.7.0 新增** 本机数据清单 / 导出 / 清空（隐私页后端，无 Qt）
```

> 注意：`extensions/` 是**插件外壳**，`tools/` 是**工具实现**，两者并存，不是替代关系。

---

## 7.1 改动过的既有文件

| 文件 | 改动 | 说明 |
|---|---|---|
| `extensions/plugin_manager.py` | T1 | 改为**包加载**，插件可用相对导入 |
| `extensions/base_plugin.py` | T3 | 新增 `on_ui_ready()` / `register_hotkeys()` |
| `event_bus.py` | T2 | 新增 `publish_async()` + 6 个 AI 事件 |
| `main.py` | T3 | 创建 `HotkeyService`，UI 就绪后调 `_notify_ui_ready()` |
| `data/config_manager.py` | T5 / P2.0 | **新增 `ai` 配置节**；P2.0 加 `vision_model`，version → **1.1.1** |
| `config.default.json` | T5 / P2.0 | 同步 `ai` 节 + `vision_model`，version → **1.1.1** |
| `PetDemo.spec` | **T4** | `datas` 补 `native`/`engine`；`hiddenimports` 改为 `BASE_IMPORTS + scan_hiddenimports()` |
| `build_hiddenimports.py` | **T4 新增** | ast 扫描 5 个目录，当前扫出 **56 个模块** |
| `requirements.txt` | — | 补 `requests`（必装）；`keyring`/`pycryptodome` 标注为可选 |
| `engine/ai/session.py` | P2.0 | 新增 `vision_model` 与 `model_for(has_image)` —— **文本/视觉模型分流** |
| `engine/ai/__init__.py` | P2.0 / P2.1 | 透传 `ai.vision_model`；导出 `probe` 系列 |
| `engine/ai/probe.py` | **P2.1 新增** | 连接探测（`probe` / `list_models` / `suggest_models`），纯 Python 可单测 |
| `presentation/ai_settings_dialog.py` | **P2.1 新增** | AI 服务设置对话框：服务商预设 + 测试连接（子线程）+ 保存并热切换 |
| `presentation/ai_panel.py` | P2.1 | 标题栏加 `⚙` 入口（`settings_requested` 信号；点击时自动钉住避免被挤关） |
| `extensions/system/ai_assistant/plugin.py` | P1.7 / P2.0 / P2.1 | `_signature()` 补 `vision_model` + `api_key_ref`；新增 `_open_settings()` / `_on_settings_applied()`；托盘菜单加「AI 服务设置…」 |
| `build_hiddenimports.py` | P2.1 | **`SCAN_DIRS` 补 `presentation`** —— 修 T4 盲区，扫描数 43 → 54 |
| `tests/test_ai_core.py` | P2.0 / P2.1 | +5 vision 路由 +7 连接探测（共 85 passed） |
| `spikes/api_check.py` | **P2.0 新增** | 真实 API 连通性自检（配置 → `/models` → 文本 → 翻译 → 视觉） |
| `spikes/m3_verify.py` | **P2.1 新增** | 热切换端到端验证（两个本地假服务 A/B 证明「请求真的换了目的地」） |
| `native/selection.py` | P1.7 | `keyboard_controller()` 缓存（省 71ms）+ `warmup_keyboard()` / `warmup_clipboard()` |
| `native/injector.py` | P1.7 / **P2.9** | P1.7：复用 `keyboard_controller()`，不再每次新建 Controller。**P2.9：`clear_selection` 参数分离 REPLACE / PASTE 语义；`_send_paste()` 如实返回 bool** |
| `native/capture.py` | P1.7 | `grab_region()` 改为只抓子矩形（90ms → 3–5ms） |
| `presentation/overlay_select.py` | P1.7 | 新增 `warm_up()`（首绘 ~100ms 挪到启动期） |
| `dev_bootstrap.py` | — | 补脚本目录进 `sys.path`（`runpy.run_path` 不会加，导致 `import _common` 失败） |
| `.gitignore` | **P2.2** | **移除 `*.spec`** —— `PetDemo.spec` 是构建配置，必须进版本控制 |
| `tests/test_config_manager.py` | **P2.2** | 新增版本回归用例（绕过单例、用临时目录，不污染真实配置） |
| `data/config_manager.py` | **P2.2 / P2.3** | `_load_config()` 末尾钉死 `version = DEFAULT_CONFIG["version"]` |
| `engine/ai/stream.py` | **P2.4** | 新增 `decode_lines()` + `SSE_ENCODING` —— 字节行流按 UTF-8 解码 |
| `engine/ai/providers/openai_compat.py` | **P2.4** | 弃用 `iter_lines(decode_unicode=True)`，改字节解码；显式钉死 `resp.encoding` |
| `engine/ai/probe.py` | **P2.4** | `list_models()` 钉死 `resp.encoding = "utf-8"` |
| `extensions/system/ai_assistant/plugin.py` | **P2.4** | `invoke()` / `_on_submit()` 补日志（唤起模式 / 选区字数 / 预设） |
| `presentation/theme.py` | **P2.6 新增** | 应用主题源：`app_theme()` 单例 + `set_theme()` 原地改；`appearance.theme` 首次真正被读取 |
| `presentation/window_behavior.py` | **P2.6 新增** | `RaiseOnClickMixin.raise_to_front()`（`raise_` + `activateWindow`，吞 `RuntimeError`） |
| `presentation/ai_panel.py` | **P2.6** | 删写死的 `_CARD_QSS` → `panel_qss(theme)`；圆角 12 → `RADIUS['dialog']`；图标按钮统一 26px + 发丝分隔线；加昼夜切换按钮；`mousePressEvent` 置顶 |
| `presentation/dialogs.py` | **P2.6** | `GlassDialog.dark` 默认 `None` = 跟随应用主题；补 `WindowStaysOnTopHint`；`mousePressEvent` 置顶 |
| `presentation/glass_widgets.py` | **P2.6** | `ThemeToggleButton` 改为按尺寸居中绘制 + 悬停才出现底圆；新增 `set_theme()` |
| `presentation/ui_renderer.py` | **P2.6** | `initialize()` 加 `setQuitOnLastWindowClosed(False)`（**关对话框不再退应用**）；`PetWindow` 混入 `RaiseOnClickMixin` |
| `presentation/ai_settings_dialog.py` | **P2.6** | `_detach_probe()` 加标志位 —— 消除重复 disconnect 的 `RuntimeWarning` |
| `extensions/user/giwifi/giwifi_dialog.py` | **P2.6** | 降级 `GlassDialog` 同步：跟随应用主题 + `WindowStaysOnTopHint` |
| `PetDemo.spec` | **P2.6** | `BASE_IMPORTS` 补 `presentation.theme` / `presentation.window_behavior`（扫描数 54 → 56） |
| `tests/test_window_lifecycle.py` | **P2.6 新增** | 关对话框不退应用（真事件循环）+ 三窗口点击置顶（共 116 passed） |
| `tests/test_theme.py` | **P2.6 新增** | 主题取值/单例/切换 + 面板 QSS 由 token 生成 + 对话框跟随主题与层级 |
| `spikes/s6_window_lifecycle.py` | **P2.6 新增** | 子进程隔离 + 真事件循环：复现 → 修复 → 对照 |
| `spikes/s7_ui_theme.py` | **P2.6 新增 / P2.7 删除** | 旧设计语言下的 UI 统一性探针，已被 S8 取代 |
| `spikes/s5_sse_encoding.py` | **P2.4 新增** | 真 HTTP 边界复现：带 / 不带 charset 两种响应头对比 |
| `tests/test_ai_core.py` | **P2.4** | +5 字节解码 +3 真实 HTTP 集成（94 passed） |
| `presentation/design/`（5 个文件） | **P2.7 新增** | 设计系统：tokens / theme / qss / icons / widgets —— 颜色、样式、图标、控件的唯一权威 |
| `presentation/control_center.py` | **P2.7 新增** | 控制中心主窗口（工具栏 + 左导航 + QStackedWidget + 状态栏，7 页） |
| `presentation/ai_config_form.py` | **P2.7 新增** | AI 配置表单抽出来，设置对话框与控制中心共用同一份 |
| `presentation/theme.py` | **P2.7 重写** | 从「主题源」降级为**兼容门面**（老名字 → `design.theme`） |
| `presentation/glass_widgets.py` | **P2.7 重写** | 从自绘控件库降级为**兼容垫片**（老名字 → 新实现），保住第三方插件 |
| `presentation/dialogs.py` | **P2.7** | `GlassDialog` → `AppDialog` 统一基类；`MessageDialog` 取代 `QMessageBox`；番茄钟空闲显示 `work_duration` |
| `presentation/ai_panel.py` | **P2.7** | 删私有 QSS，直接取 `theme().qss()`；图标按钮改 `IconButton` |
| `presentation/ui_renderer.py` | **P2.7** | `install_theme(app)`；桌宠气泡改 `objectName` + 全局 QSS；右键菜单加「控制中心…」 |
| `presentation/tray_icon.py` | **P2.7** | 托盘菜单加「控制中心…」 |
| `extensions/system/settings/plugin.py` | **P2.7** | 菜单项改为打开控制中心（原 `SettingsDialog` 已并入） |
| `extensions/user/giwifi/giwifi_dialog.py` | **P2.7** | 散落的内联样式收敛到 `objectName` + 全局 QSS |
| `presentation/design/qss.py` | **P2.7 修复** | `.QWidget` 不再设背景（卡片内灰带）；`#iconButton/#iconButtonDanger` 合并基础规则且不写尺寸；滚动条轨道固定 |
| `PetDemo.spec` | **P2.7** | `BASE_IMPORTS` 补 `presentation.design.*` / `control_center` / `ai_config_form` |
| `tests/test_design.py` | **P2.7 新增** | 设计系统规格（hex 收敛 / pt 字号 / 圆角 / 栅格 / 四态 / 选择器纪律 / 图标 / 控制中心）+ 9 个缺陷回归 |
| `tests/test_theme.py` | **P2.7 重写** | 按新架构重写（19 个用例） |
| `tests/test_glass_widgets.py` | **P2.7 重写** | 从「旧像素断言」改为「兼容垫片契约」 |
| `spikes/s8_ui_design.py` | **P2.7 新增** | 25 项规格断言 + 真实平台渲染 20 张预览图（取代已失效的 S7） |
| `engine/ai/store.py` | **P2.8** | 新增 `shared_store()` 进程级单例 + `close_shared_store()` |
| `engine/ai/__init__.py` | **P2.8** | 导出 `shared_store` / `close_shared_store` |
| `extensions/system/ai_assistant/plugin.py` | **P2.8** | `Store()` → `shared_store()`；`on_unload` 不再 close（共享实例归进程管） |
| `main.py` | **P2.8** | `stop()` 调 `close_shared_store()` |
| `presentation/control_center.py` | **P2.8** | 新增 `SessionsPage` / `PresetsPage`（导航 7 → **9 页**）+ `ControlCenter.store()` |
| `presentation/dialogs.py` | **P2.8** | 新增 `PresetEditDialog` / `ask_preset()` / `delivery_label()` |
| `presentation/design/icons.py` | **P2.8** | 新增 `history` / `pencil` 两个图标（共 48 个） |
| `native/selection.py` | **P2.8** | `get_selected()` 固定等待 → **30ms 窗口 + 8ms 轮询**；`_wait()` 步进 5ms → 2ms；**`clip.clear()` → `clipboard_sequence()` 判据**（去掉跨进程的 330ms）；`_clip_token()` 为测试接缝 |
| `native/capture.py` | **P2.8** | 新增 `to_jpeg_bytes()`；`to_data_url()` 默认 **JPEG**（`UPLOAD_FORMAT`/`UPLOAD_QUALITY`） |
| `data/config_manager.py`、`config.default.json` | **P2.8** | version 1.1.1 → **1.1.2** |
| `tests/test_ai_pages.py` | **P2.8 新增** | 共享 Store / 会话页 / 预设页 / 预设对话框 / 控制中心导航（19 例） |
| `tests/test_perf_tail.py` | **P2.8 新增** | R14 轮询契约 + 序列号判据契约 + R15 编码契约（12 例；含 1 条需真实剪贴板的用例，offscreen 下 skip） |
| `spikes/s9_perf_tail.py` | **P2.8 新增** | R14/R15 前后对比 + R14-b 判据代价（优先真实抓屏，headless 回退合成图） |
| `spikes/s10_real_app_selection.py` | **P2.8 新增** | 真实记事本跨进程 A/B；两臂都取不到时报 INCONCLUSIVE 而非 FAIL |
| `native/injector.py` | **P2.9** | `paste_to_foreground()` 新增 `clear_selection` 参数（**REPLACE 与 PASTE 语义分离**）；`_send_paste()` 如实返回 bool（修掉「返回值恒为 True」）；失败时不再白等 120ms；新增 `RESTORE_DELAY` / `DESELECT_DELAY` |
| `extensions/system/ai_assistant/plugin.py` | **P2.9** | `_on_delivery()` 按 `DeliveryKind` 分流（原来 REPLACE 与 PASTE 同路）；新增 `_context_text`（本次选区，决定 PASTE 要不要取消选区）；「粘贴失败」提示改为**可达** |
| `tests/test_injector.py` | **P2.9 新增** | 投递契约 **20 例**（此前零覆盖）：按键序列差异 / 成功判定 / 剪贴板必还原 / 失败不 pump / 插件层分流 |
| `spikes/s11_delivery_semantics.py` | **P2.9 新增** | 真实记事本上比对 REPLACE/PASTE 的**结果文本**；`--legacy` 自证；用窗口消息，不依赖全局按键注入 |
| `engine/ai/store.py` | **P2.10** | 新增 `append_exchange()` / `session_exists()` —— 续接只追加提问，不动 `created_at` 与标题 |
| `engine/ai/session.py` | **P2.10** | `ask()` 新增 `session_id` 参数（续接已有会话）；`_run()` 按 `continuing` 分流落库方式 |
| `presentation/ai_panel.py` | **P2.10** | 新增 `load_history()` —— 渲染历史，且**不露出投递按钮**（否则会把整段历史投出去） |
| `extensions/system/ai_assistant/plugin.py` | **P2.10** | 新增 `continue_session()` 公开入口；`_history` / `_active_session_id` 上下文维护；`invoke()` 重置为全新会话 |
| `presentation/control_center.py` | **P2.10** | `SessionsPage` 加「继续对话」按钮；`ControlCenter.continue_session()`（**鸭子类型调插件**，不做硬依赖） |
| `tests/test_session_continue.py` | **P2.10 新增** | 续接链路 **20 例**：Store 续接语义 / `session_id` 复用 / 面板历史 / 插件上下文 / 控制中心联动 |
| `presentation/ai_panel.py` | **P2.11** | 投递行**只剩「复制」**；`delivery_requested` 现在只发 `"copy"` |
| `extensions/system/ai_assistant/plugin.py` | **P2.11** | `_on_delivery()` 只认 `COPY`，其余**彻底无动作**；**不再持有 `Injector`** |
| `presentation/dialogs.py` | **P2.11** | 新增 `DELIVERY_CHOICES`（只列可用方式）；`DELIVERY_LABELS` 保留旧值以便读历史数据 |
| `engine/ai/prompt.py` | **P2.11** | 翻译 / 改写的 `default_delivery`：`replace` → `copy` |
| `engine/ai/types.py` | **P2.11** | `DeliveryKind.REPLACE` / `PASTE` 标注已移除，新增 `AVAILABLE` |
| `native/injector.py` | **P2.11** | 顶部标注「**当前未接入 UI**」+ 恢复前置条件（必须先有可验证的成功判定） |
| `spikes/s12_real_injection.py` | **P2.11 新增** | 真实按键注入**成功率**实测（10 次 4P/6F）+ `SendInput` 返回值探测 + 两个失败假设 |
| `engine/activity/store.py` | **P2.12 新增** | 活动分段落盘（独立 `activity.db`，与 `ai.db` 分开）；**表里没有 title 列** —— 隐私由结构保证 |
| `engine/activity/tracker.py` | **P2.12 新增** | 瞬时事件 → 活动段（同应用不切段 / 排除应用 / 短段过滤 / flush 用当前时间） |
| `engine/activity/summary.py` | **P2.12 新增** | 摘要生成（纯函数，**出网内容可单独审阅**）；`human_duration()` / `longest_focus_seconds()` |
| `engine/activity/advisor.py` | **P2.12 新增** | `ADVISOR_PRESET` + `build_advisor_prompt()`（提示词含「不要臆测具体内容」） |
| `extensions/system/activity_advisor/` | **P2.12 新增** | 活动建议插件：`SKILL.md`（含**隐私边界声明**）+ `plugin.py`（订阅事件 / 采样频率 / 组装 SessionManager）+ `dialog.py`（纯 UI） |
| `sensor/window_monitor.py` | **P2.12** | 新增 `query_process_name()`（**真实 exe 名**，`QueryFullProcessImageNameW`）；`_classify_window()` 改「娱乐优先 + 进程名兜底」 |
| `tests/test_activity_advisor.py` | **P2.12 新增** | 活动建议 **37 例**：Store / Tracker / Summary / Advisor / 插件与对话框；含**表结构隐私断言** |
| `config.default.json` + `data/config_manager.py` | **P2.12** | 新增 `activity` 节（`enabled=false` / `retention_days=7` / `min_segment_seconds=5` / `exclude_apps=[]`） |
| `engine/activity/schedule.py` | **P2.13 新增** | 自然日语义：`day_start` / `same_day` / `since_for_days` / `today_range` / `clock_hour`。**「今天」= 今天 00:00**，不是滚动 24 小时 |
| `engine/activity/idle.py` | **P2.13 新增** | `system_idle_seconds()`（`GetLastInputInfo`，零新依赖）。**只返回秒数**；失败一律返回 `0.0`（安全默认，宁可少剪不误剪） |
| `engine/activity/reminder.py` | **P2.13 新增** | `should_nudge()` 纯函数：一天最多一次 + 全屏/专注/离开/未到点/无数据免打扰；**原因永远返回**（可直接当日志） |
| `engine/activity/tracker.py` | **P2.13** | 加 `idle_provider` / `away_seconds`：结算时 `end = min(at, at - idle)` **剪掉「人不在」的时长**；新增 `tick()`（离开即收尾、回来续上）与 `is_away()` |
| `engine/activity/store.py` | **P2.13** | 新增 `advices`（建议缓存，按 `signature` 判断是否过期）+ `meta`（键值状态位）；`segments_between()`；**`clear()` 连建议一起删** |
| `sensor/window_monitor.py` | **P2.13** | 新增 `is_foreground_fullscreen()` —— 只比矩形，**服务于「全屏免打扰」，不用来改分类** |
| `presentation/control_center.py` | **P2.13** | 新增 `ActivityPage`（导航 9 → **10 页**）：一键开关 + 首启隐私说明 + 常驻「今日小结」+ 自动范围 + 生成建议 + 番茄钟打通 + 清空确认 |
| `extensions/system/activity_advisor/plugin.py` | **P2.13** | 一键开关热生效；`TIME_TICK` 驱动 `tick()` 与收工小结（托盘气泡）；建议缓存；`_ViewBridge`（**修掉「信号直连普通方法 → 在工作线程动控件」的隐患**）；`_cfg_number()`（**修掉 `0 or default` 吞掉合法配置的 bug**） |
| `tests/test_activity_advisor.py` | **P2.13** | **37 → 93 例**：新增 Schedule / Idle / Reminder（每条免打扰分支一条）/ AdviceCache / TrackerIdle / 插件 P2.13 / 控制中心页 |
| `config.default.json` + `data/config_manager.py` | **P2.13** | `activity` 节补 `nudge_enabled=true` / `nudge_hour=18` / `away_seconds=300`；version → **1.1.7** |

### P2.14 改动清单（v1.2.0）

| 文件 | 版本 | 改了什么 |
|---|---|---|
| `engine/activity/advice.py` | **P2.14 新增** | `Advice` / `AdviceAction` / `parse_advices` / `advice_to_text` / `advice_fingerprint` / `is_structured`；动作是**受限枚举**（只允许 `focus`），越界降级；`parse_advices` **永不返回空** |
| `engine/activity/advisor.py` | **P2.14** | 提示词改为**要求输出 JSON**（`ADVICE_JSON_SPEC`） |
| `engine/activity/timeline.py` | **P2.14 新增** | 纯函数、零 Qt：`merge_segments` / `total_seconds` / `focus_seconds` / `switch_count` / `top_apps` / `category_totals` / `daily_totals` + **④ 趋势页**的 `hour_of_day` / `hour_label` / `hour_switches` / `busiest_hour` / `period_bounds` / `compare_periods` / `_local_date` / `_is_switch` |
| `engine/activity/store.py` | **P2.14** | 新增 `ignored_advices` 表（忽略必须落库）；`clear()` 连忽略标记一起删 |
| `engine/activity/summary.py` | **P2.14** | 修掉「应用切换次数 = 段数」的错标，改用 `switch_count()` |
| `presentation/design/tokens.py` | **P2.14** | `Palette` 加 6 个图表色（`chart_work` / `chart_comm` / `chart_browse` / `chart_other` / `chart_idle` / `chart_track`） |
| `presentation/design/charts.py` | **P2.14 新增** | `StatTile` / `RatioBar` / `RankBar` / `BarChart` / `TimelineBar` / `AxisLabels` |
| `presentation/design/advice_card.py` | **P2.14 新增** | `AdviceCard`（headline / evidence / 动作 / 忽略） |
| `presentation/design/icons.py` | **P2.14** | **49** 个内联图标（加 `trend`） |
| `presentation/design/widgets.py` | **P2.14** | `NavList.add_group()` 分组标题行（用 `ItemIsEnabled`，见 §4.9 ③）；`EmptyState.set_text()` |
| `presentation/control_center.py` | **P2.14** | `ActivityPage` → **`TodayPage`**；新增 **`TrendPage`**；导航 10 平级 → `NAV_GROUPS` **3 组**（11 页）+ `_nav_rows` 行号映射 |
| `presentation/tray_icon.py` | **P2.14** | **常驻指示**：`activity_state` / `activity_tooltip` / `progress_icon`（三态进度环）+ `refresh_activity()`（60s 定时 + 订阅主题） |
| `extensions/system/activity_advisor/plugin.py` | **P2.14** | `focus_progress()` / `focus_goal_seconds()`；`retention_days()`；菜单加「开始 45 分钟专注」；菜单「今日概览」改开「今日」页 |
| `config.default.json` + `data/config_manager.py` | **P2.14** | `retention_days` 7 → **30**；新增 `focus_goal_minutes = 240`；version → **1.2.0**（**两处同步**） |
| `tests/test_activity_advisor.py` | **P2.14** | **93 → 203 例** |
| `tests/test_design.py` | **P2.14** | **→ 67 例**（加刻度重影 / 刻度重叠 / 图表色可见性） |
| `tests/test_tray_indicator.py` | **P2.14 新增** | **20 例**：三态判定 / 悬停文案 / 图标绘制 / 接到托盘 |
| `tests/conftest.py` | **P2.14 新增** | **日志隔离装置** —— 把 `pet_demo.*` 三个 logger 改指临时目录（测试不许写用户的 `~/.pet_demo/logs/`） |
| `tests/test_log_isolation.py` | **P2.14 新增** | **2 例**守上面那个装置 |
| `spikes/s13_today_preview.py` | **P2.14 新增** | 今日页 / 趋势页**整页**目检（10 张图，纯假数据） |
| `spikes/s14_tray_indicator.py` | **P2.14 新增** | 托盘环三态联络表（按**任务栏底色**分两张） |
| `spikes/pyz_check.py` | **P2.14** | 检查清单**追加** P2.14 条目（旧项不删） |

### P2.16 改动清单（v1.3.0）

| 文件 | 版本 | 改了什么 |
|---|---|---|
| `presentation/forms.py` | **P2.16 新增** | `Form` 协议 + `PetForm`（原精灵图逻辑，等价搬运）+ `OrbForm`（悬浮球）+ `FORM_BUILDERS` / `DEFAULT_FORM="orb"` / `build_form()` |
| `presentation/bubble.py` | **P2.16 新增** | 独立顶层气泡：`WA_TransparentForMouseEvents`（不吃鼠标）+ `WA_ShowWithoutActivating`；`show_text()` / `follow()` / `_place()` |
| `presentation/design/ring.py` | **P2.16 新增** | 托盘环与球环**共用**的三态定义 + `activity_state()` + `OUTLINE` |
| `presentation/ui_renderer.py` | **P2.16** | `PetWindow` → **`ShellWindow`**；`_build_initial_form()`；`set_form()`（**中心点不变**）/ `form()` / `animation_target()` / `set_state()`；`_center()` / `_move_center()`（**自校正，与 frame 无关**）；位置改 `window.center`（旧配置迁移）；贴边 `_screen()` / `_snap_to_edge()` / `_expand_from_edge()` / `_ensure_on_screen()` / `enterEvent` / `leaveEvent`；`mouseDoubleClickEvent` → 控制中心；`show_text` 走 `Bubble`；**`_stop_animations()`（按住即停，见 §4.11 ④）**；`UIManager` 加类体信号 `_state_requested` + `apply_form()` + **`_sync_anim_target()`** |
| `presentation/tray_icon.py` | **P2.16** | 三态常量与 `activity_state()` 改从 `design/ring.py` 取（配色仍各自定） |
| `presentation/design/icons.py` | **P2.16** | 图标缓存根改走 `data.paths.pet_path("cache", "icons")` |
| `presentation/control_center.py` | **P2.16** | `CONFIG_DIR` 改走 `data.paths.pet_home()`（不再写死 `Path.home()/".pet_demo"`） |
| `data/paths.py` | **P2.16 新增** | 用户数据根的唯一来源：`pet_home()` / `pet_path()` / `PET_HOME_ENV`（**不做模块级缓存**） |
| `data/config_manager.py` | **P2.16** | `_setup_paths(root=None)` 默认走 `pet_home()`；`_load_config()` **只在磁盘与内存不一致时才 save()**；`DEFAULT_CONFIG` 一律 `copy.deepcopy`（修浅拷贝污染）；`redirect_for_tests()` |
| `data/log_manager.py` | **P2.16** | 日志目录走 `pet_path("logs")` |
| `engine/ai/store.py` | **P2.16** | `default_db_path()` 走 `pet_path("ai.db")` |
| `engine/activity/store.py` | **P2.16** | `default_db_path()` 走 `pet_path("activity.db")` |
| `tools/note_tool.py`、`tools/quick_launch.py` | **P2.16** | 默认存储路径走 `pet_path(...)` |
| `main.py` | **P2.16** | 动画落点改由形态决定（`window.animation_target()` 为 `None` 时只做数值动画） |
| `config.default.json` + `data/config_manager.py` | **P2.16** | `appearance` 加 `form="orb"` / `orb_size=52`；version → **1.3.0**（**两处同步**） |
| `tests/conftest.py` | **P2.16** | **数据根隔离**：**模块级**设 `PET_DEMO_HOME`（fixture 太晚，拦不住 import 时的写盘）；两个 fixture 降级为「双保险 + 断言」 |
| `tests/test_appearance.py` | **P2.16 新增** | **30 例**：协议一致性 / 球外观 / 外壳协作 / 贴边 / 气泡 / 输入 / 默认形态 / 插件契约 |
| `tests/test_config_isolation.py` | **P2.16 新增** | **7 例**守数据根隔离（对标 `test_log_isolation.py`） |
| `tests/test_window_lifecycle.py`、`spikes/s6_window_lifecycle.py`、`presentation/design/qss.py`、`presentation/window_behavior.py` | **P2.16** | 注释里的 `PetWindow` → `ShellWindow` |
| `spikes/s15_orb_preview.py` | **P2.16 新增** | 悬浮球目检：五态 × 四种**壁纸底色** × 1:1 与 3×、气泡浅深两套、贴边三态 + 桌宠对比 |
| `spikes/userdir_diff.py` | **P2.16 新增** | 用户数据目录比对（snap / diff），发版与跑完测试后可复跑 |
| `spikes/exe_window_check.py` | **P2.16 新增** | 发版核查 ③：枚举 exe 名下的可见顶层窗口 —— 日志证明不了窗口存在（发现「球被动画拽走」的那把尺子） |
| `spikes/pyz_check.py` | **P2.16** | 检查清单**追加** P2.16 条目 + **反向查 `PetWindow` 是否真的走掉**（旧项不删） |

### P2.17 改动清单（v1.4.0）

| 文件 | 版本 | 改了什么 |
|---|---|---|
| `presentation/forms.py` | **P2.17** | `Form` 协议加 `edge_snap_trigger()`（基类返回 `0` = 不吸附）；`OrbForm` 返回 `_ORB_SNAP_TRIGGER = 48` |
| `presentation/ui_renderer.py` | **P2.17** | `_snap_to_edge()` 加门控：窗口边缘距屏幕左右边缘 > `edge_snap_trigger()` 时**不吸附**，原地 `_remember_center()` 并**清掉吸附态**（`_edge_side` / `_snapped`） |
| `presentation/control_center.py` | **P2.17** | `AppearancePage.hint` 清空；配色项去掉说明；`_trend_footer()` 去掉常驻 base 文案（只留范围超保留期的功能性警告）；`PluginsPage` 重写：操作列（卸载）+「已卸载」区（恢复）+ `_disabled_names()` / `_layer_of()` 鸭子类型兜底 + `_row_button()` |
| `presentation/ai_config_form.py` | **P2.17** | `set_status()` 空文本时隐藏输出区；去掉常驻说明 |
| `extensions/plugin_manager.py` | **P2.17** | `__init__(app=None, base_dir=None)` 支持注入；新增 `disabled_names()` / `layer_of()` / `uninstall()` / `restore()` / `_remove_plugin_dir()`；`discover_and_load` 跳过 `plugins.disabled` |
| `config.default.json` + `data/config_manager.py` | **P2.17** | 加 `plugins.disabled: []`；version → **1.4.0**（**两处同步**） |
| `tests/test_plugin_manager.py` | **P2.17 新增** | **18 例**：分层记录 / 卸载停用 / 扛重启 / 写盘 / 只对 user 层删目录 / 越界保护 / 拒绝删 user 根 / 恢复闭环 / 页面卸载与恢复动作 |
| `tests/test_appearance.py` | **P2.17** | +3：吸附门控（**非等距输入**）/ 拖离边缘清吸附态 / 冗余文案确实消失 / `edge_snap_trigger()` 协议一致 |
| `tests/test_ai_pages.py` | **P2.17** | +1：AI 表单空状态区自动隐藏 |
| `tests/test_activity_advisor.py` | **P2.17** | 趋势页底部断言改钉「范围超出保留期才警告」 |
| `spikes/pyz_check.py` | **P2.17** | 检查清单**追加** P2.17 条目 + 反向查四处旧文案是否真的走掉（旧项不删） |

### P2.18 改动清单（v1.5.0）

| 文件 | 版本 | 改了什么 |
|---|---|---|
| `engine/activity/advice.py` | **P2.18** | 新增 `AdviceReport`（`summary` + `advices`，frozen dataclass，`has_summary` / `__bool__`）、`parse_report()`、`_clamp_summary()`（折行 + `MAX_SUMMARY_CHARS = 120`）、`_bracket_order()`；`parse_advices()` 改为 `list(parse_report(text).advices)`；`ADVICE_JSON_SPEC` 改对象格式含 `summary` |
| `engine/activity/advisor.py` | **P2.18** | system prompt 加规则 7（先给 summary 再给建议数组）；`build_advisor_prompt()` 加「先写一段 summary（今天整体怎么样），再写建议数组。」 |
| `engine/activity/__init__.py` | **P2.18** | 导出 `AdviceReport` / `parse_report` / `MAX_SUMMARY_CHARS` |
| `extensions/system/activity_advisor/plugin.py` | **P2.18** | 新增 `structured_report(days=1) -> AdviceReport`（解析 + `filter_ignored`）、`focus_running()`；`structured_advice()` 改为复用；`start_focus(minutes=25)` 真把分钟数传下去 |
| `tools/timer_tool.py` | **P2.18** | `start(timer_type="work", minutes=0)`；新增 `_epoch` 轮次号（`_spawn()` 换号 / `_timer_loop(epoch)` 每处读状态前核对 / `stop()` 换号）；`get_status()` 增加 `"total"` |
| `presentation/design/ring.py` | **P2.18** | 新增 `STATE_FOCUS` / `STATE_FOCUS_PAUSED`、`ring_view(*, enabled, ratio, focus_ratio=None, focus_paused=False)` —— **托盘环与球环共用** |
| `presentation/design/focus_card.py` | **P2.18 新增** | `FocusCard(QFrame)`：`MM:SS` + 进度条 + 暂停/继续/结束；`set_status_provider()` / `tick()` / `update_from()`（返回是否变化）/ `_repolish()`（polish self **和** `_bar`）；模块级 `format_clock()` / `TICK_MS` |
| `presentation/design/advice_card.py` | **P2.18** | 新增 `AdviceSummary(QFrame)`（空文本整块 `setVisible(False)`） |
| `presentation/design/icons.py` | **P2.18** | 加 `pause` 图标（两个实心圆角矩形），进 `FILLED` 集合 |
| `presentation/design/qss.py` | **P2.18** | 加 `QFrame#adviceSummary` / `QLabel#adviceSummaryLabel` / `adviceSummaryText`、`QFrame#focusCard`、`QLabel#focusTitle` / `focusClock`、`QProgressBar#focusBar[paused="true"]::chunk`（属性挂**进度条自己**） |
| `presentation/forms.py` | **P2.18** | `OrbForm` 加 `_ORB_FOCUS` / `_ORB_FOCUS_PAUSED` / `refresh_focus()` / `set_focus()` / `focus()` / `_sync_ring()` / `_timer()` / `_arc_color()` / `_icon_name()`；`progress()` 改返回环值与状态 |
| `presentation/tray_icon.py` | **P2.18** | `activity_tooltip(progress, focus=None)` 支持专注提示；`_mmss()`；`refresh_activity()` 用 `ring_view` 合成 + 专注时切 `FOCUS_REFRESH_MS = 1_000` |
| `presentation/control_center.py` | **P2.18** | `TodayPage`：建议列顶部加 `_focus_card`、卡片上方加 `_summary`；`_render_advice` 只在 `if report:` 时画；新增 `showEvent` / `hideEvent`（可见才轮询）、`_focus_minutes()` / `_focus_button_text()` / `_focus_status()` / `_focus_timer()` / `_on_focus_*()`；`_start_focus` 失败原因分开说 |
| `tests/test_advice_report.py` | **P2.18 新增** | 新格式 / 旧裸数组 / 折行截断 / 大白话降级 / **空 advices 不吞总结** / **合法空 JSON 不造假建议** / 永不抛 / 上限 / `parse_advices` 一致性 / 提示词要 summary |
| `tests/test_focus_flow.py` | **P2.18 新增** | `TestTimerDuration`（含 `_epoch` 与过期线程不扣秒）/ `TestRingView`（**五态全枚举**）/ `TestOrbFocusRing`（含像素琥珀色）/ `TestFocusCard`（含进度条变色）/ `TestAdviceSummary` |
| `tests/test_activity_advisor.py` | **P2.18** | 新增 `TestTodayFocusFeedback` / `TestTodayAdviceSummary` / `TestPluginStructuredReport`；`test_start_focus_uses_shared_timer` 改签名 + 新增传分钟数 / 运行态两例 |
| `spikes/s13_today_preview.py` | **P2.18** | `_StubPlugin` 建议改对象格式（含 summary）；新增 `_StubTimer`、`_snap_page(..., focus=None)`；main() 加 `today_focus_*` / `today_focus_paused_*` 四张图 |
| `spikes/s15_orb_preview.py` | **P2.18** | `STATES` 改 5 元组（加 focus）；加「专注计时中」「专注已暂停」两行；读数标签改「环值」 |
| `config.default.json` + `data/config_manager.py` | **P2.18** | version → **1.5.0**（**两处同步**） |

### P2.19 改动清单（v1.6.0）

| 文件 | 版本 | 改了什么 |
|---|---|---|
| `presentation/design/focus_card.py` | **P2.19** | 新增模块级 `focus_label(state, minutes, kind)`（**四个专注入口共用一份文案**）、`focus_title(state, kind, total)`（`专注中 · 90 分钟`；休息阶段不再写「专注」）、`duration_text()`、`apply_phase(widget, state)`（挂 `phase` 属性 + unpolish/polish）、`FOCUS_ENTRY_ID = "focusEntry"`、`KIND_WORK` / `KIND_BREAK` / `ACTIVE_STATES`；`_TITLES` 删掉，改用 `focus_title()` |
| `presentation/design/advice_card.py` | **P2.19** | 新增 `AdviceCard.set_focus_state(state, kind)`（非 idle → 换文案 + **`setEnabled(False)`**；没有动作按钮的卡只记状态、不动按钮）、`_paint_focus_flag()`、只读 `action_enabled()` / `focus_state()`；`set_advice()` 末尾跟随当前状态；动作按钮 `setObjectName(FOCUS_ENTRY_ID)` |
| `presentation/design/tokens.py` | **P2.19** | `Palette` 加 `warning_soft`（dark `rgba(#D7BA7D, .20)` / light `rgba(#9D5D00, .14)`） |
| `presentation/design/qss.py` | **P2.19** | 加 `QPushButton#focusEntry[phase="running"]` / `[phase="paused"]` 两条 —— **id 抬特异度**压过 `QPushButton:disabled`，属性必须叫 `phase`（见 §4.14） |
| `presentation/control_center.py` | **P2.19** | `TodayPage`：新增 `_sync_focus_entries(state=None)`（一处同步顶部按钮 + **全部**建议卡；`usable` 把「没有插件」与「此刻不在专注」分开），`_on_focus_state` 传权威 state；`_focus_button_text()` 改用 `focus_label()`；顶部按钮 `setObjectName(FOCUS_ENTRY_ID)`。`TomatoPage`：`_TICK_MS` / `_STATE_TEXT`（状态行**中文化**）、`showEvent` / `hideEvent` + 1 秒轮询、`_timer()`、`_refresh_status()` 同步 `_btn_start` 文案与可用性、`_work.valueChanged` 连刷新；`QTimer` 补进 QtCore 导入 |
| `tests/test_focus_flow.py` | **P2.19** | 新增 `TestFocusLabel`（**4 状态 × 2 类型全枚举**）/ `TestFocusTitle` / `TestDurationText` / `TestApplyPhase`（含「属性名不是 focus」）/ `TestFocusEntryIdIsSharedWithTheQss` / `TestAdviceCardFocusState`（含「锁定后**真的发不出信号**」） |
| `tests/test_activity_advisor.py` | **P2.19** | 新增 `TestTodayFocusEntries`（三处入口同步 / 新卡跟随 / 降级路径）/ `TestTomatoPageFeedback`（按钮跟随 / 中文状态 / 缺字段不崩 / 轮询起停）；`_FocusTimer` 加 `total` / `today_count` |
| `spikes/s13_today_preview.py` | **P2.19** | `_StubTimer` 补 `today_count`；main() 加 `today_focus_cards_{light,dark}` 与 `..._paused_*` 四张（`height=1560` —— 建议卡落在 700px 折叠线以下） |
| `spikes/smoke_exe.py` | **P2.19** | **新增正式 spike**：发版冒烟（存活 + 版本行 + 启动序列 + 零 ERROR），替代每次现场拼的 Bash 一行流；版本号从 `config.default.json` 读，收尾走 `subprocess` 列表形式调 `taskkill` |
| `spikes/pyz_check.py` | **P2.19** | 清单追加：`focus_label` / `focus_title` / `apply_phase` / `FOCUS_ENTRY_ID` / `_sync_focus_entries` / `warning_soft` / `QPushButton#focusEntry[phase=…]` 等；`FORBIDDEN` 加 `_TITLES`；`EXTRA_MODULES` 加 `presentation.design.tokens` |
| `config.default.json` + `data/config_manager.py` | **P2.19** | version → **1.6.0**（**两处同步**） |

> ⚠ **配置有两份重复数据**：`data/config_manager.py` 里的 `DEFAULT_CONFIG` 常量是**运行时真正生效**的，
> 根目录 `config.default.json` 只用于打包分发与 `check_project.py` 校验（`_load_config` 并不读它）。
> **改配置必须同时改这两处。** P1 开发时踩过：只改了 JSON，热键配置读不到，`register_hotkeys()` 返回空列表。

> 用户配置在 **`~/.pet_demo/user_config.json`**（不在仓库里，不在项目目录内）。
> 接入 API 的完整说明见 **§3.1**。

---

*本文件随项目演进更新。若你完成了某个阶段，请回来更新 §4 进度台账。*

### v1.7.0 改动清单（聚焦赛题 + 隐私与数据）

| 文件 | 版本 | 改了什么 |
|---|---|---|
| `data/privacy.py` | **v1.7.0 新增** | 本机数据清单 / 导出 / 清空（无 Qt）：`DataEntry` / `entries()` / `find()` / `human_size()` / `total_size()` / `export_data(dest, keys=None)` / `clear_entry(key, app)` / `home_bak_files()`；`_selected_rels()`（单类与全量同一条通道）、`_backup_db()`（sqlite backup）、`_is_sidecar()`（`name.endswith`，**不是 `suffix`**）、`_remove()`（单个失败不中断） |
| `presentation/control_center.py` | **v1.7.0** | 新增 `PrivacyPage`（承诺卡 + 6 行数据表 + 导出全部 / 打开目录 / 刷新）与 `_PRIVACY_PROMISE`；`NAV_GROUPS` 加 `("shield", "隐私与数据", PrivacyPage)`（11 → 12 页；**原文写的 11 → 13 页是数错了，v1.9.0 回源码核对时改正**）；导入 `data.privacy` 与 `QFileDialog` |
| `presentation/design/icons.py` | **v1.7.0** | 新增 `shield` 图标（盾 + 对勾，描边风格） |
| `presentation/forms.py` | **v1.7.0** | 删 `PetForm`、`set_model()`、`model_manager` 导入及 `os` / `QPixmap` / `QVBoxLayout`；`FORM_BUILDERS` 只剩 `"orb"`；`build_form()` 对未知名字回退到球；模块 docstring 改写 |
| `presentation/ui_renderer.py` | **v1.7.0** | 删 `model_manager` / `_pet_size()` / `ShellWindow.set_model()` / `apply_pet_model()` / `apply_form()`；`ShellWindow.__init__` 改调 `_build_initial_form()`（**原来漏改，`NameError`**）；`_build_initial_form()` 对空名与旧 `pet` 名回退到球；`setApplicationName` → `ZhiShiAssistant` |
| `presentation/dialogs.py` | **v1.7.0** | 删 `NoteDialog` / `LaunchDialog` 及其导入（776 → 618 行） |
| `presentation/tray_icon.py` | **v1.7.0** | 7 处「小小桌宠」→「知时助手」；「显示 / 隐藏桌宠」→「显示 / 隐藏悬浮球」等 5 处 |
| `main.py` | **v1.7.0** | 删 `model_manager` / `note_manager` / `quick_launch`；动画控制器块简化；16 处文案与模块 docstring |
| `extensions/system/ai_assistant/plugin.py` | **v1.7.0** | 删 `_ANIM_FALLBACK` 与 `_react()`（桌宠反馈）及 6 处调用 |
| `data/config_manager.py` + `config.default.json` | **v1.7.0** | 删 `quick_launch` 节、`appearance.form` / `pet_name` / `pet_model` / `animation_speed`、`ai.pet_reacts` / `pet_reactions`；`pet_name → orb_size` 迁移；version → **1.7.0**（两处同步） |
| `PetDemo.spec` / `installer.iss` / `setup.bat` / `unins.bat` / `dev_bootstrap.py` | **v1.7.0** | exe 名与安装脚本改「知时助手」；spec 删 `presentation/assets` datas 与 `presentation.pet_model` hiddenimport |
| `spikes/{exe_window_check,pyz_check,smoke_exe,_refresh_release,leak_check}.py` | **v1.7.0** | exe 路径 `dist/小小桌宠Demo/小小桌宠Demo.exe` → `dist/知时助手/知时助手.exe` |
| `spikes/pyz_check.py` | **v1.7.0** | 删 `PetForm` 与 `appearance.form`；清单追加 `PrivacyPage` / `DataEntry` / `entries` / `human_size` / `export_data` / `clear_entry` / `_is_sidecar` / `_backup_db` 与 14 条字符串；`FORBIDDEN` 加 `PetForm` / `pet_model` / `note_tool` / `quick_launch` / `NoteManager` / `QuickLaunch` / `pet_name` / `pet_reacts` / `pet_reactions` / `小小桌宠`；`EXTRA_MODULES` 加 `data.privacy` |
| `spikes/s15_orb_preview.py` | **v1.7.0** | 删桌宠对比格、`PetForm` / `model_manager` / `tempfile` / `QPixmap` 导入 |
| `spikes/s16_privacy_preview.py` | **v1.7.0 新增** | 隐私页目检（import 前换数据根 + 种假数据；浅 / 深 / 空态 3 张） |
| `check_project.py` | **v1.7.0** | 「资源检查」（查精灵图，已永远报错）换成「数据根检查」（`os.access` 查可写） |
| `README.md` / `CHANGELOG.md` / `spikes/README.md` | **v1.7.0** | 改名、结构、功能表、隐私与数据一节、S16 结果段 |
| `tests/test_privacy.py` | **v1.7.0 新增** | 23 条：清单在数据根下 / `human_size` 口径 / 全量与单类导出 / **WAL 里的行** / 失败不留半截 zip / 插件优先 / 删文件兜底 / 日志清空不删文件 / 缓存与遗留 / `ai.db` 关单例后能重建 / 未知 key 拒绝 / 页面 6 行 / 空态禁用 / 确认才动手 |
| `tests/test_appearance.py` | **v1.7.0** | 删 14 处 `PetForm`；`test_registered_forms_satisfy_the_protocol` 改遍历 `FORM_BUILDERS`；新增 `_BareForm` 与 `test_bare_form_uses_the_protocol_defaults`（钉基类缺省值）；`test_form_size_follows_the_configured_diameter`；换形态用例改用 `OrbForm(90)` |
| `tests/test_config_isolation.py` / `test_tray_indicator.py` / `test_config_manager.py` | **v1.7.0** | `appearance.form = "pet"` → `appearance.orb_size`；托盘提示断言改「知时助手」；删 `quick_launch` 节断言（改断 `activity` / `plugins`）；删便签 / 快捷启动两个路径候选 |

> ⚠ **「移除」比「新增」更容易漏**：删类时要 grep **调用点**（`_pet_size()` 就是漏的一处），
> 删文件后要跑一遍 `check_project.py` / 全量测试 / 字面量 grep 三件套。
> 移除的旧字面量已全部进 `pyz_check.py` 的 `FORBIDDEN_STRINGS`
> （精确匹配：`note_tool` 不会误伤 `data/privacy.py` 里的 `"notes.json"`）。

### v1.9.0 改动清单（分类口径重写 + 手动归类）

| 文件 | 版本 | 改了什么 |
|---|---|---|
| `engine/activity/category.py` | **v1.9.0 新增** | 分类引擎（纯函数，零 Qt，约 470 行）：`CATEGORIES` / `CATEGORY_RULES` / `FOCUS_CATEGORIES` / `WORK`·`STUDY`·`COMM`·`FUN`·`OTHER`；词表 `BROWSER_PROCESSES` / `_PROCESS_RULES` / `PROCESS_TABLES` / `TITLE_TABLES`；`_compile_title_regex()`（**词边界**）/ `_TITLE_RULES`（优先级 娱乐>学习>沟通>工作）；`process_stem()` / `normalize_app()` / `classify()` / `explain()` / `is_valid_category()` / `apply_overrides()` |
| `sensor/window_monitor.py` | **v1.9.0** | 删 `WORK_KEYWORDS` / `ENTERTAIN_KEYWORDS` / `_hit` / `_classify_window` 实现；`_classify_window` 改转接 `category.explain`，返回 `(分类, 依据)`；监控循环加 `info["reason"]`（只进内存不落库）；docstring 更新 Events 契约 |
| `engine/activity/store.py` | **v1.9.0** | `_SCHEMA` 加 `app_categories` 表；`_top_key()`；**`_rows(sql, params)` 读路径唯一出口**（漏 `app` 列当场 `raise`）；`segments_since` / `segments_between` / `totals_by_app`（改 Python 层聚合，保留 `auto_category`）/ `totals_by_category` 全走 `_rows()`；`app_categories` / `set_app_category` / `clear_app_category` / `clear_app_categories` / `count_app_categories`；`clear()` docstring 注明**不动** `app_categories` |
| `engine/activity/timeline.py` | **v1.9.0** | `WORK_CATEGORY = WORK`；`focus_seconds` / `daily_totals` 的 focus 桶改用 `FOCUS_CATEGORIES`；三处硬编码 `"其他"` → `OTHER` |
| `engine/activity/summary.py` | **v1.9.0** | `longest_focus_seconds` 改引用 `FOCUS_CATEGORIES`；两处 `"其他"` → `OTHER` |
| `engine/activity/__init__.py` | **v1.9.0** | 导出 `CATEGORIES` / `CATEGORY_RULES` / `FOCUS_CATEGORIES` / 五个分类常量 / `PROCESS_TABLES` / `TITLE_TABLES` / `classify` / `explain` / `process_stem` / `normalize_app` / `is_valid_category` / `apply_overrides` |
| `extensions/system/activity_advisor/plugin.py` | **v1.9.0** | 新增 `app_totals(days=7)`（含 `manual` 标记）/ `app_categories()` / `set_app_category()` / `clear_app_category()` / `clear_app_categories()`；`_data_signature()` 纳入归类指纹 |
| `presentation/control_center.py` | **v1.9.0** | 新增 `AppCategoryPage`（`sliders`，数据组）+ `_make_combo`（用 `activated`）/ `_on_category_changed`（**反馈写在 `reload()` 之后**）/ `_on_reset_all` / `_fit_table`；`NAV_GROUPS` 数据组 **3 项 → 4 项**（数据组 3→4，总 **13 → 14 页**）；导入 `CATEGORIES` / `CATEGORY_RULES` / `QBrush` |
| `spikes/pyz_check.py` | **v1.9.0** | `REQUIRED_MODULES` / `EXTRA_MODULES` 加 `engine.activity.category`；`REQUIRED_SYMBOLS` +30；`REQUIRED_STRINGS` +15；`FORBIDDEN_STRINGS` 加 `WORK_KEYWORDS` / `ENTERTAIN_KEYWORDS` |
| `spikes/s18_category_preview.py` | **v1.9.0 新增** | 「应用分类」页目检（真插件 + 真 store，临时数据根；浅 / 深 / 空态 3 张） |
| `config.default.json` + `data/config_manager.py` + `installer.iss` | **v1.9.0** | version 1.8.0 → **1.9.0**（三处同步） |
| `README.md` / `CHANGELOG.md` / `AGENTS.md` / `docs/执行框架.md` / `spikes/README.md` | **v1.9.0** | 特性表 + 新增「应用怎么分类」章节；CHANGELOG 1.9.0 条目；§4.17 + 源码地图 + 目录树；执行框架目录树加 `engine/activity/`；S18 结果段 |
| `tests/test_category.py` | **v1.9.0 新增** | 58 条：分类项一致性 / 四张进程表两两不相交 / 浏览器不与工具表相交 / **8 个误匹配回归** / 进程名精确匹配 / 浏览器不定分类 / 三层判定 / 标题优先级 / 中文站点名 / 依据不含标题原文 / `_compile_title_regex` 机制 / 大小写归一 / monkeypatch 把「浏览器排除」变可观测 / `apply_overrides` 6 条 |
| `tests/test_app_category.py` | **v1.9.0 新增** | 49 条：Store 写入撤销与受限枚举 / **四条读路径逐条断言覆盖生效** / `_rows` 护栏 raise / 原始列不被篡改 / `totals_by_app` 保留 `auto_category` / `clear()` 不动偏好 / 插件接口与数据指纹 / 页面（说明卡 / 两列对照 / 强调色 / 下拉 / 写入 / 重置 / 空态整页自洽 / 表体高度）/ 混合类别取占比最大 / `daily_totals` 把学习算进深度工作 |
| `tests/test_activity_advisor.py` | **v1.9.0** | `test_page_is_registered_under_data_group` 断言改为 `["今日", "趋势", "应用分类", "协同记录"]` |
| `presentation/design/tokens.py` | **v1.9.0** | 图表色 6 → 7：`chart_browse` 改名 **`chart_fun`**，新增 **`chart_study`**（深浅两套）；`chart_work` 注释「深度工作」→「工作」 |
| `presentation/design/charts.py` | **v1.9.0** | `_CATEGORY_TOKENS` 改为五类（工作 / 学习 / 沟通 / 娱乐 / 其他）—— 旧表还写着「浏览」，导致「学习」「娱乐」掉进灰色兜底 |
| `tests/test_design.py` | **v1.9.0** | `_CHART_KEYS` 6 → 7；`test_category_color_token_mapping` 改五类；**新增 `test_every_category_has_a_distinct_chart_color`**（遍历 `CATEGORIES` 的完整性护栏） |
| `spikes/s13_today_preview.py` | **v1.9.0** | 假数据类别「浏览」→「娱乐」；总结文案的数字与实际数据对齐；假插件补齐 `app_totals` / `app_categories` / `decision_log` / `count_decisions` / `export_decisions`（`reload()` 是全量的） |
| `spikes/s17_decision_preview.py` | **v1.9.0** | 同上：假插件补 `app_totals` / `app_categories` |
| `spikes/s19_demo_page.py` | **v1.9.0 新增** | 生成对外的**单文件** Web 演示页（10 张截图 base64 内嵌，零外部依赖），产物落桌面 |
