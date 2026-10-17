import json
from lab import render, bbox
def az(data, mag=1, cmd="FO", y=100):
    b = bbox(render(f"^XA^{cmd}100,{y}^BON,{mag},N,0,N,0,^FD{data}^FS^XZ", 4, 4, 8))
    return b
print("FO mag2", az("ABC123", 2), "FT mag2", az("ABC123", 2, "FT", 300), "FO mag4", az("ABC123", 4))
table = {}
gens = {"dig": lambda n: ("0123456789" * 20)[:n],
        "up": lambda n: ("AB-12-CD-34-" * 20)[:n],
        "low": lambda n: ("ab-Cd:12/xY." * 20)[:n]}
for n in list(range(1, 41)) + list(range(45, 121, 5)):
    sizes = {}
    for k, g in gens.items():
        b = az(g(n))
        sizes[k] = (b[2] - b[0]) if b else None
    table[n] = max(v for v in sizes.values() if v)
    if n % 10 == 0 or n < 4: print(n, sizes)
json.dump(table, open("aztec.json", "w"))
print(table)
