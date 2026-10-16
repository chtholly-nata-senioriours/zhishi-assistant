"""发版核查 ①：PYZ 符号校验。

用途
    打包后确认「该进包的都进了、该走的都走了」。PyInstaller 把 .pyc 全塞进 exe 里的
    PYZ 归档，**肉眼看不见**，所以只能解出来比对。

用法
    PYTHONPATH="Lib;Lib/site-packages;Lib/packtools" \\
        python dev_bootstrap.py spikes/pyz_check.py

⚠ 维护提示
    下面的 `REQUIRED_MODULES` / `REQUIRED_SYMBOLS` / `REQUIRED_STRINGS` / `FORBIDDEN_STRINGS`
    是**当前版本的检查清单**，发新版时按本次改动**追加**（不要删旧的，那正是回归护栏）。

三个已知的坑（都踩过）
    1. `extract()` 默认返回 **code object**，不是 bytes（`raw=True` 才给 bytes）。
    2. 关键字参数名在 **`KW_NAMES` 元组常量**里，必须递归进容器才收得到。
    3. 「该在的」字符串可能被优化进模块级**大字符串**（如 `_SCHEMA` 里的表名），
       所以要用**子串**判断；而「不该在的」必须用**精确常量**判断（子串会误报）。
"""

from __future__ import annotations

import os
import sys
import tempfile

from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

# --- 检查清单（按版本追加）---------------------------------------------------

REQUIRED_MODULES = [
    "engine.activity",
    "engine.activity.schedule",
    "engine.activity.idle",
    "engine.activity.reminder",
    "engine.activity.store",
    "engine.activity.tracker",
    # --- P2.14 ---
    "engine.activity.advice",
    "engine.activity.advisor",
    "engine.activity.timeline",
    # --- P2.18 ---
    "presentation.design.focus_card",
    # --- v1.8.0 ---
    "engine.activity.decision",     # P1-4 决策留痕（纯函数，无 Qt）
    "data.key_store",               # P1-5 系统密钥库
    # --- v1.9.0 ---
    "engine.activity.category",     # 分类口径（纯函数，无 Qt；从 sensor 搬出来的）
]

