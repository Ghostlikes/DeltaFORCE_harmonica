import extract as ex, sys
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
