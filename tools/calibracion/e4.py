from lab import render, bbox
def t(name, body, **kw):
    img = render("^XA" + body + "^XZ", **kw); print(f"{name:44} {bbox(img)}")
for d in ["HELLO", "10-01-01-001", "AB12345678", "1234567890", "00:1A:2B:3C:4D:5E", "abc def"]:
    t(f"BY2 FO {d}", f"^BY2,3,34^FO100,100^BCN,,N,N^FD{d}^FS")
t("BY2 FT Y 10-01", "^BY2,3,34^FT100,300^BCN,,Y,N^FD10-01-01-001^FS")
t("BY1 FT Y 10-01", "^BY1,3,34^FT100,300^BCN,,Y,N^FD10-01-01-001^FS")
t("BY4 FT Y 10-01", "^BY4,3,34^FT100,300^BCN,,Y,N^FD10-01-01-001^FS")
t("BY2 FO Y 10-01", "^BY2,3,34^FO100,100^BCN,,Y,N^FD10-01-01-001^FS")
t("BY2 FO Y 10-01 12dpmm", "^BY2,3,34^FO100,100^BCN,,Y,N^FD10-01-01-001^FS", dpmm=12)
# FH + FB line breaks
t("FH FB \& 3 lines", "^FO100,100^A0N,40,40^FB400,3,0,L,0^FH\^FDH\&H\&H^FS")
t("FH escape 5E", "^FO100,100^A0N,40,40^FH\^FDA\5EB^FS")
# GF FT anchor
t("GF FO 16x16", "^FO100,100^GFA,32,32,2," + "FFFF"*16 + "^FS")
t("GF FT 16x16", "^FT100,100^GFA,32,32,2," + "FFFF"*16 + "^FS")
