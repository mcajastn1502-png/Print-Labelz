import os
import sys
import re
import json
import textwrap
import datetime
import win32print
import label_layout as LL
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont
from PIL import Image, ImageTk, ImageDraw, ImageFilter, ImageOps
from io import BytesIO
import ctypes
import math
import unicodedata

# Habilitar soporte DPI para evitar textos borrosos (pixelados) en monitores modernos
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# --- OPTIMIZACIONES DE ARRANQUE: REEMPLAZO DE PANDAS (LIGHTWEIGHT DATAFRAME) ---
def notna(val):
    if val is None:
        return False
    if isinstance(val, float):
        if math.isnan(val):
            return False
    return True

class ExcelRow:
    def __init__(self, columns, row_values):
        self.columns = columns
        self.row_values = row_values
        
    @property
    def values(self):
        return self.row_values
        
    def get(self, col_name, default=None):
        try:
            idx = self.columns.index(col_name)
            return self.row_values[idx]
        except ValueError:
            return default

class ILocIndexer:
    def __init__(self, df):
        self.df = df
        
    def __getitem__(self, index):
        return ExcelRow(self.df.columns, self.df.rows[index])

class AtIndexer:
    def __init__(self, df):
        self.df = df
        
    def __getitem__(self, key):
        row_idx, col_name = key
        col_idx = self.df.columns.index(col_name)
        return self.df.rows[row_idx][col_idx]
        
    def __setitem__(self, key, value):
        row_idx, col_name = key
        col_idx = self.df.columns.index(col_name)
        self.df.rows[row_idx][col_idx] = value

class ExcelDataFrame:
    def __init__(self, columns, rows):
        self.columns = list(columns)
        self.rows = [list(row) for row in rows]
        self.iloc = ILocIndexer(self)
        self.at = AtIndexer(self)
        
    @property
    def empty(self):
        return len(self.rows) == 0
        
    def __len__(self):
        return len(self.rows)

def read_excel_light(file_path):
    import openpyxl
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    sheet = wb.active
    
    columns = []
    rows = []
    
    first = True
    for row in sheet.iter_rows(values_only=True):
        if first:
            columns = [str(cell).strip() if cell is not None else f"Column_{i}" for i, cell in enumerate(row)]
            seen_columns = {}
            unique_columns = []
            for column in columns:
                occurrence = seen_columns.get(column, 0) + 1
                seen_columns[column] = occurrence
                if occurrence > 1:
                    suffix = (
                        " (COPIAS)"
                        if occurrence == 2
                        and column.strip().casefold() == "cantidad"
                        else f" ({occurrence})"
                    )
                    column = f"{column}{suffix}"
                while column in unique_columns:
                    column = f"{column} ({occurrence})"
                    occurrence += 1
                unique_columns.append(column)
            columns = unique_columns
            first = False
        else:
            if any(cell is not None for cell in row):
                row_val = list(row)
                if len(row_val) < len(columns):
                    row_val += [None] * (len(columns) - len(row_val))
                elif len(row_val) > len(columns):
                    row_val = row_val[:len(columns)]
                rows.append(row_val)
                
    wb.close()
    return ExcelDataFrame(columns, rows)


class ZebraPrintApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SIBO PRINT")
        
        # Tamaño inicial adaptable al área disponible de la pantalla.
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()

        win_w = min(screen_w - 40, max(1100, int(screen_w * 0.92)))
        win_h = min(screen_h - 80, max(680, int(screen_h * 0.90)))
        x = max(20, (screen_w - win_w) // 2)
        y = max(20, (screen_h - win_h) // 2)

        self.geometry(f"{win_w}x{win_h}+{x}+{y}")
        self.minsize(min(900, screen_w - 40), min(600, screen_h - 80))
        
        # Variables lógicas
        self.CHECK_COL = "__sel__"  # Id interno de la columna de checkboxes de la tabla
        self.df = None
        self.plantilla_zpl = None
        self.variables_prn = []
        self.map_columnas = {} # variable -> columna de excel auto-asociada
        
        # Determinar el directorio base (externo si es ejecutable compilado)
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            
        self.prn_folder = os.path.join(base_dir, "prn_templates")
        self._bundled_resource_dir = getattr(sys, "_MEIPASS", None)

        # Ajuste automático de etiquetas: configuración junto al ejecutable (portable)
        self.config_path = os.path.join(base_dir, "sibo_print_config.json")
        self.app_config = self._load_app_config()
        self.layout_settings = LL.LayoutSettings.from_dict(self.app_config.get("layout"))
        self.parsed_template = None      # plantilla analizada (se reutiliza en cada fila)
        self.template_sizes = {}         # nombre .prn -> (ancho_mm, alto_mm)
        self.all_templates = []
        self.last_layout = None
        self._background_source_image = None
        background_paths = [
            os.path.join(base_dir, "assets", "tech-background.png"),
        ]
        if self._bundled_resource_dir:
            background_paths.append(
                os.path.join(self._bundled_resource_dir, "assets", "tech-background.png")
            )
        for background_path in background_paths:
            if os.path.isfile(background_path):
                with Image.open(background_path) as background_image:
                    self._background_source_image = background_image.convert("RGB")
                break
        self._background_photo = None
        self._preview_timer = None # Control para slider en vivo
        self._current_preview_img = None # Guarda la imagen alta calidad descargada
        self._resize_timer = None # Control para diseño responsive
        self.preview_api_enabled = tk.BooleanVar(value=True) # Control ON/OFF de previsualizacion web (activa por defecto)
        self._switch_anim_timer = None # Timer para animar el interruptor
        self._switch_knob_x = 4 # Posicion inicial de perilla (OFF)
        
        # Construir Interfaz y Estilos
        self._setup_styles()
        self.configure(bg=self.bg_color)
        
        # Configurar icono de la aplicación
        try:
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons", "icon1.png")
            if os.path.exists(icon_path):
                icon_img = ImageTk.PhotoImage(Image.open(icon_path))
                self.iconphoto(False, icon_img)
            else:
                self.iconphoto(False, tk.PhotoImage(width=1, height=1))
        except Exception as e:
            print("No se pudo cargar el icono configurado:", e)

        self._build_ui()
        self._load_local_data()

    def _setup_styles(self):
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except:
            pass
        
        # Paleta azul oscura inspirada en la referencia, con acentos de alto contraste.
        self.bg_color = "#071827"
        self.card_color = "#10283A"
        self.border_color = "#29475B"
        self.fg_color = "#E8F1F6"
        self.fg_muted = "#A8BBC7"

        self.row_even = "#10283A"
        self.row_odd = "#142F42"
        self.row_hover = "#1B4054"

        self.preview_bg = "#DCE7ED"

        self.accent_blue = "#38B9E8"
        self.accent_blue_hover = "#59C8EF"

        # Degradados de botones (inicio -> fin)
        self.grad_excel = ("#16A878", "#0F9D91")
        self.grad_calibrate = ("#E89135", "#D97706")
        self.grad_print = ("#0F9D91", "#087F8C")
        self.grad_reset = ("#73828B", "#596A73")

        # Compatibilidad: alias usados como pares (inicio, hover) en otras partes del código
        self.accent_green, self.accent_green_hover = self.grad_excel
        self.accent_amber, self.accent_amber_hover = self.grad_calibrate
        self.accent_gray, self.accent_gray_hover = self.grad_reset

        # Configuración básica de elementos ttk
        self.style.configure("TFrame", background=self.bg_color)
        self.style.configure("Panel.TFrame", background=self.card_color)
        
        self.style.configure("TLabel", background=self.bg_color, foreground=self.fg_color, font=("Segoe UI", 9))
        self.style.configure("Panel.TLabel", background=self.card_color, foreground=self.fg_color, font=("Segoe UI", 9))
        self.style.configure("Header.TLabel", background=self.card_color, foreground=self.fg_color, font=("Segoe UI", 10, "bold"))
        self.style.configure("Muted.TLabel", background=self.card_color, foreground=self.fg_muted, font=("Segoe UI", 9))
        
        # Comboboxes estilizados oscuros
        self.style.map('TCombobox',
            fieldbackground=[('readonly', self.card_color)],
            background=[('readonly', self.card_color)],
            foreground=[('readonly', self.fg_color)]
        )
        self.style.configure('TCombobox',
            fieldbackground=self.card_color,
            background=self.border_color,
            foreground=self.fg_color,
            bordercolor=self.border_color,
            lightcolor=self.border_color,
            darkcolor=self.border_color,
            arrowcolor=self.fg_color,
            padding=6,
            insertcolor=self.fg_color,
            font=("Segoe UI", 9)
        )
        
        # Treeview de datos en Slate
        self.style.configure("Treeview",
            background=self.card_color,
            foreground=self.fg_color,
            fieldbackground=self.card_color,
            borderwidth=0,
            rowheight=34,
            font=("Segoe UI", 9)
        )
        self.style.configure("Treeview.Heading",
            background=self.card_color,
            foreground=self.fg_color,
            font=("Segoe UI", 9, "bold"),
            borderwidth=0,
            padding=(10, 9),
            relief="flat"
        )
        self.style.map("Treeview.Heading",
            background=[("active", self.border_color)],
            foreground=[("active", self.fg_color)]
        )
        self.style.map("Treeview",
            background=[("selected", self.accent_blue)],
            foreground=[("selected", "#FFFFFF")]
        )
        
        # Sliders
        self.style.configure("TScale",
            background=self.card_color,
            troughcolor=self.bg_color,
            sliderlength=18,
            sliderthickness=12
        )
        
        # Scrollbars modernas estilizadas (delgadas y sin flechas)
        self.style.layout('Dark.Vertical.TScrollbar', 
            [('Vertical.Scrollbar.trough', {'children': 
                [('Vertical.Scrollbar.thumb', {'expand': '1', 'sticky': 'nswe'})], 
            'sticky': 'ns'})])
        self.style.configure('Dark.Vertical.TScrollbar',
            troughcolor=self.bg_color,
            background="#B8C8CD",
            bordercolor=self.bg_color,
            lightcolor=self.bg_color,
            darkcolor=self.bg_color,
            arrowsize=0,
            width=10
        )
        
        self.style.layout('Dark.Horizontal.TScrollbar', 
            [('Horizontal.Scrollbar.trough', {'children': 
                [('Horizontal.Scrollbar.thumb', {'expand': '1', 'sticky': 'nswe'})], 
            'sticky': 'we'})])
        self.style.configure('Dark.Horizontal.TScrollbar',
            troughcolor=self.bg_color,
            background="#B8C8CD",
            bordercolor=self.bg_color,
            lightcolor=self.bg_color,
            darkcolor=self.bg_color,
            arrowsize=0,
            width=10
        )

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

    def _create_hover_button(self, parent, text, image, color_from, color_to, command, is_bold=True, fg_color="#FFFFFF"):
        """Botón moderno: fondo en degradado, esquinas redondeadas y sombra sutil (renderizado con PIL sobre un Canvas)."""
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

    def _fetch_icon(self, url, filename):
        icon_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
        if not os.path.exists(icon_folder):
            try: os.makedirs(icon_folder)
            except: pass
            
        path = os.path.join(icon_folder, filename)
        if not os.path.exists(path):
            try:
                import requests
                res = requests.get(url, timeout=5)
                if res.status_code == 200:
                    with open(path, 'wb') as f:
                        f.write(res.content)
            except Exception as e:
                print(f"Error descargando {filename}:", e)
        
        if os.path.exists(path):
            try:
                return ImageTk.PhotoImage(Image.open(path))
            except:
                pass
        return tk.PhotoImage(width=1, height=1)

    def _draw_tech_background(self, event):
        canvas = event.widget
        width, height = event.width, event.height
        if width < 1 or height < 1:
            return

        canvas.delete("all")
        if self._background_source_image is not None:
            background = ImageOps.fit(
                self._background_source_image,
                (width, height),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.68),
            )
            overlay = Image.new("RGB", (width, height), "#061523")
            self._background_photo = ImageTk.PhotoImage(
                Image.blend(background, overlay, 0.46)
            )
            canvas.create_image(0, 0, image=self._background_photo, anchor="nw")
        else:
            top = self._hex_to_rgb("#061523")
            bottom = self._hex_to_rgb("#0B2233")
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

        center_x, center_y = width * 0.49, height * 0.46
        for index in range(18):
            radius = min(width, height) * (0.10 + index * 0.037)
            color = "#102B3D" if index % 2 else "#0E293A"
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
                    canvas.create_line(x, y, next_x, next_y, fill="#123044", width=1)
            canvas.create_oval(x - 1.5, y - 1.5, x + 1.5, y + 1.5, fill="#1D5267", outline="")

    def _build_ui(self):
        self.background_canvas = tk.Canvas(
            self, bg=self.bg_color, highlightthickness=0, bd=0
        )
        self.background_canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.tk.call("lower", self.background_canvas._w)
        self.background_canvas.bind("<Configure>", self._draw_tech_background)

        # ---------------------------------------------
        # TOP HEADER: Barra de Herramientas Principal
        # ---------------------------------------------
        self.frame_header = tk.Frame(self, bg=self.bg_color, height=58)
        self.frame_header.pack(fill="x", padx=28, pady=(14, 8))
        self.frame_header.pack_propagate(False)

        # Título / Logo
        title_frame = tk.Frame(self.frame_header, bg=self.bg_color)
        title_frame.pack(side="left", anchor="w", pady=3)

        brand_line = tk.Frame(title_frame, bg=self.bg_color)
        brand_line.pack(anchor="w")

        lbl_logo = tk.Label(brand_line, text="SIBO", bg=self.bg_color, fg=self.accent_blue, font=("Segoe UI", 17, "bold"))
        lbl_logo.pack(side="left")

        lbl_title = tk.Label(brand_line, text=" PRINT", bg=self.bg_color, fg=self.fg_color, font=("Segoe UI", 17, "normal"))
        lbl_title.pack(side="left")

        # Cargar iconos de la web o de caché local
        self.icon_excel = self._fetch_icon("https://img.icons8.com/ios-filled/20/ffffff/ms-excel.png", "excel_btn.png")
        self.icon_print = self._fetch_icon("https://img.icons8.com/ios-filled/20/ffffff/print.png", "print_btn.png")
        self.icon_calib = self._fetch_icon("https://img.icons8.com/ios-filled/20/ffffff/settings.png", "gear_btn.png")
        self.icon_reset = self._fetch_icon("https://img.icons8.com/ios-filled/16/ffffff/restart.png", "reset_btn.png")
        
        actions_frame = tk.Frame(self.frame_header, bg=self.bg_color)
        actions_frame.pack(side="right", anchor="e")
        
        # Botón Abrir Excel (Verde Esmeralda)
        self.btn_excel = self._create_hover_button(
            actions_frame, 
            "  ABRIR EXCEL", 
            self.icon_excel, 
            self.accent_green, 
            self.accent_green_hover, 
            self.load_excel
        )
        self.btn_excel.pack(side="left", padx=5)

        self.btn_calibrate = self._create_hover_button(
            actions_frame,
            "  CALIBRAR IMPRESORA",
            self.icon_calib,
            self.accent_amber,
            self.accent_amber_hover,
            self.calibrate_printer
        )
        self.btn_calibrate.pack(side="left", padx=5)

        # Campo de Copias por etiqueta (Impresión Múltiple)
        copies_frame = tk.Frame(actions_frame, bg=self.bg_color)
        copies_frame.pack(side="left", padx=(5, 10))

        lbl_copies = tk.Label(copies_frame, text="Copias:", bg=self.bg_color, fg=self.fg_muted, font=("Segoe UI", 9, "bold"))
        lbl_copies.pack(side="left", padx=(0, 6))

        vcmd_copies = (self.register(self._validate_copies_input), "%P")
        self.spin_copies = tk.Spinbox(
            copies_frame,
            from_=1,
            to=999,
            width=4,
            justify="center",
            validate="key",
            validatecommand=vcmd_copies,
            bg=self.card_color,
            fg=self.fg_color,
            buttonbackground=self.border_color,
            insertbackground=self.fg_color,
            relief="flat",
            highlightthickness=1,
            highlightbackground=self.border_color,
            highlightcolor=self.accent_blue,
            font=("Segoe UI", 9, "bold")
        )
        self.spin_copies.delete(0, "end")
        self.spin_copies.pack(side="left", ipady=4)

        # Botón Imprimir (degradado Petróleo -> Azul)
        self.btn_print = self._create_hover_button(
            actions_frame,
            "  IMPRIMIR SELECCIÓN",
            self.icon_print,
            self.grad_print[0],
            self.grad_print[1],
            self.print_labels
        )
        self.btn_print.pack(side="left", padx=5)

        # Configuración y vista previa en la zona superior; registros debajo.
        self.paned_main = tk.PanedWindow(
            self, orient=tk.VERTICAL, bd=0, bg=self.bg_color,
            sashwidth=8, sashrelief="flat"
        )
        self.paned_main.pack(expand=True, fill="both", padx=22, pady=(4, 14))

        self.paned_workspace = tk.PanedWindow(
            self.paned_main, orient=tk.VERTICAL, bd=0, bg=self.bg_color,
            sashwidth=8, sashrelief="flat"
        )
        self.paned_main.add(self.paned_workspace, minsize=500, stretch="always")

        self.frame_top_section = tk.Frame(self.paned_workspace, bg=self.bg_color)
        self.paned_workspace.add(
            self.frame_top_section, minsize=330, height=380, stretch="never"
        )

        self.frame_top_section.columnconfigure(0, weight=2, minsize=270)
        self.frame_top_section.columnconfigure(1, weight=4, minsize=420)
        self.frame_top_section.rowconfigure(0, weight=1)
        self.frame_sidebar = tk.Frame(self.frame_top_section, bg=self.bg_color)
        self.frame_sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        card_left, body_left = self._create_card(
            self.frame_sidebar, "CONFIGURACIÓN DE IMPRESIÓN"
        )
        card_left.pack(expand=True, fill="both", pady=(8, 5))

        card_right, body_right = self._create_card(
            self.frame_top_section, "VISTA PREVIA DE ETIQUETA"
        )
        card_right.grid(row=0, column=1, sticky="nsew", pady=(8, 5))

        body_left.columnconfigure(0, weight=1)

        # 0. Tamaño de etiqueta y resolución de la impresora
        size_frame = tk.Frame(body_left, bg=self.card_color)
        size_frame.grid(row=0, column=0, columnspan=2, sticky="we", pady=(5, 7))
        size_frame.columnconfigure(0, weight=3)
        size_frame.columnconfigure(1, weight=2)

        lbl_size = tk.Label(size_frame, text="Tamaño de etiqueta:", bg=self.card_color, fg=self.fg_muted, font=("Segoe UI", 9, "bold"))
        lbl_size.grid(row=0, column=0, sticky="w", pady=(0, 2))
        lbl_dpi = tk.Label(size_frame, text="Resolución:", bg=self.card_color, fg=self.fg_muted, font=("Segoe UI", 9, "bold"))
        lbl_dpi.grid(row=0, column=1, sticky="w", padx=(8, 0), pady=(0, 2))

        self.combo_size = ttk.Combobox(size_frame, state="readonly", width=18)
        self.combo_size.grid(row=1, column=0, sticky="we")
        self.combo_size.bind("<<ComboboxSelected>>", self.on_size_selected)
        self._refresh_size_options()

        self.combo_dpi = ttk.Combobox(
            size_frame, state="readonly", width=9,
            values=[f"{dpi} dpi" for dpi in LL.DPI_OPTIONS]
        )
        self.combo_dpi.grid(row=1, column=1, sticky="we", padx=(8, 0))
        self.combo_dpi.set(f"{LL.DPI_OPTIONS[0]} dpi")
        self.combo_dpi.bind("<<ComboboxSelected>>", self.on_dpi_selected)

        # 1. Selector de Plantillas
        lbl_zpl = tk.Label(body_left, text="Plantilla ZPL:", bg=self.card_color, fg=self.fg_muted, font=("Segoe UI", 9, "bold"))
        lbl_zpl.grid(row=1, column=0, sticky="w", pady=(0, 2))

        self.combo_prn = ttk.Combobox(body_left, state="readonly")
        self.combo_prn.grid(row=2, column=0, columnspan=2, sticky="we", pady=(0, 7))
        self.combo_prn.bind("<<ComboboxSelected>>", self.on_prn_selected)

        # 2. Selector de Impresora
        lbl_printer = tk.Label(body_left, text="Impresora:", bg=self.card_color, fg=self.fg_muted, font=("Segoe UI", 9, "bold"))
        lbl_printer.grid(row=3, column=0, sticky="w", pady=(0, 2))

        self.combo_printer = ttk.Combobox(body_left, state="readonly")
        self.combo_printer.grid(row=4, column=0, columnspan=2, sticky="we", pady=(0, 7))
        self.combo_printer.bind("<<ComboboxSelected>>", self.on_printer_selected)

        # Separador sutil
        sep = tk.Frame(body_left, bg=self.border_color, height=1)
        sep.grid(row=5, column=0, columnspan=2, sticky="we", pady=(3, 8))

        # 3. Alineación Horizontal
        lbl_x = tk.Label(body_left, text="Alineación Horiz. (X):", bg=self.card_color, fg=self.fg_color, font=("Segoe UI", 9))
        lbl_x.grid(row=6, column=0, sticky="w", pady=(2, 0))

        self.slider_x = ttk.Scale(body_left, from_=-15, to=15, orient="horizontal", command=self.on_slider_change)
        self.slider_x.set(0)
        self.slider_x.grid(row=7, column=0, sticky="we", pady=(2, 6))

        self.lbl_val_x = tk.Label(body_left, text="0 mm", bg=self.card_color, fg=self.accent_blue, font=("Segoe UI", 9, "bold"), width=6)
        self.lbl_val_x.grid(row=7, column=1, padx=(5, 0))

        # 4. Alineación Vertical
        lbl_y = tk.Label(body_left, text="Alineación Vert. (Y):", bg=self.card_color, fg=self.fg_color, font=("Segoe UI", 9))
        lbl_y.grid(row=8, column=0, sticky="w", pady=(2, 0))

        self.slider_y = ttk.Scale(body_left, from_=-15, to=15, orient="horizontal", command=self.on_slider_change)
        self.slider_y.set(0)
        self.slider_y.grid(row=9, column=0, sticky="we", pady=(2, 7))

        self.lbl_val_y = tk.Label(body_left, text="0 mm", bg=self.card_color, fg=self.accent_blue, font=("Segoe UI", 9, "bold"), width=6)
        self.lbl_val_y.grid(row=9, column=1, padx=(5, 0))

        # 5. Botones Restaurar Ajustes / Ajustes de diseño
        buttons_frame = tk.Frame(body_left, bg=self.card_color)
        buttons_frame.grid(row=10, column=0, columnspan=2, sticky="w", pady=(3, 5))

        self.btn_reset = self._create_hover_button(
            buttons_frame,
            " Restaurar Ajustes",
            self.icon_reset,
            self.accent_gray,
            self.accent_gray_hover,
            self.reset_sliders
        )
        self.btn_reset.pack(side="left")

        self.btn_design = self._create_hover_button(
            buttons_frame,
            " Ajustes de diseño",
            self.icon_calib,
            "#2F8FBF",
            "#1F6E99",
            self.open_design_settings
        )
        self.btn_design.pack(side="left", padx=(6, 0))

        # Separador para interruptor
        sep2 = tk.Frame(body_left, bg=self.border_color, height=1)
        sep2.grid(row=11, column=0, columnspan=2, sticky="we", pady=(4, 8))

        # 6. Switch Vista Previa Web
        lbl_toggle = tk.Label(body_left, text="Vista Previa Web:", bg=self.card_color, fg=self.fg_color, font=("Segoe UI", 9, "bold"))
        lbl_toggle.grid(row=12, column=0, sticky="w", pady=(0, 3))

        switch_frame = tk.Frame(body_left, bg=self.card_color)
        switch_frame.grid(row=13, column=0, sticky="w")
        
        self.preview_switch_canvas = tk.Canvas(
            switch_frame,
            width=50,
            height=26,
            bg=self.card_color,
            bd=0,
            highlightthickness=0,
            cursor="hand2"
        )
        self.preview_switch_canvas.pack(side="left")
        self.preview_switch_canvas.bind("<Button-1>", self.toggle_preview_api)
        
        self.preview_switch_state = tk.Label(
            switch_frame,
            text="OFF",
            bg=self.card_color,
            fg=self.fg_muted,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2"
        )
        self.preview_switch_state.pack(side="left", padx=(10, 0))
        self.preview_switch_state.bind("<Button-1>", self.toggle_preview_api)
        
        self._render_preview_switch()

        # Estado del ajuste automático (clic para ver el detalle)
        self.lbl_layout_status = tk.Label(
            body_right,
            text="",
            bg=self.card_color,
            fg=self.fg_muted,
            font=("Segoe UI", 9),
            anchor="w",
            justify="left",
            cursor="hand2"
        )
        self.lbl_layout_status.pack(side="bottom", fill="x", pady=(6, 0))
        self.lbl_layout_status.bind("<Button-1>", self.show_layout_details)
        body_right.bind(
            "<Configure>",
            lambda e: self.lbl_layout_status.config(wraplength=max(200, e.width - 10))
        )

        # El Canvas de Preview se empaca en el cuerpo derecho
        self.preview_canvas = tk.Label(
            body_right,
            bg=self.preview_bg,
            text="Seleccione un archivo PRN para visualizar",
            fg="#5B6672",
            font=("Segoe UI", 10)
        )
        self.preview_canvas.pack(expand=True, fill="both")
        self.preview_canvas.bind("<Configure>", self.on_preview_resize)

        # --- PANEL DE EXCEL ---
        self.frame_table_section = tk.Frame(self.paned_workspace, bg=self.bg_color)
        self.paned_workspace.add(
            self.frame_table_section, minsize=230, height=400, stretch="always"
        )
        
        # Tarjeta de la Tabla
        card_table, body_table = self._create_card(self.frame_table_section, "REGISTROS DEL EXCEL PARA IMPRESIÓN")
        card_table.pack(expand=True, fill="both", pady=(5, 0))

        # Contenedor para Treeview y sus Scrollbars
        table_container = tk.Frame(body_table, bg=self.card_color)
        table_container.pack(expand=True, fill="both", pady=(5, 5))
        
        # Crear Scrollbars con nuestro estilo Dark
        self.scrolly = ttk.Scrollbar(table_container, orient="vertical", style="Dark.Vertical.TScrollbar")
        self.scrolly.pack(side="right", fill="y")
        
        self.scrollx = ttk.Scrollbar(table_container, orient="horizontal", style="Dark.Horizontal.TScrollbar")
        self.scrollx.pack(side="bottom", fill="x")
        
        self.tree = ttk.Treeview(
            table_container, 
            yscrollcommand=self._on_tree_yscroll,
            xscrollcommand=self._on_tree_xscroll,
            selectmode="extended",
            style="Treeview"
        )
        self.tree.pack(expand=True, fill="both")
        
        self.scrolly.config(command=self._scroll_tree_y)
        self.scrollx.config(command=self._scroll_tree_x)
        
        # Eventos de tabla
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_row_selected)
        self.tree.bind("<Double-1>", self.on_double_click)
        self.tree.bind("<Button-1>", self.on_tree_checkbox_click)
        self.tree.bind("<Motion>", self._on_tree_motion)
        self.tree.bind("<Leave>", self._on_tree_leave)
        self.tree.bind("<Configure>", lambda e: self._queue_copies_controls_refresh())
        self._hover_item = None
        self._copies_controls = {}
        self._copies_refresh_pending = False

        # Barra de estado inferior dentro de la tarjeta
        self.frame_status = tk.Frame(body_table, bg=self.card_color)
        self.frame_status.pack(fill="x", pady=(10, 0))

        self.lbl_status_rows = tk.Label(
            self.frame_status,
            text="Sin datos cargados. Abre un archivo Excel.",
            bg=self.card_color,
            fg=self.fg_muted,
            font=("Segoe UI", 9, "italic")
        )
        self.lbl_status_rows.pack(side="left")

        # Accesos rápidos de selección masiva (equivalen al checkbox del encabezado)
        quick_select_frame = tk.Frame(self.frame_status, bg=self.card_color)
        quick_select_frame.pack(side="left", padx=(18, 0))

        lbl_select_all = tk.Label(
            quick_select_frame, text="Marcar todo", bg=self.card_color,
            fg=self.accent_blue, font=("Segoe UI", 9, "underline"), cursor="hand2"
        )
        lbl_select_all.pack(side="left")
        lbl_select_all.bind("<Button-1>", lambda e: self.tree.selection_set(self.tree.get_children()))

        lbl_sep_quick = tk.Label(quick_select_frame, text=" | ", bg=self.card_color, fg=self.fg_muted, font=("Segoe UI", 9))
        lbl_sep_quick.pack(side="left")

        lbl_deselect_all = tk.Label(
            quick_select_frame, text="Quitar selección", bg=self.card_color,
            fg=self.fg_muted, font=("Segoe UI", 9, "underline"), cursor="hand2"
        )
        lbl_deselect_all.pack(side="left")
        lbl_deselect_all.bind("<Button-1>", lambda e: self.tree.selection_remove(self.tree.get_children()))

        self.lbl_status_selection = tk.Label(
            self.frame_status,
            text="Seleccionados: 0 etiquetas",
            bg=self.bg_color,
            fg=self.accent_blue,
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=3
        )
        self.lbl_status_selection.pack(side="right")

    def _load_local_data(self):
        # 1. Impresoras
        try:
            printers = [p[2] for p in win32print.EnumPrinters(2)]
            self.combo_printer['values'] = printers
            if printers:
                self.combo_printer.current(0)
            self._sync_dpi_for_printer()

            driver_zebra_detectado = any(
                re.search(r'zebra|zdesigner|zpl', p, re.IGNORECASE) for p in printers
            )
            if not driver_zebra_detectado:
                messagebox.showwarning(
                    "Driver de impresora no encontrado",
                    "No se detectó ningún driver de impresora Zebra/ZPL instalado en este equipo.\n\n"
                    "Para poder imprimir etiquetas necesitas instalar el driver de tu impresora "
                    "térmica (por ejemplo \"ZDesigner ZD230-203dpi ZPL\") antes de continuar.\n\n"
                    "Mientras tanto puedes seguir usando la Vista Previa Web para revisar el diseño."
                )
        except Exception as e:
            print("Error cargando impresoras:", e)

        # 2. Plantillas PRN
        template_errors = []
        try:
            os.makedirs(self.prn_folder, exist_ok=True)
        except OSError as error:
            template_errors.append(f"{self.prn_folder}: {error}")
        template_folders = [self.prn_folder]
        if self._bundled_resource_dir:
            bundled_templates = os.path.join(self._bundled_resource_dir, "prn_templates")
            if bundled_templates not in template_folders:
                template_folders.append(bundled_templates)

        archivos = []
        for folder in template_folders:
            if not os.path.isdir(folder):
                continue
            try:
                archivos = sorted(
                    filename for filename in os.listdir(folder)
                    if filename.casefold().endswith(".prn")
                    and os.path.isfile(os.path.join(folder, filename))
                )
            except OSError as error:
                template_errors.append(f"{folder}: {error}")
                continue
            if archivos:
                self.prn_folder = folder
                break

        # Tamaño físico de cada plantilla (para asociarlas a los tamaños de etiqueta)
        self.all_templates = archivos
        self.template_sizes = {}
        for filename in archivos:
            try:
                with open(os.path.join(self.prn_folder, filename), encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                pw = re.search(r"\^PW(\d+)", content, re.IGNORECASE)
                ll = re.search(r"\^LL(\d+)", content, re.IGNORECASE)
                size_mm, _, _ = LL.template_size_mm(
                    filename, int(pw.group(1)) if pw else 0, int(ll.group(1)) if ll else 0
                )
                self.template_sizes[filename] = size_mm
            except (OSError, ValueError):
                continue
        archivos = self._templates_for_current_size()

        self.combo_prn['values'] = archivos
        if archivos:
            self.combo_prn.current(0)

            def _finalize_prn_selection():
                # Se difiere a después del primer ciclo de mainloop: fuerza a Tk a
                # repintar el texto seleccionado y luego carga la plantilla.
                self.combo_prn.set(archivos[0])
                self.on_prn_selected(None)

            self.after(50, _finalize_prn_selection)
        elif template_errors:
            messagebox.showerror(
                "Error al cargar plantillas ZPL",
                "No se pudieron leer las carpetas de plantillas:\n\n"
                + "\n".join(template_errors),
                parent=self,
            )
        else:
            messagebox.showwarning(
                "Plantillas ZPL no encontradas",
                "No se encontraron archivos .prn en la carpeta de plantillas.\n\n"
                f"Coloca las plantillas en:\n{self.prn_folder}",
                parent=self,
            )

    # =========================================================================
    # EVENTOS DE USUARIO
    # =========================================================================

    def load_excel(self):
        try:
            file_path = filedialog.askopenfilename(
                parent=self,
                title="Seleccionar archivo Excel",
                filetypes=[("Archivos Excel", "*.xlsx;*.xls")]
            )
            if not file_path:
                return

            self.df = read_excel_light(file_path)
            
            # Asociar las variables requeridas en el ZPL automáticamente (Invisible)
            self.auto_map_variables()
            
            # Dibujar la cuadrícula
            self._fill_treeview()
            
            # Generar preview de la fila 0 por default
            self.generate_preview(row_index=0)
            
        except Exception as e:
            messagebox.showerror(
                "Error al cargar Excel",
                f"No se pudo abrir o leer el archivo Excel:\n{e}",
                parent=self
            )

    def on_prn_selected(self, event):
        prn_file = self.combo_prn.get()
        if not prn_file: return
        
        path = os.path.join(self.prn_folder, prn_file)
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                self.plantilla_zpl = f.read()

            # Analizar la plantilla una sola vez: el motor de ajuste la reutiliza en cada fila.
            try:
                self.parsed_template = LL.parse_template(self.plantilla_zpl, prn_file)
            except Exception as parse_error:
                print("No se pudo analizar la plantilla:", parse_error)
                self.parsed_template = None

            # Extraer nombres entre corchetes, Ej: [vlsCampo]
            self.variables_prn = list(set(re.findall(r"\[([^\]]+)\]", self.plantilla_zpl)))
            
            # Auto Mapear si ya hay un excel
            self.auto_map_variables()
            
            # Si se hace click justo al abrir, que muestre la fila que esté seleccionada, sino la 0
            self.generate_preview(row_index=self._get_selected_row_index())
            
        except Exception as e:
            messagebox.showerror("Error Lectura", f"Fallo al abrir archivo PRN:\n{str(e)}")

    def auto_map_variables(self):
        """Asocia invisiblemente cada variable del PRN con la cabecera de Excel posicionalmente y por nombre"""
        self.map_columnas.clear()
        if self.df is None or not self.variables_prn:
            return
            
        col_names = list(self.df.columns)
        col_names_lower = [str(c).strip().lower() for c in col_names]
        
        for var in self.variables_prn:
            var_norm = var.strip().lower()
            
            # --- 1. Mapeo Posicional Estricto (Nuevo estándar) ---
            # Si el PRN pide vlscampo1, va a la columna 0 (A). vlscampo2 va a la 1 (B), etc.
            match_num = re.search(r'(\d+)$', var_norm)
            if match_num and "vlscampo" in var_norm:
                idx = int(match_num.group(1)) - 1
                if 0 <= idx < len(col_names):
                    self.map_columnas[var] = col_names[idx]
                    continue
                    
            # Compatibilidad si usaste "vlscampo" clásico (sin número) -> Pasa a Col A
            # Solo aplica si la plantilla NO usa el nuevo estándar "vlscampo1", para evitar confilctos
            if var_norm == 'vlscampo':
                if not any(v.strip().lower() == 'vlscampo1' for v in self.variables_prn):
                    if len(col_names) > 0:
                        self.map_columnas[var] = col_names[0]
                        continue
                else:
                    # Es un huérfano/error de diseño en ZPL, lo dejamos sin mapear para que salga vacío
                    continue
                    
            # --- 2. Mapeo Histórico / Texto Exacto (Ej. "vlsCodigoQR") ---
            if var_norm in col_names_lower:
                idx = col_names_lower.index(var_norm)
                self.map_columnas[var] = col_names[idx]

    def _on_tree_yscroll(self, first, last):
        self.scrolly.set(first, last)
        self._queue_copies_controls_refresh()

    def _on_tree_xscroll(self, first, last):
        self.scrollx.set(first, last)
        self._queue_copies_controls_refresh()

    def _scroll_tree_y(self, *args):
        self.tree.yview(*args)
        self._queue_copies_controls_refresh()

    def _scroll_tree_x(self, *args):
        self.tree.xview(*args)
        self._queue_copies_controls_refresh()

    def _queue_copies_controls_refresh(self):
        if getattr(self, "_copies_refresh_pending", False):
            return
        self._copies_refresh_pending = True
        self.after_idle(self._refresh_copies_controls)

    def _refresh_copies_controls(self):
        self._copies_refresh_pending = False
        if not hasattr(self, "tree") or self.df is None:
            return

        copies_column = self._get_excel_copies_column()
        if copies_column is None:
            for control in self._copies_controls.values():
                control.destroy()
            self._copies_controls.clear()
            return

        column_index = self.df.columns.index(copies_column)
        tree_column = f"#{column_index + 2}"
        items = self.tree.get_children()
        if not items:
            return

        first_visible, last_visible = self.tree.yview()
        start = max(0, int(first_visible * len(items)) - 1)
        end = min(len(items), math.ceil(last_visible * len(items)) + 1)
        visible_range = items[start:end]
        visible_items = set()
        for item in visible_range:
            bbox = self.tree.bbox(item, tree_column)
            if not bbox:
                continue

            visible_items.add(item)
            x, y, width, height = bbox
            control = self._copies_controls.get(item)
            if control is None or not control.winfo_exists():
                tags = self.tree.item(item, "tags")
                if not tags:
                    continue
                row_index = int(tags[0])
                try:
                    copies = self._parse_excel_copies(
                        self.df.iloc[row_index].get(copies_column),
                        row_index + 1
                    )
                except ValueError:
                    copies = None
                copies = copies or 1

                control = tk.Spinbox(
                    self.tree,
                    from_=1,
                    to=999,
                    increment=1,
                    wrap=False,
                    width=4,
                    justify="center",
                    validate="key",
                    validatecommand=(self.register(self._validate_copies_input), "%P"),
                    command=lambda row=item: self._commit_copies_control(row),
                    bg=self.card_color,
                    fg=self.fg_color,
                    buttonbackground=self.border_color,
                    insertbackground=self.fg_color,
                    relief="flat",
                    highlightthickness=1,
                    highlightbackground=self.border_color,
                    highlightcolor=self.accent_blue,
                    font=("Segoe UI", 9),
                )
                control.delete(0, tk.END)
                control.insert(0, str(copies))
                control.bind(
                    "<KeyRelease>",
                    lambda event, row=item: self.after_idle(
                        lambda: self._commit_copies_control(row, show_error=False)
                    )
                )
                control.bind(
                    "<FocusOut>",
                    lambda event, row=item: self._commit_copies_control(row)
                )
                control.bind(
                    "<Return>",
                    lambda event, row=item: self._commit_copies_control(row)
                )
                self._copies_controls[item] = control
                self.tree.set(item, copies_column, str(copies))
                self.df.at[row_index, copies_column] = copies

            control.place(x=x, y=y, width=width, height=height)

        for item in list(self._copies_controls):
            if item not in visible_items:
                self._copies_controls.pop(item).destroy()

    def _commit_copies_control(self, item, show_error=True):
        control = self._copies_controls.get(item)
        if control is None or not control.winfo_exists():
            return

        value = control.get().strip()
        if not value:
            return

        tags = self.tree.item(item, "tags")
        if not tags:
            return
        row_index = int(tags[0])
        try:
            copies = self._parse_excel_copies(value, row_index + 1)
        except ValueError:
            if show_error:
                control.bell()
            return

        copies_column = self._get_excel_copies_column()
        if copies_column is None:
            return
        normalized_value = str(copies)
        if value != normalized_value:
            control.delete(0, tk.END)
            control.insert(0, normalized_value)
        self.tree.set(item, copies_column, normalized_value)
        self.df.at[row_index, copies_column] = copies

    def _fill_treeview(self):
        for control in getattr(self, "_copies_controls", {}).values():
            control.destroy()
        if hasattr(self, "_copies_controls"):
            self._copies_controls.clear()

        for item in self.tree.get_children():
            self.tree.delete(item)
        self._hover_item = None

        if self.df is None or self.df.empty: return

        cols = list(self.df.columns)
        # Columna de checkbox de selección, ubicada junto a la primera columna (CÓDIGO)
        self.tree["columns"] = [self.CHECK_COL] + cols
        self.tree["show"] = "headings"

        self.tree.heading(self.CHECK_COL, text="☐", command=self.toggle_select_all)
        self.tree.column(self.CHECK_COL, width=34, minwidth=34, anchor="center", stretch=False)

        # Ancho de columna auto-ajustado al contenido (máx. primeras 200 filas, por rendimiento)
        sample_size = min(len(self.df), 200)
        for col_idx, col in enumerate(cols):
            column_anchor = "center" if self._is_copies_column(col) else "w"
            self.tree.heading(col, text=col, anchor=column_anchor)

            max_len = len(str(col))
            for row_idx in range(sample_size):
                val = self.df.iloc[row_idx].values[col_idx]
                if notna(val):
                    val_len = len(str(val).strip())
                    if val_len > max_len:
                        max_len = val_len

            width = min(260, max(90, max_len * 7 + 20))
            if self._is_copies_column(col):
                width = max(width, 76)
            self.tree.column(col, width=width, anchor=column_anchor)

        self.tree.tag_configure("evenrow", background=self.row_even)
        self.tree.tag_configure("oddrow", background=self.row_odd)
        self.tree.tag_configure("hoverrow", background=self.row_hover)

        # Para imprimir selecciones manualmente, necesitamos poder ver todas las filas posibles. Límite de seguridad 10000.
        limit = min(10000, len(self.df))
        for index in range(limit):
            valores = [str(x).strip() if notna(x) else "" for x in self.df.iloc[index].values]
            tag = "evenrow" if index % 2 == 0 else "oddrow"
            self.tree.insert("", "end", values=["☐"] + valores, tags=(str(index), tag))

        self.lbl_status_rows.config(text=f"Total de registros: {len(self.df)} filas.")
        self._queue_copies_controls_refresh()

    def on_tree_checkbox_click(self, event):
        """Alterna la selección de una fila al hacer clic en su casilla de verificación."""
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return

        column_id = self.tree.identify_column(event.x)
        if column_id != "#1":  # La columna de checkbox siempre es la primera
            return

        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return

        self.tree.selection_toggle(row_id)
        return "break"  # Evita que el binding por defecto de Treeview colapse la multi-selección

    def _on_tree_motion(self, event):
        """Resalta suavemente la fila bajo el cursor para facilitar la lectura/selección."""
        row_id = self.tree.identify_row(event.y)
        if row_id == self._hover_item:
            return

        self._clear_hover()

        if row_id:
            tags = list(self.tree.item(row_id, "tags"))
            if "hoverrow" not in tags:
                tags.append("hoverrow")
                self.tree.item(row_id, tags=tags)
            self._hover_item = row_id

    def _on_tree_leave(self, event):
        self._clear_hover()

    def _clear_hover(self):
        prev = self._hover_item
        if prev and self.tree.exists(prev):
            tags = [t for t in self.tree.item(prev, "tags") if t != "hoverrow"]
            self.tree.item(prev, tags=tags)
        self._hover_item = None

    def toggle_select_all(self):
        """Marca/desmarca todas las filas visibles (checkbox del encabezado de la columna)."""
        all_items = self.tree.get_children()
        if not all_items:
            return

        if len(self.tree.selection()) == len(all_items):
            self.tree.selection_remove(all_items)
        else:
            self.tree.selection_set(all_items)

    def on_tree_row_selected(self, event):
        selected_set = set(self.tree.selection())

        # Refresca el glifo de checkbox de cada fila según su estado real de selección
        for item in self.tree.get_children():
            self.tree.set(item, self.CHECK_COL, "☑" if item in selected_set else "☐")

        all_items = self.tree.get_children()
        all_selected = bool(all_items) and len(selected_set) == len(all_items)
        self.tree.heading(self.CHECK_COL, text="☑" if all_selected else "☐")

        num_selected = len(selected_set)
        self.lbl_status_selection.config(text=f"Seleccionados: {num_selected} etiqueta(s)")
        self.generate_preview(row_index=self._get_selected_row_index())

    def _get_selected_row_index(self):
        selected = self.tree.selection()
        if selected:
            tags = self.tree.item(selected[0], "tags")
            if tags:
                return int(tags[0])
        return 0

    def on_double_click(self, event):
        # Aislar celda interactuada
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell": return
        
        row_id = self.tree.identify_row(event.y)
        column_id = self.tree.identify_column(event.x)
        if not row_id or not column_id: return

        if column_id == "#1":  # Columna de checkbox: no es editable como texto
            return

        # La columna #1 es el checkbox; las columnas de Excel empiezan en #2.
        col_index = int(column_id.replace("#", "")) - 2
        if self.df is None or not 0 <= col_index < len(self.df.columns):
            return

        real_col_name = self.df.columns[col_index]
        if self._is_copies_column(real_col_name):
            control = self._copies_controls.get(row_id)
            if control is not None and control.winfo_exists():
                control.focus_set()
            return

        if hasattr(self, 'entry_edit') and self.entry_edit.winfo_exists():
            self.entry_edit.destroy()
        
        # Geometría del bounding box (ancho/alto de la celda tocada)
        x, y, width, height = self.tree.bbox(row_id, column_id)
        current_value = self.tree.set(row_id, column_id)
        
        # 1. Insertamos caja texto temporal y absorbemos control
        self.entry_edit = ttk.Entry(self.tree, font=("Segoe UI", 8))
        self.entry_edit.place(x=x, y=y, width=width, height=height)
        self.entry_edit.insert(0, current_value)
        self.entry_edit.select_range(0, tk.END)
        self.entry_edit.focus()
        
        # 2. Reglas de Salida
        self.entry_edit.bind(
            "<Return>",
            lambda e: self.save_edit(row_id, column_id, col_index)
        )
        # Esc permite escapar si nos equivocamos de doble click
        self.entry_edit.bind("<Escape>", lambda e: self.entry_edit.destroy())

    def save_edit(self, row_id, column_id, col_index):
        if not hasattr(self, 'entry_edit') or not self.entry_edit.winfo_exists():
            return
            
        new_val = self.entry_edit.get().strip()
        self.entry_edit.destroy()
        
        # 1. Salvar FrontEnd GUI Visual
        self.tree.set(row_id, column_id, new_val)
        
        # 2. Salvar BackEnd MEMORIA Pandas
        tags = self.tree.item(row_id, "tags")
        if tags and self.df is not None:
            df_index = int(tags[0])
            real_col_name = self.df.columns[col_index]
            self.df.at[df_index, real_col_name] = new_val
            
            # 3. Auto Refrescar y Renderizar para que se note en pantalla grande
            selected_items = self.tree.selection()
            if selected_items and selected_items[0] == row_id:
                self.generate_preview(row_index=df_index)

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

    def _validate_copies_input(self, valor_propuesto):
        # Permite vacío (mientras se edita) o solo dígitos, hasta 3 cifras (máx 999)
        return valor_propuesto == "" or (valor_propuesto.isdigit() and len(valor_propuesto) <= 3)

    def _get_manual_copies(self):
        value = self.spin_copies.get().strip()
        if not value:
            return None
        if not value.isdigit() or not 1 <= int(value) <= 999:
            raise ValueError("El campo “Copias” debe estar vacío o contener un número entre 1 y 999.")
        return int(value)

    @staticmethod
    def _normalize_column_name(column):
        return re.sub(
            r"[^a-z0-9]",
            "",
            unicodedata.normalize("NFKD", str(column).strip().lower())
            .encode("ascii", "ignore")
            .decode("ascii"),
        )

    @classmethod
    def _is_copies_column(cls, column):
        normalized = cls._normalize_column_name(column)
        base_names = {
            "cantid", "cantidad", "copia", "copias", "cantidadcopias",
            "cantidaddecopias", "cantidcopias", "cantiddecopias",
            "numerocopias", "numerodecopias", "numcopias", "copies",
            "copy", "qtycopies",
        }
        if normalized in base_names:
            return True
        return any(
            normalized.startswith(base) and normalized[len(base):].isdigit()
            for base in ("cantidad", "cantid", "copia", "copias", "copies", "copy")
        )

    def _get_excel_copies_column(self):
        if self.df is None:
            return None

        columns = [
            column for column in self.df.columns
            if self._is_copies_column(column)
        ]
        if not columns:
            return None

        explicit_copies_column = next(
            (
                column for column in reversed(columns)
                if self._normalize_column_name(column).endswith("copias")
            ),
            None,
        )
        return explicit_copies_column or columns[-1]

    @staticmethod
    def _parse_excel_copies(value, record_number):
        if value is None or not str(value).strip():
            return None

        if isinstance(value, bool):
            parsed = None
        elif isinstance(value, int):
            parsed = value
        elif isinstance(value, float):
            parsed = int(value) if math.isfinite(value) and value.is_integer() else None
        else:
            text = str(value).strip()
            if re.fullmatch(r"\d+(?:\.0+)?", text):
                parsed = int(float(text))
            else:
                parsed = None

        if parsed is None or not 1 <= parsed <= 999:
            raise ValueError(
                f"La cantidad de copias del registro {record_number} debe ser un número entero entre 1 y 999."
            )
        return parsed

    def _render_preview_switch(self, knob_x=None):
        if not hasattr(self, 'preview_switch_canvas'):
            return

        is_on = self.preview_api_enabled.get()
        canvas = self.preview_switch_canvas
        canvas.delete("all")

        track_color = "#38A169" if is_on else "#4A5568"
        if knob_x is None:
            knob_x = 28 if is_on else 4

        knob_x = int(round(max(4, min(28, knob_x))))
        self._switch_knob_x = knob_x

        # Pista tipo pastilla (simulada con ovalos + rectangulo)
        canvas.create_oval(2, 2, 26, 26, fill=track_color, outline=track_color)
        canvas.create_rectangle(14, 2, 38, 26, fill=track_color, outline=track_color)
        canvas.create_oval(26, 2, 50, 26, fill=track_color, outline=track_color)

        # Perilla
        canvas.create_oval(knob_x, 4, knob_x + 20, 24, fill="#F7FAFC", outline="#E2E8F0")

        if hasattr(self, 'preview_switch_state'):
            self.preview_switch_state.config(
                text="ON" if is_on else "OFF",
                fg="#C6F6D5" if is_on else "#CBD5E0"
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
        self.on_preview_toggle(animated=True)

    def on_preview_toggle(self, animated=False):
        if animated:
            self._animate_preview_switch(self.preview_api_enabled.get())
        else:
            self._render_preview_switch()

        if self.preview_api_enabled.get():
            self.generate_preview(row_index=self._get_selected_row_index())
        else:
            self._current_preview_img = None
            self.preview_canvas.config(image='', text="Preview web desactivada. Activa el switch para usar Labelary.", fg="#5B6672")

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


    # =========================================================================
    # CORE: ENSAMBLADOR ZPL Y CONEXIÓN A LABELARY
    # =========================================================================

    def _get_series_value(self, row_series, col_name):
        val = row_series.get(col_name)
        if notna(val):
            if isinstance(val, datetime.datetime):
                if val.hour == 0 and val.minute == 0 and val.second == 0:
                    return val.strftime("%d/%m/%Y")
                return val.strftime("%d/%m/%Y %H:%M:%S")
            if isinstance(val, datetime.date):
                return val.strftime("%d/%m/%Y")
            return str(val).strip()
        return ""

    def _resolve_cantidad_auto(self, row_series):
        """Prioriza la columna de cantidad/unidad sin confundirla con la de copias."""
        if self.df is None:
            return ""

        copies_column = self._get_excel_copies_column()
        quantity_columns = [
            column for column in self.df.columns
            if self._is_copies_column(column) and column != copies_column
        ]
        for column in quantity_columns:
            value = self._get_series_value(row_series, column)
            if value:
                return value

        duplicate_quantity_headers = len(
            [column for column in self.df.columns if self._is_copies_column(column)]
        ) > 1
        for idx in (6, 4, 8):
            if idx < len(self.df.columns):
                column = self.df.columns[idx]
                if duplicate_quantity_headers and column == copies_column:
                    continue
                value = self._get_series_value(row_series, column)
                if value:
                    return value
        return ""

    def _resolve_placeholder_value(self, var_name, row_series, max_len=None):
        """Resuelve el valor de un placeholder PRN y soporta variantes tipo vlsCampo2A."""
        if var_name.strip().lower() == 'vlscantidadauto':
            return self._resolve_cantidad_auto(row_series)

        # 1) Mapeo directo (compatibilidad actual)
        if var_name in self.map_columnas:
            value = self._get_series_value(row_series, self.map_columnas[var_name])
        else:
            value = ""

        # 2) Fallback para campos posicionales con sufijo de segmento: vlsCampo2A, vlsCampo4C, etc.
        seg_match = re.match(r'(?i)^vlscampo(\d+)([a-z])$', var_name.strip())
        if seg_match:
            base_idx = int(seg_match.group(1)) - 1
            part_idx = ord(seg_match.group(2).upper()) - ord('A')

            if not value and self.df is not None and 0 <= base_idx < len(self.df.columns):
                base_col = self.df.columns[base_idx]
                value = self._get_series_value(row_series, base_col)

            if max_len and max_len > 0:
                chunks = textwrap.wrap(value, width=max_len, break_long_words=True, break_on_hyphens=False)
                return chunks[part_idx] if 0 <= part_idx < len(chunks) else ""

            return value

        # 3) Fallback para campos posicionales simples: vlsCampo1, vlsCampo2, etc.
        num_match = re.match(r'(?i)^vlscampo(\d+)$', var_name.strip())
        if not value and num_match and self.df is not None:
            base_idx = int(num_match.group(1)) - 1
            if 0 <= base_idx < len(self.df.columns):
                base_col = self.df.columns[base_idx]
                value = self._get_series_value(row_series, base_col)

        return value

    def compose_label(self, row_series=None):
        """Compone la etiqueta con ajuste automático al tamaño y resolución
        configurados. Sin fila (row_series=None) muestra los nombres de las
        variables para revisar posiciones. Devuelve un LayoutResult."""
        if not self.plantilla_zpl:
            return None

        if row_series is None:
            def resolver(var_name, max_len=None):
                return f"[{var_name}]"
        else:
            def resolver(var_name, max_len=None):
                return self._resolve_placeholder_value(var_name, row_series, max_len=max_len)

        target = self._current_target_size()
        width_mm, height_mm = target if target else (None, None)
        result = LL.compose(
            self.plantilla_zpl,
            self.combo_prn.get(),
            resolver,
            width_mm,
            height_mm,
            dpi=self._current_dpi(),
            settings=self.layout_settings,
            labeler=self._field_label,
            parsed=self.parsed_template,
        )

        # INYECTAR DESPLAZAMIENTOS CALIBRADOS (Sliders X/Y) a las coordenadas del código
        val_x = int(self.slider_x.get())
        val_y = int(self.slider_y.get())
        result.zpl = self._shift_zpl(result.zpl, val_x, val_y)
        return result

    def compose_zpl(self, row_series):
        """Compone la macro en base a la línea especificada de los datos de Excel."""
        result = self.compose_label(row_series)
        if result is None:
            return ""
        self.last_layout = result
        return result.zpl

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
            self._current_preview_img = None
            self.preview_canvas.config(image='', text="Preview web desactivada. Activa el switch para usar Labelary.", fg="#5B6672")
            return

        self._request_labelary(result.zpl, result.width_mm, result.height_mm, result.dpi)

    def _request_labelary(self, zpl, width_mm=None, height_mm=None, dpi=None):
        try:
            import requests
            self.preview_canvas.config(image='', text="Generando previsualización...", fg="#0D7AA0")
            self.update_idletasks() # Dibujarlo inmediatamente para no congelar app ciegamente

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

            url = f"http://api.labelary.com/v1/printers/{dpmm}dpmm/labels/{w_inches}x{h_inches}/0/"
            headers = {"Accept": "image/png"}

            res = requests.post(url, data=zpl_preview.encode('utf-8'), headers=headers, timeout=10)

            if res.status_code == 200:
                self._current_preview_img = Image.open(BytesIO(res.content))

                # Proyectar inicialmente sobre el espacio disponible del contenedor
                canvas_w = self.preview_canvas.winfo_width()
                canvas_h = self.preview_canvas.winfo_height()
                if canvas_w < 50: canvas_w = 700
                if canvas_h < 50: canvas_h = 400

                self._apply_resize(canvas_w, canvas_h)
            else:
                self._current_preview_img = None
                self.preview_canvas.config(image='', text=f"El servidor rechazó el código ZPL. (Error {res.status_code})", fg="#C53030")

        except Exception as e:
            self._current_preview_img = None
            self.preview_canvas.config(image='', text=f"Error en la conexión a la web:\n{str(e)[:50]}...", fg="#C53030")

    # =========================================================================
    # AJUSTE AUTOMÁTICO: TAMAÑO, RESOLUCIÓN Y CONFIGURACIÓN
    # =========================================================================

    _SIZE_AUTO_LABEL = "Según plantilla"
    _SIZE_CUSTOM_LABEL = "Personalizado…"

    def _load_app_config(self):
        try:
            with open(self.config_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_app_config(self):
        self.app_config["layout"] = self.layout_settings.to_dict()
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.app_config, f, ensure_ascii=False, indent=2)
        except OSError as error:
            if not getattr(self, "_config_warned", False):
                self._config_warned = True
                messagebox.showwarning(
                    "Configuración",
                    "No se pudo guardar la configuración junto al programa:\n"
                    f"{self.config_path}\n\n{error}\n\n"
                    "Los ajustes se usarán solo durante esta sesión.",
                    parent=self,
                )

    @staticmethod
    def _format_mm(value):
        return f"{float(value):g}"

    def _size_label(self, size):
        return f"{self._format_mm(size[0])} × {self._format_mm(size[1])} mm"

    def _custom_size(self):
        size = self.app_config.get("custom_size")
        try:
            w, h = float(size[0]), float(size[1])
            if w > 0 and h > 0:
                return (w, h)
        except (TypeError, ValueError, IndexError):
            pass
        return None

    def _refresh_size_options(self):
        options = [self._SIZE_AUTO_LABEL] + [self._size_label(s) for s in LL.LABEL_SIZES]
        custom = self._custom_size()
        options.append(f"Personalizado ({self._size_label(custom)})" if custom else self._SIZE_CUSTOM_LABEL)
        self.combo_size["values"] = options

        selected = self.app_config.get("size", "auto")
        if selected == "custom" and custom:
            self.combo_size.set(options[-1])
        elif isinstance(selected, (list, tuple)) and len(selected) == 2:
            label = self._size_label(selected)
            self.combo_size.set(label if label in options else self._SIZE_AUTO_LABEL)
        else:
            self.combo_size.set(self._SIZE_AUTO_LABEL)

    def _current_target_size(self):
        """Tamaño destino (ancho, alto) en mm, o None = el de la plantilla."""
        selected = self.app_config.get("size", "auto")
        if selected == "custom":
            return self._custom_size()
        if isinstance(selected, (list, tuple)) and len(selected) == 2:
            try:
                return (float(selected[0]), float(selected[1]))
            except (TypeError, ValueError):
                return None
        return None

    def _templates_for_current_size(self):
        target = self._current_target_size()
        if not target or not self.template_sizes:
            return list(self.all_templates)
        matching = LL.templates_for_size(target, self.template_sizes)
        return matching or list(self.all_templates)

    def on_size_selected(self, event=None):
        choice = self.combo_size.get()
        if choice == self._SIZE_AUTO_LABEL:
            self.app_config["size"] = "auto"
        elif choice.startswith("Personalizado"):
            if not self._custom_size():
                self.open_design_settings(focus_custom=True)
                if not self._custom_size():
                    self._refresh_size_options()
                    return
            self.app_config["size"] = "custom"
        else:
            numbers = re.findall(r"[\d.]+", choice)
            if len(numbers) >= 2:
                self.app_config["size"] = [float(numbers[0]), float(numbers[1])]
        self._save_app_config()
        self._apply_size_filter()

    def _apply_size_filter(self):
        """Muestra solo las plantillas asociadas al tamaño elegido."""
        values = self._templates_for_current_size()
        current = self.combo_prn.get()
        self.combo_prn["values"] = values
        if values and current not in values:
            self.combo_prn.set(values[0])
            self.on_prn_selected(None)
        else:
            self.generate_preview(row_index=self._get_selected_row_index())

    def _current_dpi(self):
        try:
            value = int(re.match(r"\d+", self.combo_dpi.get()).group(0))
            return value if value in LL.DPI_OPTIONS else LL.DPI_OPTIONS[0]
        except (AttributeError, ValueError):
            return LL.DPI_OPTIONS[0]

    def _sync_dpi_for_printer(self):
        printer = self.combo_printer.get()
        dpi = self.app_config.get("printer_dpi", {}).get(printer)
        if dpi not in LL.DPI_OPTIONS:
            # Sin dato guardado: deducirlo del nombre del driver ("ZD230-203dpi")
            match = re.search(r"(203|300|600)\s*dpi", printer or "", re.IGNORECASE)
            dpi = int(match.group(1)) if match else LL.DPI_OPTIONS[0]
        self.combo_dpi.set(f"{dpi} dpi")

    def on_printer_selected(self, event=None):
        self._sync_dpi_for_printer()
        self.generate_preview(row_index=self._get_selected_row_index())

    def on_dpi_selected(self, event=None):
        printer = self.combo_printer.get()
        self.app_config.setdefault("printer_dpi", {})[printer] = self._current_dpi()
        self._save_app_config()
        self.generate_preview(row_index=self._get_selected_row_index())

    def _field_label(self, var_name):
        """Nombre legible de una variable para las advertencias (cabecera del Excel)."""
        var_name = var_name or ""
        if var_name.strip().lower() == "vlscantidadauto":
            return "Cantidad"
        match = re.match(r"(?i)^vlscampo(\d+)", var_name.strip())
        if match and self.df is not None:
            idx = int(match.group(1)) - 1
            if 0 <= idx < len(self.df.columns):
                return str(self.df.columns[idx])
        return var_name

    def _update_layout_status(self, result):
        if result is None:
            self.lbl_layout_status.config(text="", fg=self.fg_muted)
            return
        size = f"{self._size_label((result.width_mm, result.height_mm))} · {result.dpi} dpi"
        if result.warnings:
            first = result.warnings[0]
            extra = f" (+{len(result.warnings) - 1} más)" if len(result.warnings) > 1 else ""
            text = f"⚠ {size} — {first}{extra}  · Clic para ver el detalle"
            color = "#F6AD55"
        elif result.mode == "original":
            text = f"✔ {size} — Plantilla original: el contenido cabe sin ajustes."
            color = "#68D391"
        elif result.mode == "adaptado":
            text = f"✔ {size} — Composición adaptada al área útil.  · Clic para ver el detalle"
            color = self.accent_blue
        else:
            text = f"⚠ {size} — Sin ajuste automático (plantilla no analizable)."
            color = "#F6AD55"
        self.lbl_layout_status.config(text=text, fg=color)

    def show_layout_details(self, event=None):
        result = self.last_layout
        if result is None:
            return
        s = self.layout_settings
        dpmm = LL.dots_per_mm(result.dpi)
        safe_w = result.width_mm - 2 * s.margin_mm
        safe_h = result.height_mm - 2 * s.margin_mm
        lines = [
            f"Etiqueta: {self._size_label((result.width_mm, result.height_mm))} "
            f"({LL.orientation_of(result.width_mm, result.height_mm)})",
            f"Resolución: {result.dpi} dpi ({dpmm:g} puntos/mm) → "
            f"{round(result.width_mm * dpmm)} × {round(result.height_mm * dpmm)} puntos",
            f"Área útil: {self._format_mm(round(safe_w, 2))} × {self._format_mm(round(safe_h, 2))} mm "
            f"(margen de {self._format_mm(s.margin_mm)} mm)",
            "Modo: " + {"original": "plantilla original (sin cambios)",
                        "adaptado": "composición adaptada",
                        }.get(result.mode, "sin ajuste automático"),
        ]
        if result.warnings:
            lines.append("")
            lines.append("ADVERTENCIAS (contenido que no cabe con los mínimos configurados):")
            lines += [f"  • {w}" for w in result.warnings]
        if result.notes:
            lines.append("")
            lines.append("Ajustes aplicados:")
            lines += [f"  • {n}" for n in result.notes[:12]]
            if len(result.notes) > 12:
                lines.append(f"  … y {len(result.notes) - 12} más")
        show = messagebox.showwarning if result.warnings else messagebox.showinfo
        show("Detalle del ajuste automático", "\n".join(lines), parent=self)

    def open_design_settings(self, focus_custom=False):
        """Diálogo para configurar márgenes, mínimos y tamaño personalizado."""
        dlg = tk.Toplevel(self)
        dlg.title("Ajustes de diseño")
        dlg.configure(bg=self.card_color)
        dlg.transient(self)
        dlg.resizable(False, False)

        s = self.layout_settings
        custom = self._custom_size() or (100, 50)
        fields = [
            ("margin_mm", "Margen de seguridad (mm)", s.margin_mm, 0, 15),
            ("gap_mm", "Separación mínima entre elementos (mm)", s.gap_mm, 0, 10),
            ("min_text_mm", "Altura mínima de texto (mm)", s.min_text_mm, 0.5, 20),
            ("min_qr_module_mm", "Módulo mínimo del QR (mm)", s.min_qr_module_mm, 0.1, 3),
            ("qr_quiet_modules", "Zona libre alrededor del QR (módulos)", s.qr_quiet_modules, 0, 10),
            ("min_barcode_module_mm", "Módulo mínimo del código de barras (mm)", s.min_barcode_module_mm, 0.1, 3),
            ("custom_w", "Tamaño personalizado: ancho (mm)", custom[0], 10, 380),
            ("custom_h", "Tamaño personalizado: alto (mm)", custom[1], 10, 380),
        ]

        body = tk.Frame(dlg, bg=self.card_color, padx=18, pady=14)
        body.pack(fill="both", expand=True)
        tk.Label(
            body, text="Ajuste automático de etiquetas", bg=self.card_color, fg=self.fg_color,
            font=("Segoe UI", 11, "bold")
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        tk.Label(
            body,
            text="Las medidas se convierten a puntos según la resolución de la impresora\n"
                 "(203 dpi = 8 puntos/mm · 300 dpi = 12 puntos/mm).",
            bg=self.card_color, fg=self.fg_muted, font=("Segoe UI", 9), justify="left"
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))

        entries = {}
        for i, (key, label, value, _, _) in enumerate(fields, start=2):
            tk.Label(body, text=label, bg=self.card_color, fg=self.fg_color,
                     font=("Segoe UI", 9)).grid(row=i, column=0, sticky="w", pady=3)
            entry = tk.Entry(
                body, width=10, justify="right", bg=self.bg_color, fg=self.fg_color,
                insertbackground=self.fg_color, relief="flat", highlightthickness=1,
                highlightbackground=self.border_color, highlightcolor=self.accent_blue,
                font=("Segoe UI", 9)
            )
            entry.insert(0, self._format_mm(value))
            entry.grid(row=i, column=1, sticky="e", padx=(12, 0), pady=3, ipady=3)
            entries[key] = entry

        result = {"saved": False}

        def save():
            values = {}
            for key, label, _, low, high in fields:
                raw = entries[key].get().strip().replace(",", ".")
                try:
                    number = float(raw)
                except ValueError:
                    messagebox.showerror("Ajustes de diseño", f"«{label}» debe ser un número.", parent=dlg)
                    entries[key].focus_set()
                    return
                if not low <= number <= high:
                    messagebox.showerror(
                        "Ajustes de diseño",
                        f"«{label}» debe estar entre {self._format_mm(low)} y {self._format_mm(high)}.",
                        parent=dlg,
                    )
                    entries[key].focus_set()
                    return
                values[key] = number
            values["qr_quiet_modules"] = int(round(values["qr_quiet_modules"]))
            self.layout_settings = LL.LayoutSettings.from_dict(values)
            self.app_config["custom_size"] = [values["custom_w"], values["custom_h"]]
            self._save_app_config()
            result["saved"] = True
            dlg.destroy()

        def restore_defaults():
            defaults = LL.LayoutSettings()
            for key, *_ in fields:
                if hasattr(defaults, key):
                    entries[key].delete(0, "end")
                    entries[key].insert(0, self._format_mm(getattr(defaults, key)))

        buttons = tk.Frame(body, bg=self.card_color)
        buttons.grid(row=len(fields) + 2, column=0, columnspan=2, sticky="e", pady=(14, 0))
        self._create_hover_button(buttons, "Valores por defecto", None, self.accent_gray,
                                  self.accent_gray_hover, restore_defaults).pack(side="left")
        self._create_hover_button(buttons, "Cancelar", None, self.accent_gray,
                                  self.accent_gray_hover, dlg.destroy).pack(side="left", padx=(6, 0))
        self._create_hover_button(buttons, "Guardar", None, self.grad_print[0],
                                  self.grad_print[1], save).pack(side="left", padx=(6, 0))

        dlg.bind("<Return>", lambda e: save())
        dlg.bind("<Escape>", lambda e: dlg.destroy())
        dlg.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - dlg.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - dlg.winfo_height()) // 3
        dlg.geometry(f"+{max(0, x)}+{max(0, y)}")
        (entries["custom_w"] if focus_custom else entries["margin_mm"]).focus_set()
        dlg.grab_set()
        self.wait_window(dlg)

        if result["saved"]:
            self._refresh_size_options()
            self._apply_size_filter()

    # =========================================================================
    # IMPRESIÓN MASIVA
    # =========================================================================

    def _show_printer_error(self, error):
        messagebox.showerror(
            "Error Físico",
            f"Falla conectando con el driver Windows Zebra:\n{error}",
            parent=self
        )

    def calibrate_printer(self):
        printer_name = self.combo_printer.get()
        if not printer_name:
            messagebox.showwarning("Calibrar", "Selecciona una impresora válida de la lista.")
            return

        respuesta = messagebox.askyesno("Calibrar Impresora", f"¿Estás seguro de enviar el comando de calibración a la impresora '{printer_name}'?")
        if not respuesta: return

        try:
            hPrinter = win32print.OpenPrinter(printer_name)
            try:
                win32print.StartDocPrinter(hPrinter, 1, ("Calibracion_Zebra", None, "RAW"))
                win32print.StartPagePrinter(hPrinter)
                
                # Comando ZPL para calibrar la etiqueta
                win32print.WritePrinter(hPrinter, b"~JC")
                
                win32print.EndPagePrinter(hPrinter)
                win32print.EndDocPrinter(hPrinter)
            finally:
                win32print.ClosePrinter(hPrinter)
                
            messagebox.showinfo("Calibración", "Comando de calibración (~JC) enviado exitosamente a la impresora.")
            
        except Exception as e:
            self._show_printer_error(e)

    def print_labels(self):
        printer_name = self.combo_printer.get()
        if not printer_name:
            messagebox.showwarning("Imprimir", "Selecciona una impresora válida de la lista.")
            return
            
        if self.df is None or self.df.empty:
            messagebox.showwarning("Imprimir", "Aún no has cargado un set de datos de Excel o está vacío.")
            return

        # Filtrar solo elementos seleccionados por el usuario en la tabla
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("Imprimir", "No hay renglones seleccionados.\n\nPor favor, da clic en los renglones de la tabla que deseas mandar a imprimir.")
            return

        try:
            manual_copies = self._get_manual_copies()
            excel_copies_column = self._get_excel_copies_column()
            print_plan = []
            source_totals = {}

            for item in selected_items:
                tags = self.tree.item(item, "tags")
                if not tags:
                    raise ValueError("No se pudo identificar una de las filas seleccionadas.")

                try:
                    row_index = int(tags[0])
                    row = self.df.iloc[row_index]
                except (ValueError, IndexError):
                    raise ValueError("No se pudo leer una de las filas seleccionadas del Excel.")

                if manual_copies is not None:
                    copies = manual_copies
                    source = "Campo Copias"
                elif excel_copies_column is not None:
                    copies = self._parse_excel_copies(
                        row.get(excel_copies_column),
                        row_index + 1
                    )
                    if copies is None:
                        copies = 1
                        source = "Valor por defecto (1)"
                    else:
                        source = "Excel"
                else:
                    copies = 1
                    source = "Valor por defecto (1)"

                print_plan.append((row, copies, row_index))
                totals = source_totals.setdefault(source, [0, 0])
                totals[0] += 1
                totals[1] += copies

            total_etiquetas = sum(copies for _, copies, _ in print_plan)
        except ValueError as e:
            messagebox.showerror("Cantidad de copias inválida", str(e), parent=self)
            return

        # Componer cada etiqueta con el ajuste automático y reunir advertencias
        composed = []
        rows_with_warnings = []
        layout_size = None
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            for row, copies, row_index in print_plan:
                result = self.compose_label(row)
                composed.append((result.zpl, copies))
                layout_size = (result.width_mm, result.height_mm)
                if result.warnings:
                    rows_with_warnings.append((row_index + 1, result.warnings))
        finally:
            self.config(cursor="")

        if rows_with_warnings:
            detail = []
            for row_number, warnings in rows_with_warnings[:8]:
                detail.append(f"• Fila {row_number}: {warnings[0]}"
                              + (f" (+{len(warnings) - 1} más)" if len(warnings) > 1 else ""))
            if len(rows_with_warnings) > 8:
                detail.append(f"• … y {len(rows_with_warnings) - 8} fila(s) más.")
            imprimir = messagebox.askyesno(
                "Contenido que no cabe",
                f"{len(rows_with_warnings)} de {len(print_plan)} etiqueta(s) no caben respetando "
                "los márgenes y tamaños mínimos configurados:\n\n"
                + "\n".join(detail)
                + "\n\nSi continúas, esas etiquetas se imprimirán con el texto al tamaño mínimo "
                "y podrían quedar ilegibles o con elementos superpuestos.\n\n"
                "¿Deseas imprimirlas de todas formas?",
                icon="warning",
                parent=self,
            )
            if not imprimir:
                return

        summary_lines = [
            f"Líneas seleccionadas: {len(print_plan)}",
            f"Total de copias a imprimir: {total_etiquetas}",
            "Origen de la cantidad:",
        ]
        for source in ("Campo Copias", "Excel", "Valor por defecto (1)"):
            if source in source_totals:
                lines, copies = source_totals[source]
                summary_lines.append(f"  • {source}: {lines} línea(s), {copies} copia(s)")
        summary_lines.append(f"Impresora: {printer_name} ({self._current_dpi()} dpi)")
        if layout_size and all(layout_size):
            summary_lines.append(f"Tamaño de etiqueta: {self._size_label(layout_size)}")
        summary_lines.append("\n¿Deseas continuar?")

        respuesta = messagebox.askyesno("Resumen de impresión", "\n".join(summary_lines), parent=self)
        if not respuesta: return

        try:
            hPrinter = win32print.OpenPrinter(printer_name)
            try:
                win32print.StartDocPrinter(hPrinter, 1, ("Impresion_Etiquetas_PRN", None, "RAW"))
                win32print.StartPagePrinter(hPrinter)

                # Iterar todas las filas marcadas con su cantidad de copias efectiva.
                for zpl, copies in composed:
                    zpl_bytes = zpl.encode("utf-8")
                    for _ in range(copies):
                        win32print.WritePrinter(hPrinter, zpl_bytes)

                win32print.EndPagePrinter(hPrinter)
                win32print.EndDocPrinter(hPrinter)
            finally:
                win32print.ClosePrinter(hPrinter)

            messagebox.showinfo("Proceso Completo", f"¡Se generaron y enviaron {total_etiquetas} comandos ZPL de forma exitosa hacia la impresora!")
            
        except Exception as e:
            self._show_printer_error(e)


if __name__ == "__main__":
    app = ZebraPrintApp()
    app.mainloop()