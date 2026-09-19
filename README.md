# DeltaFORCE_harmonica · 三角洲行动 口琴自动演奏

把**谱面**变成**游戏里的按键**，让游戏内的口琴自己弹出来。支持中文交互、在线曲库取谱、
帧率自适应时序，并自带一套"缺音检查"——因为这个项目踩过的坑，全在**缺音**上。

```bash
python play.py                 # 回车 → 提示输入谱面路径；输入 1 可按歌名从曲库下载
```

---

## 1. 和别的方案比，它不一样在哪

| 方案 | 常见做法 | 本项目 |
|---|---|---|
| 通用按键精灵 / AutoHotkey 手录 | 对着视频**一音一音手录**，换首歌要从头再来 | 谱面**自动编译**成按键时间轴；换歌只换文件 |
| 现成的 MIDI 播放器（如 midikey-player） | 只吃 **MIDI**，不管简谱；音高时序按固定 60fps | **5 种输入**：jiko 简谱 / 数字简谱 / DFH / viz2 谱 / MIDI；时序**按你的帧率**算 |
| 网页播放器（harmonica-visualizer 等） | 只在网页里出声，**进不了游戏** | 直接驱动游戏内按键（SendInput，绕开 ACE 对全局钩子的屏蔽） |
| 别人写的口琴脚本 | 只弹一个八度 / 不管同键连击 / 没有校验 | 37 键全音域 + 同键连击保护 + 数据级不变量校验 + 逐音时序探针 |

**一句话**：别人给你的是一段能弹的按键；这里给的是一条**从谱面到按键的可验证流水线**——
每个音为什么在这个时刻被按下、有没有被吞掉，都能查得出来。

## 2. 核心优势

1. **中文交互入口**：`python play.py` 直接回车 → 提示输入谱面路径；**带引号也能识别**
   （`"…"` `'…'` `“…”` `‘…’` `「…」`，套两层也认），也认 Git-Bash 的 `/f/…` 和 `~`；
   不带扩展名、只写歌名都能命中 `songs/`。
