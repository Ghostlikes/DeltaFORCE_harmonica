# DeltaFORCE_harmonica

**《三角洲行动》(Delta Force) 口琴玩法 · 谱面 → 游戏内自动演奏工具**

把任意谱面（简谱 / 文本谱 / DFH 三行谱 / 标准 MIDI）解析成游戏内的按键 + 鼠标操作，
按 60fps 逐帧时序排好时间轴，直接演奏、导出宏、或导出人类可读的时间线。

> ⚠️ **仅供个人本地学习与娱乐**。请先阅读文末「免责声明」。
> 本项目的演奏走**本机键鼠输入**，不做任何内存读写、DLL 注入或反作弊对抗。

---

## 快速开始

```bash
pip install numpy                      # 仅自动基准八度/文件解析需要；播放本身是纯标准库

python play.py --list-songs                                   # 看看有哪些现成曲子（15 首）
python play.py --song songs/天空之城.jianpu --dry-run          # 只排时间轴，不按键
python play.py --song songs/天空之城.jianpu --countdown 8 --debug-timing   # 正式演奏 + 逐音延迟报表
python selftest3.py                                            # 端到端自检（不发按键）
```

`--countdown 8` 给你 8 秒切到游戏窗口并把口琴唤出；演奏中随时按 **F10** 中止。

---

## 1. 游戏键位（定死，来自 midikey 的「8 键半音」方案）

```
Z X C V B N M ,        ↔  1 2 3 4 5 6 7 高音1    （相对 C4 的半音偏移 0 2 4 5 7 9 11 12）
鼠标中键 = 升半音(+1)    鼠标右键 = 升八度(+12)    鼠标左键 = 降八度(-12)
可弹音域 = MIDI 48..85（C3..C#6）
```

`keymap.py` 提供两个方向：`map_pitch()` 音高→按键、`pitch_of()` 按键→音高。
**音高映射是绝对的**：基准八度只决定用哪几个键、要不要按变调键，绝不悄悄整体移调；
`auto_base_octave()` 的判据依次是「越界最少 → 变调键最少 → 贴近原生 C4」。

## 2. 支持的输入格式

```bash
python play.py --song songs/天空之城.jianpu        # jiko 简谱 DSL（站点曲库可直接粘贴）
python play.py --song "songs/小星星.txt"           # BPM=/TITLE= 文本谱（viz2）
python play.py --song "songs/春日影…三角洲.txt"      # DFH 三行小节谱（简谱/键位/节奏）
python play.py --song "某首歌.mid"                 # 标准 MIDI 文件
python play.py --score score2.json                # 本项目自己解析出来的事件表
```

MIDI 会自动跳过打击乐轨、挑旋律轨（默认音高最高；`--track 2`、`--track-name 主旋律`、`--merge` 全并）。

## 3. 常用命令

```bash
python play.py --song songs/鸟之诗.jianpu --export ahk      # 导出 AutoHotkey v2 宏
python play.py --song songs/鸟之诗.jianpu --export lua      # 导出罗技 G HUB Lua 宏
python play.py --score score2.json --export jianpu          # 事件表 → 人人可读的简谱
python hud.py --score score2.json                           # 屏幕左上角置顶提示条（配任意播放方式）
python check_invariants.py score2.json standard             # 独立校验器：时间轴不变量
python play.py --timing safe                                # 30fps / 卡顿机器用安全档
python play.py --calib                                      # 校准中键/右键的升半音/升八度语义
```

导出宏后**不用一直开着 Python**：`.ahk` 双击运行（脚本自带数据 + `QueryPerformanceCounter` 忙等定时）、
`.lua` 全量粘进 G HUB、`csv`/`timeline` 是逐动作时刻表与人类可读时间线。

## 4. 时序口径（这是本项目最较真的部分）

游戏是 **60fps 逐帧采样**输入（≈16.7ms/帧），所以三个值都有硬约束：

| 档位 | 修饰键提前 | 音间「松→按」 | 最短按住 | 适用 |
|---|---|---|---|---|
| `standard`（默认） | 40ms | 40ms | 45ms | 60fps 正常帧率 |
| `safe` | 70ms | 70ms | 90ms | 30fps / 卡顿 / 省电 |
| `aggressive` | 25ms | 25ms | 30ms | 高帧率且想更贴原曲 |

`--debug-timing` 结束时打印汇总（调度迟到、「修饰键提前量 < 一帧」的个数、同键重触发、按住不足一帧、时值被压到下限）
并导出 `timing_log.csv`。**实测（《天空之城》，87 BPM，109 音，真实游戏内一轮）**：

