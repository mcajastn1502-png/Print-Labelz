from lab import render, bbox
def q(data, mag=2, dpmm=8, cmd="FO", y=100):
    img = render(f"^XA^{cmd}100,{y}^BQN,2,{mag}^FD{data}^FS^XZ", w_in=4, h_in=4, dpmm=dpmm)
    b = bbox(img); return b, (b[2]-b[0])//mag
for d in ["LA,10-01-01-001", "LA,ABCDEFGHIJKLMNOPQRST", "LA,abcdefghijklmnopqrstuvwxyz0123", "LA,https://example.com/abc/def/ghi/jkl/mno", "QA,10-01-01-001", "QA,abcdefghijklmnopqrstuvwxyz0123", "MA,abcdefghijklmnopqrstuvwxyz0123", "LA,0123456789012345678901234567890123", "LA,ÑAÑO-áé"]:
    print(f"{d[:40]:42}", q(d))
print("12dpmm FO", q("LA,ABC", 4, 12), "FT", q("LA,ABC", 4, 12, "FT", 300))
print("8dpmm FT mag2 v2", q("LA,ABCDEFGHIJKLMNOPQRST", 2, 8, "FT", 300))
print("8dpmm FO mag1", q("LA,ABC", 1, 8), "mag10", q("LA,ABC", 10, 8))
