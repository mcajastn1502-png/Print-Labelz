"""Lector ligero de Excel (reemplaza a pandas para arrancar rápido).

Expone una interfaz mínima tipo DataFrame: columns, iloc[i], at[i, col], len().
"""

import math


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
