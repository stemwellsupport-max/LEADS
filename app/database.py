import psycopg2

def get_db():
    return psycopg2.connect(
        host="localhost",
        port=5432,
        database="stemwell",
        user="crm_user",
        password="crm2024",          # contraseña que SÍ funciona
        client_encoding="latin1"      # evita el error Unicode
    )