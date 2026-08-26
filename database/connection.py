import psycopg
from psycopg.rows import dict_row
from psycopg.rows import DictRow
from config import settings
from models import User, UpdateUser

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

def get_or_create_user(db: psycopg.Connection, firebase_uid: str, email: str, name: str) -> User:
    """
    Firebase UIDをもとにDBからユーザーを取得し、存在しなければ作成して返す
    """

    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
                INSERT INTO users (firebase_uid, email, display_name)
                VALUES (%s, %s, %s)
                ON CONFLICT (firebase_uid)
                DO UPDATE SET firebase_uid = EXCLUDED.firebase_uid
                RETURNING id, firebase_uid, email, display_name;
            """,
            (firebase_uid, email or "", name or "")
        )
        user_row = cur.fetchone()
        assert user_row is not None

        cur.execute(
            """
            SELECT notify_token
            FROM user_notify_token
            WHERE user_id = %s;
            """,
            (user_row["id"],)
        )
        token_rows = cur.fetchall()
        notify_tokens = [t["notify_token"] for t in token_rows]

        db.commit()

        return User(
            display_name=user_row["display_name"],
            email=user_row["email"],
            firebase_uid=user_row["firebase_uid"],
            notify_tokens=notify_tokens
        )

def update_user(db: psycopg.Connection, update_user: UpdateUser, current_user: User):
    """
    ユーザー情報の更新
    """

    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            UPDATE users
            SET
                display_name = COALESCE(%s, display_name),
                email = COALESCE(%s, email)
            WHERE firebase_uid = %s
            RETURNING id, firebase_uid, COALESCE(email, '') AS email, COALESCE(display_name, '') AS display_name;
            """,
            (update_user.display_name, update_user.email, current_user.firebase_uid)
        )
        user_row = cur.fetchone()
        assert user_row is not None

        cur.execute(
            "SELECT token_value FROM user_notify_token WHERE user_id = %s;",
            (user_row["id"],)
        )
        token_rows = cur.fetchall()
        notify_tokens = [t["token_value"] for t in token_rows]

        db.commit()

        return User(
            display_name=user_row["display_name"],
            email=user_row["email"],
            firebase_uid=user_row["firebase_uid"],
            notify_tokens=notify_tokens
        )