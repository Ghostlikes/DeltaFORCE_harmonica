# 三角洲行动 · 口琴自动演奏工具（v4）

把任意谱面变成游戏内的按键/鼠标操作。**照搬了三份开源实现**并在此基础上优化：

| 参考实现 | 照搬了什么 |
|---|---|
| [ChickenD233/midikey-player](https://github.com/ChickenD233/midikey-player)（`harmonica-auto-player` 的下架迁移版） | `KeymapProfile.BuildChromatic8` 的本局键位表、`NoteMapper` 的「音高→键+变调键」查找、`MidiLoader` 的 MIDI 读法、`InputTiming.cs` 的逐帧采样时序（**40/40/45ms**）、`MacroExporter` 的宏导出与「误差进位」 |
| [ChiZhou6/harmonica-visualizer](https://github.com/ChiZhou6/harmonica-visualizer) | `BPM=/TITLE=` 文本谱格式、DFH 三行小节谱解析、`b/#/^` 变调前缀语义 |
| [jiko-official.top/delta](https://jiko-official.top/delta/) | 简谱 DSL 全套语法（`_` 减时线、`.` 附点、`-` 增时线、`:`/`/` 精确拍数、`#`/`b`、`'`/`,` 高低八度、`~` 连音、`L/M/R` 变调前缀、`||:`/`:||`）、气口/过渡间隔常量、站点曲库 |

---

## 1. 游戏键位（定死，来自 midikey 的默认方案「8 键半音」）

```
Z X C V B N M ,        ↔  1 2 3 4 5 6 7 高音1   （相对 C4 的半音偏移 0 2 4 5 7 9 11 12）
鼠标中键 = 升半音(+1)   鼠标右键 = 升八度(+12)   鼠标左键 = 降八度(-12)
可弹音域 = MIDI 48..85（C3..C#6）
```
`keymap.py` 负责两个方向：`map_pitch()` 音高→按键、`pitch_of()` 按键→音高（用来把图片谱换算、比对、移调）。

## 2. 三种输入格式 + MIDI

```
python play.py --song songs/天空之城.jianpu       # 简谱 DSL（jiko 站点可直接粘贴）
python play.py --song "songs/小星星.txt"          # BPM=/TITLE= 文本谱（viz2）
python play.py --song "songs/春日影…三角洲.txt"     # DFH 三行小节谱（简谱/键位/节奏）
python play.py --song "某首歌.mid"                # 标准 MIDI 文件
python play.py --score score2.json               # 本项目自己解析出来的事件表
python play.py --list-songs                      # 列出 songs/ 里 15 首现成曲子
```
MIDI 会自动跳过打击乐轨、挑音轨（默认挑音高最高的旋律轨；`--track 2` 指定、`--track-name 主旋律` 按名字、`--merge` 全并）。

## 3. 常用命令

```bash
python play.py --song songs/天空之城.jianpu --dry-run          # 只看时间轴，不按键
python play.py --song songs/天空之城.jianpu --countdown 8 --debug-timing   # 正式弹 + 逐音延迟报表
python play.py --song songs/鸟之诗.jianpu --export ahk          # 导出 AutoHotkey 宏
python play.py --song songs/鸟之诗.jianpu --export lua          # 导出罗技 G HUB 宏
python play.py --score score2.json --export jianpu              # 把我解析的图片谱导成人人可读的简谱
python hud.py --score score2.json                               # 屏幕左上角置顶提示条（配任何播放方式）
python selftest3.py                                            # 端到端自检：17 首谱面全流程（不发按键）
python check_invariants.py score2.json standard                # 独立校验器：时间轴不变量
```

**导出宏后就不用开着 Python 了**（游戏里 ACE 会屏蔽全局钩子，宏走的是驱动层，更省事）：
* `ahk` —— 装 [AutoHotkey v2](https://www.autohotkey.com/) → 双击 `.ahk` → 切到游戏 → `Ctrl+Alt+S` 起弹，`F10` 中止（脚本内自带数据 + `QueryPerformanceCounter` 忙等定时，不依赖 Python）
* `lua` —— Logitech G HUB → 游戏与应用程序 → 新建 Lua 脚本 → 全量粘贴 → 绑定鼠标侧键
* `csv` / `timeline` —— 逐动作时刻表 / 人类可读时间线（对齐站点「事件时间线」列）

## 4. 每音之间的实际 delay（用户最关心的那件事）

`--debug-timing` 会在结束时打印一行汇总，并导出 `timing_log.csv`；`timeline` 导出则是逐音一行：

```
# 时刻ms  动作 对象 音 修饰键      按住ms 与上一音间隔ms
      40   按下  V   4  middle       672
     760   按下  C   3  middle       440    48      ← 音间距 = 时值 - 40ms 松手气口
    1240   按下  Z   1  middle+right 192    40
```

三个「缓一会」的根因（已修，见 git 历史里的 `reparse.py` / `play.py`）：
1. **演奏器把每个音弹成 70ms 的「点」** → 音与音之间是大段静音。改成**连奏按住**（按住到时值末尾减 40ms）。
2. **谱面解析没实现增时线 `-`** → 小节凑不满 4 拍 → 旧代码静音补齐（最多补到 1.2 秒）。现在补齐了 172 处增时线。
3. **修饰键只提前 6ms**，而游戏是 60fps 逐帧采样（16.7ms/帧）→ 变调经常采样不到 = 「个别音不准」。按 midikey 的权威值改为**提前 40ms**。

## 5. 时序档位（`--timing`）

| 档位 | 修饰键提前 | 音间松-按 | 最短按住 | 适用 |
|---|---|---|---|---|
| `standard`（默认） | 40ms | 40ms | 45ms | 60fps 正常帧率 |
| `safe` | 70ms | 70ms | 90ms | 30fps / 卡顿 / 笔记本省电 |
| `aggressive` | 25ms | 25ms | 30ms | 高帧率且想更贴原曲节奏 |

## 6. 已知限制（如实说明）

* **超出口琴音域的音**：`auto` 会先保证「尽量不挪八度」，再挑变调键最少的方案；仍然弹不出来的音（48..85 之外）**按休止处理并明确报数**，绝不偷偷改速度。要整体挪八度用 `--base-octave 3|5`，要半音移调用 `--transpose N`。
* **口琴一次只能吹一个音**：解析时会把与上一音重叠的尾巴截掉（并报数），否则时间轴会出现「同一个键没松手又按」。
* **DFH 三行小节谱的节奏列不含休止**，小节起点按谱面自己写的小节号对齐；个别小节时值不足时，导出简谱会有 0.25 拍级别的记谱偏移（音高 100% 一致）。
* **图片谱面的固有不确定性**（曲目 *I Really Want to Stay at Your House*）：37/120 小节的像素拍数不等于 4，其中 35 处按「缺口延长到本小节最后一个音」处理；红字母↔数字交叉校验 98%；2 处高音点↔括号自相矛盾仍存疑。
* **本机没装 AutoHotkey / Lua**，所以 `.ahk`/`.lua` 只做到「数据核对 + 结构检查」，**没有实跑过**；Python 播放器那条路径是实跑验证过的。
* 游戏在跑时 ACE 会屏蔽全局低层钩子（`err=126`），所以注入类自检要用 `selftest2.py`（游戏没开时验证），时序核对用 `timing_check2.py`（空注入）。

## 7. 文件一览

| 文件 | 作用 |
|---|---|
| `play.py` | 主程序：载入任意格式谱面 → 排时间轴 → 注入按键 / 导出宏 / 打印延迟 |
| `keymap.py` | 游戏键位与音高双向映射、自动基准八度、简谱音名 |
| `score.py` | 统一谱面模型 + 4 个解析器（简谱/viz2/DFH/MIDI）+ 简谱导出 + 事件表换算 |
| `midi_in.py` | 纯 Python 的 SMF 读取（音轨挑选、和弦取最高音、打击乐剔除） |
| `macros.py` | 导出 AutoHotkey / G HUB Lua / CSV / 时间线 |
| `hud.py` | 置顶提示条（独立运行，配 Python 播放器或导出的宏都行） |
| `reparse.py` | 从 3 页图片像素重建事件表（本项目曲目专用） |
| `check_invariants.py` / `timing_check2.py` / `selftest3.py` | 校验器 / 时序探针 / 端到端自检 |
| `songs/` | 15 首现成谱面（jiko 站点曲库 6 首 + viz2/DFH 9 首） |
| `refs/` | 三份参考实现的快照（midikey-player、harmonica-visualizer、jiko app.js） |
| `jiko_lib.py` | jiko 站点公共曲库直连：按歌名搜索 → 下载成可弹简谱（116 首，不用登录） |
| `harmonica_config.py` | 本机帧率 → 时序档位（首次运行问一次，存 `~/.harmonica_config.json`） |

## 8. 交互式入口 + 帧率档位 + 短休止（2026-09-19）

### 8.1 `python play.py` 直接回车流

* 不带参数直接跑 → 提示输入谱面路径；**带引号也能识别**：`"…"` `'…'` `“…”` `‘…’` `「…」`（套两层也认），
  也认 Git-Bash 的 `/f/…` 写法和 `~`；不带扩展名、只写歌名（`天空之城`）都能解析到 `songs/` 里的文件。
* 输入 `1` → 提示输入歌名 → 在 https://jiko-official.top/delta 公共曲库搜索（无需账号）→ 存进 `songs/`
  并**直接接着弹**。同名正文不同的**绝不覆盖**，另存 `曲名(曲库).jianpu`；正文相同直接复用；
  多条匹配列编号选；搜不到给相近曲名。
* 空输入 / `?` → 列 `songs/` 曲目；`q` → 退出；弹完问「再来一首？」（直接回车退出）。
* 管道/脚本里跑（stdin 非终端）**不提示**，退回老行为（`score2.json`），不卡住自动化。

### 8.2 帧率 → 时序档位（首次运行问一次）

目标程序按帧采样输入，「修饰键提前量 / 最短按住 / 抬-按间隔」本质是**帧长的倍数**。
从上游 `InputTiming.cs` 三个档位反推出统一比例 `帧长×2.4 / 2.7 / 2.4`（下限 20/22/18ms），
于是任意帧率都能算 —— 60Hz 精确还原上游 standard，144Hz 精确还原 aggressive：

| 帧率 | 帧长 | 修饰键提前 | 最短按住 | 抬-按间隔 |
|---|---|---|---|---|
| 30Hz | 33.3ms | 80ms | 90ms | 80ms |
| 60Hz | 16.7ms | 40ms | 45ms | 40ms（= standard） |
| 144Hz | 6.9ms | 20ms | 22ms | 18ms（= aggressive） |
| **165Hz（本机）** | **6.1ms** | **20ms** | **22ms** | **18ms** |

首次运行自动读显示器刷新率当默认值（本机检测到 **165Hz**），回车即采用并存进
`~/.harmonica_config.json`；改：`--fps 165` / `--reconfig`；`--timing standard|safe|aggressive` 仍可强制内置档。

### 8.3 `--min-rest`：谱面里的 `0` 会被**如实**弹成静音

`0` 是休止符，脚本忠实照弹 —— 谱面里写几个 `0`，就有几段静音。`父亲.jianpu` 有 **27 处、合计 9.31s**，
其中 14 处是快速跑句里插的 **0.25 拍休止**（形如 `6-- 0__ 6__ 7_`），听感就是「一顿一顿」。
若这些 `0` 是当初图片转录时补空档塞进去的（不是原曲真有停顿），用 `--min-rest` 抹平：

```
python play.py --song songs/父亲.jianpu --min-rest 0.25   # 只抹 0__ ：27 处 → 7 处
python play.py --song songs/父亲.jianpu --min-rest 0.5    # 再抹 0_  ：27 处 → 3 处
python play.py --song songs/父亲.jianpu --min-rest 1.5    # 整拍休止也抹：27 处 → 0 处
```

默认 `0` = 保留谱面原样（休止是谱面内容，不偷偷改）。
对照：`天空之城.jianpu` 一个 `0` 都没有 → 所以它实机听起来是连贯的。