```
调度迟到   平均 0.0ms / 最大 0.1ms     超过一帧的 0 个
修饰键提前 <16.7ms 的 0 个，最小 39.0ms（目标 ≥40ms）
同键重触发 <45ms 的 0 个；按住 <16.7ms 的 0 个；时值被压到下限的 0 个
```

## 5. 最近修复：整曲被凭空多塞 5.16 秒静音

同一轮实机日志暴露出一个**真 bug**（时序层没问题，是时间轴本身错）：

* **现象**：演奏比谱面长 5.16 秒，中途 9 处莫名停顿（最早用户口径叫「缓一会」）。
* **根因**：小节分组用的是「从 0 开始的固定 4 拍网格」。当某个网格格子里含**跨小节线**的音时，
  该格实际用到 5.0 拍，代码就按 5.0 拍往后推进 → 每处凭空多 0.5～1 拍静音；共 9 处 = **7.50 拍 = 5.16s**。
  另外本曲是**弱起**（第 1 小节只有 1 拍），网格没算这个偏移，导致小节编号整体错位一格。
* **修法**：音符带 `measure` 字段，按**谱面自己的小节线**分组；事件表每小节带 `start_beat`（小节线真实位置），
  `play.py` 据此重建绝对时刻；小节长度取真实值（弱起 1 拍 / 末节 3 拍）不再补成 4 拍。
  顺带修正 DFH 谱读取文件内**真实拍号**（如 `念张师` 是 3/4）。
* **验证**：全曲库 14 首「事件表重建时刻 vs 源谱自身时刻」最大偏差 **0.00ms**；
  用旧算法复现旧日志逐点吻合（0.0ms），修复后 9 处静音全部消失；末音结束 93.44s → **88.28s**；
  `selftest3.py` 18 个谱面全通过；`score2.json` 不变量未受影响（540 音 / 1189 动作 / 230.52s）。

历史上另外三个「缓一会 / 个别音不准」的根因（已修）：
①每个音只弹 70ms 的「点」→ 改成按到时值末尾减 40ms 的**连奏按住**；
②解析器漏实现**增时线 `-`**（172 处）导致小节凑不满 4 拍→静音补齐；
③修饰键只提前 6ms（小于一帧）→ 按 midikey 的权威值改为 **40ms**。

## 6. 已知限制（如实说明）

* **超出口琴音域的音**（48..85 之外）：按休止处理并**明确报数**，绝不偷偷改速度；整体移调用 `--base-octave` / `--transpose`。
* **口琴一次只能吹一个音**：与上一音重叠的尾巴会被截掉（并报数）。
* **DFH 三行谱的节奏列不含休止**：个别小节时值不足时，导出简谱会有 0.25 拍级记谱偏移（音高 100% 一致）。
* **图片谱面的固有不确定性**（曲目 *I Really Want to Stay at Your House*）：37/120 小节的像素拍数 ≠ 4，
  其中 35 处按「缺口延长到本小节最后一个音」处理；红字母↔数字交叉校验约 98%；2 处高音点↔括号矛盾仍存疑。
  原始扫描图与像素重建中间产物**未随仓库分发**，该路径无法从本仓库完整复现。
* **本机没装 AutoHotkey / Lua**：`.ahk` / `.lua` 只做到数据核对与结构检查，**未实跑**；Python 播放器路径已实机验证。
* **游戏运行时 ACE 会屏蔽全局低层钩子**（`err=126`）：注入类自检用 `selftest2.py`（游戏未开时跑），
  时序核对用 `timing_check2.py`（空注入）。本项目的正式演奏不依赖钩子。

## 7. 文件一览

| 文件 | 作用 |
|---|---|
| `play.py` | 主程序：载入任意格式谱面 → 排时间轴 → 注入按键 / 导出宏 / 打印延迟 |
| `keymap.py` | 键位与音高双向映射、自动基准八度、简谱音名 |
| `score.py` | 统一谱面模型 + 4 个解析器（简谱 / viz2 / DFH / MIDI）+ 简谱导出 + 事件表换算 |
| `midi_in.py` | 纯 Python 的 SMF 读取（音轨挑选、和弦取最高音、打击乐剔除） |
| `macros.py` | 导出 AutoHotkey / G HUB Lua / CSV / 时间线 |
| `hud.py` | 置顶提示条（独立运行，配 Python 播放器或导出的宏都行） |
| `reparse.py` | 从 3 页图片像素重建事件表（曲目 *I Really Want to Stay at Your House* 专用） |
| `check_invariants.py` / `timing_check2.py` / `selftest3.py` | 校验器 / 时序探针 / 端到端自检 |
| `songs/` | 15 首现成谱面（jiko 曲库 6 首 + viz2 / DFH 9 首） |
| `导出示例/` | 四种导出产物示例（csv / timeline / ahk / lua / 事件表 / 简谱） |
| `score2.json` | 图片谱重建出的事件表（540 音 / 1189 动作 / 230.52s） |

