"""Final pass: classify every glyph in the song using the complete cluster inventory
(digit clusters 0-7 verified against key-letter row + VLM montage reads)."""
import pickle, json, numpy as np
from collections import Counter, defaultdict
from PIL import Image
import extract as ex
import song

DIGMAP = {0:'4', 5:'5', 2:'1', 6:'0', 1:'3', 3:'6', 7:'0', 4:'6', 12:'6', 13:'1',
          14:'6', 8:'2', 17:'3', 10:'7', 11:'3', 16:'2', 9:'1', 15:'2', 18:'5'}
# letter clusters: ids that carry verified seed labels (V/C/Z/N/B/parens)
LSEED = {(0,0,209):'V',(0,0,342):'C',(0,0,475):'Z',(0,0,538):'Z',(0,0,601):'V',(0,0,703):'V',
         (0,0,769):'Z',(0,0,825):'Z',(0,0,886):'N',(0,0,948):'N',(0,0,1009):'B',(0,0,1076):'N',
         (0,0,1138):'B',(0,0,1240):'N',(0,0,1316):'B',(0,0,466):'(',(0,0,490):')',(0,0,529):'(',
         (0,0,553):')',(0,0,592):'(',(0,0,619):')',(0,0,694):'(',(0,0,720):')',(0,0,760):'(',
         (0,0,783):')',(0,0,816):'(',(0,0,839):')'}

def build_from_clusters(path='clusters2.pkl'):
    d = pickle.load(open(path, 'rb'))
    dc, lc = d['dc'], d['lc']
    d_meta, d_id, l_meta, l_id = d['d_meta'], d['d_id'], d['l_meta'], d['l_id']
    # digit templates: one per cluster (labelled by DIGMAP)
    dt = []
    for k in range(len(dc)):
        acc, cnt = dc[k]
        dt.append(((acc / cnt > 0.5).astype(np.uint8), DIGMAP.get(k, '?')))
    # letter templates
    lab = {}
    for i, m in enumerate(l_meta):
        s = LSEED.get((m[0], m[1], m[2]))
        if s: lab.setdefault(l_id[i], Counter())[s] += 1
    lt = []
    for k in range(len(lc)):
        acc, cnt = lc[k]
        if k in lab: l = lab[k].most_common(1)[0][0]
        elif cnt <= 3: continue
        else: l = '?'
        lt.append(((acc / cnt > 0.5).astype(np.uint8), l))
    for k in sorted(lab): print(f"   letter cluster @{k} n={int(lc[k][1])} -> {lab[k].most_common(1)[0][0]}")
    print(f"digit templates {len(dt)}, letter templates {len(lt)}")
    return song.NN(dt), song.NN(lt)

def main():
    dnn, lnn = build_from_clusters()
    data = []
    for pi in range(3):
        _, dark, red = ex.masks("hd/" + ex.PAGES[pi])
        for si, s in enumerate(ex.run(pi)[0]):
            r = song.analyse_system(dark, red, s, dnn, lnn, pi, si)
            if r: data.append(r)
    json.dump(data, open('song_sys.json', 'w'), ensure_ascii=False)
    LETTER = {'1':'Z','2':'X','3':'C','4':'V','5':'B','6':'N','7':'M','i':','}
    D2L = {v:k for k,v in LETTER.items()}
    agree=0; tot=0; bad=[]
    for sd in data:
        for n in sd['notes']:
            ks=[g for g in sd['keys'] if g['kind']=='key' and abs((g['x0']+g['x1'])/2-n['x'])<20]
            if not ks: continue
            g=min(ks,key=lambda g:abs((g['x0']+g['x1'])/2-n['x'])); tot+=1
            want = D2L.get(n['digit'])
            if g['label']==want or (want is None): agree+=1
            else: bad.append((sd['page'],sd['sys'],round(n['x']),n['digit'],g['label'],n['dist']))
    print(f"digit<->letter agreement {agree}/{tot}  (rests excluded from error list)")
    nb=[b for b in bad if b[3]!='0']
    print(f"non-rest disagreements: {len(nb)}"); 
    for b in nb[:15]: print("   ",b)
    h=Counter()
    for sd in data:
        for m in song.measures(sd): h[round(sum(song.dur_of(sd['notes'][i]) for i in m),2)]+=1
    print("measure-beat histogram:", h.most_common(10))
    print(f"measures={sum(h.values())} exact4={h[4.0]}")
    print("digit clusters used:", Counter(n['digit'] for sd in data for n in sd['notes']).most_common())
    print("octaves:", Counter(n['oct'] for sd in data for n in sd['notes']).most_common())

if __name__ == '__main__':
    main()
