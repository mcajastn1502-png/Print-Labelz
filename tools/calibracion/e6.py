from lab import render, bbox
img = render("^XA^CI0^FO20,20^A0N,60,60^FH_^FD" + "".join(f"_{b:02X}" for b in "ÁÉÍÓÚÑáéíóúñü°".encode("cp850")) + "^FS^FO20,120^A0N,60,60^CI28^FDÁÉÍÓÚÑáéíóúñü°^FS^XZ", w_in=6, h_in=1.5)
img.save("accents.png"); print(bbox(img))
