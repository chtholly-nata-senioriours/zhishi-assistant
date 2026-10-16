# -*- coding: utf-8 -*-
"""S19：生成对外的单文件 Web 演示页（放到桌面）。

为什么要生成而不是手写 HTML
    演示页里要嵌 10 张界面截图。手写的话，图片一改就得手工重新贴一遍
    base64 —— 迟早出现「图换了、页面还是旧图」。这里把「取图 → 嵌图 → 排版」
    做成一条命令，改完界面重跑一次就行。

为什么是**单文件**
    桌面上的 HTML 一旦引用相对路径的图片，用户把 html 单独挪走就全变红叉。
    所以图片一律 base64 内嵌，整个页面**零外部依赖**（无 CDN、无字体、无 JS 库），
    断网双击也能正常打开。

为什么图片不用 Pillow 压
    项目依赖里没有 Pillow，为了压图去装一个库不划算；10 张 PNG 内嵌后
    约 1.5 MB，本地打开毫无压力。

产物：`<桌面>/知时助手-功能演示.html`

用法：python dev_bootstrap.py spikes/s19_demo_page.py
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.activity.category import CATEGORIES, CATEGORY_RULES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SHOT_DIR = ROOT / "spikes" / "results" / "ui_design"

#: 桌面上产物的文件名
OUT_NAME = "知时助手-功能演示.html"


def _desktop() -> Path:
    """桌面目录 —— 优先 `USERPROFILE/Desktop`，退回 OneDrive 重定向后的位置。"""
    import os

    home = Path(os.path.expanduser("~"))
    for cand in (home / "Desktop", home / "OneDrive" / "Desktop",
                 home / "OneDrive" / "桌面", home / "桌面"):
        if cand.is_dir():
            return cand
    raise SystemExit("找不到桌面目录")


def _img(name: str, alt: str, *, cls: str = "shot") -> str:
    """把一张 PNG 读成 base64 data URI，包成 `<img>`。

    找不到图就**直接报错退出**，不静默留个空框 —— 页面上一块空白比报错难查得多。
    """
    path = SHOT_DIR / name
    if not path.is_file():
        raise SystemExit(f"缺图：{path}（先跑对应的 s1x_*_preview.py）")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f'<img class="{cls}" alt="{alt}" src="data:image/png;base64,{data}">'


# ---------------------------------------------------------------- 内容片段

#: 五类配色取**浅色主题的设计 token**（presentation/design/tokens.py::LIGHT）。
#: 页面是深色的，所以这里挑浅色那套（在深底上更跳），但仍与产品内一致 ——
#: 演示页的颜色不该是第二套配色。
_CATEGORY_COLORS = {
    "工作": "#5B9BD5",
    "学习": "#3E9E7E",
    "沟通": "#E8A33D",
    "娱乐": "#E07B5A",
    "其他": "#A8A8A0",
}


def _category_rows() -> str:
    """五类判定依据表 —— 文案**逐字取自** `category.CATEGORY_RULES`。

    不在页面里另写一份：另写一份的下场是改了分类器忘了改这里，
    页面开始说假话（产品内的「应用分类」页也是同一条纪律）。
    """
    out = []
    for cat in CATEGORIES:
        rule = CATEGORY_RULES[cat]
        color = _CATEGORY_COLORS[cat]
        out.append(
            f'<div class="cat-row">'
            f'<span class="cat-dot" style="background:{color}"></span>'
            f'<span class="cat-name" style="color:{color}">{cat}</span>'
            f'<span class="cat-rule">{rule}</span>'
            f"</div>"
        )
    return "\n".join(out)


def _card(title: str, body: str, *, icon: str = "") -> str:
    return (f'<div class="card"><h3>{icon} {title}</h3>'
            f'<p>{body}</p></div>')


# ---------------------------------------------------------------- 页面模板

_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>知时助手 · 功能演示</title>
<style>
  :root {
    --bg: #0B0F14;
    --bg-soft: #11161D;
    --card: #151B23;
    --line: #232B36;
    --fg: #E7EDF4;
    --fg-dim: #93A1B1;
    --fg-faint: #64748B;
    --accent: #4C8DFF;
    --study: #5FBF9F;
    --comm: #D7BA7D;
    --fun: #CE9178;
  }
  * { box-sizing: border-box; }
  html { scroll-behavior: smooth; }
  body {
    margin: 0; background: var(--bg); color: var(--fg);
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC",
                 "Hiragino Sans GB", "Segoe UI", system-ui, sans-serif;
    font-size: 16px; line-height: 1.75;
    -webkit-font-smoothing: antialiased;
  }
  .wrap { max-width: 1120px; margin: 0 auto; padding: 0 24px; }
  a { color: var(--accent); text-decoration: none; }

  /* ---------- 顶栏 ---------- */
  header {
    position: sticky; top: 0; z-index: 50;
    background: rgba(11,15,20,.82); backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--line);
  }
  .bar { display: flex; align-items: center; gap: 28px; height: 60px; }
  .brand { font-weight: 700; letter-spacing: .5px; }
  .brand i {
    display: inline-block; width: 10px; height: 10px; border-radius: 50%;
    background: var(--accent); margin-right: 9px; vertical-align: middle;
    box-shadow: 0 0 12px rgba(76,141,255,.9);
  }
  nav { display: flex; gap: 20px; margin-left: auto; flex-wrap: wrap; }
  nav a { color: var(--fg-dim); font-size: 14px; }
  nav a:hover { color: var(--fg); }

  /* ---------- Hero ---------- */
  .hero { padding: 84px 0 56px; position: relative; overflow: hidden; }
  .hero::before {
    content: ""; position: absolute; inset: -40% 30% auto -20%; height: 620px;
    background: radial-gradient(closest-side, rgba(76,141,255,.20), transparent);
    pointer-events: none;
  }
  .eyebrow {
    display: inline-block; font-size: 13px; letter-spacing: .12em;
    color: var(--accent); border: 1px solid rgba(76,141,255,.35);
    background: rgba(76,141,255,.10); border-radius: 999px;
    padding: 5px 14px; margin-bottom: 22px;
  }
  h1 {
    font-size: 60px; line-height: 1.12; margin: 0 0 16px;
    letter-spacing: -.02em; font-weight: 800;
  }
  .lede { font-size: 20px; color: var(--fg-dim); max-width: 760px; margin: 0 0 34px; }
  .stats {
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px;
    margin: 40px 0 8px;
  }
  .stat {
    border: 1px solid var(--line); background: var(--card);
    border-radius: 14px; padding: 18px 20px;
  }
  .stat b { display: block; font-size: 30px; line-height: 1.25; letter-spacing: -.01em; }
  .stat span { color: var(--fg-dim); font-size: 14px; }
  .stat.hi { border-color: rgba(76,141,255,.45); background: rgba(76,141,255,.08); }
  .stat.hi b { color: var(--accent); }

  /* ---------- 区块 ---------- */
  section { padding: 62px 0; border-top: 1px solid var(--line); }
  .kicker {
    font-size: 13px; letter-spacing: .14em; color: var(--accent);
    text-transform: uppercase; margin-bottom: 10px; font-weight: 600;
  }
  h2 { font-size: 34px; margin: 0 0 14px; letter-spacing: -.01em; }
  .sub { color: var(--fg-dim); max-width: 820px; margin: 0 0 30px; }
  h3 { font-size: 17px; margin: 0 0 8px; }
  p { margin: 0 0 14px; }

  /* ---------- 截图 ---------- */
  figure { margin: 0 0 8px; }
  .shot {
    display: block; width: 100%; height: auto;
    border: 1px solid var(--line); border-radius: 14px;
    box-shadow: 0 26px 60px rgba(0,0,0,.55);
    cursor: zoom-in; background: #fff;
  }
  figcaption { color: var(--fg-faint); font-size: 13.5px; margin-top: 12px; }
  .shot-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }

  /* ---------- 卡片网格 ---------- */
  .grid { display: grid; gap: 16px; }
  .g3 { grid-template-columns: repeat(3, 1fr); }
  .g2 { grid-template-columns: repeat(2, 1fr); }
  .card {
    border: 1px solid var(--line); background: var(--card);
    border-radius: 14px; padding: 22px 22px 6px;
  }
  .card p { color: var(--fg-dim); font-size: 15px; }

  /* ---------- 列表 ---------- */
  ul.clean { list-style: none; padding: 0; margin: 0; }
  ul.clean li {
    padding: 9px 0 9px 26px; position: relative; color: var(--fg-dim);
    border-bottom: 1px dashed rgba(35,43,54,.9);
  }
  ul.clean li:last-child { border-bottom: 0; }
  ul.clean li::before {
    content: ""; position: absolute; left: 4px; top: 19px;
    width: 7px; height: 7px; border-radius: 50%; background: var(--accent);
  }
  ul.clean li b { color: var(--fg); font-weight: 600; }

  /* ---------- 分类表 ---------- */
  .cats {
    border: 1px solid var(--line); border-radius: 14px;
    background: var(--card); overflow: hidden; margin: 0 0 26px;
  }
  .cat-row {
    display: grid; grid-template-columns: 16px 74px 1fr;
    gap: 14px; align-items: baseline;
    padding: 16px 22px; border-bottom: 1px solid var(--line);
  }
  .cat-row:last-child { border-bottom: 0; }
  .cat-dot {
    width: 11px; height: 11px; border-radius: 3px;
    display: inline-block; transform: translateY(-1px);
  }
  .cat-name { font-weight: 700; }
  .cat-rule { color: var(--fg-dim); font-size: 15px; }

  /* ---------- 三层判定 ---------- */
  .layers { counter-reset: layer; margin: 0 0 30px; }
  .layer {
    display: flex; gap: 18px; padding: 18px 0;
    border-bottom: 1px dashed rgba(35,43,54,.9);
  }
  .layer:last-child { border-bottom: 0; }
  .layer .n {
    counter-increment: layer; flex: 0 0 38px; height: 38px; border-radius: 10px;
    background: rgba(76,141,255,.12); border: 1px solid rgba(76,141,255,.32);
    color: var(--accent); font-weight: 700; display: grid; place-items: center;
  }
  .layer .n::before { content: counter(layer); }
  .layer h3 { margin-bottom: 4px; }
  .layer p { color: var(--fg-dim); font-size: 15px; margin: 0; }
  code {
    background: rgba(110,118,129,.18); border-radius: 5px;
    padding: 1px 7px; font-size: 13.5px;
    font-family: "Cascadia Mono", Consolas, "Courier New", monospace;
  }

  /* ---------- 页脚 ---------- */
  footer {
    border-top: 1px solid var(--line); padding: 40px 0 60px;
    color: var(--fg-faint); font-size: 14px;
  }

  /* ---------- 灯箱 ---------- */
  #lb {
    position: fixed; inset: 0; background: rgba(4,7,10,.94);
    display: none; place-items: center; z-index: 100; padding: 24px;
    cursor: zoom-out;
  }
  #lb.on { display: grid; }
  #lb img { max-width: 100%; max-height: 92vh; border-radius: 10px;
            box-shadow: 0 30px 80px rgba(0,0,0,.7); }

  @media (max-width: 900px) {
    h1 { font-size: 40px; }
    .stats, .g3, .g2, .shot-pair { grid-template-columns: 1fr 1fr; }
    nav { display: none; }
  }
  @media (max-width: 620px) {
    .stats, .g3, .g2, .shot-pair { grid-template-columns: 1fr; }
    .cat-row { grid-template-columns: 16px 1fr; }
    .cat-rule { grid-column: 2; }
  }
</style>
</head>
<body>

<header>
  <div class="wrap bar">
    <div class="brand"><i></i>知时助手</div>
    <nav>
      <a href="#time">时间感知</a>
      <a href="#classify">分类判定</a>
      <a href="#evidence">决策留痕</a>
      <a href="#ai">AI 助手</a>
      <a href="#privacy">隐私可控</a>
      <a href="#quality">工程可信度</a>
    </nav>
  </div>
</header>

<div class="hero">
  <div class="wrap">
    <span class="eyebrow">WINDOWS 桌面应用 · PYTHON + PYSIDE6</span>
    <h1>知时助手</h1>
    <p class="lede">
      一个懂你工作节律的 Windows 桌面助手。常驻一枚悬浮球，替你记录时间去向、
      在合适的时候提醒你休息，也能随时问答、改写、翻译 ——
      而所有记录都只留在你自己的电脑里。
    </p>
    <div class="stats">
      <div class="stat hi"><b>14</b><span>功能页（3 组导航）</span></div>
      <div class="stat"><b>5</b><span>类时间分类，可手动纠正</span></div>
      <div class="stat"><b>856</b><span>项自动化测试通过</span></div>
      <div class="stat"><b>0</b><span>明文密钥落盘</span></div>
    </div>
  </div>
</div>

<div class="wrap">

<!-- ================= 时间感知 ================= -->
<section id="time">
  <div class="kicker">时间感知</div>
  <h2>今天的时间，到底去哪了</h2>
  <p class="sub">
    在后台安静地记录「前台应用 + 停留时长」，把碎片合并成完整时段，
    再画成一条 24 小时时间轴。离开电脑的那段时间会自动剪掉 ——
    挂着不动不算在用。
  </p>
  <figure>
    @@IMG_TODAY@@
    <figcaption>今日：总时长 / 深度工作 / 最长应用 / 切换打断，时间轴、应用排行与 AI 建议</figcaption>
  </figure>
  <div class="grid g2" style="margin-top:34px">
    <div class="card">
      <h3>看得懂的三件事</h3>
      <ul class="clean">
        <li><b>时间轴</b>：24 小时铺满，碎片自动合并，一眼看出哪段被切碎</li>
        <li><b>应用排行</b>：谁占了大头，按类别着色</li>
        <li><b>切换打断</b>：一天切了多少次窗口 —— 比总时长更能说明状态</li>
      </ul>
    </div>
    <div class="card">
      <h3>深度工作的口径</h3>
      <p>
        只算<b>工作 + 学习</b>，且口径在代码里只有一处定义 ——
        悬浮球、托盘、趋势页读的是同一个数，不会各说各话。
      </p>
      <p>
        番茄钟与悬浮球打通：专注时进度环改画本轮专注，
        倒计时卡带暂停 / 结束，四种入口的文案同一套。
      </p>
    </div>
  </div>
  <figure style="margin-top:34px">
    @@IMG_TREND@@
    <figcaption>趋势：近 7 / 30 天，每日深度工作、周期对比、时间构成、最易被打断的时段</figcaption>
  </figure>
</section>

<!-- ================= 分类判定 ================= -->
<section id="classify">
  <div class="kicker">分类判定</div>
  <h2>判定要准，更要能解释、能纠正</h2>
  <p class="sub">
    时间记录只有分对了类才有意义。分类按<b>行为类型</b>划分，不按场景 ——
    场景（上班 / 在家）判不出来，行为判得出来。
  </p>

  <div class="layers">
    <div class="layer">
      <div class="n"></div>
      <div>
        <h3>先看进程名（精确匹配）</h3>
        <p>
          <code>code.exe</code> → 工作，<code>steam.exe</code> → 娱乐。
          进程名是受控标识符，按词干精确比对，不会把 <code>barcode.exe</code> 误认成代码编辑器。
          <b>浏览器除外</b> —— <code>chrome.exe</code> 只是个容器，不代表你在做什么。
        </p>
      </div>
    </div>
    <div class="layer">
      <div class="n"></div>
      <div>
        <h3>再看窗口标题（词边界匹配）</h3>
        <p>
          英文按<b>词边界</b>匹配：能命中 <code>vs code</code>，
          但不会命中 <code>decode</code>；中文按子串匹配。
          早期版本用裸子串判断，含 <code>digital</code>、<code>knowledge</code>、
          <code>password</code> 的页面会被误判成工作 —— 现已修正，并逐条钉了回归用例。
        </p>
      </div>
    </div>
    <div class="layer">
      <div class="n"></div>
      <div>
        <h3>判不出来就归「其他」，不猜</h3>
        <p>
          两个方向同时命中时宁可放进「其他」，也不硬塞一个类别。
          每一次判定都会附上<b>依据</b>（命中了哪个词），而依据只回命中的词，
          不会把窗口标题原文写进记录。
        </p>
      </div>
    </div>
  </div>

  <h3 style="margin:0 0 14px;font-size:20px">五个分类项与判定依据</h3>
  <div class="cats">
@@CATEGORY_ROWS@@
  </div>

  <figure>
    @@IMG_CATEGORY@@
    <figcaption>应用分类页：逐应用显示「停留时长 / 系统判定 / 你的归类」，改过的行用强调色标出</figcaption>
  </figure>

  <div class="grid g2" style="margin-top:34px">
    <div class="card">
      <h3>每个应用都能被你改</h3>
      <p>
        判定不可能全对，所以每个应用都能手动归到指定分类。
        你的归类与系统判定<b>分开存</b>：原始记录不被篡改，
        随时可以「恢复自动判定」，而「系统当初判成什么」永远查得到。
      </p>
    </div>
    <div class="card">
      <h3>改了就立刻生效</h3>
      <p>
        归类在<b>读取时</b>叠加，改动对该应用的全部记录生效（含历史），
        摘要、趋势与深度工作时长会同步变化 ——
        而不是只改了一个标签、统计数字还是旧的。
      </p>
    </div>
  </div>
</section>

<!-- ================= 决策留痕 ================= -->
<section id="evidence">
  <div class="kicker">人机协同</div>
  <h2>每条建议，都留下可核对的证据</h2>
  <p class="sub">
    AI 给出建议、你决定采纳还是忽略 —— 这个决定本身也会被记录下来，
    用来回答三个问题：凭什么这么建议、当时的数据是什么样、这个决定改变了什么。
  </p>
  <figure>
    @@IMG_DECISIONS@@
    <figcaption>协同记录：时间 / 决定 / 结论 / 影响范围，可按全部·采纳·忽略筛选，并可导出</figcaption>
  </figure>
  <div class="grid g3" style="margin-top:34px">
    <div class="card">
      <h3>凭什么</h3>
      <p>建议基于哪几条依据提出，逐条列出，不用猜。</p>
    </div>
    <div class="card">
      <h3>当时什么样</h3>
      <p>
        记录现场数据 —— 只放聚合数字（条数 / 总时长 / 起止 / 是否过期），
        连应用名都不放，且用白名单过滤，认不出的字段直接丢掉。
      </p>
    </div>
    <div class="card">
      <h3>改变了什么</h3>
      <p>
        记的是<b>实际结果</b>：专注真的开始了才写「已开始」，
        失败就如实写失败，不谎称。
      </p>
    </div>
  </div>
</section>

<!-- ================= AI 助手 ================= -->
<section id="ai">
  <div class="kicker">AI 助手</div>
  <h2>随时唤起，问完就走</h2>
  <p class="sub">
    三个全局热键，一个悬浮面板：问答、改写、翻译、截图提问。
    回答流式吐字，可以随时打断；历史会话能一键载入继续追问。
  </p>
  <div class="grid g2" style="margin-top:0">
    <figure>
      @@IMG_PANEL@@
      <figcaption>AI 面板：热键唤起，流式输出</figcaption>
    </figure>
    <figure>
      @@IMG_AISET@@
      <figcaption>AI 服务：服务地址、模型与密钥保存位置</figcaption>
    </figure>
  </div>
  <div class="grid g3" style="margin-top:34px">
    <div class="card">
      <h3>三种问法</h3>
      <p>划词翻译、截图提问、直接问答 —— 都是全局热键，不用先切窗口。</p>
    </div>
    <div class="card">
      <h3>接自己的模型服务</h3>
      <p>兼容 OpenAI 接口的服务都能接：填地址、选模型，一键探测连通性与可用模型。</p>
    </div>
    <div class="card">
      <h3>密钥不落配置文件</h3>
      <p>
        API Key 存进操作系统凭据库（或 Windows DPAPI 加密文件），
        配置里只留一个引用；界面上永远只显示脱敏后的样子。
      </p>
    </div>
  </div>
</section>

<!-- ================= 隐私 ================= -->
<section id="privacy">
  <div class="kicker">隐私可控</div>
  <h2>数据归你自己管</h2>
  <p class="sub">
    隐私不是一句承诺，而是结构上的保证：不该记的东西<b>表里根本没有那一列</b>，
    所以想记也记不下来。
  </p>
  <figure>
    @@IMG_PRIVACY@@
    <figcaption>隐私与数据：逐类查看占用、导出、清空</figcaption>
  </figure>
  <div class="grid g2" style="margin-top:34px">
    <div class="card">
      <h3>不采集什么</h3>
      <ul class="clean">
        <li><b>窗口标题</b>：活动记录表里没有 title 列，有测试直接钉住表结构</li>
        <li><b>按键内容</b>：只统计敲击频率，不记录按了什么</li>
        <li><b>剪贴板与截图</b>：只在按下热键的那一刻读取，用完即走</li>
      </ul>
    </div>
    <div class="card">
      <h3>会出网什么</h3>
      <ul class="clean">
        <li><b>只在你主动提问时</b>才发送，发到你自己填的地址</li>
        <li><b>只发聚合摘要</b>：应用名 + 时长，不含任何窗口内容</li>
        <li><b>行为数据与对话记录分库</b>：清空一个不会动另一个</li>
      </ul>
    </div>
  </div>
  <div class="card" style="margin-top:16px">
    <h3>可自决的三件事</h3>
    <p>
      控制中心的「隐私与数据」页可以逐类<b>查看占用大小、导出成 zip、一键清空</b>；
      活动采集默认<b>关闭</b>，不开启就不订阅事件、不落任何数据。
      导出走数据库的备份接口，不会漏掉还留在写入缓冲里的最近几轮记录。
    </p>
  </div>
</section>

<!-- ================= 双主题 ================= -->
<section id="theme">
  <div class="kicker">界面</div>
  <h2>一套设计系统，深浅两套主题</h2>
  <p class="sub">
    颜色、间距、圆角、字号全部来自统一的令牌表，样式表里零个硬编码色值 ——
    所以切主题时整界面一起变，不会出现「面板深色、对话框浅色」的割裂。
  </p>
  <div class="shot-pair">
    <figure>
      @@IMG_TODAY_L@@
      <figcaption>浅色</figcaption>
    </figure>
    <figure>
      @@IMG_TODAY_D@@
      <figcaption>深色</figcaption>
    </figure>
  </div>
</section>

<!-- ================= 工程可信度 ================= -->
<section id="quality">
  <div class="kicker">工程可信度</div>
  <h2>每个结论都留了证据</h2>
  <p class="sub">
    界面好不好看可以主观，但「功能是不是真的能用」必须可验证。
    项目里每一条改动都配了自动化测试或可复现的验证脚本。
  </p>
  <div class="grid g3">
    <div class="card">
      <h3>856 项自动化测试</h3>
      <p>
        覆盖分类判定、密钥存储、隐私导出、页面规格、状态机与规则引擎。
        测试全部跑在临时数据根下，不会碰你的真实数据。
      </p>
    </div>
    <div class="card">
      <h3>反向验证</h3>
      <p>
        故意把实现改坏，确认测试<b>真的会红</b> ——
        跑不到「0 漏网」就说明有测试是摆设。本轮分类与配色改动共验证 40 处。
      </p>
    </div>
    <div class="card">
      <h3>打包后四查</h3>
      <p>
        每次发版都核对：模块与符号清单、包内密钥泄漏、程序真能起来并显示窗口、
        启动零错误。清单里还专门检查<b>旧代码的残留字面量</b>。
      </p>
    </div>
  </div>
  <div class="grid g2" style="margin-top:16px">
    <div class="card">
      <h3>分层架构</h3>
      <p>
        系统代理（热键 / 选区 / 截图）→ 决策引擎（状态机 / 活动分析 / AI 编排）
        → 表现层（悬浮球 / 托盘 / 控制中心）→ 数据层。
        依赖严格单向向上，核心分析层零界面依赖，可脱离界面单测。
      </p>
    </div>
    <div class="card">
      <h3>插件化</h3>
      <p>
        内置能力都以插件形式装载，可单独启用 / 卸载 / 恢复；
        插件按清单自动发现，第三方插件不需要改动主程序。
      </p>
    </div>
  </div>
</section>

</div>

<footer>
  <div class="wrap">
    知时助手 · Windows 桌面应用（Python + PySide6 / Qt6）· 所有数据仅存于本机
  </div>
</footer>

<div id="lb"><img alt="放大查看"></div>
<script>
  (function () {
    var lb = document.getElementById('lb');
    var big = lb.querySelector('img');
    document.querySelectorAll('img.shot').forEach(function (img) {
      img.addEventListener('click', function () {
        big.src = img.src;
        lb.classList.add('on');
      });
    });
    lb.addEventListener('click', function () {
      lb.classList.remove('on');
      big.removeAttribute('src');
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { lb.classList.remove('on'); }
    });
  })();
</script>
</body>
</html>
"""


