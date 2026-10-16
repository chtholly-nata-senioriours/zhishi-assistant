# -*- coding: utf-8 -*-
"""分类口径的契约测试（纯函数层，零 Qt）。

为什么这一层以前一条测试都没有 —— 以及为什么要补
    「工作 / 娱乐」的判定原来长在 `sensor/window_monitor.py` 里，用裸子串匹配，
    没有测试。没测试的地方就是会烂的地方，它真的烂了：
        "git" in "digital"      → 含 digital 的标题判「工作」
        "edge" in "knowledge"   → 含 knowledge 的标题判「工作」
        "word" in "password"    → 含 password / wordle 的标题判「工作」
        "code" in "decode"      → 含 decode / barcode 的标题判「工作」
        "vim" in "vimeo"        → Vimeo 播放页判「工作」
    上面每一条都在 `test_*_is_not_misread_as_work` 里钉着 —— 它们是这次
    重写的**理由**，删掉就等于把那些误判放回去。

    另一半是「浏览器一律算工作」：`chrome.exe` 在旧表里是工作工具，
    于是在 Chrome 里刷 B 站被记成工作。现在浏览器在**进程层不定分类**。
"""
import pytest

from engine.activity.category import (
    BROWSER_PROCESSES,
    CATEGORIES,
    CATEGORY_RULES,
    COMM,
    FOCUS_CATEGORIES,
    FUN,
    OTHER,
    PROCESS_TABLES,
    STUDY,
    TITLE_TABLES,
    WORK,
    apply_overrides,
    classify,
    explain,
    is_valid_category,
    normalize_app,
    process_stem,
)


# ================================================================
# 分类项本身
# ================================================================

def test_category_set_is_the_five_agreed_names():
    assert CATEGORIES == ("工作", "学习", "沟通", "娱乐", "其他")


def test_every_category_has_a_rule_and_every_rule_has_a_category():
    """判定依据与分类项必须一一对应 —— 少一条，界面上就会有一个
    说不出凭什么判的类别；多一条，就是没人用的死文案。"""
    assert set(CATEGORY_RULES) == set(CATEGORIES)


def test_focus_categories_is_work_plus_study():
    """深度工作 = 工作 + 学习。只算「工作」的话，看两小时网课在进度环上是 0。"""
    assert FOCUS_CATEGORIES == (WORK, STUDY)


def test_is_valid_category_only_accepts_the_enum():
    assert all(is_valid_category(c) for c in CATEGORIES)
    assert not is_valid_category("摸鱼")
    assert not is_valid_category("")
    assert not is_valid_category(None)


def test_normalize_app_is_case_and_space_insensitive():
    assert normalize_app("  Chrome.EXE ") == "chrome.exe"
    assert normalize_app(None) == ""


def test_process_stem_strips_exe():
    assert process_stem("Code.EXE") == "code"
    assert process_stem("pycharm64.exe") == "pycharm64"
    assert process_stem("pid_1234") == "pid_1234"


# ================================================================
# 词表自身的约束
# ================================================================

def test_process_tables_are_pairwise_disjoint():
    """四张进程表两两不相交。

    交集会让「谁先谁后」变成一条**隐式规则** —— 改一处顺序就悄悄改了判定，
    而且没有任何地方写着这件事。所以宁可让测试在这里炸。
    """
    names = list(PROCESS_TABLES)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            overlap = PROCESS_TABLES[a] & PROCESS_TABLES[b]
            assert not overlap, f"{a} 与 {b} 的进程表有交集：{sorted(overlap)}"


def test_browser_processes_are_not_also_tool_processes():
    """浏览器进程不能同时出现在任何工具表里 —— 否则「进程层不定分类」
    这条规则会被自己绕过，chrome 又变回工作。"""
    for cat, table in PROCESS_TABLES.items():
        overlap = BROWSER_PROCESSES & table
        assert not overlap, f"浏览器进程 {sorted(overlap)} 同时被当成{cat}类工具"


def test_every_title_table_is_non_empty():
    """空的词表 = 那一类永远判不出来，而且不报错。"""
    for cat, words in TITLE_TABLES.items():
        assert words, f"{cat} 的标题词表是空的"


# ================================================================
# 误匹配回归 —— 这一组就是「判定不准」的原样重现
# ================================================================