REQUIRED_SYMBOLS = [
    "should_nudge",
    "day_start",
    "since_for_days",
    "today_range",
    "same_day",
    "clock_hour",
    "system_idle_seconds",
    "DEFAULT_NUDGE_HOUR",
    "DEFAULT_AWAY_SECONDS",
    "segments_between",
    "get_advice",
    "save_advice",
    "is_foreground_fullscreen",
    "is_away",
    # --- P2.14 ① 结构化建议 + 时间轴聚合 ---
    "parse_advices",
    "advice_to_text",
    "advice_fingerprint",
    "is_structured",
    "merge_segments",
    "total_seconds",
    "focus_seconds",
    "switch_count",
    "top_apps",
    "category_totals",
    "daily_totals",
    # --- P2.14 ④ 趋势页 ---
    "hour_of_day",
    "hour_label",
    "hour_switches",
    "busiest_hour",
    "period_bounds",
    "compare_periods",
    "HOURS_PER_DAY",
    "DAY_SECONDS",
    # --- P2.14 ⑤ 常驻指示 ---
    "focus_progress",
    "focus_goal_seconds",
    "DEFAULT_FOCUS_GOAL_MINUTES",
    "activity_state",
    "activity_tooltip",
    "progress_icon",
    "refresh_activity",
    "PROGRESS_REFRESH_MS",
    # --- P2.15 概览仪表盘 ---
    "OverviewBoard",
    "stretch_of",
    "add_tile",
    "is_primary",
    "set_value",
    # --- P2.16 外壳 / 外观分层 ---
    "ShellWindow",              # 原 PetWindow，形态无关的外壳
    "_build_initial_form",
    "set_form",
    "animation_target",
    "form_size",
    "wants_edge_snap",
    "edge_snap_inset",
    "preferred_opacity",
    "is_snapped",
    "edge_side",
    "OrbForm",                  # 悬浮球（2026-10-15 起唯一形态）
    "FORM_BUILDERS",
    "DEFAULT_FORM",
    "build_form",
    "set_progress",
    "refresh_progress",
    "wants_shell_motion",       # 位移动画是否作用在外壳上（球：否）
    "_sync_anim_target",        # 把动画目标对齐到当前形态
    "_numeric_origin",          # 位移动画起点（被打断时还原用）
    "Bubble",                   # 独立顶层气泡
    "show_text",
    "follow",
    "pet_home",                 # 用户数据根的唯一来源
    "pet_path",
    "PET_HOME_ENV",
    "STATE_OFF",                # 托盘环与球环共用的三态
    "STATE_ACTIVE",
    "STATE_DONE",
    "OUTLINE",
    # --- P2.17 贴边门控 / 插件卸载 ---
    "edge_snap_trigger",        # 形态声明的吸附触发距离（基类 0 = 不吸附）
    "disabled_names",           # 已卸载名单（配置 plugins.disabled）
    "layer_of",                 # 插件来自哪一层（system / user / dev）
    "uninstall",
    "restore",
    "_remove_plugin_dir",
    "_reload_removed",          # 插件页「已卸载」区刷新
    "_on_uninstall",
    "_on_restore",
    "_row_button",              # 表格单元格按钮（垫一层容器，否则被拉伸到整格）
    # --- P2.18 建议总结 + 专注可见化 ---
    "AdviceReport",             # summary + advices（总结不是「第 0 条建议」）
    "parse_report",             # 单一解析口径（parse_advices 复用它）
    "_bracket_order",           # 按「哪个括号先出现」决定先试对象还是数组
    "_clamp_summary",           # 折行 + 截断
    "MAX_SUMMARY_CHARS",
    "has_summary",
    "STATE_FOCUS",              # 环的专注态（与「已达成」必须分开）
    "STATE_FOCUS_PAUSED",
    "ring_view",                # 托盘环与球环共用的单一口径
    "FocusCard",                # 倒计时卡
    "format_clock",
    "TICK_MS",
    "update_from",              # 返回「状态是否变化」（没变不发信号）
    "_repolish",                # 同时 polish 自己**和进度条**
    "AdviceSummary",            # 建议区顶部的总结段
    "set_summary",
    "refresh_focus",            # 球 / 托盘的专注环刷新
    "set_focus",
    "focus_running",            # 插件侧「有没有专注在跑」
    "structured_report",        # 插件侧结构化输出（含 summary）
    "_epoch",                   # 番茄钟轮次号（防「停→再开」两倍速）
    "_arc_color",
    "_icon_name",
    "_mmss",
    "FOCUS_REFRESH_MS",         # 专注期间托盘环切 1 秒轮询
    # --- P2.19 统一「开始专注」入口的反馈口径 ---
    "KIND_WORK",                # 「工作」/「休息」在界面上是两个词
    "KIND_BREAK",
    "ACTIVE_STATES",            # running / paused 才算「在跑」
    "FOCUS_ENTRY_ID",           # 所有专注入口共用的 objectName
    "apply_phase",              # 挂 `phase` 属性 + 重新 polish
    "_is_break",
    "duration_text",            # `5400` → `90 分钟`（标题里要能核对时长）
    "focus_label",              # 入口按钮文案的**唯一**来源
    "focus_title",              # 倒计时卡标题（含总时长）
    "set_focus_state",          # 建议卡跟随全局专注状态
    "_paint_focus_flag",        # 卡按钮的琥珀态（不是通用禁用灰）
    "action_enabled",           # 只读：按钮真被 setEnabled(False) 了
    "focus_state",
    "_focus_state",
    "_sync_focus_entries",      # 一处收口：新入口只要记得调它
    "_TICK_MS",                 # 番茄钟页自刷新间隔
    "_STATE_TEXT",              # 中文状态词（不再把裸英文塞进界面）
    "_refresh_status",
    # --- v1.7.0 隐私与数据 ---
    "PrivacyPage",              # 控制中心新页（导航 shield 图标）
    "DataEntry",                # data/privacy.py 的清单条目
    "entries",                  # 本机数据清单（页面的数据源）
    "human_size",               # 体积的唯一口径（页面与导出提示共用）
    "total_size",
    "export_data",              # 打包（单类 / 全量同一条通道）
    "clear_entry",              # 清空（有插件借插件，没插件才删文件）
    "home_bak_files",           # 配置历史备份单独点数
    "_is_sidecar",              # WAL/SHM 旁车过滤（name.endswith，不是 suffix）
    "_backup_db",               # sqlite backup API（防漏掉只在 WAL 里的行）
    # --- v1.8.0 P1-4 人机协同决策留痕 ---
    "DecisionNote",             # 一次决定的完整留痕（frozen dataclass）
    "build_note",               # 生成留痕（纯函数，可单测）
    "build_context",            # 决定那一刻的数据现场
    "_clean_context",           # 上下文白名单（认不出的键直接丢掉）
    "_build_basis",             # 推荐依据（采纳时把「同意的动作」也算一条）
    "_build_impact",            # 影响范围（记实际结果，不谎称已开始）
    "format_notes",             # 导出成人可读的审计文本
    "format_context",           # 上下文字典 → 一行中文（展示层唯一口径）
    "ACTION_ADOPT",             # 受限枚举：界面只有两个按钮，库里只有两种取值
    "ACTION_IGNORE",
    "ACTION_LABELS",            # 中文标签（界面上不出现裸英文）
    "CONTEXT_KEYS",             # 白名单本身
    "MAX_CONTEXT_SUMMARY",      # 总结进留痕也要夹长度
    "record_decision",          # 插件侧入口（现场只有插件拿得到）
    "_decision_message",        # 回给用户的一句话
    "decision_log",             # 读留痕（页面拿到的直接是 DecisionNote）
    "count_decisions",
    "decisions",                # 落库表的读写
    "clear_decisions",          # 只清留痕、留分段
    "export_decisions",         # 证据链导出
    "DecisionLogPage",          # 控制中心「协同记录」页
    "_DECISION_FILTERS",        # 全部 / 采纳 / 忽略
    "decided",                  # 建议卡的新信号（带 action，替代只管专注的旧信号）
    "_detail_card",             # 详情卡（空态要整块藏起来）
    "_btn_export",              # 导出按钮（空态要禁用，不隐藏 —— 免得跳版）
    "_fit_detail",              # 详情区高度按内容算（目检 S17 抓到的问题）
    "_DETAIL_MIN",              # 下限 / 上限 / 「还没布局过」的宽度阈值
    "_DETAIL_MAX",
    "_DETAIL_MIN_WIDTH",
    "setLineWrapMode",          # QPlainTextEdit 默认 NoWrap，长句会被切掉
    # --- v1.8.0 P1-5 系统密钥库 ---
    "REF_PREFIX",               # 配置里标记「密钥在密钥库」的前缀
    "SERVICE",                  # keyring 的 service 名
    "DPAPI_FILE",               # 无 keyring 时的加密回退文件
    "_ENTRY_RE",                # 条目名白名单（同时挡路径穿越）
    "_MASK_HEAD",               # 脱敏保留的头尾位数（安全参数）
    "_MASK_TAIL",
    "entry_for_base_url",       # 按接口地址推导条目名
    "valid_entry",
    "entry_of",
    "ref_for",
    "backend_name",             # keyring / dpapi / none
    "available",
    "store_key",
    "load_key",                 # 取密钥的唯一入口（取不到返回空串，不抛异常）
    "has_key",
    "delete_key",
    "mask",                     # 脱敏（只露头尾且总长度固定）
    "status",                   # 「密钥存在哪」的现状说明
    "_dpapi_protect",           # CryptProtectData（按当前用户加密）
    "_dpapi_unprotect",
    "_dpapi_write",
    "_dpapi_read",
    "resolve_api_key",          # 全项目唯一读密钥的地方
    "_key_mode",                # 「保存位置」分段控件
    "_keyring_mode",            # 当前是不是密钥库模式
    "_on_key_mode_changed",     # 切换时说清「现在这把钥匙会怎样」
    "_key_storage_note",        # 隐私页里那句现状说明
    # --- v1.9.0 分类口径 + 手动归类 ---
    "CATEGORIES",               # 受限枚举（五个分类项）
    "CATEGORY_RULES",           # 每类的判定依据（界面原样展示）
    "FOCUS_CATEGORIES",         # 深度工作 = 工作 + 学习（三处共用一个口径）
    "PROCESS_TABLES",           # 四张进程词表（测试断言两两不相交）
    "TITLE_TABLES",
    "BROWSER_PROCESSES",        # 浏览器在进程层**不定分类**
    "classify",
    "explain",                  # 返回 (分类, 依据)；依据只回命中的词，不回标题原文
    "process_stem",             # 进程名精确匹配词干（barcode != code）
    "normalize_app",            # 应用名归一（大小写 / 空白）
    "is_valid_category",
    "apply_overrides",          # 读时叠加用户归类（不篡改原始观测）
    "_compile_title_regex",     # 词边界正则（decode 不命中 code）
    "_PROCESS_RULES",
    "_TITLE_RULES",
    "_top_key",                 # 聚合取占比最大的类别（结果必须确定性）
    "_rows",                    # 所有 segments 读路径的**唯一出口**
    "app_categories",
    "set_app_category",
    "clear_app_category",
    "clear_app_categories",
    "count_app_categories",
    "app_totals",
    "AppCategoryPage",
    "_AUTO_LABEL",
    "_APP_CATEGORY_DAYS",
    "_make_combo",
    "_fit_table",
    "_on_category_changed",
    "_on_reset_all",
]

