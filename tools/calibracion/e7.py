from lab import render, bbox
def w(text):
    b = bbox(render(f"^XA^FO20,20^A0N,100,100^FD{text}^FS^XZ", w_in=8, h_in=2)); return b[2]-b[0]
base = w("HH")
for c in "-+=<>%@.:/ ":
    print(repr(c), (w("H"+c*5+"H") - base)/5/100)
print("10-01-01-001 measured", w("10-01-01-001"))
