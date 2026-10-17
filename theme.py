"""Temas visuales de SIBO PRINT.

Cada tema es una paleta con nombre (`Theme`). La interfaz no usa colores
escritos a mano: los toma del tema activo, que se elige en "Ajustes de diseño"
y se guarda en sibo_print_config.json (`theme`). Se aplica al abrir la app.
"""

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class Theme:
    name: str
    # Superficies y texto
    bg_color: str
    card_color: str
    border_color: str
    fg_color: str
    fg_muted: str
    row_even: str
    row_odd: str
    row_hover: str
    selected_fg: str             # texto de la fila seleccionada (sobre accent_blue)
    scrollbar_thumb: str
    # Acentos y botones (degradado inicio -> fin; el texto va en button_fg)
    accent_blue: str
    accent_blue_hover: str
    grad_excel: tuple
    grad_calibrate: tuple
    grad_print: tuple
    grad_reset: tuple
    grad_design: tuple
    button_fg: str
    # Vista previa (el "papel" de la etiqueta siempre es claro)
    preview_bg: str
    preview_text: str
    preview_info: str
    preview_error: str
    # Interruptor de vista previa web
    switch_on: str
    switch_off: str
    switch_knob: str
    switch_knob_outline: str
    switch_text_on: str
    switch_text_off: str
    # Estado del ajuste automático
    status_ok: str
    status_warn: str
    # Fondo de la ventana
    bg_image: bool               # usar assets/tech-background.png
    bg_overlay: str
    bg_overlay_alpha: float
    bg_top: str
    bg_bottom: str
    bg_decor: bool               # anillos y red de puntos
    bg_ring_a: str
    bg_ring_b: str
    bg_line: str
    bg_dot: str


