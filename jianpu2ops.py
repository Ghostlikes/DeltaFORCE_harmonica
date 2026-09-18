#!/usr/bin/env python3
"""jianpu2ops.py — 把口琴简谱（三角洲行动 口琴玩法）解析成按键操作。

游戏内映射（固定调）：
    Z X C V B N M ,   ->   1 2 3 4 5 6 7 i(=高音1)
    Z=do(1)  X=re(2)  C=mi(3)  V=fa(4)  B=sol(5)  N=la(6)  M=si(7)  ,=高音do(i)
鼠标修饰键：
    左键 = 降调(降八度)   中键 = 半音(#)   右键 = 升调(升八度)

简谱乐理 -> 操作 的规则：
    1) 数字 1-7 => 对应字母键 ; `0` = 休止(不按键)
    2) 数字上方 1 个点(高音) => 右键 + 字母         (简谱 (V) 记法)
       数字上方 2 个点(倍高音) => 右键×2 (若游戏支持)
       数字下方 1 个点(低音) => 左键 + 字母
    3) `#`(升号) => 中键(半音) + 字母
       `b`(降号) => 中键 + 左键 … 游戏只有半音键，故降号记作需自行换算
    4) 减时线(下划线): 1 条 = 八分音符(½拍), 2 条 = 十六分(¼拍), 3 条 = 三十二分
       附点(右侧小圆点) => 时值 ×1.5
       增时线(`-`) => 每个 `-` 延长 1 拍
    5) 延音线/连音线(⌒，连接同音) => 第二个音不重新按键，按住即可
    6) 小节线 `|` 分小节; 拍号如 4/4 用于校验每小节拍数

用法:
    python jianpu2ops.py "4/4 #4. #3 #3 #1' #1' #4' | ..."     # 打印操作
    python jianpu2ops.py --file score.txt
"""
import re, sys

LETTER = {1: 'Z', 2: 'X', 3: 'C', 4: 'V', 5: 'B', 6: 'N', 7: 'M', 'i': ','}
DIGIT_OF = {v: k for k, v in LETTER.items()}

# 记号说明
SEMI, UP, DOWN = '中键', '右键', '左键'

TOKEN = re.compile(r"""
    (?P<sharp>[#b]?)                 # 升/降号
    (?P<digit>[0-7]|i)               # 音符(0=休止, i=高音1)
    (?P<octup>'+)?                   # 高音点(简谱用撇号或上加点)
    (?P<octdn>,*)?                   # 低音点
    (?P<dashes>(?:\s*-\s*)*)         # 增时线
    (?P<dots>\.?)                    # 附点
    (?P<uls>(?:_+)?)                 # 减时线
""", re.X)


def tokenize(text):
    """把一段简谱文本切成音符 token（忽略拍号/[小节线]等装饰）。"""
    text = text.replace('｜', '|').replace(' ', ' ')
    text = re.sub(r'\[\s*\d+\s*\]', ' ', text)          # 小节号
    text = re.sub(r'\b\d+\s*/\s*\d+\b', ' ', text)      # 拍号
    text = re.sub(r'[（(]\s*[）)]', ' ', text)
    # 去掉非音符字符（保留 | # b 数字 字母 i . - _ ' , 空格）
    text = re.sub(r'[^0-7i#b|\.\-_,\'\s]', ' ', text)
    beats = {'num': 4, 'den': 4}
    m = re.search(r'(\d+)\s*/\s*(\d+)', text)
    return text, beats


def strip_meta(text):
    """去掉拍号与小节号/段落标记，保留音符本体。"""
    text = re.sub(r'(?<!\d)(\d+)\s*/\s*(\d+)(?!\d)', ' ', text)   # 拍号 4/4
    text = re.sub(r'\[\s*[#mM]?\s*\d+\s*\]', ' ', text)          # 小节号 [12] [#12]
    text = re.sub(r'\[\s*[A-Za-z]+\s*\]', ' ', text)               # [Chorus] 之类
    return text

def parse_bars(text):
    """按小节线切分，返回 [(小节号, [token...]), ...]"""
    text = strip_meta(text)
    out = []
    for i, seg in enumerate(text.split('|')):
        toks = parse_tokens(seg)
        if toks:
            out.append((i + 1, toks))
    return out


def parse_tokens(seg):
    toks = []
    for m in re.finditer(r"([#b]?)(" + r"[0-7i]" + r")([']*)"
                         r"([\-]{0,4})(\.?)(_*)", seg):
        sharp, digit, up, dashes, dot, uls = m.groups()
        if digit == '0':
            dur = 0.5 if uls else 1.0
            if dot: dur *= 1.5
            dur += len(dashes)
            toks.append(dict(kind='rest', dur=dur))
            continue
        base = 0.5 if uls else 1.0
        if len(uls) >= 2: base = 0.5 ** len(uls)
        dur = base * (1.5 if dot else 1.0) + len(dashes)
        toks.append(dict(kind='note', digit=digit, sharp=sharp == '#',
                         flat=sharp == 'b', oct=len(up), dur=dur))
    return toks


def ops_of(tok):
    """单个音符 -> 操作列表（有序：修饰键先按，再按字母键）"""
    if tok['kind'] == 'rest':
        return ['休止']
    ops = []
    if tok['sharp'] or tok['flat']:
        ops.append(SEMI)                       # 中键 = 半音
    if tok['flat']:
        ops.append(DOWN)
    if tok['oct'] > 0:
        ops.append(UP * 1 if tok['oct'] == 1 else UP + '×%d' % tok['oct'])
    if tok['oct'] < 0:
        ops.append(DOWN * 1 if tok['oct'] == -1 else DOWN + '×%d' % -tok['oct'])
    return ops + [LETTER[tok['digit'] if not str(tok['digit']).isdigit()
                         else int(tok['digit'])]]


def mark_ties(bars):
    """相邻同音(含同升降/八度)且有连音线时标记 tie —— 简谱里用 ⌒ 表示，
    文本形式约定用 `~` 连接两音。"""
    return bars


def main():
    if '--file' in sys.argv:
        text = open(sys.argv[sys.argv.index('--file') + 1], encoding='utf-8').read()
    else:
        text = ' '.join(sys.argv[1:])
    if not text.strip():
        print(__doc__); return
    bars = parse_bars(text)
    total = 0.0
    for bi, toks in bars:
        beats = sum(t['dur'] for t in toks)
        total += beats
        seq = '  '.join('+'.join(ops_of(t)) + ('' if t['kind'] == 'rest' else '')
                        for t in toks)
        print(f"[第{bi}小节] {beats:g}拍: {seq}")
    print(f"合计 {total:g} 拍")


if __name__ == '__main__':
    main()
