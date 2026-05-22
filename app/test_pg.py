import psycopg2

passwords = ["crm2024", "crm_password_2024"]

for pw in passwords:
    try:
        conn = psycopg2.connect(
            host="localhost",
            port=5432,
            database="stemwell",
            user="crm_user",
            password=pw,
            client_encoding="latin1"
        )
        print(f"Conectado con {pw}")
        conn.close()
        break
    except psycopg2.OperationalError as e:
        print(f"Fallo con {pw}: {e}")
    except Exception as e:
        print(f"Error inesperado con {pw}: {e}")