THEMES = {
    # Paleta original: azul marino con acentos cian.
    "marino": Theme(
        name="Marino",
        bg_color="#071827", card_color="#10283A", border_color="#29475B",
        fg_color="#E8F1F6", fg_muted="#A8BBC7",
        row_even="#10283A", row_odd="#142F42", row_hover="#1B4054",
        selected_fg="#FFFFFF", scrollbar_thumb="#B8C8CD",
        accent_blue="#38B9E8", accent_blue_hover="#59C8EF",
        grad_excel=("#16A878", "#0F9D91"), grad_calibrate=("#E89135", "#D97706"),
        grad_print=("#0F9D91", "#087F8C"), grad_reset=("#73828B", "#596A73"),
        grad_design=("#2F8FBF", "#1F6E99"), button_fg="#FFFFFF",
        preview_bg="#DCE7ED", preview_text="#5B6672", preview_info="#0D7AA0",
        preview_error="#C53030",
        switch_on="#38A169", switch_off="#4A5568", switch_knob="#F7FAFC",
        switch_knob_outline="#E2E8F0", switch_text_on="#C6F6D5", switch_text_off="#CBD5E0",
        status_ok="#68D391", status_warn="#F6AD55",
        bg_image=True, bg_overlay="#061523", bg_overlay_alpha=0.46,
        bg_top="#061523", bg_bottom="#0B2233", bg_decor=True,
        bg_ring_a="#102B3D", bg_ring_b="#0E293A", bg_line="#123044", bg_dot="#1D5267",
    ),
    # Claro, para naves con mucha luz o pantallas con reflejo.
    "claro": Theme(
        name="Claro de bodega",
        bg_color="#EEF2F5", card_color="#FFFFFF", border_color="#C9D3DB",
        fg_color="#14212B", fg_muted="#55646F",
        row_even="#FFFFFF", row_odd="#F3F6F8", row_hover="#E0EEF3",
        selected_fg="#FFFFFF", scrollbar_thumb="#A9B6BF",
        accent_blue="#0F7C8C", accent_blue_hover="#13919F",
        grad_excel=("#13805C", "#0E6F50"), grad_calibrate=("#C26A0A", "#A85A08"),
        grad_print=("#0F7C8C", "#0B6672"), grad_reset=("#5F6E77", "#4D5B63"),
        grad_design=("#246F9A", "#1C5A7E"), button_fg="#FFFFFF",
        preview_bg="#E3E9ED", preview_text="#55646F", preview_info="#0B6672",
        preview_error="#B42318",
        switch_on="#1E8E4E", switch_off="#9AA7B0", switch_knob="#FFFFFF",
        switch_knob_outline="#C9D3DB", switch_text_on="#1E7A46", switch_text_off="#55646F",
        status_ok="#1E7A46", status_warn="#A85A08",
        bg_image=False, bg_overlay="#EEF2F5", bg_overlay_alpha=0.0,
        bg_top="#F4F7F9", bg_bottom="#E3EAEF", bg_decor=True,
        bg_ring_a="#E3E9EE", bg_ring_b="#E7EDF1", bg_line="#DAE2E8", bg_dot="#BCCAD4",
    ),
    # Máxima legibilidad: negro, blanco y amarillo.
    "contraste": Theme(
        name="Alto contraste",
        bg_color="#000000", card_color="#0D0D0D", border_color="#BFBFBF",
        fg_color="#FFFFFF", fg_muted="#E0E0E0",
        row_even="#0D0D0D", row_odd="#1A1A1A", row_hover="#333300",
        selected_fg="#000000", scrollbar_thumb="#FFFFFF",
        accent_blue="#FFD400", accent_blue_hover="#FFE45C",
        grad_excel=("#006B3C", "#005A32"), grad_calibrate=("#A34700", "#8A3B00"),
        grad_print=("#00507A", "#004266"), grad_reset=("#3A3A3A", "#2A2A2A"),
        grad_design=("#1F4E99", "#173D78"), button_fg="#FFFFFF",
        preview_bg="#FFFFFF", preview_text="#333333", preview_info="#00507A",
        preview_error="#B00020",
        switch_on="#00A651", switch_off="#666666", switch_knob="#FFFFFF",
        switch_knob_outline="#FFFFFF", switch_text_on="#7CFF9B", switch_text_off="#FFFFFF",
        status_ok="#7CFF9B", status_warn="#FFB000",
        bg_image=False, bg_overlay="#000000", bg_overlay_alpha=0.0,
        bg_top="#000000", bg_bottom="#000000", bg_decor=False,
        bg_ring_a="#000000", bg_ring_b="#000000", bg_line="#000000", bg_dot="#000000",
    ),
    # Oscuro neutro, más sobrio que Marino.
    "grafito": Theme(
        name="Grafito",
        bg_color="#1C1F23", card_color="#262A30", border_color="#3A4048",
        fg_color="#E6E8EB", fg_muted="#A7ADB5",
        row_even="#262A30", row_odd="#2B3036", row_hover="#343A42",
        selected_fg="#0E1A14", scrollbar_thumb="#8A929B",
        accent_blue="#4CC38A", accent_blue_hover="#63D29C",
        grad_excel=("#2E8B5E", "#26774F"), grad_calibrate=("#B8661A", "#9E5614"),
        grad_print=("#2F7A62", "#256650"), grad_reset=("#5A616A", "#4A5058"),
        grad_design=("#3A6F99", "#2F5C80"), button_fg="#FFFFFF",
        preview_bg="#D9DDE1", preview_text="#4A5058", preview_info="#256650",
        preview_error="#B42318",
        switch_on="#2E8B5E", switch_off="#4A5058", switch_knob="#F2F4F6",
        switch_knob_outline="#D0D4D9", switch_text_on="#9BE3BE", switch_text_off="#C4C9CF",
        status_ok="#7DD8A8", status_warn="#F2B266",
        bg_image=False, bg_overlay="#1C1F23", bg_overlay_alpha=0.0,
        bg_top="#1A1D21", bg_bottom="#22262B", bg_decor=True,
        bg_ring_a="#22262B", bg_ring_b="#24282D", bg_line="#2A2F35", bg_dot="#3A4048",
    ),
}

