import csv
import sys
import os

CSV_FILE = "LEADS.csv"

# Mismo mapeo que antes
COL_DEBUG = {
    "ADMISSION_DATE (col7)": 7,
    "APPOINTMENT_SCHEDULE (col18)": 18,
    "LAST_CONTACT (col36)": 36,
}

def leer_primeras_filas(path):
    delimitadores = ['\t', ',', ';', '|']
    filas = None
    for delim in delimitadores:
        try:
            with open(path, 'r', encoding='latin1') as f:
                reader = csv.reader(f, delimiter=delim)
                filas = list(reader)
            if len(filas) > 1 and len(filas[0]) > 30:
                print(f"✓ Delimitador usado: {repr(delim)}\n")
                break
        except:
            continue
    if not filas:
        print("❌ No se pudo leer")
        return

    # Mostrar cabecera (índices)
    cabecera = filas[0]
    for nombre, idx in COL_DEBUG.items():
        if idx < len(cabecera):
            print(f"Columna {idx}: '{cabecera[idx]}'")
    print()

    # Mostrar 10 filas de ejemplo
    for i, fila in enumerate(filas[1:11], start=2):
        print(f"--- Fila {i} ---")
        for nombre, idx in COL_DEBUG.items():
            valor = fila[idx] if idx < len(fila) else "(no existe)"
            print(f"  {nombre}: {repr(valor)}")
        print()

if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else CSV_FILE
    full_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), csv_path)

    if not os.path.exists(full_path):
        print(f"\n❌ Archivo no encontrado: {csv_path}")
        sys.exit(1)

    leer_primeras_filas(full_path)