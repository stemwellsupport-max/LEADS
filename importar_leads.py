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

# MAPA ACTUALIZADO según la cabecera real del CSV
MAPA_ORIGINAL = {
    "nombre":                   0,   # NOMBRE
    "genero":                   1,   # GENDER
    "email_mkt":                2,   # Email mkt
    "clicks":                   3,   # CLICKS
    "categoria":                4,   # CATEGORY
    "canal":                    5,   # CANALES
    "day":                      6,   # DAY
    "admission_date":           7,   # ADMISSION DATE
    "month":                    8,   # MONTH
    "year":                     9,   # YEAR
    "pipeline":                10,   # PIPELINE (INTERNATIONAL / LOCAL)
    "telefono":                11,   # PHONE
    "contact_method":          12,   # CONTACT METHOD
    "email":                   13,   # EMAIL
    "crm":                     14,   # CRM
    "sales_status":            15,   # STATUS
    "num_patients":            16,   # Num_Patients ← AQUÍ ESTÁ
    "schedule_month":          17,   # SCHEDULE MONTH
    "appointment_schedule_date":18,  # APPOINTMENT SCHEDULE (DATE)
    "appointment_status":      19,   # APPOIMENT STATUS
    "treatment_proposal_sent": 20,   # TREATMENT PROPOSAL SENT (DATE)
    "treatment_confirmed":     21,   # TREATMENT CONFIRMED OR REJECTED (DATE)
    "treatment_scheduled":     22,   # TREATMENT SCHEDULED (DATE)
    "treatment_completed":     23,   # TREATMENT COMPLETED (DATE)
    "eligibility":             24,   # ELEGIBITY FOR TREATMENT
    "program":                 25,   # PROGRAM TO WHICH BELONG IT IS
    "icd10":                   26,   # ICD-10
    "tipo_consulta":           27,   # TYPE OF MEDICAL CONSULTATION
    "proposal_sent_by":        28,   # PROPOSAL SENT BY
    "first_contact":           29,   # FIRST CONTACT
    "consultation_with":       30,   # CONSULTATION WITH
    "assigned_to":             31,   # ASSIGNED TO
    "converted_to_consultation":32,  # CONVERTED TO CONSULTATION
    "treatment_proposal_sent_to":33, # TREATMENT PROPOSAL SENT TO PATIENT
    "treatment_confirmed_date":34,   # TREATMENT CONFIRMED
    "fecha_contacto_inicial":  35,   # DATE OF INICIAL CONTACT
    "last_contact_date":       36,   # LAST CONTACT DATE
    "follow_up_indicator":     37,   # FOLLOW UP-INDICATOR
    "comentarios":             38,   # Comment
    "asesor":                  39,   # ASESOR
    "procesado":               40,   # PROCESADO
    "columna_42":              41,   # Column 42
    "columna_43":              42,   # Column 43
    "columna_44":              43,   # Column 44
}

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
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(valor, fmt).date()
        except:
            continue
    return None

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
    
    # Mostrar la cabecera para verificar
    print(f"📋 Cabecera del CSV:")
    for i, col in enumerate(filas[0]):
        print(f"   [{i}] {col}")

    filas_saltadas = 0
    for i, fila in enumerate(filas[1:], start=2):
        # Asegurar que la fila tenga suficientes columnas
        max_idx = max(MAPA_ORIGINAL.values())
        if len(fila) < max_idx + 1:
            fila.extend([''] * (max_idx - len(fila) + 1))

        nombre = limpiar_texto(fila[MAPA_ORIGINAL["nombre"]], 255)
        if not nombre:
            filas_saltadas += 1
            continue

        # Extraer número de paciente (Num_Patients)
        num_patients_raw = limpiar_texto(fila[MAPA_ORIGINAL["num_patients"]], 50)
        
        # Extraer fechas de tratamiento
        treatment_date = parse_fecha(fila[MAPA_ORIGINAL["appointment_schedule_date"]])
        treatment_start_date = parse_fecha(fila[MAPA_ORIGINAL["treatment_scheduled"]])
        treatment_end_date = parse_fecha(fila[MAPA_ORIGINAL["treatment_completed"]])
        
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
            "medilink_numero": num_patients_raw,  # ← Num_Patients
            "last_contact_date": parse_fecha(fila[MAPA_ORIGINAL["last_contact_date"]]),
            "comentarios": limpiar_texto(fila[MAPA_ORIGINAL["comentarios"]], None),
            "appointment_status": limpiar_texto(fila[MAPA_ORIGINAL["appointment_status"]], 100),
            "appointment_schedule_date": parse_fecha(fila[MAPA_ORIGINAL["appointment_schedule_date"]]),
            "treatment_date": treatment_date,
            "treatment_start_date": treatment_start_date,
            "treatment_end_date": treatment_end_date,
            "treatment_proposal_sent": parse_fecha(fila[MAPA_ORIGINAL["treatment_proposal_sent"]]),
            "treatment_confirmed": parse_fecha(fila[MAPA_ORIGINAL["treatment_confirmed"]]),
            "eligibility": limpiar_texto(fila[MAPA_ORIGINAL["eligibility"]], 100),
            "program": limpiar_texto(fila[MAPA_ORIGINAL["program"]], 100),
            "icd10": limpiar_texto(fila[MAPA_ORIGINAL["icd10"]], 50),
            "tipo_consulta": limpiar_texto(fila[MAPA_ORIGINAL["tipo_consulta"]], 100),
            "proposal_sent_by": limpiar_texto(fila[MAPA_ORIGINAL["proposal_sent_by"]], 255),
            "asesor_nombre": limpiar_texto(fila[MAPA_ORIGINAL["asesor"]], 255),
            "pipeline": limpiar_texto(fila[MAPA_ORIGINAL["pipeline"]], 100),
            "creado_por": "google_sheets",
        }
        leads.append(lead)

        if i % 500 == 0:
            print(f"  ... procesada fila {i}")

    print(f"✓ Filas sin nombre (saltadas): {filas_saltadas}")
    print(f"📊 Total leads con nombre: {len(leads)}")
    
    # Estadísticas
    with_medilink = [l for l in leads if l.get("medilink_numero")]
    with_treatment_start = [l for l in leads if l.get("treatment_start_date")]
    with_treatment_end = [l for l in leads if l.get("treatment_end_date")]
    
    print(f"📊 Leads con número de paciente (Num_Patients): {len(with_medilink)}")
    print(f"📊 Leads con fecha de inicio de tratamiento: {len(with_treatment_start)}")
    print(f"📊 Leads con fecha de fin de tratamiento: {len(with_treatment_end)}")
    
    if with_medilink:
        print(f"   Ejemplos Num_Patients: {[l['medilink_numero'] for l in with_medilink[:5]]}")
    
    return leads