DEFAULT_THEME = "marino"


def get_theme(key):
    return THEMES.get(key) or THEMES[DEFAULT_THEME]


def apply_theme(app, theme):
    """Copia la paleta en la app (self.bg_color, self.card_color…) y configura
    los estilos ttk. Los nombres de atributo son los que ya usa la interfaz."""
    app.theme = theme
    for f in fields(theme):
        setattr(app, f.name, getattr(theme, f.name))
    # Compatibilidad: alias usados como pares (inicio, hover) en otras partes del código
    app.accent_green, app.accent_green_hover = theme.grad_excel
    app.accent_amber, app.accent_amber_hover = theme.grad_calibrate
    app.accent_gray, app.accent_gray_hover = theme.grad_reset
    _configure_styles(app.style, theme)


def _configure_styles(style, t):
    try:
        style.theme_use("clam")
    except Exception:
        pass

    # Configuración básica de elementos ttk
    style.configure("TFrame", background=t.bg_color)
    style.configure("Panel.TFrame", background=t.card_color)

    style.configure("TLabel", background=t.bg_color, foreground=t.fg_color, font=("Segoe UI", 9))
    style.configure("Panel.TLabel", background=t.card_color, foreground=t.fg_color, font=("Segoe UI", 9))
    style.configure("Header.TLabel", background=t.card_color, foreground=t.fg_color, font=("Segoe UI", 10, "bold"))
    style.configure("Muted.TLabel", background=t.card_color, foreground=t.fg_muted, font=("Segoe UI", 9))

    # Comboboxes estilizados
    style.map('TCombobox',
        fieldbackground=[('readonly', t.card_color)],
        background=[('readonly', t.card_color)],
        foreground=[('readonly', t.fg_color)]
    )
    style.configure('TCombobox',
        fieldbackground=t.card_color,
        background=t.border_color,
        foreground=t.fg_color,
        bordercolor=t.border_color,
        lightcolor=t.border_color,
        darkcolor=t.border_color,
        arrowcolor=t.fg_color,
        padding=6,
        insertcolor=t.fg_color,
        font=("Segoe UI", 9)
    )

    # Treeview de datos
    style.configure("Treeview",
        background=t.card_color,
        foreground=t.fg_color,
        fieldbackground=t.card_color,
        borderwidth=0,
        rowheight=34,
        font=("Segoe UI", 9)
    )
    style.configure("Treeview.Heading",
        background=t.card_color,
        foreground=t.fg_color,
        font=("Segoe UI", 9, "bold"),
        borderwidth=0,
        padding=(10, 9),
        relief="flat"
    )
    style.map("Treeview.Heading",
        background=[("active", t.border_color)],
        foreground=[("active", t.fg_color)]
    )
    style.map("Treeview",
        background=[("selected", t.accent_blue)],
        foreground=[("selected", t.selected_fg)]
    )

    # Sliders
    style.configure("TScale",
        background=t.card_color,
        troughcolor=t.bg_color,
        sliderlength=18,
        sliderthickness=12
    )

    # Scrollbars delgadas y sin flechas
    for orient, sticky in (("Vertical", "ns"), ("Horizontal", "we")):
        name = f"Dark.{orient}.TScrollbar"
        style.layout(name,
            [(f'{orient}.Scrollbar.trough', {'children':
                [(f'{orient}.Scrollbar.thumb', {'expand': '1', 'sticky': 'nswe'})],
            'sticky': sticky})])
        style.configure(name,
            troughcolor=t.bg_color,
            background=t.scrollbar_thumb,
            bordercolor=t.bg_color,
            lightcolor=t.bg_color,
            darkcolor=t.bg_color,
            arrowsize=0,
            width=10
        )