REQUIRED_STRINGS = [
    "advices",
    "meta",
    "last_nudged_at",
    "nudge_enabled",
    "nudge_hour",
    "away_seconds",
    "活动建议",
    "开始 25 分钟专注",
    "今日小结",
    # --- P2.14 ---
    "ignored_advices",      # ① 忽略必须落库
    "headline",             # ① 结构化建议字段
    "evidence",
    "focus_goal_minutes",   # ⑤ 配置项（两处同步）
    "今日概览",             # ③⑤ 导航页名 / 托盘菜单项
    "开始 45 分钟专注",      # ⑤ 托盘菜单项
    "本机记录",             # ③ 今日页第一张卡
    "今日深度工作",          # ⑤ 托盘悬停提示
    "时间构成",             # ④ 趋势页
    "最容易被打断",          # ④ 趋势页
    "chart_work",           # ② 6 个图表色 token
    "chart_comm",
    "chart_browse",
    "chart_other",
    "chart_idle",
    "chart_track",
    # --- P2.15 概览仪表盘 ---
    "overviewBoard",        # 台面（QSS 选择器 + objectName）
    "overviewTitle",        # 台面标题
    "vHairline",            # 格间竖分隔线
    "本周期概览",            # 趋势页台面标题（与今日页同一套）
    # --- P2.16 外壳 / 外观分层 ---
    "PET_DEMO_HOME",        # 用户数据根的环境变量名
    "window.center",        # 位置持久化改中心点（旧配置迁移的键）
    "orb_size",             # 球直径配置项（两处同步）
    "petBubble",            # 气泡沿用全局 QSS 的 objectName
    "presentation.forms",   # 新模块确实被 import 进包
    "presentation.bubble",
    "presentation.design.ring",
    "data.paths",
    # --- P2.17 ---
    "plugins.disabled",     # 已卸载名单的配置键（两处同步）
    "已卸载",               # 插件页「已卸载」区
    "卸载插件",             # 卸载确认对话框标题
    # --- P2.18 ---
    '"summary": "一段整体总结',   # 格式说明里真的要求了 summary（不是只在别处提过这个词）
    "先给一段 summary",          # system prompt 规则 7（精确到短语，防「只出现 summary 一词」的假断言）
    "focusCard",                # 专注卡 objectName（QSS 选择器 + 代码里 setObjectName）
    "focusBar",
    "focusClock",
    "QProgressBar#focusBar[paused",   # 属性挂在进度条**自己**身上（祖先属性穿透不到子部件）
    "adviceSummary",            # 总结段的 objectName
    "paused",                   # 动态属性名
    # --- P2.19 ---
    "focusEntry",               # 入口按钮共用 id（QSS 选择器 + 代码 setObjectName）
    'QPushButton#focusEntry[phase="running"]',   # id 抬特异度压过通用 :disabled
    'QPushButton#focusEntry[phase="paused"]',
    "warning_soft",             # 新增 token：「进行中」的软底（不是禁用灰）
    "phase",                    # 动态属性名 —— **不能叫 focus**（QWidget 内建属性）
    "专注中…",                  # 入口按钮 running 文案（focus_label 的字面量）
    "休息中…",                  # 休息阶段的 running 文案
    "休息已暂停",
    "已暂停",                   # 暂停文案（focus_label 与 focus_title 共用这段字面量）
    "分钟专注",                 # `开始 N 分钟专注` 的后半段字面量
    # --- v1.7.0 隐私与数据 ---
    "隐私与数据",               # 导航项名 / 页标题
    "shield",                   # 新图标名（ICONS 里的键）
    "AI 会话历史",              # 清单六类（data/privacy.py 的 label）
    "活动记录",
    "设置与偏好",
    "界面缓存",
    "运行日志",
    "旧版本遗留数据",
    "知时助手数据导出_",        # 导出 zip 的文件名前缀（f-string 前半段）
    "README.txt",               # zip 里附的说明文件
    "notes.json",               # 遗留数据（便签 / 快捷启动已移除但仍可能留在盘上）
    "quick_launch.json",
    "-wal",                     # sqlite 旁车：导出要排掉、清空要一起删
    "-shm",
    "不会采集的：窗口标题",      # 承诺卡里的结构性事实（不是营销话术）
    "还没有数据可导出",         # 失败也要说清楚，不许静默成功
    # --- v1.8.0 P1-4 决策留痕 ---
    "人机协同决策留痕（知时助手）",   # 导出文本的标题（整串，防只出现半句的假断言）
    "协同记录",                 # 导航项名 / 页标题
    "file-check",               # 新图标名（ICONS 里的键）
    "推荐依据：",               # 导出文本的小节标题
    "影响范围：",
    "该建议及其同类（同指纹）不再出现在后续推荐中",   # 忽略的影响范围原文
    "生成后数据未变化",          # 「没检查」与「检查了没变」必须分得开
    "决定时专注正在进行",
    "还没有决策记录",            # 空状态标题
    "留档",                     # 回给用户的那句话（证明真的写进去了）
    # --- v1.8.0 P1-5 系统密钥库 ---
    "keyring:",                 # REF_PREFIX 字面量（写进配置的就是它）
    "pet_demo_ai",              # keyring service 名
    "secure_keys.bin",          # DPAPI 回退文件名
    "系统密钥库",                # 界面用词（不出现裸 keyring）
    "配置文件（明文）",          # 退路那一档要写明代价
    "保存位置",                  # 表单行名
    "•",                        # 遮罩字符（脱敏就是它）
    "已保存到系统密钥库",
    "系统密钥库不可用",          # 不可用时要说清楚，不许静默降级
    "API Key 保存在系统密钥库里",  # 隐私页的现状说明
    # --- v1.9.0 分类口径 + 手动归类 ---
    "应用分类",                  # 导航项名 / 页标题
    "分类项与判定依据",           # 说明卡的标题
    "系统判定",                  # 只读列（分类器给出的结果）
    "你的归类",                  # 下拉列（用户的选择，优先）
    "自动判定",                  # 下拉首项 = 不覆盖
    "全部恢复自动判定",
    "生产力工具（编辑器 / IDE / Office / 设计 / 终端 / 数据库 / 远程），"
    "或标题命中工作站点与流程词。",   # 判定依据原文（整串，防只出现半句的假断言）
    "游戏平台与游戏本体、影音播放器与音乐客户端，"
    "或标题命中视频、短视频、直播、社交娱乐站点。",
    "以上都不命中，或同时命中两个方向 —— 判不出就不猜。"
    "浏览器停在空白页时也在这里。",
    "浏览器窗口，标题里没有可判定的信号",   # 依据文案（浏览器不是「判不出」）
    "还没有可归类的应用",        # 空状态标题
    "保持系统判定",              # 选了等于系统判定的类别时的反馈
    "已手动归类",                # 汇总行
    "app_categories",            # 覆盖表名（库里真的有这张表）
]

