import os
import sys
import re
import textwrap
import datetime
import win32print
import label_layout as LL
from excel_reader import notna, read_excel_light
import theme as THEME
from ui_widgets import WidgetsMixin
from ui_table import TableMixin
from ui_preview import PreviewMixin
from ui_printing import PrintingMixin
from ui_layout import LayoutMixin
from app_paths import app_dir, resource_path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
import ctypes
import queue
import threading


# Habilitar soporte DPI para evitar textos borrosos (pixelados) en monitores modernos
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

class ZebraPrintApp(WidgetsMixin, TableMixin, PreviewMixin, PrintingMixin, LayoutMixin, tk.Tk):
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
        
        # Directorio base (externo si es ejecutable compilado)
        base_dir = app_dir()
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
        background_path = resource_path("assets", "tech-background.png")
        if os.path.isfile(background_path):
            with Image.open(background_path) as background_image:
                self._background_source_image = background_image.convert("RGB")
        self._background_photo = None
        # Trabajo en segundo plano (vista previa web, impresión): los hilos dejan el
        # resultado en esta cola y el hilo de Tk lo recoge con after().
        self._async_results = queue.Queue()
        self._async_pending = 0
        self._async_polling = False
        self._preview_seq = 0      # descarta vistas previas que llegan tarde
        self._printing = False
        self._preview_timer = None # Control para slider en vivo
        self._current_preview_img = None # Guarda la imagen alta calidad descargada
        self._resize_timer = None # Control para diseño responsive
        # Control ON/OFF de previsualización web (envía la etiqueta a Labelary); se recuerda entre sesiones
        self.preview_api_enabled = tk.BooleanVar(value=bool(self.app_config.get("preview_web", True)))
        self._switch_anim_timer = None # Timer para animar el interruptor
        self._switch_knob_x = 4 # Posicion inicial de perilla (OFF)
        
        # Construir Interfaz y Estilos
        self._setup_styles()
        self.configure(bg=self.bg_color)
        
        # Configurar icono de la aplicación
        try:
            icon_path = resource_path("icons", "icon1.png")
            if os.path.exists(icon_path):
                icon_img = ImageTk.PhotoImage(Image.open(icon_path))
                self.iconphoto(False, icon_img)
            else:
                self.iconphoto(False, tk.PhotoImage(width=1, height=1))
        except Exception as e:
            print("No se pudo cargar el icono configurado:", e)

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._load_local_data()

    def _setup_styles(self):
        """Aplica el tema elegido en Ajustes de diseño (ver theme.py)."""
        self.style = ttk.Style(self)
        THEME.apply_theme(self, THEME.get_theme(self.app_config.get("theme")))

    def _run_async(self, work, on_done):
        """Ejecuta work() en un hilo y después on_done(resultado, error) en el hilo
        de Tk, para que la ventana no se congele con la red o la impresora."""
        def runner():
            try:
                outcome = (work(), None)
            except Exception as error:  # se informa en on_done
                outcome = (None, error)
            self._async_results.put((on_done, outcome))

        self._async_pending += 1
        threading.Thread(target=runner, daemon=True).start()
        if not self._async_polling:
            self._async_polling = True
            self.after(40, self._poll_async)

    def _poll_async(self):
        while True:
            try:
                on_done, (result, error) = self._async_results.get_nowait()
            except queue.Empty:
                break
            self._async_pending -= 1
            try:
                on_done(result, error)
            except tk.TclError:
                pass  # la ventana se cerró mientras tanto
        if self._async_pending > 0:
            self.after(40, self._poll_async)
        else:
            self._async_polling = False

    def _on_close(self):
        if self._printing and not messagebox.askyesno(
            "Impresión en curso",
            "Todavía se están enviando etiquetas a la impresora.\n\n"
            "Si cierras ahora, el trabajo puede quedar incompleto. ¿Cerrar de todas formas?",
            icon="warning", default="no", parent=self,
        ):
            return
        self.destroy()

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

        # Iconos de los botones (icons8, guardados en icons/)
        self.icon_excel = self._load_icon("excel_btn.png")
        self.icon_print = self._load_icon("print_btn.png")
        self.icon_calib = self._load_icon("gear_btn.png")
        self.icon_reset = self._load_icon("reset_btn.png")
        
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
            *self.grad_design,
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
            fg=self.preview_text,
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


if __name__ == "__main__":
    app = ZebraPrintApp()
    app.mainloop()