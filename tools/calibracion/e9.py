from lab import render
chars = "ÁÉÍÓÚÑáéíóúñ"
z = "^XA^CI27^FO20,20^A0N,50,50^FH_^FD" + "".join(f"_{b:02X}" for b in chars.encode("cp1252")) + "^FS"
z += "^FO20,90^A0N,50,50^FH_^FD" + "".join(f"_{b:02X}" for b in chars.encode("cp850")) + "^FS"
z += "^CI28^FO20,160^A0N,50,50^FH_^FD" + "".join(f"_{b:02X}" for b in chars.encode("utf-8")) + "^FS^XZ"
render(z, 5, 1.2).save("ci27.png")