# 移除类改动要查「旧字面量有没有真走掉」—— 精确匹配，子串会误报
FORBIDDEN_STRINGS = [
    "已替换原文",
    "粘贴到前台",
    # P2.14 ③：ActivityPage 整个被 TodayPage 取代。
    # 类名会落进引用方的 `co_names`，所以「残留 = 还有地方在用它」。
    "ActivityPage",
    # P2.16：PetWindow 整个被 ShellWindow 取代。
    # 精确匹配 —— `forms.py` 的**文档字符串**里还提到 PetWindow（那是在解释历史），
    # 而 docstring 在 co_consts 里是**一整段**，不是裸词，所以不会被误判。
    # 真有人写 `PetWindow(...)` / `isinstance(x, PetWindow)` 时名字会落进 co_names → 抓到。
    "PetWindow",
    # P2.17：四处冗余提示文案（同样是精确常量）。
    # 现在只有**文档字符串/注释**里还提到它们（解释为什么删），
    # 那些在 co_consts 里是整段，不会与这里的裸常量相等。
    "主题、形象与窗口行为。主题切换会立即生效并保存。",   # 外观页副标题
    "深色参考 VS Code Dark+，浅色参考 Windows 11 原生",   # 配色说明
    "数据只在本机，保留最近 ",                            # 趋势页底部常驻文案（f-string 前半段）
    "填好后点「测试连接」验证，再「保存并生效」——无需重启。",  # AI 表单常驻说明
    # P2.19：`_TITLES` 那张「状态 → 标题」表被 `focus_title()` 取代。
    # 精确匹配 —— 模块级赋值会落进 `co_names`，残留 = 还有地方在用它。
    # （注意 `ai_panel.MODE_TITLES` 是**另一个**名字，不会误判。）
    "_TITLES",
    # --- v1.7.0：宠物模型子系统 / 便签 / 快捷启动移除 + 改名「知时助手」---
    # 理由同 PetWindow：类名与模块名会落进引用方的 `co_names`，
    # 残留 = 还有地方在 import / 实例化它们。
    "PetForm",
    "pet_model",
    "NoteManager",
    "note_tool",
    "QuickLaunch",
    "quick_launch",
    # 配置键与产品名 —— 已从 DEFAULT_CONFIG / 界面文案中删除。
    # 精确匹配：`data/config_manager.py` 的注释里还提到它们（解释为什么删），
    # 但注释不进字节码；docstring 在 co_consts 里是整段，不会与裸常量相等。
    "pet_name",
    "pet_reacts",
    "pet_reactions",
    "小小桌宠",
    # --- v1.9.0：分类从裸子串匹配改为进程词干 + 标题词边界 ---
    # 这两个类属性被整个删掉了（判定搬进 engine.activity.category）。
    # 精确匹配：残留 = 还有地方在用那套 `"git" in text` 的匹配。
    "WORK_KEYWORDS",
    "ENTERTAIN_KEYWORDS",
]

