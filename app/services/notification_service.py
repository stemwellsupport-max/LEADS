# app/services/notification_service.py
# -*- coding: utf-8 -*-
"""
Servicio de notificaciones para Stemwell CRM.
Versión corregida - Notificaciones asignadas correctamente por rol y relación con el lead.
"""
from datetime import datetime
from typing import List, Dict, Optional
from psycopg2.extras import RealDictCursor

# Tipos de notificación
NOTIF_LLAMADA_PENDIENTE = "llamada_pendiente"
NOTIF_CITA_VENCIDA_DOCTOR = "cita_vencida_doctor"
NOTIF_LEAD_DEVUELTO_ASESOR = "lead_devuelto_asesor"
NOTIF_TRATAMIENTO_CANCELADO = "tratamiento_cancelado"


# ══════════════════════════════════════════════════════════════
#  FUNCIONES BÁSICAS DE NOTIFICACIONES
# ══════════════════════════════════════════════════════════════

def validar_asignacion_notificacion(conn, lead_id, usuario_id, tipo):
    """
    Valida que el usuario tenga relación con el lead antes de crear notificación.
    Evita que las notificaciones lleguen a usuarios que no tienen relación con el paciente.
    """
    cur = conn.cursor()
    
    if tipo in [NOTIF_CITA_VENCIDA_DOCTOR, NOTIF_TRATAMIENTO_CANCELADO]:
        # Para doctores: verificar si es el doctor del lead O el doctor de alguna cita
        cur.execute("""
            SELECT EXISTS(
                SELECT 1 FROM leads l
                LEFT JOIN agenda_doctor ad ON l.id = ad.lead_id
                WHERE l.id = %s 
                  AND (l.doctor_id = %s OR ad.doctor_id = %s)
                LIMIT 1
            )
        """, (lead_id, usuario_id, usuario_id))
    elif tipo in [NOTIF_LLAMADA_PENDIENTE, NOTIF_LEAD_DEVUELTO_ASESOR]:
        # Para asesores: verificar si es el asesor asignado al lead
        cur.execute("""
            SELECT EXISTS(
                SELECT 1 FROM leads WHERE id = %s AND asesor_id = %s
                LIMIT 1
            )
        """, (lead_id, usuario_id))
    else:
        cur.close()
        return True  # Permitir otros tipos de notificación
    
    valido = cur.fetchone()[0]
    cur.close()
    
    if not valido:
        print(f"⚠️ [NOTIFICACIONES] Intento de crear notificación tipo '{tipo}' "
              f"para usuario {usuario_id} sin relación con lead {lead_id}")
    
    return valido