@pytest.mark.parametrize("title", [
    "digital marketing course - google chrome",   # 旧实现："git" in "digital"
    "knowledge base - google chrome",             # 旧实现："edge" in "knowledge"
    "password manager - google chrome",           # 旧实现："word" in "password"
    "wordle - play online",                       # 旧实现："word" in "wordle"
    "decode json online",                         # 旧实现："code" in "decode"
    "barcode generator",                          # 旧实现："code" in "barcode"
    "vimeo - watch videos",                       # 旧实现："vim" in "vimeo"
    "atomic habits summary",                      # 旧实现："atom" in "atomic"
])
def test_substring_traps_are_not_misread_as_work(title):
    """这些标题以前全被判成「工作」。它们含的是**别的词**，不是工作信号。"""
    assert classify("chrome.exe", title) == OTHER


def test_title_matching_uses_word_boundaries():
    """词边界是**机制**层面的保证 —— 直接测它，而不是绕道测某个具体标题。

    为什么值得单独立一条：当前的工作标题词表里恰好没有 `code` / `git` /
    `word` 这类短词（它们是**进程**词表的成员，进程走精确匹配），所以
    「把边界去掉」在现有词表上**看不出任何差别** —— 反向验证时这条
    mutation 静默通过了。而边界本身是必须的：词表随时可能加进 `api` /
    `sql` / `ui` 这种短词，那时没有边界就会在 `capital` / `mysql` /
    `build` 里乱命中。
    """
    from engine.activity.category import _compile_title_regex

    rx = _compile_title_regex({"code", "api"})
    assert rx.search("vs code") is not None
    assert rx.search("api 文档") is not None
    assert rx.search("decode") is None
    assert rx.search("barcode") is None
    assert rx.search("capital") is None


def test_title_is_matched_case_insensitively():
    """窗口标题的大小写不受我们控制（"YouTube" / "BILIBILI"），
    而关键词表是小写的 —— 标题必须先归一，否则一半站点认不出来。"""
    assert classify("chrome.exe", "YouTube - Google Chrome") == FUN
    assert classify("chrome.exe", "BILIBILI 弹幕网") == FUN


def test_browser_is_never_classified_by_process_even_if_listed(monkeypatch):
    """护栏：即使将来有人把 chrome 写进工作工具表，进程层也必须放行它。

    `test_browser_processes_are_not_also_tool_processes` 挡的是「别写进去」，
    这条挡的是「万一写进去了，行为也得对」—— 两道都在。
    （反向验证时发现：现有词表下「浏览器排除」这一步是**不可观测**的，
    因为 chrome 本来就不在任何工具表里。不可观测的守卫等于没有守卫，
    所以用 monkeypatch 把它变成可观测的。）
    """
    from engine.activity import category as cat_mod

    monkeypatch.setattr(cat_mod, "_PROCESS_RULES", (
        (cat_mod.WORK, frozenset({"chrome"})),
    ))
    assert cat_mod.classify("chrome.exe", "") == OTHER
    assert "浏览器" in cat_mod.explain("chrome.exe", "")[1]


@pytest.mark.parametrize("proc", ["barcode.exe", "wordle.exe", "mycode.exe",
                                 "decode.exe", "vimeo.exe", "knowledge.exe"])
def test_process_names_match_exactly_not_by_substring(proc):
    """进程名是受控标识符，用**精确相等**匹配。

    `barcode.exe` 的词干是 `barcode`，不等于 `code` —— 不该被当成编辑器。
    """
    assert classify(proc, "") == OTHER


# ================================================================
# 浏览器：进程层不定分类
# ================================================================

@pytest.mark.parametrize("proc", ["chrome.exe", "msedge.exe", "firefox.exe",
                                 "brave.exe", "360se.exe", "qqbrowser.exe",
                                 "sogouexplorer.exe", "iexplore.exe"])
def test_browser_without_a_signal_is_other_not_work(proc):
    """浏览器停在空白页 / 无信号标题时判「其他」。

    旧实现用进程名兜底把 chrome.exe 当工作工具 —— 那是「在 Chrome 里刷 B 站
    被记成工作」的根因。判不出就说判不出，不猜。
    """
    assert classify(proc, "") == OTHER


def test_browser_content_is_still_classified_by_title():
    """浏览器不是「永远判不出」—— 标题给了站点信号就照判。"""
    assert classify("chrome.exe", "哔哩哔哩") == FUN
    assert classify("chrome.exe", "coursera | online courses") == STUDY


def test_browser_reason_says_it_is_a_browser():
    _cat, why = explain("chrome.exe", "")
    assert "浏览器" in why


# ================================================================
# 三层判定：进程 > 标题 > 其他
# ================================================================

def test_process_wins_over_title():
    """在 Word 里打开一份标题带「b站」的文案，仍然是在工作。

    进程名回答「在用什么工具」（行为意图），标题回答「内容是什么」——
    前者更可信。
    """
    assert classify("winword.exe", "b站文案.docx") == WORK


