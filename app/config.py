import os
import urllib.parse
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    url = urllib.parse.urlparse(DATABASE_URL)
    DB_HOST = url.hostname or "localhost"
    DB_PORT = url.port or 5432
    DB_NAME = url.path.lstrip("/") or "stemwell"
    DB_USER = url.username or "crm_user"
    DB_PASSWORD = url.password or "crm2024"
else:
    DB_HOST = "localhost"
    DB_PORT = 5432
    DB_NAME = "stemwell"
    DB_USER = "crm_user"
    DB_PASSWORD = "crm2024"

# NUEVA LÍNEA:
DB_CLIENT_ENCODING = os.getenv("CLIENT_ENCODING", "UTF8")

APP_NAME = os.getenv("APP_NAME", "CRM Stemwell")
DEBUG = os.getenv("DEBUG", "True").lower() in ("true", "1", "yes")
BACKOFFICE_EMAIL = os.getenv("BACKOFFICE_EMAIL", "stemwellsupport@gmail.com")
CALENDLY_WEBHOOK_SIGNING_SECRET = os.getenv("CALENDLY_WEBHOOK_SIGNING_SECRET", "")
