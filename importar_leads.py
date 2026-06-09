import csv
import psycopg2
import sys
import glob
from datetime import datetime

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "stemwell",
    "user": "crm_user",
    "password": "crm2024",
}

def encontrar_csv():
    for archivo in glob.glob("LEADS*.csv"):
        return archivo
    archivos = glob.glob("*.csv")
    return archivos[0] if archivos else None

def detectar_delimitador(archivo, encoding):
    """Prueba varios delimitadores y devuelve el que dé más columnas."""
    delimitadores = [';', ',', '\t', '|']
    mejor = None
    max_cols = 0
    for delim in delimitadores:
        try:
            with open(archivo, 'r', encoding=encoding) as f:
                reader = csv.reader(f, delimiter=delim)
                primera_fila = next(reader)
                if len(primera_fila) > max_cols:
                    max_cols = len(primera_fila)
                    mejor = delim
        except:
            continue
    return mejor if max_cols > 1 else ','

def parse_fecha(val):
    if not val or val.strip() == "":
        return None
    val = val.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(val, fmt).date()
        except:
            continue
    return None

def parse_bool(val):
    if isinstance(val, bool):
        return val
    if not val or val.strip() == "":
        return None
    return val.strip().lower() in ("true", "t", "yes", "1", "sí", "si")

def main():
    archivo = encontrar_csv()
    if not archivo:
        print("❌ No se encontró ningún archivo CSV (LEADS*.csv).")
        sys.exit(1)

    print(f"✅ Archivo encontrado: {archivo}")
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    try:
        # Intentar varias codificaciones
        codificaciones = ["latin1", "cp1252", "utf-8", "utf-8-sig"]
        encoding = None
        reader_data = None
        columnas = None

        for enc in codificaciones:
            try:
                with open(archivo, "r", encoding=enc) as f:
                    # Solo probamos la lectura, no cargamos todavía
                    pass
                encoding = enc
                break
            except (UnicodeDecodeError, UnicodeError):
                continue

        if not encoding:
            print("❌ No se pudo detectar la codificación del archivo.")
            sys.exit(1)

        # Detectar delimitador
        delimitador = detectar_delimitador(archivo, encoding)
        print(f"   Codificación: {encoding}, Delimitador: {repr(delimitador)}")

        # Leer el archivo completo con DictReader
        with open(archivo, "r", encoding=encoding) as f:
            lector = csv.DictReader(f, delimiter=delimitador)
            columnas = lector.fieldnames
            reader_data = list(lector)

        if not columnas or not reader_data:
            print("❌ El archivo no tiene datos o columnas.")
            sys.exit(1)

        # Quitar columna 'id' si existe
        columnas_sin_id = [c for c in columnas if c.lower() != "id"]

        resp = input("¿Vaciar la tabla leads antes de importar? (SI para confirmar): ").strip()
        if resp.upper() == "SI":
            cur.execute("TRUNCATE leads RESTART IDENTITY CASCADE;")
            print("✅ Tabla leads vaciada.")

        placeholders = ", ".join(["%s"] * len(columnas_sin_id))
        query = f"INSERT INTO leads ({', '.join(columnas_sin_id)}) VALUES ({placeholders})"

        inserts = 0
        errores = 0
        for fila in reader_data:
            valores = []
            for col in columnas_sin_id:
                val = fila.get(col, "")
                if col in ("treatment_date", "treatment_start_date", "treatment_end_date",
                           "next_treatment_date", "admission_date", "last_contact_date",
                           "appointment_schedule_date", "fecha_creacion", "fecha_actualizacion"):
                    val = parse_fecha(val)
                elif col in ("cita_confirmada", "treatment_completed", "treatment_confirmed"):
                    val = parse_bool(val)
                elif col in ("asesor_id", "doctor_id"):
                    try:
                        val = int(val) if val and val.strip() else None
                    except:
                        val = None
                else:
                    val = val.strip() if val else None
                    if val == "":
                        val = None
                valores.append(val)

            try:
                cur.execute(query, valores)
                inserts += 1
                if inserts % 200 == 0:
                    conn.commit()
                    print(f"   ... {inserts} registros insertados")
            except Exception as e:
                errores += 1
                if errores <= 5:  # solo mostrar los primeros errores
                    print(f"❌ Error: {e}")
                conn.rollback()

        conn.commit()
        print(f"\n✅ {inserts} registros insertados correctamente.")
        if errores:
            print(f"⚠️ {errores} errores.")

        # Ajustar secuencia del id
        cur.execute("SELECT setval('leads_id_seq', COALESCE((SELECT MAX(id) FROM leads), 1));")
        conn.commit()
        print("✅ Secuencia de ID actualizada.")

    except Exception as e:
        print(f"❌ Error general: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    main()
    