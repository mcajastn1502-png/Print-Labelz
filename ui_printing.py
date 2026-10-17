"""Impresión: cantidad de copias, resumen, envío RAW en segundo plano y calibración.

Mixin de ZebraPrintApp (app.py): usa sus atributos y métodos vía self."""

import re
import math
import unicodedata
import win32print
from tkinter import messagebox
import label_layout as LL


class PrintingMixin:
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

        if self._printer_busy():
            return

        respuesta = messagebox.askyesno("Calibrar Impresora", f"¿Estás seguro de enviar el comando de calibración a la impresora '{printer_name}'?")
        if not respuesta: return

        # Comando ZPL para calibrar la etiqueta
        self._send_raw_async(
            printer_name, "Calibracion_Zebra", [b"~JC"],
            lambda: messagebox.showinfo(
                "Calibración",
                "Comando de calibración (~JC) enviado exitosamente a la impresora.",
                parent=self,
            ),
        )

    # A partir de este total el resumen avisa y propone "No" por defecto.
    _TOTAL_COPIAS_AVISO = 300

    def print_labels(self):
        printer_name = self.combo_printer.get()
        if not printer_name:
            messagebox.showwarning("Imprimir", "Selecciona una impresora válida de la lista.")
            return

        if self._printer_busy():
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
        trabajo_grande = total_etiquetas > self._TOTAL_COPIAS_AVISO
        if trabajo_grande:
            summary_lines.append(
                f"\n⚠ Trabajo grande: {total_etiquetas} etiquetas. "
                "Revisa las cantidades antes de continuar."
            )
        summary_lines.append("\n¿Deseas continuar?")

        respuesta = messagebox.askyesno(
            "Resumen de impresión",
            "\n".join(summary_lines),
            icon="warning" if trabajo_grande else "question",
            default="no" if trabajo_grande else "yes",
            parent=self,
        )
        if not respuesta: return

        # Una etiqueta por fila; la impresora repite las copias con ^PQ.
        chunks = [LL.set_print_quantity(zpl, copies).encode("utf-8") for zpl, copies in composed]
        self._send_raw_async(
            printer_name, "Impresion_Etiquetas_PRN", chunks,
            lambda: messagebox.showinfo(
                "Proceso Completo",
                f"¡Se enviaron {total_etiquetas} etiqueta(s) a la impresora '{printer_name}'!",
                parent=self,
            ),
        )

    def _printer_busy(self):
        if self._printing:
            messagebox.showinfo(
                "Impresora ocupada",
                "Espera a que termine el envío actual a la impresora.",
                parent=self,
            )
        return self._printing

    def _send_raw_async(self, printer_name, doc_name, chunks, on_success):
        """Envía datos RAW a la impresora en segundo plano (la ventana sigue
        respondiendo aunque el driver tarde o la impresora no conteste)."""
        def work():
            hPrinter = win32print.OpenPrinter(printer_name)
            try:
                win32print.StartDocPrinter(hPrinter, 1, (doc_name, None, "RAW"))
                win32print.StartPagePrinter(hPrinter)
                for chunk in chunks:
                    win32print.WritePrinter(hPrinter, chunk)
                win32print.EndPagePrinter(hPrinter)
                win32print.EndDocPrinter(hPrinter)
            finally:
                win32print.ClosePrinter(hPrinter)

        def done(_result, error):
            self._printing = False
            self.config(cursor="")
            if error is not None:
                self._show_printer_error(error)
            else:
                on_success()

        self._printing = True
        self.config(cursor="watch")
        self._run_async(work, done)
