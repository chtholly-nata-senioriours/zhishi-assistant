---
name: activity_advisor
description: 活动建议 - 记录本机应用使用情况，交给 AI 分析后给出节奏建议与规划
version: 1.0.0
author: system
category: tool
requires: requests
permissions: [window_process, input_rate, local_storage, network]
---

# 活动建议（activity_advisor）

记录用户在本机的**应用使用情况**，聚合成摘要后交给 AI 分析，
输出「观察 → 建议 → 明日规划」。

## 这个插件采集什么、不采集什么

**采集**（落本地 `~/.pet_demo/activity.db`）：

| 字段 | 说明 |
| --- | --- |
| `app` | 可执行文件名，如 `code.exe` |
| `category` | 工作 / 娱乐 / 其他（启发式分类，见 `sensor/window_monitor.py`） |
| `start_at` / `end_at` / `seconds` | 该段的起止与时长 |
| `key_rate` | 该段结束时的键盘敲击**次数**（30 秒窗口） |

> **「人不在」的时间会被剪掉。** 通过系统空闲时长
> （`GetLastInputInfo`，见 `engine/activity/idle.py`）判断：结算某一段时，
> 结束点会拉回到「最后一次输入之后」。所以「打开 Chrome → 出去吃饭 → 回来」
> 不会被记成「Chrome 3 小时」。顺带也覆盖了锁屏（锁屏 = 没有输入 = 空闲）。
>
> 空闲与全屏都**只读强度 / 状态，不产生新字段**，也不含任何内容。

**不采集**（不是「代码里没写」，而是数据库表里**根本没有这些列**）：

- ❌ 窗口标题（可能含文件名、网页标题、聊天对象）
- ❌ 按键内容（只有次数，没有字符）
- ❌ 剪贴板、截图、窗口内容

## 数据出网的边界

只有**聚合摘要**会发给模型，形如「`code.exe`（工作）2 小时 10 分，占 45%」——
**不含**逐条明细，**不含**窗口标题，**不含**任何输入内容。

摘要由 `engine/activity/summary.py::build_summary()` 生成，是纯函数，
可以单独审阅它到底发了什么。

摘要**会本地缓存**（`advices` 表），记录没变就不重复调用模型。

## 怎么用（尽量少操作）

| 入口 | 说明 |
| --- | --- |
| **控制中心 →「活动建议」页** | 一键开关 + 常驻「今日小结」+ 生成建议 + 开始专注 + 清空数据 |
| 右键菜单 / 托盘菜单「活动建议」 | 打开对话框（同一套视图协议） |

「收工小结」是**一天最多一次**的托盘气泡提醒，全屏 / 专注计时中 /
人不在电脑前时**一律不推**。判定逻辑见 `engine/activity/reminder.py::should_nudge()`
（纯函数，每条免打扰分支都有单测）。

## 默认关闭

`config.activity.enabled` 默认为 `false`。为 `false` 时：

- 不订阅事件总线，**不落任何数据**
- 控制中心页面上的开关是关闭的；打开它即可开始（**立即生效，不用重启**）

> 注意：`main.py::_start_sensors()` 本来就会启动 `WindowMonitor` /
> `InputMonitor` / `TimeTrigger`（与宠物状态机共用）。本插件**不自己启动传感器**，
> 只订阅事件 —— 否则会装两个键盘钩子。

## 相关文件

| 文件 | 职责 |
| --- | --- |
| `engine/activity/store.py` | 落盘（独立 `activity.db`，与 `ai.db` 分开）；含建议缓存表 |
| `engine/activity/tracker.py` | 把瞬时事件合并成活动段；空闲剪裁与离开/回来 |
| `engine/activity/summary.py` | 摘要生成（纯函数，可单测） |
| `engine/activity/advisor.py` | 预设与提示词 |
| `engine/activity/schedule.py` | 自然日语义（「今天」= 今天 00:00） |
| `engine/activity/idle.py` | 系统空闲秒数（只读强度，零依赖） |
| `engine/activity/reminder.py` | 收工小结的时机判定（纯函数） |
| `plugin.py` | 接线：订阅事件 / 一键开关 / 收工小结 / 建议缓存 / 跨线程回主线程 |
| `dialog.py` | 对话框（只发信号，不碰业务） |
