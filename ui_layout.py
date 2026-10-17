"""Ajuste automático: configuración, tamaño, resolución, estado y diálogo de ajustes.

Mixin de ZebraPrintApp (app.py): usa sus atributos y métodos vía self."""

import re
import json
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
import label_layout as LL
import theme as THEME


class LayoutMixin:
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
            color = self.status_warn
        elif result.mode == "original":
            text = f"✔ {size} — Plantilla original: el contenido cabe sin ajustes."
            color = self.status_ok
        elif result.mode == "adaptado":
            text = f"✔ {size} — Composición adaptada al área útil.  · Clic para ver el detalle"
            color = self.accent_blue
        else:
            text = f"⚠ {size} — Sin ajuste automático (plantilla no analizable)."
            color = self.status_warn
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

        # Tema visual (se aplica al volver a abrir la app)
        theme_keys = list(THEME.THEMES)
        theme_names = [THEME.THEMES[k].name for k in theme_keys]
        current_theme = self.app_config.get("theme", THEME.DEFAULT_THEME)
        theme_row = len(fields) + 2
        tk.Label(body, text="Tema de la interfaz", bg=self.card_color, fg=self.fg_color,
                 font=("Segoe UI", 9)).grid(row=theme_row, column=0, sticky="w", pady=(10, 3))
        combo_theme = ttk.Combobox(body, values=theme_names, state="readonly", width=16)
        combo_theme.set(THEME.get_theme(current_theme).name)
        combo_theme.grid(row=theme_row, column=1, sticky="e", padx=(12, 0), pady=(10, 3))

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
            new_theme = theme_keys[theme_names.index(combo_theme.get())]
            active_theme = current_theme if current_theme in THEME.THEMES else THEME.DEFAULT_THEME
            theme_changed = new_theme != active_theme
            self.app_config["theme"] = new_theme
            self._save_app_config()
            result["saved"] = True
            dlg.destroy()
            if theme_changed:
                messagebox.showinfo(
                    "Tema de la interfaz",
                    f"El tema «{THEME.THEMES[new_theme].name}» se aplicará la próxima vez "
                    "que abras SIBO PRINT.",
                    parent=self,
                )

        def restore_defaults():
            defaults = LL.LayoutSettings()
            for key, *_ in fields:
                if hasattr(defaults, key):
                    entries[key].delete(0, "end")
                    entries[key].insert(0, self._format_mm(getattr(defaults, key)))

        buttons = tk.Frame(body, bg=self.card_color)
        buttons.grid(row=len(fields) + 3, column=0, columnspan=2, sticky="e", pady=(14, 0))
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
