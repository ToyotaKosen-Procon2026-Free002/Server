import psycopg
from config import settings

def get_connection():
    connection = psycopg.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        dbname=settings.DB_NAME,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD
    )

    try:
        yield connection
    finally:
        connection.close()