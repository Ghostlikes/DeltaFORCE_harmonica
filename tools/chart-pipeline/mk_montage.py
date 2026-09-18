import extract as ex, sys

# --- 让本脚本无论放在哪一层子目录，都能 import 到项目根下的模块（play.py / score.py / keymap.py …）---
import os as _os, sys as _sys
_d = _os.path.dirname(_os.path.abspath(__file__))
while _d and not _os.path.isfile(_os.path.join(_d, "play.py")):
    _p = _os.path.dirname(_d)
    if _p == _d:
        break
    _d = _p
if _d and _d not in _sys.path:
    _sys.path.insert(0, _d)
pi = int(sys.argv[1]) if len(sys.argv) > 1 else 0
systems, _ = ex.run(pi)
import montage as mg
for si, s in enumerate(systems):
    if len(sys.argv) > 2 and si != int(sys.argv[2]): continue
    digs = [c for c in s["notes"] if ex.classify(c) in ("digit", "other")]
    keys = s["keys"]
    mg.montage(pi, digs, f"crops/m_notes_{pi}_{si}.png", cols=8, H=150)
    mg.montage(pi, keys, f"crops/m_keys_{pi}_{si}.png", cols=10, H=120)
    if len(sys.argv) <= 2 or si >= 0: pass
