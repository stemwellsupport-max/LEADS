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

# Mapeo de columnas del CSV a las columnas originales del CRM
# Solo las que realmente necesita el sistema
MAPA_ORIGINAL = {
    "nombre":                   0,    # NOMBRE
    "genero":                   1,    # GENDER
    "categoria":                4,    # CATEGORY
    "canal":                    5,    # CANALES
    "admission_date":           7,    # ADMISSION DATE
    "telefono":                11,    # PHONE  (lo guardamos en "telefono")
    "email":                   13,    # EMAIL
    "sales_status":            15,    # STATUS (lo mapeamos a sales_status)
    "first_contact":           29,    # FIRST CONTACT
    "consultation_with":       30,    # CONSULTATION WITH
    "assigned_to":             31,    # ASSIGNED TO
    "last_contact_date":       36,    # LAST CONTACT DATE
    "comentarios":             38,    # Comment (lo guardamos en "comentarios")
    "appointment_status":      19,    # APPOIMENT STATUS
    "appointment_schedule_date":18,   # APPOINTMENT SCHEDULE (DATE)
    # NOTA: no importamos "asesor_id" ni "doctor_id", se asignarán después
}

# ------------------------------------------------------------
def limpiar_texto(valor, max_len=None):
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    if max_len and len(texto) > max_len:
        texto = texto[:max_len]
    return texto

def limpiar_telefono(valor):
    if not valor:
        return None
    texto = str(valor).strip()
    digitos = re.sub(r'\D', '', texto)
    if len(digitos) < 7:
        return None
    return digitos[:20]

def parse_fecha(valor):
    if not valor:
        return None
    valor = str(valor).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(valor, fmt).date()
        except:
            continue
    return None

# ------------------------------------------------------------
def leer_csv_para_crm(path):
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
        if len(fila) < max(MAPA_ORIGINAL.values()):
            fila.extend([''] * (max(MAPA_ORIGINAL.values()) - len(fila) + 1))

        nombre = limpiar_texto(fila[MAPA_ORIGINAL["nombre"]], 255)
        if not nombre:
            filas_saltadas += 1
            continue

        lead = {
            "nombre": nombre,
            "genero": limpiar_texto(fila[MAPA_ORIGINAL["genero"]], 10),
            "categoria": limpiar_texto(fila[MAPA_ORIGINAL["categoria"]], 100),
            "canal": limpiar_texto(fila[MAPA_ORIGINAL["canal"]], 100) or "Google Sheets",
            "admission_date": parse_fecha(fila[MAPA_ORIGINAL["admission_date"]]),
            "telefono": limpiar_telefono(fila[MAPA_ORIGINAL["telefono"]]),
            "email": limpiar_texto(fila[MAPA_ORIGINAL["email"]], 255),
            "sales_status": limpiar_texto(fila[MAPA_ORIGINAL["sales_status"]], 100) or "New Lead",
            "first_contact": limpiar_texto(fila[MAPA_ORIGINAL["first_contact"]], None),
            "consultation_with": limpiar_texto(fila[MAPA_ORIGINAL["consultation_with"]], 255),
            "assigned_to": limpiar_texto(fila[MAPA_ORIGINAL["assigned_to"]], 255),
            "last_contact_date": parse_fecha(fila[MAPA_ORIGINAL["last_contact_date"]]),
            "comentarios": limpiar_texto(fila[MAPA_ORIGINAL["comentarios"]], None),
            "appointment_status": limpiar_texto(fila[MAPA_ORIGINAL["appointment_status"]], 100),
            "appointment_schedule_date": parse_fecha(fila[MAPA_ORIGINAL["appointment_schedule_date"]]),
            "creado_por": "google_sheets",
        }
        leads.append(lead)

        if i % 500 == 0:
            print(f"  ... procesada fila {i}")

    print(f"✓ Filas sin nombre (saltadas): {filas_saltadas}")
    print(f"📊 Total leads con nombre: {len(leads)}")
    return leads

