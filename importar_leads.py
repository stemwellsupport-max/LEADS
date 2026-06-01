import csv
import sys
import os
import re
import psycopg2
from datetime import datetime

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "stemwell",
    "user": "crm_user",
    "password": "crm2024",
}

CSV_FILE = "LEADS.csv"

# Índices exactos según tu cabecera
COL = {
    "NOMBRE": 0,
    "GENERO": 1,
    "CATEGORIA": 4,
    "CANAL": 5,
    "ADMISSION_DATE": 7,
    "PHONE": 11,
    "EMAIL": 13,
    "STATUS": 15,
    "APPOINTMENT_STATUS": 19,
    "APPOINTMENT_SCHEDULE_DATE": 18,
    "FIRST_CONTACT": 29,
    "CONSULTATION_WITH": 30,
    "ASSIGNED_TO": 31,
    "LAST_CONTACT": 36,
    "COMENTARIO": 38,
}

# ------------------------------------------------------------
def limpiar_campo(valor, max_len=None):
    if not valor:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    if ';' in texto:
        texto = texto.split(';')[0].strip()
    if max_len and len(texto) > max_len:
        texto = texto[:max_len]
    return texto

def limpiar_telefono(valor):
    if not valor:
        return None
    texto = str(valor).strip()
    if ';' in texto:
        texto = texto.split(';')[0].strip()
    digitos = re.sub(r'\D', '', texto)
    if len(digitos) < 7:
        return None
    return digitos[:20]

def parse_fecha(valor):
    if not valor:
        return None
    valor = str(valor).strip()
    if ';' in valor:
        valor = valor.split(';')[0].strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(valor, fmt).date()
        except:
            continue
    return None

# ------------------------------------------------------------
def leer_csv(path):
    leads = []
    delimitadores = ['\t', ',', ';', '|']
    filas = None
    dialecto_usado = None

    for delim in delimitadores:
        try:
            with open(path, 'r', encoding='latin1') as f:
                reader = csv.reader(f, delimiter=delim)
                filas = list(reader)
            if len(filas) > 1 and len(filas[0]) > 30:
                dialecto_usado = delim
                break
        except:
            continue

    if filas is None:
        print("❌ No se pudo leer el CSV")
        sys.exit(1)

    print(f"✓ Delimitador detectado: {repr(dialecto_usado)}")
    print(f"✓ Filas totales en CSV (incl. cabecera): {len(filas)}")
    print(f"✓ Columnas en cabecera: {len(filas[0])}")

    filas_saltadas = 0
    for i, fila in enumerate(filas[1:], start=2):
        if len(fila) <= max(COL.values()):
            fila.extend([''] * (max(COL.values()) - len(fila) + 1))

        # Extraer y limpiar el nombre, y saltar si queda vacío
        nombre = limpiar_campo(fila[COL["NOMBRE"]], 255)
        if not nombre:
            filas_saltadas += 1
            continue   # <--- esta línea es la clave: no importamos filas sin nombre

        lead = {
            "nombre": nombre,
            "telefono": limpiar_telefono(fila[COL["PHONE"]]),
            "email": limpiar_campo(fila[COL["EMAIL"]], 255),
            "genero": limpiar_campo(fila[COL["GENERO"]], 10),
            "categoria": limpiar_campo(fila[COL["CATEGORIA"]], 100),
            "canal": limpiar_campo(fila[COL["CANAL"]], 100) or "Google Sheets",
            "sales_status": limpiar_campo(fila[COL["STATUS"]], 100) or "New Lead",
            "appointment_status": limpiar_campo(fila[COL["APPOINTMENT_STATUS"]], 100),
            "appointment_schedule_date": parse_fecha(fila[COL["APPOINTMENT_SCHEDULE_DATE"]]),
            "comentarios": limpiar_campo(fila[COL["COMENTARIO"]], None),
            "first_contact": limpiar_campo(fila[COL["FIRST_CONTACT"]], None),
            "consultation_with": limpiar_campo(fila[COL["CONSULTATION_WITH"]], 255),
            "assigned_to": limpiar_campo(fila[COL["ASSIGNED_TO"]], 255),
            "admission_date": parse_fecha(fila[COL["ADMISSION_DATE"]]),
            "last_contact_date": parse_fecha(fila[COL["LAST_CONTACT"]]),
            "creado_por": "google_sheets",
        }
        leads.append(lead)

        if i % 500 == 0:
            print(f"  ... procesada fila {i}")

    print(f"✓ Filas sin nombre saltadas: {filas_saltadas}")
    print(f"📝 Primeros 5 nombres extraídos:")
    for j in range(min(5, len(leads))):
        print(f"   {j+1}. {leads[j]['nombre']}")
    print(f"\n📊 Total leads con nombre: {len(leads)}")
    return leads

# ------------------------------------------------------------
def importar_limpio(leads):
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    print("\n🗑️  Eliminando todos los leads existentes...")
    cur.execute("DELETE FROM historial_estados")
    cur.execute("DELETE FROM controles")
    cur.execute("DELETE FROM leads")
    conn.commit()
    print("✅ Tablas limpias.")

    insert_sql = """
        INSERT INTO leads (
            nombre, telefono, email, genero, categoria, canal,
            sales_status, appointment_status, appointment_schedule_date,
            comentarios, first_contact, consultation_with, assigned_to,
            admission_date, last_contact_date, creado_por, fecha_creacion
        ) VALUES (
            %(nombre)s, %(telefono)s, %(email)s, %(genero)s, %(categoria)s, %(canal)s,
            %(sales_status)s, %(appointment_status)s, %(appointment_schedule_date)s,
            %(comentarios)s, %(first_contact)s, %(consultation_with)s, %(assigned_to)s,
            %(admission_date)s, %(last_contact_date)s, %(creado_por)s, NOW()
        )
    """

    insertados = 0
    errores = 0

    for idx, lead in enumerate(leads, 1):
        try:
            cur.execute(insert_sql, lead)
            insertados += 1
            if insertados % 200 == 0:
                conn.commit()
                print(f"  ✅ {insertados}/{len(leads)} insertados")
        except Exception as e:
            errores += 1
            if errores <= 10:
                print(f"  ❌ Error con '{lead['nombre'][:30]}': {str(e)[:100]}")
            conn.rollback()
            cur = conn.cursor()

    conn.commit()
    cur.close()
    conn.close()

    print("\n" + "="*60)
    print(f"  ✅ INSERTADOS: {insertados} de {len(leads)}")
    if errores:
        print(f"  ❌ ERRORES: {errores}")
    print("="*60)

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM leads")
    total = cur.fetchone()[0]
    print(f"\n📊 Total leads en la base de datos: {total}")
    cur.close()
    conn.close()

# ------------------------------------------------------------
if __name__ == "__main__":
    print("="*60)
    print("  STEMWELL CRM – SOLO FILAS CON NOMBRE")
    print("="*60)

    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CSV_FILE)
    if not os.path.exists(csv_path):
        print(f"\n❌ Archivo no encontrado: {csv_path}")
        sys.exit(1)

    leads = leer_csv(csv_path)
    if not leads:
        print("❌ No hay leads con nombre en el archivo.")
        sys.exit(1)

    resp = input(f"\n⚠️  Se BORRARÁN todos los leads actuales y se importarán {len(leads)} leads con nombre. ¿Continuar? (escribe 'BORRAR'): ").strip()
    if resp.upper() != "BORRAR":
        print("Cancelado")
        sys.exit(0)

    importar_limpio(leads)