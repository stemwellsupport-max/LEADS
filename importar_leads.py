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
    if texto == "#VALUE!" or texto == "#REF!" or texto == "N/A" or texto == "n/a":
        return None
    if len(texto) > 2 and texto[0] == '=' and texto[-1] == ')':
        m = re.search(r'["\']([^"\']+)["\']', texto)
        if m:
            texto = m.group(1)
    return texto[:max_len] if max_len and texto else texto or None

def limpiar_telefono(valor):
    if not valor:
        return None
    digitos = re.sub(r'\D', '', str(valor))
    if len(digitos) < 7:
        return None
    return digitos[:20]

def parse_fecha_csv(valor):
    """Parsea fechas del CSV en formato MM/DD/YYYY a YYYY-MM-DD"""
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
    
    # Limpiar caracteres no deseados
    valor = re.sub(r'[^0-9/]', '', valor)
    
    if not valor or len(valor) < 8:
        return None
    
    partes = valor.split('/')
    if len(partes) != 3:
        return None
    
    try:
        p1, p2, anio = int(partes[0]), int(partes[1]), int(partes[2])
        
        if anio < 100:
            anio = 2000 + anio if anio < 50 else 1900 + anio
        
        # Determinar si es MM/DD/YYYY o DD/MM/YYYY
        if p1 > 12:
            dia, mes = p1, p2
        else:
            mes, dia = p1, p2
        
        if mes < 1 or mes > 12 or dia < 1 or dia > 31:
            if p2 <= 12 and p2 >= 1:
                mes, dia = p2, p1
        
        if mes < 1 or mes > 12 or dia < 1 or dia > 31:
            return None
        
        return datetime(anio, mes, dia).date()
    except (ValueError, TypeError):
        return None