def crear_tabla_original(conn):
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
            notas TEXT,
            eligibility VARCHAR(100),
            program VARCHAR(100),
            icd10 VARCHAR(50),
            tipo_consulta VARCHAR(100),
            proposal_sent_by VARCHAR(255),
            pipeline VARCHAR(100)
        )
    """)
    conn.commit()
    cur.close()
    print("✅ Tabla 'leads' recreada con campos adicionales (Num_Patients, fechas de tratamiento, etc.)")

def importar_limpio(leads):
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # Limpiar tablas relacionadas
    cur.execute("DELETE FROM historial_estados")
    cur.execute("DELETE FROM controles")
    cur.execute("DELETE FROM agenda_doctor")
    conn.commit()

    insert_sql = """
        INSERT INTO leads (
            nombre, genero, categoria, canal, admission_date,
            telefono, email, sales_status, first_contact,
            consultation_with, assigned_to, medilink_numero, last_contact_date,
            comentarios, appointment_status, appointment_schedule_date,
            treatment_date, treatment_start_date, treatment_end_date,
            eligibility, program, icd10, tipo_consulta, proposal_sent_by, pipeline,
            creado_por, fecha_creacion, fecha_actualizacion
        ) VALUES (
            %(nombre)s, %(genero)s, %(categoria)s, %(canal)s, %(admission_date)s,
            %(telefono)s, %(email)s, %(sales_status)s, %(first_contact)s,
            %(consultation_with)s, %(assigned_to)s, %(medilink_numero)s, %(last_contact_date)s,
            %(comentarios)s, %(appointment_status)s, %(appointment_schedule_date)s,
            %(treatment_date)s, %(treatment_start_date)s, %(treatment_end_date)s,
            %(eligibility)s, %(program)s, %(icd10)s, %(tipo_consulta)s, %(proposal_sent_by)s, %(pipeline)s,
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
            print(f"  ❌ Error en lead {idx} ({lead.get('nombre','')[:50]}): {str(e)[:150]}")
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

    # Verificar importación
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM leads")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM leads WHERE medilink_numero IS NOT NULL AND medilink_numero != ''")
    con_medilink = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM leads WHERE treatment_start_date IS NOT NULL")
    con_trat_inicio = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM leads WHERE treatment_end_date IS NOT NULL")
    con_trat_fin = cur.fetchone()[0]
    
    print(f"\n📊 Total leads en la base de datos: {total}")
    print(f"📊 Leads con Num_Patients (Medilink): {con_medilink}")
    print(f"📊 Leads con fecha inicio tratamiento: {con_trat_inicio}")
    print(f"📊 Leads con fecha fin tratamiento: {con_trat_fin}")
    cur.close()
    conn.close()

def asignar_asesores():
    """Asigna asesor_id según assigned_to"""
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("UPDATE leads SET asesor_id = 1 WHERE LOWER(TRIM(assigned_to)) IN ('sofia', 'sofía')")
    cur.execute("UPDATE leads SET asesor_id = 2 WHERE LOWER(TRIM(assigned_to)) IN ('diana')")
    conn.commit()
    cur.close()
    conn.close()
    print("✅ Asesores asignados (Sofía=1, Diana=2)")

if __name__ == "__main__":
    print("="*60)
    print("  STEMWELL CRM – IMPORTACIÓN COMPLETA")
    print("  Incluye: Num_Patients, fechas de tratamiento, etc.")
    print("="*60)

    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CSV_FILE)
    if not os.path.exists(csv_path):
        print(f"\n❌ Archivo no encontrado: {csv_path}")
        sys.exit(1)

    leads = leer_csv_para_crm(csv_path)
    if not leads:
        print("❌ No hay leads con nombre en el archivo.")
        sys.exit(1)

    resp = input(f"\n⚠️  Se ELIMINARÁ la tabla leads actual y se importarán {len(leads)} leads.\n   ¿Continuar? (escribe 'BORRAR'): ").strip()
    if resp.upper() != "BORRAR":
        print("Cancelado")
        sys.exit(0)

    conn = psycopg2.connect(**DB_CONFIG)
    crear_tabla_original(conn)
    conn.close()

    importar_limpio(leads)
    asignar_asesores()

    print("\n✅ Proceso completado. Reinicia el servidor y limpia el navegador.")