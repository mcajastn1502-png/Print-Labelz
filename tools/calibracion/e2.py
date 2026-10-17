import json
from lab import render, bbox
def w(text, h=100, wd=100, ci="^CI28"):
    img = render(f"^XA{ci}^FO20,20^A0N,{h},{wd}^FH\^FD{text}^FS^XZ", w_in=8, h_in=2)
    b = bbox(img); return (b[2]-b[0]) if b else 0
chars = [chr(c) for c in range(33,127) if chr(c) not in '^~\_'] + list("ÁÉÍÓÚÑÜáéíóúñü°¿¡")
adv = {}
for c in chars:
    one = w(c); many = w(c*11)
    adv[c] = (many - one)/10/100  # advance in em (h=100,w=100)
# space
adv[' '] = (w("H"+" "*10+"H") - w("HH"))/10/100
for c in '^~\_': adv[c] = adv.get('M', 0.6)
json.dump(adv, open('adv.json','w', encoding='utf-8'), ensure_ascii=False, indent=0)
print({k: round(v,3) for k,v in list(adv.items())[:12]}, 'space', round(adv[' '],3), 'W', adv['W'], 'i', adv['i'])
# width scaling
print('w scaling', w("HHHHHHHHHH",100,100), w("HHHHHHHHHH",100,50), w("HHHHHHHHHH",50,100), w("HHHHHHHHHH",100,200))
