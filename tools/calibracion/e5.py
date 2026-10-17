from lab import render, bbox
def t(name, body, **kw):
    img = render("^XA" + body + "^XZ", **kw); print(f"{name:44} {bbox(img)}")
t("FH_ FB \& 3 lines", "^FO100,100^A0N,40,40^FB400,3,0,L,0^FH_^FDH\&H\&H^FS")
t("FH_ escape _5E", "^FO100,100^A0N,40,40^FH_^FDA_5EB^FS")
t("noFH FB \& 3 lines", "^FO100,100^A0N,40,40^FB400,3,0,L,0^FDH\&H\&H^FS")
t("FH_ FB long wrap auto 2 lines", "^FO100,100^A0N,40,40^FB200,2,0,L,0^FH_^FDHHHHHH HHHHHH^FS")
t("CI28 FH_ accents", "^CI28^FO100,100^A0N,40,40^FH_^FDÁÑ^FS")
t("CI0 accents utf8", "^CI0^FO100,100^A0N,40,40^FH_^FDÁÑ^FS")
t("CI0 accents _C1_D1", "^CI0^FO100,100^A0N,40,40^FH_^FD_C1_D1^FS")
