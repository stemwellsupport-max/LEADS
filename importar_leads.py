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

COL = {
    "NOMBRE": 0,
    "GENERO": 1,
    "CATEGORIA": 4,
    "CANAL": 5,
    "ADMISSION_DATE": 7,
    "PHONE": 11,
    "EMAIL": 13,
    "STATUS": 15,
    "FIRST_CONTACT": 29,
    "LAST_CONTACT": 36,
    "COMENTARIO": 38,
}

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

def fila_util(fila, indices):
    """Verifica si la fila tiene al menos un dato útil (nombre, teléfono, email o comentario)"""
    nombre = limpiar_campo(fila[indices["NOMBRE"]] if len(fila) > indices["NOMBRE"] else "", 255)
    telefono = limpiar_telefono(fila[indices["PHONE"]] if len(fila) > indices["PHONE"] else "")
    email = limpiar_campo(fila[indices["EMAIL"]] if len(fila) > indices["EMAIL"] else "", 255)
    comentario = limpiar_campo(fila[indices["COMENTARIO"]] if len(fila) > indices["COMENTARIO"] else "", None)
    return nombre or telefono or email or comentario

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
    print(f"✓ Filas totales en CSV: {len(filas)}")
    print(f"✓ Columnas en cabecera: {len(filas[0])}")
    
    filas_saltadas = 0
    for i, fila in enumerate(filas[1:], start=2):
        if len(fila) <= max(COL.values()):
            fila.extend([''] * (max(COL.values()) - len(fila) + 1))
        
        # Verificar si la fila tiene al menos un dato útil
        if not fila_util(fila, COL):
            filas_saltadas += 1
            continue
        
        nombre_raw = fila[COL["NOMBRE"]] if COL["NOMBRE"] < len(fila) else ""
        nombre = limpiar_campo(nombre_raw, 255)
        if not nombre:
            # Si después de limpiar sigue sin nombre, pero hay otros datos, asignamos genérico
            nombre = f"Lead_Fila_{i}"
        
        lead = {
            "nombre": nombre,
            "telefono": limpiar_telefono(fila[COL["PHONE"]] if COL["PHONE"] < len(fila) else ""),
            "email": limpiar_campo(fila[COL["EMAIL"]] if COL["EMAIL"] < len(fila) else "", 255),
            "genero": limpiar_campo(fila[COL["GENERO"]] if COL["GENERO"] < len(fila) else "", 10),
            "categoria": limpiar_campo(fila[COL["CATEGORIA"]] if COL["CATEGORIA"] < len(fila) else "", 100),
            "canal": limpiar_campo(fila[COL["CANAL"]] if COL["CANAL"] < len(fila) else "", 100) or "Google Sheets",
            "sales_status": limpiar_campo(fila[COL["STATUS"]] if COL["STATUS"] < len(fila) else "", 100) or "New Lead",
            "comentarios": limpiar_campo(fila[COL["COMENTARIO"]] if COL["COMENTARIO"] < len(fila) else "", None),
            "first_contact": limpiar_campo(fila[COL["FIRST_CONTACT"]] if COL["FIRST_CONTACT"] < len(fila) else "", None),
            "admission_date": parse_fecha(fila[COL["ADMISSION_DATE"]] if COL["ADMISSION_DATE"] < len(fila) else ""),
            "last_contact_date": parse_fecha(fila[COL["LAST_CONTACT"]] if COL["LAST_CONTACT"] < len(fila) else ""),
            "creado_por": "google_sheets",
        }
        leads.append(lead)
        
        if i % 500 == 0:
            print(f"  ... procesada fila {i}")
    
    print(f"✓ Filas completamente vacías saltadas: {filas_saltadas}")
    print(f"📝 Primeros 5 nombres extraídos:")
    for j in range(min(5, len(leads))):
        print(f"   {j+1}. {leads[j]['nombre']}")
    
    print(f"\n📊 Total leads a importar: {len(leads)}")
    return leads

def importar(leads):
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    print("\n🗑️  Limpiando datos existentes...")
    cur.execute("DELETE FROM historial_estados")
    cur.execute("DELETE FROM controles")
    cur.execute("DELETE FROM leads")
    conn.commit()
    
    print(f"\n📤 Insertando {len(leads)} leads...\n")
    insertados = 0
    errores = 0
    
    sql = """
        INSERT INTO leads (
            nombre, telefono, email, genero, categoria, canal,
            sales_status, comentarios, first_contact, admission_date,
            last_contact_date, creado_por, fecha_creacion
        ) VALUES (
            %(nombre)s, %(telefono)s, %(email)s, %(genero)s, %(categoria)s, %(canal)s,
            %(sales_status)s, %(comentarios)s, %(first_contact)s, %(admission_date)s,
            %(last_contact_date)s, %(creado_por)s, NOW()
        )
    """
    
    for lead in leads:
        try:
            cur.execute(sql, lead)
            insertados += 1
            if insertados % 200 == 0:
                conn.commit()
                print(f"  ✅ {insertados}/{len(leads)} insertados")
        except Exception as e:
            errores += 1
            if errores <= 10:
                print(f"  ❌ {lead['nombre'][:30]}: {str(e)[:100]}")
            conn.rollback()
            cur = conn.cursor()
    
    conn.commit()
    cur.close()
    conn.close()
    
    print("\n" + "="*60)
    print(f"  ✅ INSERTADOS: {insertados} de {len(leads)} leads")
    if errores:
        print(f"  ❌ ERRORES: {errores}")
    print("="*60)
    
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM leads")
    total = cur.fetchone()[0]
    print(f"\n📊 Verificación final: {total} leads en la tabla 'leads'")
    cur.close()
    conn.close()

if __name__ == "__main__":
    print("="*60)
    print("  STEMWELL CRM - IMPORTADOR (SOLO FILAS CON DATOS)")
    print("="*60)
    
    csv_path = sys.argv[1] if len(sys.argv) > 1 else CSV_FILE
    full_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), csv_path)
    
    if not os.path.exists(full_path):
        print(f"\n❌ Archivo no encontrado: {csv_path}")
        sys.exit(1)
    
    leads = leer_csv(full_path)
    if not leads:
        print("❌ No hay leads para importar")
        sys.exit(1)
    
    resp = input(f"\n⚠️  Se importarán {len(leads)} leads (borrando los actuales). ¿Continuar? (escribe 'SI'): ").strip()
    if resp.upper() != "SI":
        print("Cancelado")
        sys.exit(0)
    
    importar(leads)