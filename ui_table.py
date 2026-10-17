"""Tabla de registros del Excel: llenado, selección, edición y copias por fila.

Mixin de ZebraPrintApp (app.py): usa sus atributos y métodos vía self."""

import math
import tkinter as tk
from tkinter import ttk
from excel_reader import notna


class TableMixin:
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