def parse_fecha_hora_csv(valor):
    """Parsea fechas con hora del CSV"""
    if not valor:
        return None
    valor = str(valor).strip()
    if valor.startswith("="):
        m = re.search(r'["\']([^"\']+)["\']', valor)
        if m:
            valor = m.group(1)
    
    # Intentar parsear con hora
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(valor, fmt)
        except:
            continue
    
    # Si no tiene hora, parsear solo fecha
    fecha = parse_fecha_csv(valor)
    if fecha:
        return datetime.combine(fecha, datetime.min.time())
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
    print("=" * 70)
    print("  ACTUALIZACIÓN DE LEADS DESDE CSV")
    print("  Actualiza: last_contact_date, admission_date, comentarios,")
    print("            sales_status, appointment_status")
    print("=" * 70)

    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CSV_FILE)
    if not os.path.exists(csv_path):
        print(f"\n❌ Archivo no encontrado: {csv_path}")
        sys.exit(1)

    delim, filas = detectar_delimitador(csv_path)
    total_filas = len(filas) - 1
    print(f"✓ Delimitador: {repr(delim)}")
    print(f"✓ Filas a procesar: {total_filas}")

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        print("✓ Conexión a base de datos exitosa")
    except Exception as e:
        print(f"❌ Error de conexión: {e}")
        sys.exit(1)

    # Estadísticas
    stats = {
        "encontrados": 0,
        "no_encontrados": 0,
        "actualizados": 0,
        "errores": 0,
        "last_contact": 0,
        "admission": 0,
        "comentarios": 0,
        "sales_status": 0,
        "appointment_status": 0,
    }

    max_idx = max(MAPA_ORIGINAL.values())
    
    print("\nProcesando...\n")
    
    for i, fila in enumerate(filas[1:], start=2):
        if len(fila) < max_idx + 1:
            fila.extend([''] * (max_idx - len(fila) + 1))

        # Buscar el lead
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
            stats["no_encontrados"] += 1
            continue

        stats["encontrados"] += 1
        
        updates = {}

        # 1. last_contact_date
        last_contact_raw = fila[MAPA_ORIGINAL["last_contact_date"]]
        last_contact_date = parse_fecha_csv(last_contact_raw)
        if last_contact_date is not None:
            updates["last_contact_date"] = last_contact_date
            stats["last_contact"] += 1

        # 2. admission_date
        admission_raw = fila[MAPA_ORIGINAL["admission_date"]]
        admission_date = parse_fecha_csv(admission_raw)
        if admission_date is not None:
            updates["admission_date"] = admission_date
            stats["admission"] += 1

        # 3. comentarios
        comentarios_raw = fila[MAPA_ORIGINAL["comentarios"]]
        comentarios = limpiar_texto(comentarios_raw, 10000)
        if comentarios is not None:
            # Obtener comentario existente para concatenar
            cur.execute("SELECT comentarios FROM leads WHERE id = %s", (lead_id,))
            existing = cur.fetchone()
            if existing and existing[0]:
                # No duplicar si ya existe el mismo comentario
                if comentarios not in existing[0]:
                    updates["comentarios"] = existing[0] + "\n\n[CSV] " + comentarios
                else:
                    updates["comentarios"] = existing[0]
            else:
                updates["comentarios"] = "[CSV] " + comentarios
            stats["comentarios"] += 1

        # 4. sales_status
        sales_status_raw = fila[MAPA_ORIGINAL["sales_status"]]
        sales_status = limpiar_texto(sales_status_raw, 100)
        if sales_status is not None:
            updates["sales_status"] = sales_status
            stats["sales_status"] += 1

        # 5. appointment_status
        appointment_status_raw = fila[MAPA_ORIGINAL["appointment_status"]]
        appointment_status = limpiar_texto(appointment_status_raw, 100)
        if appointment_status is not None:
            updates["appointment_status"] = appointment_status
            stats["appointment_status"] += 1

        # Si no hay nada que actualizar, continuar
        if not updates:
            continue

        # Construir UPDATE
        set_clauses = [f"{k} = %s" for k in updates.keys()]
        set_clauses.append("fecha_actualizacion = CURRENT_TIMESTAMP")
        query = f"UPDATE leads SET {', '.join(set_clauses)} WHERE id = %s"
        valores = list(updates.values()) + [lead_id]

        try:
            cur.execute(query, valores)
            stats["actualizados"] += 1
            
            if stats["actualizados"] % 100 == 0:
                conn.commit()
                print(f"  ... {stats['actualizados']} leads actualizados")
                
        except Exception as e:
            stats["errores"] += 1
            print(f"❌ Error fila {i} (id={lead_id}): {e}")
            conn.rollback()

    # Commit final
    conn.commit()
    cur.close()
    conn.close()

    # Resumen
    print("\n" + "=" * 70)
    print("  📊 RESUMEN DE ACTUALIZACIÓN")
    print("=" * 70)
    print(f"  📝 Total filas CSV:        {total_filas}")
    print(f"  ✅ Leads encontrados:      {stats['encontrados']}")
    print(f"  ⚠️ Leads NO encontrados:   {stats['no_encontrados']}")
    print(f"  🔄 Leads actualizados:     {stats['actualizados']}")
    print(f"     ├─ last_contact_date:   {stats['last_contact']}")
    print(f"     ├─ admission_date:      {stats['admission']}")
    print(f"     ├─ comentarios:         {stats['comentarios']}")
    print(f"     ├─ sales_status:        {stats['sales_status']}")
    print(f"     └─ appointment_status:  {stats['appointment_status']}")
    if stats['errores']:
        print(f"  ❌ Errores:               {stats['errores']}")
    print("=" * 70)
    
    # Mostrar ejemplos
    if stats['actualizados'] > 0:
        print("\n📋 Ejemplos de últimos leads actualizados:")
        try:
            conn2 = psycopg2.connect(**DB_CONFIG)
            cur2 = conn2.cursor()
            cur2.execute("""
                SELECT nombre, last_contact_date, sales_status, 
                       LEFT(comentarios, 60) as comentarios_corto
                FROM leads 
                WHERE last_contact_date IS NOT NULL 
                ORDER BY fecha_actualizacion DESC 
                LIMIT 5
            """)
            for row in cur2.fetchall():
                nombre = (row[0] or "Sin nombre")[:35]
                fecha = row[1] or "N/A"
                status = row[2] or "N/A"
                coment = (row[3] or "")[:40]
                print(f"  • {nombre:35} | Last: {fecha} | Status: {status}")
                if coment:
                    print(f"    Comentario: {coment}...")
            cur2.close()
            conn2.close()
        except Exception as e:
            print(f"  (No se pudieron obtener ejemplos: {e})")

if __name__ == "__main__":
    actualizar_desde_csv()