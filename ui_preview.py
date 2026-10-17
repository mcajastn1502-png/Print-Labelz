"""Vista previa: imagen de Labelary (en segundo plano), sliders de alineación e interruptor.

Mixin de ZebraPrintApp (app.py): usa sus atributos y métodos vía self."""

import re
from io import BytesIO
import label_layout as LL
from PIL import Image, ImageTk, ImageDraw, ImageFilter


class PreviewMixin:
    def on_preview_resize(self, event):
        if not getattr(self, '_current_preview_img', None):
            return
            
        width = event.width
        height = event.height
        
        if width < 50 or height < 50: return # Ignorar encogimientos irreales
        
        if self._resize_timer is not None:
            self.after_cancel(self._resize_timer)
        # Redimensiona la imagen después de soltar o detener el arrastre de la ventana
        self._resize_timer = self.after(150, lambda: self._apply_resize(width, height))

    def _apply_resize(self, width, height):
        if not getattr(self, '_current_preview_img', None): return
        img = self._current_preview_img.copy()

        try:
            resample_filter = Image.Resampling.LANCZOS # Alta calidad en Pillow modernas
        except AttributeError:
            resample_filter = Image.ANTIALIAS

        margin = 4  # espacio reservado para la sombra alrededor de la etiqueta
        img.thumbnail((max(1, width - margin), max(1, height - margin)), resample_filter)

        composed = self._compose_label_with_shadow(img, width, height)
        img_tk = ImageTk.PhotoImage(composed)
        self.preview_canvas.config(image=img_tk, text="")
        self.preview_canvas.image = img_tk

    def _compose_label_with_shadow(self, label_img, canvas_w, canvas_h):
        """Simula una etiqueta física: sombra suave detrás, sin redondear ni alterar su contenido real."""
        label_img = label_img.convert("RGBA")
        lw, lh = label_img.size
        canvas_w, canvas_h = max(canvas_w, lw + 20), max(canvas_h, lh + 20)

        base = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        ox, oy = (canvas_w - lw) // 2, (canvas_h - lh) // 2

        shadow = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rectangle([ox + 2, oy + 4, ox + lw + 2, oy + lh + 4], fill=(0, 0, 0, 110))
        shadow = shadow.filter(ImageFilter.GaussianBlur(8))
        base.alpha_composite(shadow)

        base.alpha_composite(label_img, (ox, oy))
        return base

    def on_slider_change(self, *args):
        # Bloqueo de seguridad para evitar errores al crear los widgets al abrir la app
        if not hasattr(self, 'slider_x') or not hasattr(self, 'slider_y') or not hasattr(self, 'lbl_val_y'):
            return
            
        # Actualizar labels visuales
        val_x = int(self.slider_x.get())
        val_y = int(self.slider_y.get())
        self.lbl_val_x.config(text=f"{val_x} mm")
        self.lbl_val_y.config(text=f"{val_y} mm")
        
        if self._preview_timer is not None:
            self.after_cancel(self._preview_timer)
        # Debounce de 400ms para no saturar Labelary mientras el usuario arrastra la perilla
        self._preview_timer = self.after(400, lambda: self.generate_preview(row_index=self._get_selected_row_index()))

    def reset_sliders(self):
        self.slider_x.set(0)
        self.slider_y.set(0)
        self.on_slider_change()

    def _render_preview_switch(self, knob_x=None):
        if not hasattr(self, 'preview_switch_canvas'):
            return

        is_on = self.preview_api_enabled.get()
        canvas = self.preview_switch_canvas
        canvas.delete("all")

        track_color = self.switch_on if is_on else self.switch_off
        if knob_x is None:
            knob_x = 28 if is_on else 4

        knob_x = int(round(max(4, min(28, knob_x))))
        self._switch_knob_x = knob_x

        # Pista tipo pastilla (simulada con ovalos + rectangulo)
        canvas.create_oval(2, 2, 26, 26, fill=track_color, outline=track_color)
        canvas.create_rectangle(14, 2, 38, 26, fill=track_color, outline=track_color)
        canvas.create_oval(26, 2, 50, 26, fill=track_color, outline=track_color)

        # Perilla
        canvas.create_oval(knob_x, 4, knob_x + 20, 24, fill=self.switch_knob, outline=self.switch_knob_outline)

        if hasattr(self, 'preview_switch_state'):
            self.preview_switch_state.config(
                text="ON" if is_on else "OFF",
                fg=self.switch_text_on if is_on else self.switch_text_off
            )

    def _animate_preview_switch(self, target_on):
        if not hasattr(self, 'preview_switch_canvas'):
            return

        if self._switch_anim_timer is not None:
            self.after_cancel(self._switch_anim_timer)
            self._switch_anim_timer = None

        start_x = getattr(self, '_switch_knob_x', 4)
        end_x = 28 if target_on else 4
        steps = 8
        delta = (end_x - start_x) / steps if steps else 0

        def step(frame=0, current_x=start_x):
            self._render_preview_switch(knob_x=current_x)
            if frame < steps:
                self._switch_anim_timer = self.after(16, lambda: step(frame + 1, current_x + delta))
            else:
                self._switch_anim_timer = None
                self._render_preview_switch(knob_x=end_x)

        step()

    def toggle_preview_api(self, event=None):
        self.preview_api_enabled.set(not self.preview_api_enabled.get())
        self.app_config["preview_web"] = self.preview_api_enabled.get()
        self._save_app_config()
        self.on_preview_toggle(animated=True)

    def on_preview_toggle(self, animated=False):
        if animated:
            self._animate_preview_switch(self.preview_api_enabled.get())
        else:
            self._render_preview_switch()

        if self.preview_api_enabled.get():
            self.generate_preview(row_index=self._get_selected_row_index())
        else:
            self._preview_seq += 1  # descarta la petición en curso, si la hay
            self._set_preview_loading(False)
            self._current_preview_img = None
            self.preview_canvas.config(image='', text="Preview web desactivada. Activa el switch para usar Labelary.", fg=self.preview_text)

    def _shift_zpl(self, zpl, mm_x, mm_y):
        if mm_x == 0 and mm_y == 0:
            return zpl
            
        dpmm = LL.dots_per_mm(self._current_dpi())  # 8 pt/mm a 203 dpi, 12 a 300 dpi
        dots_x = int(round(mm_x * dpmm))
        dots_y = int(round(mm_y * dpmm))
        
        def mover_punto(match):
            cmd = match.group(1) # Extrae ^FO o ^FT
            try:
                x = max(0, int(match.group(2)) + dots_x)
                y = max(0, int(match.group(3)) + dots_y)
                return f"{cmd}{x:03d},{y:03d}"
            except:
                return match.group(0) # Si algo excepcionalmente falla, dejar original
                
        # Regex captura todos los comandos de coordenadas en ZPL Ej: ^FO100,200 o ^FT30,40
        return re.sub(r'(\^F[OT])(\d+),(\d+)', mover_punto, zpl, flags=re.IGNORECASE)


    def generate_preview(self, row_index=0):
        if not self.plantilla_zpl:
            return

        if self.df is None or self.df.empty:
            # Estado base: Solo PRN cargado -> Mostrar las literales [variables] para confirmar posiciones
            result = self.compose_label(None)
        elif row_index < len(self.df):
            result = self.compose_label(self.df.iloc[row_index])
        else:
            return

        self.last_layout = result
        self._update_layout_status(result)

        if not self.preview_api_enabled.get():
            self._preview_seq += 1
            self._current_preview_img = None
            self.preview_canvas.config(image='', text="Preview web desactivada. Activa el switch para usar Labelary.", fg=self.preview_text)
            return

        self._request_labelary(result.zpl, result.width_mm, result.height_mm, result.dpi)

    def _request_labelary(self, zpl, width_mm=None, height_mm=None, dpi=None):
        """Pide la imagen a Labelary en segundo plano; solo se muestra la respuesta
        de la petición más reciente."""
        self._preview_seq += 1
        seq = self._preview_seq
        try:
            url, payload = self._labelary_request_args(zpl, width_mm, height_mm, dpi)
        except Exception as e:
            self._show_preview_error(f"Error preparando la previsualización:\n{str(e)[:50]}...")
            return
        if self._current_preview_img is None:
            self.preview_canvas.config(image='', text="Generando previsualización...", fg=self.preview_info)
        self._set_preview_loading(True)

        def work():
            import requests
            res = requests.post(url, data=payload, headers={"Accept": "image/png"}, timeout=10)
            if res.status_code != 200:
                return res.status_code
            img = Image.open(BytesIO(res.content))
            img.load()  # decodificar aquí, fuera del hilo de la interfaz
            return img

        def done(result, error):
            if seq != self._preview_seq or not self.preview_api_enabled.get():
                return  # llegó tarde: hay una petición más nueva o se apagó la vista previa
            self._set_preview_loading(False)
            if error is not None:
                self._show_preview_error(f"Error en la conexión a la web:\n{str(error)[:50]}...")
            elif isinstance(result, int):
                self._show_preview_error(f"El servidor rechazó el código ZPL. (Error {result})")
            else:
                self._current_preview_img = result
                # Proyectar sobre el espacio disponible del contenedor
                canvas_w = self.preview_canvas.winfo_width()
                canvas_h = self.preview_canvas.winfo_height()
                if canvas_w < 50: canvas_w = 700
                if canvas_h < 50: canvas_h = 400
                self._apply_resize(canvas_w, canvas_h)

        self._run_async(work, done)

    def _set_preview_loading(self, loading):
        """Cursor de espera sobre la vista previa mientras llega la imagen."""
        self.preview_canvas.config(cursor="watch" if loading else "")

    def _show_preview_error(self, text):
        self._current_preview_img = None
        self.preview_canvas.config(image='', text=text, fg=self.preview_error)

    def _labelary_request_args(self, zpl, width_mm=None, height_mm=None, dpi=None):
        """(url, cuerpo) de la petición a Labelary para la etiqueta dada."""
        # Aislar únicamente la etiqueta válida del final
        bloques = re.findall(r"\^XA.*?\^XZ", zpl, re.IGNORECASE | re.DOTALL)
        zpl_preview = bloques[-1] if bloques else zpl

        # PARCHE FUENTES: Compatibilidad obligatoria en labelary para E:ARIAL.FNT (^A@)
        zpl_preview = re.sub(r'\^A@([NRIBnrib]?)[,]*(\d*)[,]*(\d*)[^\^]*', r'^A0\1,\2,\3', zpl_preview)

        # Dimensiones físicas exactas de la etiqueta y resolución real de la impresora
        dpi = dpi or self._current_dpi()
        dpmm = int(round(LL.dots_per_mm(dpi)))
        if width_mm and height_mm:
            w_inches = round(width_mm / 25.4, 3)
            h_inches = round(height_mm / 25.4, 3)
        else:
            w_inches, h_inches = 4.0, 4.0
            pw_match = re.search(r"\^PW(\d+)", zpl, re.IGNORECASE)
            ll_match = re.search(r"\^LL(\d+)", zpl, re.IGNORECASE)
            if pw_match and ll_match:
                w_inches = max(1.0, round(int(pw_match.group(1)) / (dpmm * 25.4), 3))
                h_inches = max(1.0, round(int(ll_match.group(1)) / (dpmm * 25.4), 3))

        url = f"https://api.labelary.com/v1/printers/{dpmm}dpmm/labels/{w_inches}x{h_inches}/0/"
        return url, zpl_preview.encode("utf-8")