def build() -> Path:
    html = _TEMPLATE
    html = html.replace("@@CATEGORY_ROWS@@", _category_rows())
    html = html.replace("@@IMG_TODAY@@", _img("today_page_light.png", "今日页"))
    html = html.replace("@@IMG_TREND@@", _img("trend_light.png", "趋势页"))
    html = html.replace("@@IMG_CATEGORY@@", _img("app_category_light.png", "应用分类页"))
    html = html.replace("@@IMG_DECISIONS@@", _img("decisions_light.png", "协同记录页"))
    html = html.replace("@@IMG_PANEL@@", _img("panel_light.png", "AI 面板"))
    html = html.replace("@@IMG_AISET@@", _img("ai_settings_light.png", "AI 服务设置"))
    html = html.replace("@@IMG_PRIVACY@@", _img("privacy_light.png", "隐私与数据页"))
    html = html.replace("@@IMG_TODAY_L@@", _img("today_page_light.png", "浅色主题"))
    html = html.replace("@@IMG_TODAY_D@@", _img("today_page_dark.png", "深色主题"))

    assert "@@" not in html, "还有没替换的占位符：" + \
        str([ln for ln in html.splitlines() if "@@" in ln][:3])

    out = _desktop() / OUT_NAME
    out.write_text(html, encoding="utf-8")
    return out


def main() -> int:
    path = build()
    print(f"[完成] {path}")
    print(f"       体积 {path.stat().st_size / 1024 / 1024:.2f} MB（图片已 base64 内嵌，零外部依赖）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
