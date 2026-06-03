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

MAPA_ORIGINAL = {
    "nombre":                   0,
    "genero":                   1,
    "email_mkt":                2,
    "clicks":                   3,
    "categoria":                4,
    "canal":                    5,
    "day":                      6,
    "admission_date":           7,
    "month":                    8,
    "year":                     9,
    "pipeline":                10,
    "telefono":                11,
    "contact_method":          12,
    "email":                   13,
    "crm":                     14,
    "sales_status":            15,
    "num_patients":            16,
    "schedule_month":          17,
    "appointment_schedule_date":18,
    "appointment_status":      19,
    "treatment_proposal_sent": 20,
    "treatment_confirmed":     21,
    "treatment_scheduled":     22,
    "treatment_completed":     23,
    "eligibility":             24,
    "program":                 25,
    "icd10":                   26,
    "tipo_consulta":           27,
    "proposal_sent_by":        28,
    "first_contact":           29,
    "consultation_with":       30,
    "assigned_to":             31,
    "converted_to_consultation":32,
    "treatment_proposal_sent_to":33,
    "treatment_confirmed_date":34,
    "fecha_contacto_inicial":  35,
    "last_contact_date":       36,
    "follow_up_indicator":     37,
    "comentarios":             38,
    "asesor":                  39,
    "procesado":               40,
    "columna_42":              41,
    "columna_43":              42,
    "columna_44":              43,
}

def limpiar_texto(valor, max_len=None):
    if not valor:
        return None
    texto = str(valor).strip()
    return texto[:max_len] if max_len and texto else texto or None

def limpiar_telefono(valor):
    if not valor:
        return None
    digitos = re.sub(r'\D', '', str(valor))
    return digitos[:20] if len(digitos) >= 7 else None

def parse_fecha_us(valor):
    if not valor:
        return None
    valor = str(valor).strip()
    if valor.startswith("="):
        m = re.search(r'["\'](\d{2}/\d{2}/\d{4})["\']', valor)
        if m:
            valor = m.group(1)
        else:
            return None
    if 'T' in valor:
        valor = valor.split('T')[0]
    for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%m-%d-%y"):
        try:
            return datetime.strptime(valor, fmt).date()
        except:
            continue
    try:
        return datetime.strptime(valor, "%Y-%m-%d").date()
    except:
        pass
    return None

def detectar_delimitador(path):
    delimitadores = ['\t', ',', ';', '|']
    for delim in delimitadores:
        try:
            with open(path, 'r', encoding='latin1') as f:
                reader = csv.reader(f, delimiter=delim)
                filas = list(reader)
            if len(filas) > 1 and len(filas[0]) > 30:
                return delim, filas
        except:
            continue
    raise Exception("No se pudo detectar el delimitador del CSV")

def actualizar_desde_csv():
    print("=" * 60)
    print("  ACTUALIZACIÓN DE LEADS DESDE CSV")
    print("  Busca por: medilink_numero → email → teléfono")
    print("=" * 60)

    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CSV_FILE)
    if not os.path.exists(csv_path):
        print(f"\n❌ Archivo no encontrado: {csv_path}")
        sys.exit(1)

    delim, filas = detectar_delimitador(csv_path)
    print(f"✓ Delimitador: {repr(delim)}")
    print(f"✓ Filas a procesar: {len(filas)-1}")

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    actualizados = 0
    no_encontrados = 0
    errores = 0

    max_idx = max(MAPA_ORIGINAL.values())
    for i, fila in enumerate(filas[1:], start=2):
        if len(fila) < max_idx + 1:
            fila.extend([''] * (max_idx - len(fila) + 1))

        # Intentar encontrar el lead
        lead_id = None
        num_patients = limpiar_texto(fila[MAPA_ORIGINAL["num_patients"]], 50)
        email = limpiar_texto(fila[MAPA_ORIGINAL["email"]], 255)
        telefono = limpiar_telefono(fila[MAPA_ORIGINAL["telefono"]])

        if num_patients:
            cur.execute("SELECT id FROM leads WHERE medilink_numero = %s", (num_patients,))
            row = cur.fetchone()
            if row:
                lead_id = row[0]
        if not lead_id and email:
            cur.execute("SELECT id FROM leads WHERE email = %s", (email,))
            row = cur.fetchone()
            if row:
                lead_id = row[0]
        if not lead_id and telefono:
            cur.execute("SELECT id FROM leads WHERE telefono = %s", (telefono,))
            row = cur.fetchone()
            if row:
                lead_id = row[0]

        if not lead_id:
            no_encontrados += 1
            # print(f"⚠️ Fila {i}: no encontrado (medilink={num_patients}, email={email}, tel={telefono})")
            continue

        updates = {}

        # Actualizar last_contact_date
        last_contact_raw = fila[MAPA_ORIGINAL["last_contact_date"]]
        last_contact_date = parse_fecha_us(last_contact_raw)
        if last_contact_date is not None:
            updates["last_contact_date"] = last_contact_date
        elif last_contact_raw:
            print(f"⚠️ Fila {i}: last_contact_date no parseado: '{last_contact_raw}'")

        # Actualizar otros campos (opcional)
        sales_status = limpiar_texto(fila[MAPA_ORIGINAL["sales_status"]], 100)
        if sales_status:
            updates["sales_status"] = sales_status
        
        appointment_status = limpiar_texto(fila[MAPA_ORIGINAL["appointment_status"]], 100)
        if appointment_status:
            updates["appointment_status"] = appointment_status

        # Si no hay nada que actualizar, saltar
        if not updates:
            continue

        set_clauses = [f"{k} = %s" for k in updates.keys()]
        set_clauses.append("fecha_actualizacion = CURRENT_TIMESTAMP")
        query = f"UPDATE leads SET {', '.join(set_clauses)} WHERE id = %s"
        valores = list(updates.values()) + [lead_id]

        try:
            cur.execute(query, valores)
            actualizados += 1
            if actualizados % 100 == 0:
                conn.commit()
                print(f"  ... {actualizados} actualizados")
        except Exception as e:
            errores += 1
            print(f"❌ Error en fila {i} (id={lead_id}): {e}")
            conn.rollback()

    conn.commit()
    cur.close()
    conn.close()

    print("\n" + "=" * 60)
    print(f"✅ ACTUALIZADOS: {actualizados}")
    print(f"⚠️ NO ENCONTRADOS: {no_encontrados}")
    if errores:
        print(f"❌ ERRORES: {errores}")
    print("=" * 60)

if __name__ == "__main__":
    actualizar_desde_csv()