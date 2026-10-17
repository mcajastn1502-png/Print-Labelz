import segno
from segno import DataOverflowError
samples = {'numeric': '1', 'alphanumeric': 'A', 'byte': 'a'}
out = {}
for e in 'LMQH':
    out[e] = {}
    for mode, ch in samples.items():
        caps = []
        n = 1
        for v in range(1, 26):
            while True:
                try:
                    segno.make(ch * (n + 1), version=v, error=e, mode=mode, boost_error=False, micro=False)
                    n += 1
                except DataOverflowError:
                    break
            caps.append(n)
        out[e][mode[:1].upper()] = caps
print(out)