## 8. 来源出处参考

本项目**照搬了以下开源实现 / 公开规范，并在其基础上移植优化**。它们各自的版权与许可归原作者所有。

| 来源 | 地址 | 借鉴内容 | 许可状态 |
|---|---|---|---|
| **ChickenD233 / midikey-player**（`harmonica-auto-player` 被投诉下架后的迁移版） | https://github.com/ChickenD233/midikey-player | `KeymapProfile.BuildChromatic8` 的本局键位表；`NoteMapper` 的「音高→键+变调键」查找；`MidiLoader` 的 MIDI 读法；**`Engine/InputTiming.cs` 的逐帧采样时序（修饰键提前 40ms / 音间松-按 ≥40ms / 最短按住 45ms）**；`MacroExporter` 的宏导出与「误差进位」 | MIT（`Copyright (c) 2026 ChickenD233`） |
| **ChiZhou6 / harmonica-visualizer** | https://github.com/ChiZhou6/harmonica-visualizer | `BPM=` / `TITLE=` 文本谱格式；DFH 三行小节谱解析；`b` / `#` / `^` 变调前缀语义 | 上游仓库未见许可证文件 |
| **jiko-official.top · Delta 口琴工具站** | https://jiko-official.top/delta/ | 简谱 DSL 全套语法（`_` 减时线、`.` 附点、`-` 增时线、`:` `/` 精确拍数、`#` / `b`、`'` / `,` 高低八度、`~` 连音、`L`/`M`/`R` 变调前缀、`||:` / `:||`）；气口 / 过渡间隔常量；站点曲库 | 站点公开内容，版权归站点所有 |
| 曲库谱面来源 | jiko 站点曲库；viz2 自带 `songs/`；社区整理的 DFH 谱 | `songs/` 下各 `.jianpu` / `.txt` 谱面数据 | 归各谱面作者所有 |

### 逐文件对应关系（本仓库 → 上游）

| 本仓库文件 | 移植自 |
|---|---|
| `keymap.py` | midikey：`KeymapProfile.BuildChromatic8()` + `NoteMapper.cs` |
| `midi_in.py` | midikey：`MidiLoader.cs` |
| `macros.py` | midikey：`MacroExporter.cs` |
| `hud.py` | midikey：`OverlayWindow` + harmonica-visualizer 的可视化思路 |
| `score.py` 的简谱解析部分 | jiko 站点 DSL 规范；viz2 的文本谱 / DFH 格式 |
| `play.py` 的时序部分 | midikey：`Engine/InputTiming.cs` |

> **关于上游参考快照**：开发期间在本地 `refs/` 下保存了 midikey-player、harmonica-visualizer 与 jiko 站点 `app.js` 的快照用于对照，
> 其中 **harmonica-visualizer 与 jiko 站点资源未附许可证**，故**不随本仓库分发**，请从上方上游地址自行获取。
> 如需自包含验证，可将上游 MIT 项目 `midikey-player` 按其 `LICENSE` 附在 `refs/` 下。

## 9. 免责声明

* 本项目仅用于**个人学习、音乐练习与本地自动化技术研究**，不提供任何游戏对战优势，不修改游戏文件、不读写游戏内存。
* 在游戏中使用自动化输入**可能违反游戏用户协议**（如《三角洲行动》相关条款）；ACE 反作弊环境下的风险（封号等）由使用者自行承担。
* 请勿将本项目用于商业用途、账号代练或任何破坏公平竞技的场景。
* 上游代码与曲库的版权归各自作者所有；本项目仅为技术移植与学习，若权利人认为不妥请联系删除。

## 10. 许可

本仓库**自身**的代码以 **MIT** 许可发布，见 [`LICENSE`](LICENSE)。
从上游移植的部分**保留其原始许可与版权声明**（尤其 midikey-player 为 MIT，版权 `(c) 2026 ChickenD233`）。
