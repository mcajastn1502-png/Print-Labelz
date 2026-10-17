from lab import render, bbox
from PIL import ImageOps
def interp(data, by):
    img = render(f"^XA^BY{by},3,40^FO50,50^BCN,40,Y,N,N^FD{data}^FS^XZ", w_in=6, h_in=1)
    crop = img.crop((0, 50 + 40 + 1, img.width, img.height))
    b = bbox(crop)
    full = bbox(img)
    return (b[2]-b[0], b[3]-b[1]) if b else None, full[2]-full[0]
for by in (1, 2, 3):
    for d in ["10-01-01-001", "ABC", "UB-GYE-RACK-A-03-02", "1234567890"]:
        print(by, d, interp(d, by))