# 额外按模块收符号（不在 engine.activity 下的）
EXTRA_MODULES = [
    "presentation.control_center",
    "presentation.tray_icon",              # P2.14 ⑤
    "presentation.design.charts",          # P2.14 ②
    "presentation.design.advice_card",     # P2.14 ②
    "extensions.system.activity_advisor.plugin",
    "sensor.window_monitor",
    "presentation.ui_renderer",            # P2.16 外壳（也是 PetWindow 残留的检查面）
    "presentation.forms",                  # P2.16 外观
    "presentation.bubble",                 # P2.16 气泡
    "presentation.design.ring",            # P2.16 共用环状态
    "presentation.anim_controller",        # P2.16 位移动画起点还原（_numeric_origin）
    "data.paths",                          # P2.16 用户数据根
    "extensions.plugin_manager",           # P2.17 卸载 / 恢复 / 已卸载名单
    "presentation.ai_config_form",         # P2.17 输出区按内容自动显隐
    "presentation.ai_settings_dialog",     # P2.17 同一份实现的对话框外壳
    "presentation.design.focus_card",      # P2.18 专注倒计时卡
    "presentation.design.qss",             # P2.18 QSS 选择器写法（属性挂在进度条自己身上）
    "tools.timer_tool",                    # P2.18 轮次号 _epoch / 分钟数 / total
    "presentation.design.tokens",          # P2.19 新增 warning_soft token
    "data.privacy",                        # v1.7.0 隐私与数据页的后端
    "data.key_store",                      # v1.8.0 系统密钥库（P1-5）
    "engine.activity.decision",            # v1.8.0 决策留痕（P1-4）
    "engine.ai",                           # v1.8.0 resolve_api_key（唯一读密钥处）
    "engine.activity.category",            # v1.9.0 分类口径（词表 / 正则 / 覆盖）
]