# ------------------------------------------------------------
def crear_tabla_original(conn):
    """Crea la tabla leads con las columnas exactas que tenía el CRM originalmente."""
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS leads CASCADE")
    cur.execute("""
        CREATE TABLE leads (
            id SERIAL PRIMARY KEY,
            nombre VARCHAR(255),
            telefono VARCHAR(20),
            email VARCHAR(255),
            genero VARCHAR(10),
            categoria VARCHAR(100),
            canal VARCHAR(100),
            sales_status VARCHAR(100),
            appointment_status VARCHAR(100),
            medical_status VARCHAR(100),
            asesor_id INTEGER,
            doctor_id INTEGER,
            creado_por VARCHAR(100),
            comentarios TEXT,
            rejection_reason VARCHAR(100),
            quit_reason TEXT,
            medilink_numero VARCHAR(50),
            cita_confirmada BOOLEAN,
            treatment_date DATE,
            treatment_start_date DATE,
            treatment_end_date DATE,
            next_treatment_date DATE,
            treatment_completed BOOLEAN,
            fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            admission_date DATE,
            last_contact_date DATE,
            first_contact TEXT,
            semaforo VARCHAR(10),
            consultation_with VARCHAR(255),
            assigned_to VARCHAR(255),
            appointment_schedule_date DATE,
            ciudad VARCHAR(100),
            notas TEXT
        )
    """)
    conn.commit()
    cur.close()
    print("✅ Tabla 'leads' recreada con la estructura original.")

# ------------------------------------------------------------
def importar_limpio(leads):
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # Limpiar otras tablas dependientes
    cur.execute("DELETE FROM historial_estados")
    cur.execute("DELETE FROM controles")
    cur.execute("DELETE FROM agenda_doctor")
    conn.commit()

    insert_sql = """
        INSERT INTO leads (
            nombre, genero, categoria, canal, admission_date,
            telefono, email, sales_status, first_contact,
            consultation_with, assigned_to, last_contact_date,
            comentarios, appointment_status, appointment_schedule_date,
            creado_por, fecha_creacion, fecha_actualizacion
        ) VALUES (
            %(nombre)s, %(genero)s, %(categoria)s, %(canal)s, %(admission_date)s,
            %(telefono)s, %(email)s, %(sales_status)s, %(first_contact)s,
            %(consultation_with)s, %(assigned_to)s, %(last_contact_date)s,
            %(comentarios)s, %(appointment_status)s, %(appointment_schedule_date)s,
            %(creado_por)s, NOW(), NOW()
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
                print(f"  ❌ Error con '{lead.get('nombre','')[:30]}': {str(e)[:100]}")
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
def asignar_asesores():
    """Asigna asesor_id según first_contact"""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("UPDATE leads SET asesor_id = 1 WHERE LOWER(TRIM(first_contact)) IN ('sofia', 'sofía')")
    cur.execute("UPDATE leads SET asesor_id = 2 WHERE LOWER(TRIM(first_contact)) IN ('diana')")
    conn.commit()
    cur.close()
    conn.close()
    print("✅ Asesores asignados (Sofía=1, Diana=2)")

# ------------------------------------------------------------
if __name__ == "__main__":
    print("="*60)
    print("  STEMWELL CRM – IMPORTACIÓN CORRECTA (SOLO COLUMNAS ORIGINALES)")
    print("="*60)

    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CSV_FILE)
    if not os.path.exists(csv_path):
        print(f"\n❌ Archivo no encontrado: {csv_path}")
        sys.exit(1)

    leads = leer_csv_para_crm(csv_path)
    if not leads:
        print("❌ No hay leads con nombre en el archivo.")
        sys.exit(1)

    resp = input(f"\n⚠️  Se ELIMINARÁ la tabla leads actual y se importarán {len(leads)} leads con la estructura original. ¿Continuar? (escribe 'BORRAR'): ").strip()
    if resp.upper() != "BORRAR":
        print("Cancelado")
        sys.exit(0)

    conn = psycopg2.connect(**DB_CONFIG)
    crear_tabla_original(conn)
    conn.close()

    importar_limpio(leads)
    asignar_asesores()

    print("\n✅ Proceso completado. Reinicia el servidor y limpia el navegador.")