def crear_notificacion(conn, lead_id, tipo, asunto, mensaje, usuario_id, lead_name=None):
    """
    Crea una notificación pendiente con validación de asignación.
    Retorna el ID de la notificación creada o None si no se pudo crear.
    """
    # Validar que el usuario tenga relación con el lead
    if not validar_asignacion_notificacion(conn, lead_id, usuario_id, tipo):
        return None
    
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO notificaciones (lead_id, tipo, asunto, mensaje, fecha_envio, estado, usuario_id, lead_name)
        VALUES (%s, %s, %s, %s, NOW(), 'pendiente', %s, %s)
        RETURNING id
    """, (lead_id, tipo, asunto, mensaje, usuario_id, lead_name))
    nid = cur.fetchone()[0]
    conn.commit()
    cur.close()
    return nid


def resolver_notificacion(conn, notificacion_id, usuario_id):
    """Marca una notificación como resuelta."""
    cur = conn.cursor()
    cur.execute("""
        UPDATE notificaciones 
        SET estado = 'resuelta', resuelta_por = %s, fecha_resolucion = NOW()
        WHERE id = %s
    """, (usuario_id, notificacion_id))
    ok = cur.rowcount > 0
    conn.commit()
    cur.close()
    return ok


def resolver_todas(conn, usuario_id):
    """Resuelve todas las notificaciones pendientes de un usuario."""
    cur = conn.cursor()
    cur.execute("""
        UPDATE notificaciones 
        SET estado = 'resuelta', resuelta_por = %s, fecha_resolucion = NOW()
        WHERE usuario_id = %s AND estado = 'pendiente'
    """, (usuario_id, usuario_id))
    count = cur.rowcount
    conn.commit()
    cur.close()
    return count


def listar_notificaciones(conn, usuario_id, solo_pendientes=True):
    """Lista notificaciones de un usuario. Retorna lista de dicts."""
    cur = conn.cursor()
    q = """
        SELECT n.id, n.lead_id, n.tipo, n.asunto, n.mensaje, n.fecha_envio, n.estado,
               n.usuario_id, n.lead_name
        FROM notificaciones n
        WHERE n.usuario_id = %s
    """
    if solo_pendientes:
        q += " AND n.estado = 'pendiente'"
    q += " ORDER BY n.fecha_envio DESC LIMIT 50"
    cur.execute(q, (usuario_id,))
    rows = cur.fetchall()
    cols = ["id", "lead_id", "tipo", "asunto", "mensaje", "fecha_envio", "estado", "usuario_id", "lead_name"]
    resultado = []
    for row in rows:
        d = {}
        for i, col in enumerate(cols):
            val = row[i]
            if isinstance(val, datetime):
                val = val.isoformat()
            d[col] = val
        resultado.append(d)
    cur.close()
    return resultado


def contar_pendientes(conn, usuario_id):
    """Cuenta notificaciones pendientes de un usuario."""
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM notificaciones WHERE usuario_id = %s AND estado = 'pendiente'",
        (usuario_id,)
    )
    c = cur.fetchone()[0]
    cur.close()
    return c


def notificacion_existe(conn, lead_id, tipo, usuario_id):
    """Verifica si ya existe una notificación pendiente del mismo tipo para el mismo usuario."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id FROM notificaciones 
        WHERE lead_id = %s AND tipo = %s AND usuario_id = %s AND estado = 'pendiente'
        LIMIT 1
    """, (lead_id, tipo, usuario_id))
    ex = cur.fetchone() is not None
    cur.close()
    return ex


# ══════════════════════════════════════════════════════════════
#  AUTO-LIMPIEZA DE NOTIFICACIONES HUÉRFANAS
# ══════════════════════════════════════════════════════════════

def limpiar_notificaciones_huerfanas(conn):
    """
    Resuelve automáticamente notificaciones que ya no aplican:
    
    1. llamada_pendiente → Si el booked_call ya no está Pendiente o fecha futura
    2. cita_vencida_doctor → Si el lead ya no está en 'Scheduled Appointment'
    3. tratamiento_cancelado → Si el appointment_status ya no es 'Canceled'
    4. lead_devuelto_asesor → Si el medical_status ya no es 'Candidate Rejected'
    
    También elimina duplicados (conserva el más reciente).
    """
    total_resueltas = 0
    
    # 1. Resolver llamadas pendientes que ya no aplican
    cur = conn.cursor()
    cur.execute("""
        UPDATE notificaciones n
        SET estado = 'resuelta', 
            resuelta_por = n.usuario_id, 
            fecha_resolucion = NOW()
        FROM booked_calls bc
        WHERE n.lead_id = bc.lead_id
          AND n.tipo = 'llamada_pendiente'
          AND n.estado = 'pendiente'
          AND (
              bc.estado != 'Pendiente' 
              OR bc.fecha_llamada > NOW()
          )
    """)
    total_resueltas += cur.rowcount
    conn.commit()
    cur.close()
    
    # 2. Resolver citas vencidas que ya no aplican
    cur = conn.cursor()
    cur.execute("""
        UPDATE notificaciones n
        SET estado = 'resuelta', 
            resuelta_por = n.usuario_id, 
            fecha_resolucion = NOW()
        FROM leads l
        WHERE n.lead_id = l.id
          AND n.tipo = 'cita_vencida_doctor'
          AND n.estado = 'pendiente'
          AND l.sales_status NOT IN ('Scheduled Appointment', 'Appointment Scheduled')
    """)
    total_resueltas += cur.rowcount
    conn.commit()
    cur.close()
    
    # 3. Resolver tratamientos cancelados que ya no aplican
    cur = conn.cursor()
    cur.execute("""
        UPDATE notificaciones n
        SET estado = 'resuelta', 
            resuelta_por = n.usuario_id, 
            fecha_resolucion = NOW()
        FROM leads l
        WHERE n.lead_id = l.id
          AND n.tipo = 'tratamiento_cancelado'
          AND n.estado = 'pendiente'
          AND l.appointment_status != 'Canceled'
    """)
    total_resueltas += cur.rowcount
    conn.commit()
    cur.close()
    
    # 4. Resolver leads devueltos que ya no aplican
    cur = conn.cursor()
    cur.execute("""
        UPDATE notificaciones n
        SET estado = 'resuelta', 
            resuelta_por = n.usuario_id, 
            fecha_resolucion = NOW()
        FROM leads l
        WHERE n.lead_id = l.id
          AND n.tipo = 'lead_devuelto_asesor'
          AND n.estado = 'pendiente'
          AND l.medical_status != 'Candidate Rejected'
    """)
    total_resueltas += cur.rowcount
    conn.commit()
    cur.close()
    
    # 5. Eliminar duplicados (conserva el más reciente)
    cur = conn.cursor()
    cur.execute("""
        DELETE FROM notificaciones a
        USING notificaciones b
        WHERE a.lead_id = b.lead_id
          AND a.tipo = b.tipo
          AND a.usuario_id = b.usuario_id
          AND a.estado = 'pendiente'
          AND b.estado = 'pendiente'
          AND a.fecha_envio < b.fecha_envio
    """)
    duplicados = cur.rowcount
    conn.commit()
    cur.close()
    
    if total_resueltas > 0 or duplicados > 0:
        print(f"🧹 Auto-limpieza: {total_resueltas} notificaciones resueltas, {duplicados} duplicados eliminados")
    
    return total_resueltas + duplicados


# ══════════════════════════════════════════════════════════════
#  DETECCIÓN MASIVA DE NOTIFICACIONES (CORREGIDAS)
# ══════════════════════════════════════════════════════════════

def detectar_llamadas_pendientes(conn):
    """
    Encuentra booked_calls con fecha_llamada <= NOW() y estado = 'Pendiente'.
    Crea notificación para el asesor si no existe ya.
    Solo notifica al asesor asignado al lead.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT bc.id, bc.lead_id, bc.asesor_id, bc.fecha_llamada, l.nombre
        FROM booked_calls bc
        JOIN leads l ON bc.lead_id = l.id
        WHERE bc.estado = 'Pendiente' 
          AND bc.fecha_llamada <= NOW()
          AND bc.asesor_id IS NOT NULL
    """)
    calls = cur.fetchall()
    cur.close()

    creadas = 0
    for c in calls:
        _, lead_id, asesor_id, fecha, nombre = c
        
        # Solo notificar si el asesor de la llamada está asignado al lead
        if not notificacion_existe(conn, lead_id, NOTIF_LLAMADA_PENDIENTE, asesor_id):
            hora = fecha.strftime("%H:%M") if fecha else ""
            nid = crear_notificacion(
                conn, lead_id, NOTIF_LLAMADA_PENDIENTE,
                "📞 Callback pendiente",
                f"Debes llamar a {nombre} ahora. Agendada para las {hora}.",
                asesor_id, nombre
            )
            if nid:
                creadas += 1
    return creadas


def detectar_citas_vencidas_doctor(conn):
    """
    CORREGIDO: Encuentra citas en agenda_doctor con fecha_inicio < NOW() 
    cuyo lead sigue en sales_status de cita agendada.
    Notifica al doctor CORRECTO:
    - Si el doctor de la cita existe, notifica a él
    - Si no, notifica al doctor asignado al lead
    - Si ambos existen y son diferentes, notifica a AMBOS con mensajes apropiados
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT ad.id, ad.lead_id, ad.doctor_id as cita_doctor_id, 
               ad.fecha_inicio, l.nombre, l.doctor_id as lead_doctor_id
        FROM agenda_doctor ad
        JOIN leads l ON ad.lead_id = l.id
        WHERE ad.fecha_inicio <= NOW()
          AND l.sales_status IN ('Scheduled Appointment', 'Appointment Scheduled')
    """)
    citas = cur.fetchall()
    cur.close()

    creadas = 0
    doctores_notificados = set()  # Para evitar duplicados
    
    for c in citas:
        _, lead_id, cita_doctor_id, fecha, nombre, lead_doctor_id = c
        fstr = fecha.strftime("%d/%m/%Y %H:%M") if fecha else ""
        
        # Lista de doctores a notificar (sin duplicados)
        doctores_a_notificar = []
        if cita_doctor_id:
            doctores_a_notificar.append(cita_doctor_id)
        if lead_doctor_id and lead_doctor_id != cita_doctor_id:
            doctores_a_notificar.append(lead_doctor_id)
        
        for doctor_id in doctores_a_notificar:
            # Evitar duplicados en esta ejecución
            key = (lead_id, NOTIF_CITA_VENCIDA_DOCTOR, doctor_id)
            if key in doctores_notificados:
                continue
            doctores_notificados.add(key)
            
            if not notificacion_existe(conn, lead_id, NOTIF_CITA_VENCIDA_DOCTOR, doctor_id):
                # Personalizar mensaje según el rol
                if doctor_id == cita_doctor_id and doctor_id != lead_doctor_id:
                    mensaje = (
                        f"{nombre} tuvo cita contigo el {fstr} y sigue en 'Scheduled Appointment'. "
                        f"Actualiza el estado del paciente."
                    )
                elif doctor_id == lead_doctor_id and doctor_id != cita_doctor_id:
                    mensaje = (
                        f"{nombre} (tu paciente) tuvo cita con otro doctor el {fstr} "
                        f"y sigue en 'Scheduled Appointment'. Coordina la actualización del estado."
                    )
                else:
                    mensaje = (
                        f"{nombre} tuvo cita el {fstr} y sigue en 'Scheduled Appointment'. "
                        f"Actualiza el estado."
                    )
                
                nid = crear_notificacion(
                    conn, lead_id, NOTIF_CITA_VENCIDA_DOCTOR,
                    "⚠️ Cita vencida sin gestionar",
                    mensaje,
                    doctor_id, nombre
                )
                if nid:
                    creadas += 1
    
    return creadas


def detectar_leads_devueltos_asesor(conn):
    """
    CORREGIDO: Detecta leads cuyo medical_status fue cambiado a 'Candidate Rejected'
    y notifica al asesor asignado para que haga seguimiento.
    Solo notifica al asesor actual del lead.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT l.id, l.nombre, l.asesor_id, l.doctor_id
        FROM leads l
        WHERE l.medical_status = 'Candidate Rejected'
          AND l.asesor_id IS NOT NULL
          AND l.sales_status NOT IN ('Lost', 'Won')
    """)
    leads = cur.fetchall()
    cur.close()

    creadas = 0
    for l in leads:
        lead_id, nombre, asesor_id, doctor_id = l
        
        if not notificacion_existe(conn, lead_id, NOTIF_LEAD_DEVUELTO_ASESOR, asesor_id):
            # Personalizar mensaje según si hay doctor asignado
            if doctor_id and doctor_id != asesor_id:
                mensaje = (
                    f"{nombre} fue rechazado como candidato por el doctor asignado. "
                    f"Contacta al paciente para dar seguimiento y explorar otras opciones."
                )
            else:
                mensaje = (
                    f"{nombre} fue rechazado como candidato. "
                    f"Contacta al paciente para dar seguimiento."
                )
            
            nid = crear_notificacion(
                conn, lead_id, NOTIF_LEAD_DEVUELTO_ASESOR,
                "🔄 Lead devuelto por el doctor",
                mensaje,
                asesor_id, nombre
            )
            if nid:
                creadas += 1
    
    return creadas


def detectar_tratamientos_cancelados(conn):
    """
    CORREGIDO: Detecta leads cuyo appointment_status cambió a 'Canceled'.
    Notifica tanto al asesor como al doctor asignado (si existen y son diferentes).
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT l.id, l.nombre, l.asesor_id, l.doctor_id, l.appointment_status
        FROM leads l
        WHERE l.appointment_status = 'Canceled'
          AND l.sales_status NOT IN ('Lost', 'Won')
    """)
    leads = cur.fetchall()
    cur.close()

    creadas = 0
    for l in leads:
        lead_id, nombre, asesor_id, doctor_id, app_status = l
        
        # 1. Notificar al asesor (si existe)
        if asesor_id:
            if not notificacion_existe(conn, lead_id, NOTIF_TRATAMIENTO_CANCELADO, asesor_id):
                nid = crear_notificacion(
                    conn, lead_id, NOTIF_TRATAMIENTO_CANCELADO,
                    "❌ Cita cancelada - Seguimiento requerido",
                    f"La cita de {nombre} fue cancelada. Como asesor, revisa el caso y contacta al paciente para reprogramar.",
                    asesor_id, nombre
                )
                if nid:
                    creadas += 1
        
        # 2. Notificar al doctor (si existe y es diferente al asesor)
        if doctor_id and doctor_id != asesor_id:
            if not notificacion_existe(conn, lead_id, NOTIF_TRATAMIENTO_CANCELADO, doctor_id):
                nid = crear_notificacion(
                    conn, lead_id, NOTIF_TRATAMIENTO_CANCELADO,
                    "❌ Cita cancelada - Paciente tuyo",
                    f"La cita de {nombre} (tu paciente) fue cancelada. Coordina con el asesor si es necesario.",
                    doctor_id, nombre
                )
                if nid:
                    creadas += 1
    
    return creadas


# ══════════════════════════════════════════════════════════════
#  FUNCIÓN PRINCIPAL DE DETECCIÓN
# ══════════════════════════════════════════════════════════════

def detectar_y_crear_notificaciones(conn):
    """
    Ejecuta primero la limpieza automática y luego todas las detecciones masivas.
    Retorna el total de notificaciones creadas.
    """
    print("🔍 [NOTIFICACIONES] Iniciando ciclo de detección y limpieza...")
    
    # 1. PRIMERO LIMPIAR notificaciones que ya no aplican
    limpiadas = limpiar_notificaciones_huerfanas(conn)
    
    # 2. LUEGO detectar nuevas notificaciones
    t1 = detectar_llamadas_pendientes(conn)
    t2 = detectar_citas_vencidas_doctor(conn)
    t3 = detectar_leads_devueltos_asesor(conn)
    t4 = detectar_tratamientos_cancelados(conn)
    
    total_creadas = t1 + t2 + t3 + t4
    
    if total_creadas > 0:
        print(f"✅ [NOTIFICACIONES] Creadas: {total_creadas} nuevas "
              f"(Llamadas: {t1}, Citas vencidas: {t2}, Leads devueltos: {t3}, Tratamientos cancelados: {t4})")
    else:
        print("ℹ️ [NOTIFICACIONES] No se encontraron nuevas notificaciones para crear")
    
    return total_creadas


# ══════════════════════════════════════════════════════════════
#  FUNCIONES DE DEPURACIÓN Y DIAGNÓSTICO
# ══════════════════════════════════════════════════════════════

def diagnosticar_asignaciones(conn):
    """
    Función de diagnóstico: Muestra estadísticas de asignación de notificaciones
    para identificar posibles problemas de notificaciones mal asignadas.
    """
    print("\n📊 DIAGNÓSTICO DE ASIGNACIONES DE NOTIFICACIONES")
    print("=" * 60)
    
    cur = conn.cursor()
    
    # 1. Notificaciones sin relación válida
    cur.execute("""
        SELECT n.id, n.lead_id, n.tipo, n.usuario_id, n.lead_name,
               l.asesor_id, l.doctor_id
        FROM notificaciones n
        LEFT JOIN leads l ON n.lead_id = l.id
        WHERE n.estado = 'pendiente'
          AND (
              (n.tipo = 'llamada_pendiente' AND l.asesor_id != n.usuario_id)
              OR
              (n.tipo = 'cita_vencida_doctor' AND l.doctor_id != n.usuario_id)
              OR
              (n.tipo = 'lead_devuelto_asesor' AND l.asesor_id != n.usuario_id)
              OR
              (n.tipo = 'tratamiento_cancelado' AND l.asesor_id != n.usuario_id AND l.doctor_id != n.usuario_id)
          )
        LIMIT 20
    """)
    mal_asignadas = cur.fetchall()
    
    if mal_asignadas:
        print(f"\n⚠️ Se encontraron {len(mal_asignadas)} notificaciones posiblemente mal asignadas:")
        for n in mal_asignadas:
            print(f"  - ID:{n[0]} | Lead:{n[1]} | Tipo:{n[2]} | Usuario:{n[3]} | "
                  f"Asesor real:{n[5]} | Doctor real:{n[6]}")
    else:
        print("✅ No se encontraron notificaciones mal asignadas")
    
    # 2. Resumen por tipo
    cur.execute("""
        SELECT tipo, COUNT(*) as total, 
               COUNT(DISTINCT usuario_id) as usuarios_unicos
        FROM notificaciones
        WHERE estado = 'pendiente'
        GROUP BY tipo
        ORDER BY total DESC
    """)
    resumen = cur.fetchall()
    
    print(f"\n📈 RESUMEN DE NOTIFICACIONES PENDIENTES:")
    for r in resumen:
        print(f"  - {r[0]}: {r[1]} notificaciones, {r[2]} usuarios únicos")
    
    cur.close()
    return {
        "mal_asignadas": len(mal_asignadas),
        "resumen": [{"tipo": r[0], "total": r[1], "usuarios": r[2]} for r in resumen]
    }