# -*- coding: utf-8 -*-
"""活动分类 —— 「这个应用该算工作还是娱乐」的判定口径（纯函数，零 Qt）。

为什么从 `sensor/window_monitor.py` 搬到这里
    原来判定逻辑长在 `WindowMonitor._classify_window` 里，**一条测试都没有**
    （`tests/` 下搜 `_classify_window` 是零命中）。没测试的地方就是会烂的地方：
    它用的是裸子串匹配，于是
        `"git" in "digital"`      → 任何含 digital 的标题判「工作」
        `"edge" in "knowledge"`   → 含 knowledge 的标题判「工作」
        `"word" in "password"`    → 含 password / wordle 的标题判「工作」
        `"code" in "decode"`      → 含 decode / barcode 的标题判「工作」
        `"vim" in "vimeo"`        → Vimeo 播放页判「工作」
    搬出来是为了**能被单测覆盖**（本模块纯 Python、不碰 Qt、不碰 win32），
    而不是「换个地方写同一堆 if」。

五个分类项按「**行为类型**」划分，不按场景
    场景（上班 / 在家）判不出来，行为判得出来：
        工作 —— 产出：写代码、写文档、做设计、跑数据
        学习 —— 摄入：看课、查文档、读论文、刷题
        沟通 —— 交流：IM、邮件、会议
        娱乐 —— 消遣：游戏、影音、短视频、社交娱乐
        其他 —— 判不出，或**同时像两类**（不猜）
    所以钉钉、飞书算「沟通」而不是「工作」：它们本身是沟通工具，
    至于聊的是不是公事，代码无从得知 —— 硬猜一个「工作」才是撒谎。

判定顺序（三层，越靠前越可信）
    ① **进程名**（精确匹配词干）：用户在用什么工具，这是最强的信号。
       `code.exe` → 工作，`steam.exe` → 娱乐，`wechat.exe` → 沟通。
       **浏览器除外** —— `chrome.exe` 只是个容器，不代表在做什么，
       把它算「工作」正是旧实现最大的误判来源。
    ② **标题**（ASCII 用词边界、中文用子串）：浏览器里靠它认站点。
       词边界是必须的：`(?<![a-z0-9])code(?![a-z0-9])` 匹配 "vs code"，
       但不会匹配 "decode"。中文没有词边界概念，直接用子串。
    ③ 都没有信号 → 「其他」。**不猜**。

    标题内部的优先级是 娱乐 > 学习 > 沟通 > 工作：站点名（bilibili /
    coursera）最明确，办公词（「周报」「审批」）最泛，越泛越容易误伤。

隐私
    `explain()` 的「依据」只回**命中的词**，不回窗口标题原文 ——
    词来自本模块的白名单，不是用户内容。依据也**不落库**（`segments`
    表仍然只有 app / category 两列，见 `store._SCHEMA`）。
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Sequence, Tuple

# ================================================================
# 分类项
# ================================================================

WORK = "工作"
STUDY = "学习"
COMM = "沟通"
FUN = "娱乐"
OTHER = "其他"

#: 全部可选分类。**受限枚举** —— 和 `advice.ACTION_*` 同一思路：
#: 界面给几个选项，库里就不该出现第六种取值。
CATEGORIES: Tuple[str, ...] = (WORK, STUDY, COMM, FUN, OTHER)

#: 计入「深度工作」的类别。学习也是专注投入 ——
#: 只算「工作」的话，看两小时网课在进度环上是 0，那是错的。
FOCUS_CATEGORIES: Tuple[str, ...] = (WORK, STUDY)

#: 每个分类项的判定依据（**界面上原样展示**）。
#: 放在这里而不是写在页面里：页面重写一份，改了一处另一处就成了假话。
CATEGORY_RULES: Dict[str, str] = {
    WORK: "生产力工具（编辑器 / IDE / Office / 设计 / 终端 / 数据库 / 远程），"
          "或标题命中工作站点与流程词。",
    STUDY: "学习工具（词典 / 文献 / 记忆卡 / 阅读器），"
           "或标题命中课程、题库、论文、开发文档站。",
    COMM: "即时通讯、邮件与会议客户端（微信 / 钉钉 / 飞书 / Slack / "
          "Teams / Zoom / Outlook…）。",
    FUN: "游戏平台与游戏本体、影音播放器与音乐客户端，"
         "或标题命中视频、短视频、直播、社交娱乐站点。",
    OTHER: "以上都不命中，或同时命中两个方向 —— 判不出就不猜。"
           "浏览器停在空白页时也在这里。",
}


def is_valid_category(value: str) -> bool:
    """是不是一个合法的分类名（写库前的校验）。"""
    return str(value or "") in CATEGORIES


def normalize_app(app: str) -> str:
    """应用名归一化 —— 小写去空白，与 `ActivityTracker.record` 同一口径。

    两边口径必须一致：一边存 `Chrome.exe `、另一边查 `chrome.exe`，
    手动分类就会「设了不生效」而且不报错。
    """
    return str(app or "").strip().lower()


# ================================================================
# ① 进程名表（精确匹配词干）
# ================================================================

#: 浏览器 —— **在进程层不定分类**。
#: 它们只是容器：同一个 chrome.exe 可能在写代码、也可能在刷 B 站。
#: 旧实现把 chrome 当工作工具，于是「在 Chrome 里刷 B 站」被记成工作。
BROWSER_PROCESSES = frozenset({
    "chrome", "googlechrome", "msedge", "microsoftedge", "edge",
    "firefox", "brave", "opera", "vivaldi", "chromium", "iexplore",
    "360se", "360chrome", "360se6", "qqbrowser", "sogouexplorer",
    "maxthon", "theworld", "2345explorer", "ucbrowser", "quarkpc",
    "liebao", "baidubrowser", "avastbrowser", "waterfox", "palemoon",
})

#: 生产力工具 —— 产出行为。
_WORK_PROCESSES = frozenset({
    # 编辑器 / IDE
    "code", "code - insiders", "vscodium", "codium", "cursor", "windsurf",
    "zed", "fleet", "pycharm", "pycharm64", "idea", "idea64", "webstorm",
    "webstorm64", "clion", "clion64", "goland", "goland64", "rider64",
    "phpstorm64", "rubymine64", "datagrip64", "dataspell64", "aqua64",
    "studio64", "eclipse", "sublime_text", "notepad++", "notepad",
    "vim", "nvim", "gvim", "macvim", "emacs", "atom", "textmate",
    # Office / 文档
    "winword", "excel", "powerpnt", "msaccess", "onenote", "mspub",
    "wps", "et", "wpp", "pdfelement", "acrobat", "acrord32",
    "typora", "notion", "obsidian", "joplin", "logseq", "evernote",
    "xmind", "mindmaster", "processon",
    # 终端 / 开发工具
    "windowsterminal", "wt", "cmd", "powershell", "pwsh", "conhost",
    "git-bash", "mintty", "putty", "mobaxterm", "xshell", "xftp",
    "termius", "sourcetree", "tortoisegit", "gitkraken", "fork",
    "githubdesktop", "docker desktop", "postman", "insomnia",
    "wireshark", "fiddler", "charles",
    # 数据库 / 数据
    "ssms", "navicat", "dbeaver", "workbench", "jupyter",
    "jupyter-notebook", "jupyter-lab", "rstudio", "spyder",
    "matlab", "spss", "stata", "tableau", "powerbi", "pbidesktop",
    # 设计 / 影音后期（生产，不是消遣）
    "figma", "photoshop", "illustrator", "indesign", "aftereffects",
    "premiere", "adobe xd", "blender", "sketch", "coreldrw", "inkscape",
    "gimp", "krita", "resolve", "audition", "lightroom", "affinity",
    # 工程 / 三维
    "acad", "autocad", "sldworks", "solidworks", "revit", "sketchup",
    "catia", "inventor", "nx", "creo",
    # 远程 / 虚拟化
    "mstsc", "vmware", "vmware-vmx", "virtualbox", "anydesk", "teamviewer",
})

#: 学习工具 —— 摄入行为。
_STUDY_PROCESSES = frozenset({
    "anki", "eudic", "youdaodict", "youdao", "oald", "marginnote",
    "zotero", "mendeley", "endnote", "calibre", "sumatrapdf",
    "baicizhan", "shanchazidian", "notability", "goodnotes",
})

#: 沟通工具 —— 交流行为。
_COMM_PROCESSES = frozenset({
    "wechat", "weixin", "wechatappex",
    "qq", "qqnt", "tim", "qqprotect",
    "dingtalk", "feishu", "lark", "wxwork",
    "wemeetapp", "tencentmeeting", "voov", "zoom", "zoommtg",
    "slack", "teams", "ms-teams", "skype",
    "discord", "telegram", "whatsapp", "signal", "line", "messenger",
    "outlook", "hxoutlook", "thunderbird", "foxmail", "mailspring",
})

#: 娱乐工具 —— 消遣行为。
_FUN_PROCESSES = frozenset({
    # 游戏平台 / 启动器
    "steam", "steamwebhelper", "steamservice",
    "epicgameslauncher", "epicwebhelper", "uplay", "ubisoftconnect",
    "upc", "origin", "eaapp", "eadesktop", "goggalaxy", "galaxyclient",
    "riotclientservices", "riotclientux", "wegame", "tgp", "battle.net",
    # 游戏本体（常见）
    "yuanshen", "genshinimpact", "starrail", "bh3", "hyp",
    "leagueclient", "leagueclientux", "league of legends", "valorant",
    "dota2", "cs2", "csgo", "tslgame", "pubg", "gta5", "rdr2",
    "minecraft", "hmcl", "pcl2", "crossfire", "dnf",
    "wow", "wowclassic", "hearthstone", "overwatch",
    "eldenring", "sekiro", "cyberpunk2077", "stardew valley",
    "hollowknight", "terraria",
    # 影音播放 / 音乐
    "potplayer", "potplayermini64", "vlc", "mpv", "mpc-hc64", "mpc-be64",
    "kmplayer", "gomplayer", "qqplayer", "stormplayer", "iina",
    "cloudmusic", "qqmusic", "kugou", "kuwo", "spotify", "musicbee",
    "foobar2000", "aimp", "itunes", "groove",
    # 视频 / 直播 / 阅读客户端
    "bilibili", "哔哩哔哩", "qiyi", "iqiyi", "qqlive", "tencentvideo",
    "youkudesktop", "youku", "mgtv", "ixigua", "douyin", "kuaishou",
    "huya", "douyu", "weread", "qqreader", "qidian",
})

#: 判定顺序。四张表**两两不相交**（`tests/test_category.py` 有断言钉住）——
#: 交集会让「谁先谁后」变成隐式规则，改一处顺序就悄悄改了判定。
_PROCESS_RULES: Tuple[Tuple[str, frozenset], ...] = (
    (WORK, _WORK_PROCESSES),
    (STUDY, _STUDY_PROCESSES),
    (COMM, _COMM_PROCESSES),
    (FUN, _FUN_PROCESSES),
)

#: 供测试与界面使用（「这张表里都有什么」）。
PROCESS_TABLES: Dict[str, frozenset] = {
    WORK: _WORK_PROCESSES,
    STUDY: _STUDY_PROCESSES,
    COMM: _COMM_PROCESSES,
    FUN: _FUN_PROCESSES,
}


# ================================================================
# ② 标题关键词表（ASCII 词边界 + 中文子串）
# ================================================================

#: 娱乐：站点名与内容类型。
_FUN_TITLE_WORDS = frozenset({
    # 视频 / 短视频 / 直播
    "bilibili", "b站", "哔哩哔哩", "youtube", "netflix", "twitch",
    "iqiyi", "爱奇艺", "qqlive", "腾讯视频", "youku", "优酷", "mgtv",
    "芒果tv", "ixigua", "西瓜视频", "douyin", "抖音", "tiktok",
    "kuaishou", "快手", "huya", "虎牙", "douyu", "斗鱼", "zhanqi",
    "pandatv", "熊猫直播",
    # 音乐
    "spotify", "cloudmusic", "网易云音乐", "qq音乐", "kugou", "酷狗",
    "kuwo", "酷我", "music.163", "y.qq.com",
    # 社交娱乐 / 社区
    "weibo", "微博", "xiaohongshu", "小红书", "douban", "豆瓣",
    "tieba", "贴吧", "instagram", "facebook", "twitter", "x.com",
    # 游戏
    "steam", "steamcommunity", "epicgames", "wegame", "game", "gaming",
    "gameplay", "原神", "genshin", "王者荣耀", "英雄联盟", "league of legends",
    "和平精英", "绝地求生", "我的世界", "minecraft", "穿越火线", "地下城与勇士",
    "第五人格", "明日方舟", "崩坏", "阴阳师", "游戏", "手游", "网游", "单机",
    # 影视 / 阅读
    "movie", "anime", "manga", "comic", "netflix.com", "电影", "电视剧",
    "综艺", "动漫", "番剧", "追剧", "小说", "漫画", "直播",
})

#: 学习：课程平台、题库、论文库、开发文档站。
_STUDY_TITLE_WORDS = frozenset({
    # 课程平台
    "coursera", "edx.org", "udemy", "udacity", "khanacademy", "icourse163",
    "mooc", "中国大学", "学堂在线", "超星", "学习通", "智慧树", "网易公开课",
    # 题库 / 刷题
    "leetcode", "nowcoder", "牛客", "codeforces", "atcoder", "kaggle",
    "洛谷", "lintcode", "hackerrank",
    # 论文 / 文献
    "arxiv", "scholar.google", "researchgate", "sciencedirect", "springer",
    "ieee", "知网", "cnki", "万方", "维普", "论文", "文献", "综述",
    # 开发文档（查资料 = 摄入）
    "stackoverflow", "stack overflow", "developer.mozilla", "mdn",
    "docs.python", "readthedocs", "w3schools", "geeksforgeeks",
    "csdn", "掘金", "juejin", "博客园", "cnblogs", "segmentfault",
    "freecodecamp", "tutorial", "documentation", "官方文档", "开发文档",
    "api 文档", "教程", "网课", "课程", "讲义", "课件", "题库", "真题",
    "考研", "四六级", "雅思", "托福", "知识点", "实验报告",
})

#: 沟通：IM / 邮件 / 会议（标题里出现，多半是网页版）。
_COMM_TITLE_WORDS = frozenset({
    "wechat", "微信", "企业微信", "wx.qq.com", "dingtalk", "钉钉",
    "feishu", "飞书", "lark", "slack", "teams", "zoom", "skype",
    "discord", "telegram", "whatsapp", "messenger",
    "gmail", "mail.google", "outlook", "foxmail", "网易邮箱", "qq邮箱",
    "腾讯会议", "视频会议", "会议中", "视频通话", "语音通话", "收件箱",
})

#: 工作：办公站点与流程词。
#: 刻意收得**很窄** —— 「数据」「文档」「代码」这类词在任何标题里都会出现
#: （「王者荣耀数据分析」也含「数据」），放进来的话误判比命中还多。
_WORK_TITLE_WORDS = frozenset({
    # 办公站点
    "docs.google.com", "office.com", "sharepoint", "onedrive",
    "confluence", "jira", "trello", "asana", "notion.so", "feishu.cn",
    "slack.com", "teams.microsoft", "gitlab", "github", "gitee",
    "coding.net", "tapd", "禅道", "worktile", "teambition",
    "figma.com", "mastergo", "即时设计",
    # 流程词（高置信、少歧义）
    "pull request", "merge request", "code review", "stack trace",
    "周报", "月报", "日报", "季度", "复盘", "排期", "里程碑",
    "需求评审", "项目计划", "审批", "报销", "发票", "合同", "投标",
    "招标", "预算", "报价", "工单", "会议纪要", "okr", "kpi",
})


def _compile_title_regex(words: Iterable[str]) -> "re.Pattern[str]":
    """把一组关键词编成**一个**正则（含词边界断言）。

    为什么要词边界
        `"code" in title` 会命中 "decode"、`"git" in title` 会命中 "digital" ——
        旧实现就是这么把「含 digital 的网页」判成工作的。
        `(?<![a-z0-9])code(?![a-z0-9])` 匹配 "vs code"、不匹配 "decode"。
    为什么中文不需要边界
        中文没有词间空格，`(?<![a-z0-9])` 对中文字符恒为真，
        所以中文关键词自动退化成子串匹配 —— 正是想要的行为。
    为什么合成一个正则
        150 多个词逐个 `re.search` 是 150 次扫描；合成一个后由 re 引擎
        内部一次性匹配，且命中时能直接取回**命中的那个词**（给用户看依据）。
    """
    parts = sorted({str(w).lower() for w in words if str(w)}, key=len, reverse=True)
    if not parts:
        return re.compile(r"(?!x)x")          # 永不匹配
    body = "|".join(re.escape(p) for p in parts)
    return re.compile(r"(?<![a-z0-9])(?:" + body + r")(?![a-z0-9])")


#: 标题判定顺序：娱乐 > 学习 > 沟通 > 工作（越靠前越明确，见模块 docstring）。
_TITLE_RULES: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    (FUN, _compile_title_regex(_FUN_TITLE_WORDS)),
    (STUDY, _compile_title_regex(_STUDY_TITLE_WORDS)),
    (COMM, _compile_title_regex(_COMM_TITLE_WORDS)),
    (WORK, _compile_title_regex(_WORK_TITLE_WORDS)),
)

#: 供测试与界面使用。
TITLE_TABLES: Dict[str, frozenset] = {
    FUN: _FUN_TITLE_WORDS,
    STUDY: _STUDY_TITLE_WORDS,
    COMM: _COMM_TITLE_WORDS,
    WORK: _WORK_TITLE_WORDS,
}


# ================================================================
# 判定
# ================================================================

def process_stem(process: str) -> str:
    """进程名 → 词干（`"Code.exe"` → `"code"`）。

    用**精确相等**而不是子串：进程名是受控标识符，
    `barcode.exe` 的词干是 `barcode`，不等于 `code`，于是不会被误判成工作。
    """
    name = normalize_app(process)
    if name.endswith(".exe"):
        name = name[:-4]
    return name


def explain(process: str, title: str = "") -> Tuple[str, str]:
    """返回 `(分类, 依据)`。依据是给人看的一句话，**不含窗口标题原文**。

    三层判定，越靠前越可信：
        ① 进程名（浏览器除外）  ② 标题  ③ 其他
    为什么进程优先于标题
        进程名回答「在用什么工具」（行为意图），标题回答「内容是什么」。
        用 Word 打开一份标题里带「b站」的文案，仍然是在工作。
    """
    stem = process_stem(process)
    text = normalize_app(title)

    # ① 进程名 —— 最强信号
    if stem and stem not in BROWSER_PROCESSES:
        for cat, names in _PROCESS_RULES:
            if stem in names:
                return cat, f"应用 {stem} 属于{cat}类工具"

    # ② 标题 —— 浏览器里只能靠它认站点
    if text:
        for cat, rx in _TITLE_RULES:
            hit = rx.search(text)
            if hit:
                return cat, f"标题命中「{hit.group(0)}」"

    # ③ 不猜
    if stem in BROWSER_PROCESSES:
        return OTHER, "浏览器窗口，标题里没有可判定的信号"
    return OTHER, "没有可判定的信号"


def classify(process: str, title: str = "") -> str:
    """只要分类名（`explain` 的第一项）。"""
    return explain(process, title)[0]


# ================================================================
# 手动归类（用户覆盖）
# ================================================================

def apply_overrides(segments: Iterable[Dict],
                    mapping: Dict[str, str]) -> List[Dict]:
    """把用户手动指定的分类覆盖到分段上。

    为什么在**读**的时候覆盖，而不是写的时候 UPDATE 掉历史行
        写时改等于**篡改原始观测**：`segments.category` 是「系统当时判成了
        什么」，它是证据（与 P1-4 的决策留痕同一条纪律）。用户的手动归类是
        「后来人的判断」，两者是两层，混在一起就没法回答「当初为什么记错」，
        也没法撤销。所以原始列不动，覆盖在读路径上叠加。

    被覆盖的段会多一个 `auto_category` 键 = 原来的自动判定，
    供界面显示「自动判定 工作 → 已改为 学习」。

    返回新的 dict 列表（没被覆盖的项**原样复用**，不复制 —— 读路径是热路径）。
    """
    if not mapping:
        return list(segments or [])
    # **映射的键也要归一化**：调用方可能手搓一个映射（大小写 / 带空白不同），
    # 只归一其中一侧的话，覆盖会**静默不生效** —— 「设了分类但数字没变」
    # 是最难查的一类 bug（不报错、不崩、只是没反应）。
    # 映射很小（几个到几十个应用），每次读重建一遍的代价可以忽略。
    # 值不做校验：写入口 `store.set_app_category` 已经卡过受限枚举。
    table = {normalize_app(k): v for k, v in mapping.items()}
    out: List[Dict] = []
    for seg in (segments or []):
        forced = table.get(normalize_app(seg.get("app")))
        auto = seg.get("category") or OTHER
        if forced and forced != auto:
            item = dict(seg)
            item["auto_category"] = auto
            item["category"] = forced
            out.append(item)
        else:
            out.append(seg)
    return out
