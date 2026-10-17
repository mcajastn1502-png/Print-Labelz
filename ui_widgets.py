"""Componentes visuales: botones en degradado, tarjetas y fondo de la ventana.

Mixin de ZebraPrintApp (app.py): usa sus atributos y métodos vía self."""

import math
import tkinter as tk
from tkinter import font as tkfont
from app_paths import resource_path
from PIL import Image, ImageTk, ImageDraw, ImageFilter, ImageOps


class WidgetsMixin:
    @staticmethod
    def _hex_to_rgb(hex_color):
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))

    def _render_gradient_rounded(self, width, height, color_from, color_to, radius=8, shadow=True):
        """Genera (con PIL) un rectángulo redondeado con relleno en degradado horizontal
        y una sombra suave debajo, para simular botones modernos con elevación."""
        scale = 3  # supersampling para bordes redondeados suaves
        pad = 6 if shadow else 0
        canvas_w, canvas_h = width + pad * 2, height + pad * 2

        big = Image.new("RGBA", (canvas_w * scale, canvas_h * scale), (0, 0, 0, 0))

        if shadow:
            shadow_layer = Image.new("RGBA", (canvas_w * scale, canvas_h * scale), (0, 0, 0, 0))
            sd = ImageDraw.Draw(shadow_layer)
            off = 3 * scale
            sd.rounded_rectangle(
                [pad * scale, pad * scale + off, (pad + width) * scale, (pad + height) * scale + off],
                radius=radius * scale, fill=(0, 0, 0, 100)
            )
            shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(radius=max(2, radius // 2) * scale // 2))
            big.alpha_composite(shadow_layer)

        r1, g1, b1 = self._hex_to_rgb(color_from)
        r2, g2, b2 = self._hex_to_rgb(color_to)
        grad = Image.new("RGB", (width, 1))
        px = grad.load()
        for x in range(width):
            t = x / max(1, width - 1)
            px[x, 0] = (round(r1 + (r2 - r1) * t), round(g1 + (g2 - g1) * t), round(b1 + (b2 - b1) * t))
        grad = grad.resize((width * scale, height * scale)).convert("RGBA")

        mask = Image.new("L", (width * scale, height * scale), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, width * scale - 1, height * scale - 1], radius=radius * scale, fill=255
        )
        grad.putalpha(mask)
        big.alpha_composite(grad, (pad * scale, pad * scale))

        final = big.resize((canvas_w, canvas_h), Image.LANCZOS)
        return final, pad

    def _create_hover_button(self, parent, text, image, color_from, color_to, command, is_bold=True, fg_color=None):
        """Botón moderno: fondo en degradado, esquinas redondeadas y sombra sutil (renderizado con PIL sobre un Canvas)."""
        fg_color = fg_color or self.button_fg
        label_text = text.strip()
        font_spec = ("Segoe UI", 9, "bold" if is_bold else "normal")
        measure_font = tkfont.Font(family="Segoe UI", size=9, weight="bold" if is_bold else "normal")
        text_w = measure_font.measure(label_text)
        text_h = measure_font.metrics("linespace")

        icon_w = (image.width() + 8) if image else 0
        content_w = icon_w + text_w
        btn_w = max(84, content_w + 22)
        btn_h = max(26, text_h + 8)

        normal_img, pad = self._render_gradient_rounded(btn_w, btn_h, color_from, color_to, radius=8, shadow=True)
        hover_img, _ = self._render_gradient_rounded(btn_w, btn_h, color_to, color_from, radius=8, shadow=True)
        normal_photo = ImageTk.PhotoImage(normal_img)
        hover_photo = ImageTk.PhotoImage(hover_img)

        canvas_w, canvas_h = normal_img.width, normal_img.height
        btn = tk.Canvas(parent, width=canvas_w, height=canvas_h, bg=parent.cget("background"), highlightthickness=0, bd=0, cursor="hand2")
        btn._normal_img = normal_photo
        btn._hover_img = hover_photo
        btn._icon_img = image

        btn.create_image(0, 0, image=normal_photo, anchor="nw", tags="bgimg")

        cx, cy = canvas_w / 2, canvas_h / 2
        if image:
            total_w = image.width() + 8 + text_w
            start_x = cx - total_w / 2
            btn.create_image(start_x + image.width() / 2, cy, image=image, anchor="center", tags="hit")
            btn.create_text(start_x + image.width() + 8 + text_w / 2, cy, text=label_text, fill=fg_color, font=font_spec, tags="hit")
        else:
            btn.create_text(cx, cy, text=label_text, fill=fg_color, font=font_spec, tags="hit")

        def on_enter(e):
            btn.itemconfig("bgimg", image=hover_photo)

        def on_leave(e):
            btn.itemconfig("bgimg", image=normal_photo)

        def on_click(e):
            command()

        for seq, fn in (("<Enter>", on_enter), ("<Leave>", on_leave), ("<Button-1>", on_click)):
            btn.bind(seq, fn)

        return btn

    def _create_card(self, parent, title):
        # Card outer container con borde sutil
        card = tk.Frame(
            parent,
            bg=self.card_color,
            highlightbackground=self.border_color,
            highlightcolor=self.border_color,
            highlightthickness=1,
            bd=0
        )

        # Franja superior de acento (look moderno tipo dashboard)
        accent_strip = tk.Frame(card, bg=self.accent_blue, height=3)
        accent_strip.pack(fill="x", side="top")

        # Title bar
        header_frame = tk.Frame(card, bg=self.card_color)
        header_frame.pack(fill="x", padx=14, pady=(9, 7))

        lbl_title = tk.Label(
            header_frame,
            text=title,
            bg=self.card_color,
            fg=self.fg_color,
            font=("Segoe UI", 10, "bold")
        )
        lbl_title.pack(side="left")

        # Content body frame
        content_frame = tk.Frame(card, bg=self.card_color)
        content_frame.pack(fill="both", expand=True, padx=14, pady=(0, 12))

        return card, content_frame

    def _load_icon(self, filename):
        """Icono de botón desde icons/ (viene dentro del .exe; ya no se descarga)."""
        path = resource_path("icons", filename)
        try:
            return ImageTk.PhotoImage(Image.open(path))
        except (OSError, ValueError):
            return tk.PhotoImage(width=1, height=1)

    def _draw_tech_background(self, event):
        canvas = event.widget
        width, height = event.width, event.height
        if width < 1 or height < 1:
            return

        canvas.delete("all")
        if self._background_source_image is not None and self.theme.bg_image:
            background = ImageOps.fit(
                self._background_source_image,
                (width, height),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.68),
            )
            overlay = Image.new("RGB", (width, height), self.theme.bg_overlay)
            self._background_photo = ImageTk.PhotoImage(
                Image.blend(background, overlay, self.theme.bg_overlay_alpha)
            )
            canvas.create_image(0, 0, image=self._background_photo, anchor="nw")
        else:
            top = self._hex_to_rgb(self.theme.bg_top)
            bottom = self._hex_to_rgb(self.theme.bg_bottom)
            bands = 36
            for index in range(bands):
                ratio = index / max(1, bands - 1)
                color = "#%02X%02X%02X" % tuple(
                    round(top[channel] + (bottom[channel] - top[channel]) * ratio)
                    for channel in range(3)
                )
                y0 = round(height * index / bands)
                y1 = round(height * (index + 1) / bands) + 1
                canvas.create_rectangle(0, y0, width, y1, fill=color, outline=color)

        if not self.theme.bg_decor:
            return
        center_x, center_y = width * 0.49, height * 0.46
        for index in range(18):
            radius = min(width, height) * (0.10 + index * 0.037)
            color = self.theme.bg_ring_a if index % 2 else self.theme.bg_ring_b
            canvas.create_oval(
                center_x - radius,
                center_y - radius,
                center_x + radius,
                center_y + radius,
                outline=color,
                width=1
            )

        points = []
        for index in range(42):
            angle = index * 2.399963
            radius = min(width, height) * (0.12 + (index % 9) * 0.045)
            x = center_x + math.cos(angle) * radius
            y = center_y + math.sin(angle) * radius
            points.append((x, y))

        for index, (x, y) in enumerate(points):
            for next_index in (index + 1, index + 7):
                if next_index < len(points):
                    next_x, next_y = points[next_index]
                    canvas.create_line(x, y, next_x, next_y, fill=self.theme.bg_line, width=1)
            canvas.create_oval(x - 1.5, y - 1.5, x + 1.5, y + 1.5, fill=self.theme.bg_dot, outline="")