def test_title_decides_when_process_is_a_container():
    assert classify("chrome.exe", "github - pull request #42") == WORK


def test_no_signal_is_other_not_a_guess():
    assert classify("explorer.exe", "下载") == OTHER
    assert classify("pid_1234", "") == OTHER
    assert classify("", "") == OTHER


# ================================================================
# 标题内部的优先级：娱乐 > 学习 > 沟通 > 工作
# ================================================================

@pytest.mark.parametrize("title,want", [
    ("youtube.com - google docs", FUN),        # 娱乐 > 工作
    ("github 上的 arxiv 论文", STUDY),          # 学习 > 工作
    ("腾讯会议 - 会议纪要", COMM),                # 沟通 > 工作
    ("qq音乐", FUN),                            # 娱乐 > 沟通（"qq" 是沟通词）
])
def test_title_priority_order(title, want):
    """越靠前越明确：站点名（bilibili / coursera）最明确，办公词最泛。"""
    assert classify("chrome.exe", title) == want


# ================================================================
# 中文站点名（窗口标题常写中文）
# ================================================================

@pytest.mark.parametrize("title,want", [
    ("哔哩哔哩 (゜-゜)つロ", FUN),
    ("抖音 - 记录美好生活", FUN),
    ("网易云音乐", FUN),
    ("中国大学MOOC", STUDY),
    ("知网 - 文献检索", STUDY),
    ("企业微信", COMM),
    ("周报 - 飞书文档", COMM),        # 「飞书」比「周报」明确
])
def test_chinese_site_names(title, want):
    assert classify("chrome.exe", title) == want


# ================================================================
# 依据（可解释）：只回命中的词，不回标题原文
# ================================================================

def test_reason_never_quotes_the_window_title():
    """依据里**不能**出现窗口标题原文 —— 那等于把用户内容搬进日志 / 界面。

    `segments` 表连 title 列都没有（隐私由表结构保证），依据也不能是后门。
    只允许回「命中了白名单里的哪个词」。
    """
    secret = "哔哩哔哩 我的私人收藏夹 项目代号猎鹰"
    _cat, why = explain("chrome.exe", secret)
    assert "哔哩哔哩" in why                  # 命中的词来自我们的白名单
    assert "私人收藏夹" not in why
    assert "项目代号猎鹰" not in why
    assert secret not in why


def test_reason_mentions_the_process_for_process_hits():
    _cat, why = explain("code.exe", "")
    assert "code" in why


# ================================================================
# 读时覆盖（用户手动归类）
# ================================================================

def _seg(app, cat, seconds=60.0):
    return {"app": app, "category": cat, "start_at": 0.0,
            "end_at": seconds, "seconds": seconds}


def test_apply_overrides_returns_input_when_no_mapping():
    segs = [_seg("chrome.exe", OTHER)]
    assert apply_overrides(segs, {}) == segs


def test_apply_overrides_replaces_category_and_keeps_the_original():
    """被覆盖的段要**同时**带 `auto_category`（系统判定），
    界面靠它显示「系统判定 其他 → 你的归类 工作」这组对照。"""
    out = apply_overrides([_seg("chrome.exe", OTHER)], {"chrome.exe": WORK})
    assert out[0]["category"] == WORK
    assert out[0]["auto_category"] == OTHER


def test_apply_overrides_does_not_touch_other_apps():
    segs = [_seg("chrome.exe", OTHER), _seg("code.exe", WORK)]
    out = apply_overrides(segs, {"chrome.exe": WORK})
    assert out[1] is segs[1], "没被覆盖的段应当原样复用（读路径是热路径）"


def test_apply_overrides_matches_on_normalized_app_name():
    """库里存的是小写，用户界面传进来的可能带空白 / 大写 —— 两边必须归一。"""
    out = apply_overrides([_seg("chrome.exe", OTHER)], {" Chrome.EXE ": WORK})
    assert out[0]["category"] == WORK


def test_apply_overrides_skips_when_forced_equals_original():
    """强制值与系统判定相同时**不算覆盖** —— 否则界面上会出现一个
    「已手动归类」的标记，而它和自动判定一模一样，用户没法理解。"""
    out = apply_overrides([_seg("chrome.exe", WORK)], {"chrome.exe": WORK})
    assert "auto_category" not in out[0]


def test_apply_overrides_does_not_mutate_the_input_dict():
    seg = _seg("chrome.exe", OTHER)
    apply_overrides([seg], {"chrome.exe": WORK})
    assert seg["category"] == OTHER, "原始分段是证据，不能被就地改写"