def collect_symbols(code, out=None):
    """递归收集 code object 里出现的所有名字 / 字符串常量。"""
    if out is None:
        out = set()
    for c in code.co_consts:
        if isinstance(c, str):
            out.add(c)
        elif isinstance(c, (tuple, frozenset, list)):
            for item in c:
                if isinstance(item, str):
                    out.add(item)
        elif hasattr(c, "co_consts"):
            collect_symbols(c, out)
    for attr in ("co_names", "co_varnames", "co_freevars", "co_cellvars"):
        for n in getattr(code, attr, ()):
            out.add(n)
    return out


def main() -> int:
    exe = os.path.join("dist", "知时助手", "知时助手.exe")
    if not os.path.isfile(exe):
        print(f"[FAIL] exe not found: {exe}")
        return 2

    car = CArchiveReader(exe)
    pyz_bytes = car.extract("PYZ.pyz")
    if isinstance(pyz_bytes, str):
        tmp, created = pyz_bytes, False
    else:
        fd, tmp = tempfile.mkstemp(suffix=".pyz")
        with os.fdopen(fd, "wb") as fh:
            fh.write(pyz_bytes)
        created = True

    try:
        reader = ZlibArchiveReader(tmp)
        toc = reader.toc
        print(f"[i] PYZ 总条目: {len(toc)}")
        mods = sorted(k for k in toc if k.startswith("engine.activity"))
        print(f"[i] engine.activity* 条目 ({len(mods)}): " + ", ".join(mods))

        missing_mods = [m for m in REQUIRED_MODULES if m not in toc]

        all_syms: set[str] = set()
        for m in mods + [e for e in EXTRA_MODULES if e in toc]:
            obj = reader.extract(m)
            if obj is not None:
                collect_symbols(obj, all_syms)

        missing_syms = [s for s in REQUIRED_SYMBOLS if s not in all_syms]

        # 「该在的」用子串（可能嵌在模块级大字符串里）
        haystack = "\n".join(s for s in all_syms if isinstance(s, str))
        missing_strs = [s for s in REQUIRED_STRINGS if s not in haystack]

        # 「不该在的」用精确常量
        leaked = [s for s in FORBIDDEN_STRINGS if s in all_syms]

        print()
        print(f"[{'OK' if not missing_mods else 'FAIL'}] 必需模块: "
              f"{'全部命中' if not missing_mods else '缺 ' + str(missing_mods)}")
        print(f"[{'OK' if not missing_syms else 'FAIL'}] 必需符号: "
              f"{'全部命中' if not missing_syms else '缺 ' + str(missing_syms)}")
        print(f"[{'OK' if not missing_strs else 'FAIL'}] 必需字符串: "
              f"{'全部命中' if not missing_strs else '缺 ' + str(missing_strs)}")
        print(f"[{'OK' if not leaked else 'FAIL'}] 旧字面量已移除: "
              f"{'无残留' if not leaked else '残留 ' + str(leaked)}")

        ok = not (missing_mods or missing_syms or missing_strs or leaked)
        print()
        print("RESULT:", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        # ZlibArchiveReader 每次读都重新 open，但保险起见提取完再删
        if created:
            os.unlink(tmp)


if __name__ == "__main__":
    sys.exit(main())