2. **三个曲库一起搜**：输入 `1` → 输歌名 → 跨三个公开曲库检索（**500+ 条**，数量实时增长），能下的直接下到
   `songs/` 并**接着弹**；不能下的给出**直达链接**：

   | 曲库 | 目录 | 谱面 |
   |---|---|---|
   | [jiko-official.top/delta](https://jiko-official.top/delta) | 116 首 | **可下载**（公开 JSON，免登录） |
   | [shushu.fan/fun/harmonica](https://shushu.fan/fun/harmonica) | 195+ 首 | 需登录 → 给直达链接 |
   | [delta-test.shallow.ink/harmonica](https://delta-test.shallow.ink/harmonica) | 196+ 首 | 不在公开接口 → 给直达链接 |

   同名文件正文不同时**绝不覆盖**（另存 `曲名(曲库).jianpu`）；两站同名曲的 `songId` 相同（同库镜像）。
   另两站的谱面也能弹：在页面里把谱面文本复制下来 → `python play.py --paste` 直接弹（不用登录接口）。
3. **帧率自适应时序**：目标程序按帧采样输入，"修饰键提前量 / 最短按住 / 抬-按间隔"本质都是
   **帧长的倍数**，比例由上游 `InputTiming.cs` 三个档位反推（`帧长×2.4 / 2.7 / 2.4`）。
   首次运行问一次帧率并存进 `~/.harmonica_config.json`：

   | 帧率 | 修饰键提前 | 最短按住 | 抬-按间隔 |
   |---|---|---|---|
   | 60Hz | 40ms | 45ms | 40ms（= 上游 standard） |
   | 144Hz | 20ms | 22ms | 18ms（= 上游 aggressive） |
   | **165Hz（作者机器）** | **20ms** | **22ms** | **18ms** |

4. **同键连击保护**：谱面里 `,7_ ,7` 是**同一个音连响两下**，游戏要看到"抬手"才认第二下。
   同一个键的「抬→按」因此强制 **≥40ms**（上游 60fps 档权威值）：不够就**把这一下往后挪**，
   实在挪不下就**并进前一个同键音**——宁可连成一片，也绝不缺音。
5. **缺音三来源全部堵住**（见 §5）：同键连击、`--late drop` 丢音、音域外静音。
6. **数据级不变量校验**：`dev/check_invariants.py` 独立复算 6 条不变量——动作时间不倒退、
   同键不重叠按下、按下的修饰键集合恰好匹配、按住 ≥ 档位下限、抬→按 ≥ 余量、同键重触发 ≥ 阈值。
7. **逐音时序探针**：`--debug-timing` 打印每个音的计划/实际时刻、调度迟到、修饰键提前量、
   与上一音的间隔、按住时长，并导出 CSV。**实测**（《天空之城》87 BPM / 109 音 / 真实游戏内一轮）：
   调度迟到平均 **0.0ms**、最大 **0.1ms**，修饰键提前量最小 **39.0ms**，同键重触发违规 **0**。
8. **全音域 + 自动变调**：可弹 MIDI **48..85**（37 键），超出的音**按整八度折回**（不是丢掉）；
   左键=降调、中键=升半音、右键=升调，按音高自动排布，谱面不用手改。
9. **6 种导出**：`ahk`（AutoHotkey）/ `lua`（罗技 G HUB）/ `csv` / `timeline` / `jianpu`（可粘回网站）/ `json`。
   简谱导出→重解析**无损往返**，等于自带谱面格式转换器。
10. **播放部分零第三方依赖**：纯 Python 标准库 + `ctypes` SendInput（谱面制作流水线才需要 numpy/Pillow 等）。

## 3. 快速开始

```bash
# 0) 需要 Python 3.10+（只用到标准库）
git clone https://github.com/Ghostlikes/DeltaFORCE_harmonica.git
cd DeltaFORCE_harmonica

# 1) 先看时间轴（不按键、最安全）
python play.py --song songs/天空之城.jianpu --dry-run

# 2) 实机：8 秒倒计时 → 切到游戏窗口并唤出口琴 → 开弹（F10 中止）
| 播放某张谱面 | `python play.py --song songs/暗号.jianpu --countdown 8` |
| 导入 MP3/音频 | `python play.py --song 某首歌.mp3 --dry-run`（见 §3.1b） |

# 3) 交互模式：回车给路径；输入 1 按歌名从曲库下载
python play.py
```

### 3.1b 直接喂 MP3（把音频听成谱面）

```bash
python play.py --song "D:/音乐/某首歌.mp3" --dry-run                            # 先看听成了什么
python play.py --song "D:/音乐/某首歌.mp3" --countdown 8 --debug-timing         # 实弹
python play.py --song "D:/音乐/清唱.mp3" --mp3-fmin 200 --mp3-fmax 1000 --dry-run   # 只认人声区间
python play.py --song "D:/音乐/某首歌.mp3" --mp3-save 我的歌                     # 听出来存进 songs/
```

不用装 ffmpeg：解码用 **PyAV**（自带 FFmpeg 库），音高检测是自己写的 **YIN**（纯 numpy/scipy）。
支持 `.mp3 .wav .ogg .flac .m4a .aac .opus .wma`。

**效果边界说清楚**：单声部、旋律突出的音频（清唱、单乐器、口琴录音）听得准
（自测里合成旋律的音高命中 ≥90%）；编曲厚重的流行歌会**跟着最突出的那件乐器走**，只能当参考 ——
想更干净就收窄区间（`--mp3-fmin/--mp3-fmax`）、提高门限（`--mp3-conf 0.7`）。
一个音都没听出来时会**明确报错并给建议**，不会悄悄给你一份跑偏的谱。

## 4. 目录结构

```
DeltaFORCE_harmonica/
├── README.md                  ← 你正在看的
├── play.py                    ★ 唯一需要运行的脚本（交互入口 / 时间轴 / 注入 / 导出 / 探针）
├── score.py                    谱面解析与编译（5 种格式 → 音符 → 按键事件表）
├── keymap.py                   键位与音高映射（音域 48..85、左中右键语义）
├── harmonica_config.py         帧率 → 时序档位（首次问一次，记住）
├── songlib.py                 多源曲库：jiko / shushu / shallow 一起搜（能下的直接下）
├── jiko_lib.py                 jiko 曲源：搜索 / 下载 / 正文去重
├── midi_in.py                  标准 MIDI 读取器（纯 Python，无第三方依赖）
├── macros.py                   导出 AHK / Lua / CSV / 时间线 / 简谱
├── 弹奏.bat                    一键启动菜单（含各种自检入口）
├── songs/                      曲谱文件夹（现成曲目 + 下载目标）
├── data/                       事件表示例（score2.json 540 音 / score.json）
├── docs/                       详细手册 · 来源出处与许可 · 单曲按键说明
├── examples/                   四种导出产物示例（csv / timeline / ahk / lua / 事件表 / 简谱）
├── dev/                        自检与校验：check_invariants.py · selftest3.py · 时序探针 · 运行日志
└── tools/                      辅助工具：hud.py（置顶显示条）· chart-pipeline/（图片谱制作流水线）
```

> `songs/` 与 `data/` 是**数据**，`docs/` `dev/` `tools/` 是**辅助**——根目录只留你真正要跑的东西。

## 5. 缺音的五个来源（本项目的实战结论）

实机上"听着缺音"基本就这五种，**这个项目把它们全堵了**，而且每一条都能查：

| 来源 | 现象 | 现在怎么处理 |
|---|---|---|
| ① **同键连击间隔不足** | 开头密集连击的 riff 糊掉、听不出旋律，中段（长音/16 分）正常 | 同键「抬→按」强制 ≥40ms：挪后或并成长音（`--retrigger-ms` 可调，`--timing safe` 更保守） |
| ② **`--late drop` 丢音** | 随机位置零星缺音，机器越卡越多 | **默认已改为 `--late shift`**：宁可晚十几毫秒，也把每个音都按出来 |
| ③ **音域外的音变静音** | 跨度超过 3 个八度的谱面，低音/高音整段消失 | 超域音**按整八度折回**到 48..85，`stats['folded']` 里能看到折了几个 |
| ④ **超短音**（时值 < 最短按住） | 谱面里 4ms 级的装饰音整段听不见 | 按住时长**提到档位下限**（165Hz→22ms / 60Hz→45ms），宁可略长也不静音 |
| ⑤ **连发**（两音起点 < 20ms） | 密集装饰音只剩一个音 | 后面的音**顺延到 ≥20ms**（听不出来，但两个音都在） |

> ⑤ 的实例：`songs/起风了.jianpu` 原谱最短 4ms —— 实机就是"少音"；现在自动拉到 20ms/22ms。

**自查命令**（弹完看这几行）：

```bash
python play.py --song songs/暗号.jianpu --countdown 8 --debug-timing
```

* `同键连击修正：挪后 N 个 / 并成长音 M 个` —— N 就是被救回来的连击音数量
* `同键重触发 <40ms 的 0 个` —— 不为 0 说明还有连击会被游戏吞掉
* `调度迟到：平均 … 最大 …ms` + `丢掉了 N 个` —— 迟到过大就换 `--late shift`（现在已是默认）
* 还缺音就上更保守的档位：`--timing safe`（同键 80ms、气口 70ms、修饰键提前 70ms）

> 度量口径的坑：同键间隔要量「上一次这个键**抬起** → 这次**按下**」。
> 用「按下→按下」会把按住的那段时间算进去（26ms 的真实间隔被报成 250ms），
> 这类缺音就永远查不出来。`check_invariants.py` 与 `--debug-timing` 都是正确口径。

## 6. 谱面格式与常用命令

| 输入格式 | 说明 |
|---|---|
| jiko 简谱 DSL `.jianpu` | jiko 站点的写法：`5`=1 拍、`5-`=2 拍、`5_`=半拍、`0`=休止、`N:比例` 精确时值、`,5` 低音、`5'` 高音 |
| 数字简谱 `.txt` | 常见简谱文本；支持反复线、连音线、附点、增时线、弱起、拍号校验 |
| DFH 谱 / viz2 谱 | 三角洲社区常见的两种按键/数字写法 |
| MIDI `.mid` | 自动选旋律轨、同刻和弦只留一个音（对齐 midikey-player 的行为） |
| 事件表 `.json` | 本项目自己产出的按键事件表（`data/score2.json`），可再导出成别的格式 |

| 命令 | 作用 |
|---|---|
| `python play.py` | 交互：输入谱面路径，或输 `1` 从曲库按歌名下载 |
| `--dry-run` | 只打印时间轴，不按键（先看这个） |
| `--countdown 8 --debug-timing` | 实机弹 + 逐音时序诊断 |
| `--min-rest 0.5` | 抹平谱面里短于 0.5 拍的休止（`0` 会被如实弹成静音，见手册 §8.3） |
| `--timing safe` | 更保守的内置档（30fps：70/80/70） |
| `--fps 165` / `--reconfig` | 改/重问帧率；不给 `--timing` 就按它自适应 |
| `--export ahk,lua…` | 导出宏/时间线/简谱/事件表（`--export csv` 等，单值） |
| `--song-search 歌名` | 非交互跨三库搜索（`--jiko-search` 是同义别名），`--source jiko\|shushu\|shallow` 限定来源 |
| `--paste` | 把**剪贴板里的谱面文本**存进 `songs/` 并直接弹（用于只能登录看谱的站点） |
| `--list-songs` | 列出现成曲目 |

## 7. 校验与自检（`dev/`）

```bash
python dev/selftest3.py                        # 端到端：解析→按键→时间轴→不变量→导出→简谱往返（不发按键）
python dev/check_invariants.py                 # 独立校验器（默认 data/score2.json）
python dev/check_invariants.py data/score2.json standard
python dev/selftest2.py vk                     # 注入类自检（游戏未开时跑；ACE 会屏蔽全局钩子）
python dev/timing_check2.py 1 4                # 空注入时序核对
```

## 7.5 音频导入自测

```bash
python dev/selftest4.py
```

自己合成一段已知旋律（带谐波的口琴式音色）→ 编成 MP3 和 WAV → 用 `audio_in` 听回来对答案，
所以**可复现、不含任何版权音频**。同时覆盖：YIN 音高精度（130/220/440/659/1200Hz）、
`parse_any` 按扩展名分发、全静音明确报错、找不到文件明确报错。

## 8. 已知限制

* **ACE 反作弊**：游戏运行时屏蔽全局低层钩子（`err=126`），所以注入走 `SendInput`；
  注入类自检必须在游戏未开时跑。
* `0` 休止符会被**如实**弹成静音（忠实谱面），想连贯用 `--min-rest`。
* 同键连击被挪后最多 ~25ms、塞不下的会并成长音——**保音优先于严格对齐**。
* 图片谱转谱面（`tools/chart-pipeline/`）是作者自用的一次性流水线，环境依赖较重（numpy/Pillow/pymupdf/rapidocr）。

## 9. 来源与许可

本项目基于三个开源实现移植并大幅改造：**ChickenD233/midikey-player**（MIT，时序预算与
`BuildSchedule` 规则、MIDI 选轨）、**ChiZhou6/harmonica-visualizer**、**jiko-official.top/delta**
（简谱 DSL 语义与公共曲库）。

另外接入两个**第三方曲库目录**（只读检索，用于"按歌名找谱"）：
[shushu.fan/fun/harmonica](https://shushu.fan/fun/harmonica)（三角洲鼠鼠工具 · 口琴曲谱）与
[delta-test.shallow.ink/harmonica](https://delta-test.shallow.ink/harmonica)（DeltaForce 口琴曲库）。
两者都**只用各家公开接口/公开页面**：shallow 走它自己的匿名令牌（`POST /api/v1/auth/anonymous-token`，
带一个本地随机设备指纹）；shushu 只解析其公开页面上的目录信息。**不绕过登录、不伪造凭证、不转载谱面本体**。

`refs/` 下的快照仅供对照、**不随仓库分发**；详见 [`docs/来源出处与许可.md`](docs/来源出处与许可.md)。
本仓库代码：MIT（见 `LICENSE`）。

详细手册见 [`docs/README_自动弹奏.md`](docs/README_自动弹奏.md)。
