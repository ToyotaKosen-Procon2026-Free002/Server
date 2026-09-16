from fastapi import HTTPException, status
import psycopg
from psycopg.rows import dict_row
from config import settings
from models import Device, DeviceSeal, DeviceUpdateRequest, Seal, SealPackResponse, SealPackRootTable, SosRequest, User, UpdateUser
from typing import Optional

from notify import send_sos_notification

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
                RETURNING id, firebase_uid, email, display_name, roll;
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
        id=str(user_row["id"]),
        display_name=user_row["display_name"],
        email=user_row["email"],
        firebase_uid=user_row["firebase_uid"],
        notify_tokens=notify_tokens,
        roll=user_row["roll"]
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
                roll = COALESCE(%s, roll)
            WHERE firebase_uid = %s
            RETURNING id, firebase_uid, COALESCE(email, '') AS email, COALESCE(display_name, '') AS display_name, COALESCE(roll, '') AS roll;
            """,
            (update_user.display_name, update_user.email, update_user.roll, current_user.firebase_uid)
        )
        user_row = cur.fetchone()
        assert user_row is not None

        cur.execute(
            "SELECT notify_token FROM user_notify_token WHERE user_id = %s;",
            (user_row["id"],)
        )
        token_rows = cur.fetchall()
        notify_tokens = [t["notify_token"] for t in token_rows]

        db.commit()

    return User(
        id=user_row["id"],
        display_name=user_row["display_name"],
        email=user_row["email"],
        firebase_uid=user_row["firebase_uid"],
        notify_tokens=notify_tokens,
        roll=user_row["roll"]
    )

def init_new_device(db: psycopg.Connection, device_id: str, public_key: bytes, name: Optional[str] = None) -> Device | None:
    """
    子機から送られてきた情報を初期登録する。
    """

    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO devices (id, public_key, name)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            RETURNING id, user_id, name, public_key, coins, battery, last_timestamp;
            """,
            (device_id, public_key, name or device_id)
        )

        device = cur.fetchone()

        if device is None:
            cur.execute("SELECT id, user_id, name, coins FROM devices WHERE id = %s;", (device_id,))
            device = cur.fetchone()

        db.commit()

    if device:
        return Device(
            id=str(device["id"]),
            owner=str(device["user_id"]) if device["user_id"] else None,
            public_key=bytes(device["public_key"]),
            name=device["name"],
            coins=device["coins"],
            battery=device["battery"],
            last_timestamp=device["last_timestamp"]
        )
    else: return None


def register_device(db: psycopg.Connection, device_id: str, user: User):
    """
    初期登録のみされたデバイスをユーザーに割り当てる。
    """

    device = get_device(db, device_id)
    if device is not None and device.owner is None:
        with db.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE devices
                SET user_id = %s
                WHERE id = %s AND user_id IS NULL
                RETURNING id, user_id, name, public_key, coins, battery, last_timestamp;
                """,
                (user.id, device_id)
            )
            row = cur.fetchone()
            db.commit()

        if row is None:
            return None

        return Device(
            id=str(row["id"]),
            owner=str(row["user_id"]) if row["user_id"] else None,
            public_key=bytes(row["public_key"]),
            name=row["name"],
            coins=row["coins"],
            battery=row["battery"],
            last_timestamp=row["last_timestamp"]
        )
    else: return None


def get_device(db: psycopg.Connection, device_id: str) -> Device | None:
    """
    デバイスidからデバイスオブジェクトを取得する。
    """

    with db.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT id, user_id, name, public_key, coins, battery, last_timestamp FROM devices WHERE id = %s;", (device_id,))
        device = cur.fetchone()

        db.commit()
    
    if device:
        return Device(
            id=str(device["id"]),
            owner=str(device["user_id"]) if device["user_id"] else None,
            public_key=bytes(device["public_key"]),
            name=device["name"],
            coins=device["coins"],
            battery=device["battery"],
            last_timestamp=device["last_timestamp"]
        )
    else: return None


def get_devices(db: psycopg.Connection, user: User) -> list[Device]:
    """
    ユーザーに割り当てられているデバイス一覧を返す。
    """

    with db.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT id, user_id, name, public_key, coins, battery, last_timestamp FROM devices WHERE user_id = %s;", (user.id,))
        rows = cur.fetchall()

    return [
        Device(
            id=str(row["id"]),
            owner=str(row["user_id"]) if row["user_id"] else None,
            name=row["name"],
            public_key=bytes(row["public_key"]),
            coins=row["coins"],
            battery=row["battery"],
            last_timestamp=row["last_timestamp"]
        ) for row in rows
    ]


def update_device_status(db: psycopg.Connection, request: DeviceUpdateRequest, origin_device: Device):
    """
    受け取った情報更新リクエストに応じて、データベースを更新する。
    """

    with db.cursor(row_factory=dict_row) as cur:
        for comm in request.nearby_communications:
            opponent_device_id = None if comm.partner_is_gateway else comm.partner_id
            gateway_id = comm.partner_id if comm.partner_is_gateway else None

            cur.execute(
                """
                INSERT INTO encounters (request_id, device_id, opponent_device_id, gateway_id, detected_at, send_seal_id, receive_seal_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (request_id) DO NOTHING;
                """,
                (comm.event_id, origin_device.id, opponent_device_id, gateway_id, comm.timestamp, comm.send_seal_id, comm.receive_seal_id)
            )
            inserted = cur.fetchone()

            if inserted is not None:
                if comm.send_seal_id:
                    cur.execute(
                        """
                        DELETE FROM device_seals
                        WHERE id = (
                            SELECT id FROM device_seals
                            WHERE device_id = %s AND seal_id = %s
                            ORDER BY
                                CASE status_id
                                    WHEN 2 THEN 1
                                    WHEN 0 THEN 2
                                    WHEN 1 THEN 3
                                    ELSE 4
                                END,
                                id
                            LIMIT 1
                        );
                        """,
                        (origin_device.id, comm.send_seal_id)
                    )

                if comm.receive_seal_id:
                    cur.execute(
                        """
                        INSERT INTO device_seals (device_id, seal_id, status_id)
                        VALUES (%s, %s, 0);
                        """,
                        (origin_device.id, comm.receive_seal_id)
                    )
        
        db.commit()


def get_device_notify_tokens(db: psycopg.Connection, device: Device) -> list[str]:
    if device.owner:
        with db.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT notify_token
                FROM user_notify_token
                WHERE user_id = %s;
                """,
                (device.owner, )
            )
            token_rows = cur.fetchall()
            tokens = [row["notify_token"] for row in token_rows]
        return tokens
    else:
        return []



def received_sos(db: psycopg.Connection, request: SosRequest, child_device: Device):
    """
    受け取ったSOSをデータベースに登録する。
    """

    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO sos_events (request_id, device_id, sos_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (request_id) DO UPDATE SET request_id = EXCLUDED.request_id
            RETURNING id, notified;
            """,
            (request.event_id, child_device.id, request.trigger_timestamp)
        )
        sos_row = cur.fetchone()

        if sos_row:
            sos_id = sos_row["id"]
            is_notified = sos_row["notified"]

            cur.execute(
                """
                INSERT INTO sos_receivers (sos_id, gateway_id, received_at)
                VALUES (%s, %s, %s);
                """,
                (sos_id, request.gateway_id, request.receive_timestamp)
            )

            if not is_notified and child_device.owner:
                tokens = get_device_notify_tokens(db, child_device)
                if tokens:
                    try:
                        success = send_sos_notification(tokens, child_device.name)
                        if success:
                            cur.execute(
                                """
                                UPDATE sos_events
                                SET notified = TRUE
                                WHERE id = %s;
                                """,
                                (sos_id, )
                            )
                    except Exception as e:
                        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="SOSの送信に失敗しました。: [{sos_id}] {e}")

        db.commit()


def get_seal_packs(db: psycopg.Connection) -> list[SealPackResponse]:
    """
    現在開催中のシールパック一覧を返す。
    """

    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT 
                sp.id,
                sp.name,
                sp.description,
                sp.once_price,
                sp.image_path,
                COALESCE(
                    json_agg(
                        json_build_object(
                            'seal_id', sprt.seal_id::text,
                            'weight', sprt.weight
                        )
                    ) FILTER (WHERE sprt.id IS NOT NULL),
                    '[]'::json
                ) AS root_table
            FROM seal_packs sp
            LEFT JOIN seal_packs_root_tables sprt ON sp.id = sprt.seal_pack_id
            WHERE sp.is_opened = TRUE
            GROUP BY sp.id;
            """
        )
        rows = cur.fetchall()

    return [
        SealPackResponse(
            id=str(row["id"]),
            name=row["name"],
            description=row["description"],
            once_price=row["once_price"],
            image_path=row["image_path"],
            root_table=[
                SealPackRootTable(
                    seal_id=item["seal_id"],
                    weight=item["weight"]
                )
                for item in row["root_table"]
            ]
        )
        for row in rows
    ]


def get_device_seals(db: psycopg.Connection, device: Device) -> list[DeviceSeal]:
    """
    デバイスが所持しているシール一覧を返す。
    """

    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT 
                id,
                device_id,
                seal_id,
                status_id,
                book_page,
                book_x,
                book_y,
                book_rotation,
                book_scale
            FROM device_seals
            WHERE device_id = %s;
            """,
            (device.id,)
        )
        rows = cur.fetchall()

    return [
        DeviceSeal(
            id=str(row["id"]),
            device_id=str(row["device_id"]),
            seal_id=str(row["seal_id"]),
            status_id=row["status_id"],
            book_page=row["book_page"],
            book_x=row["book_x"],
            book_y=row["book_y"],
            book_rotation=row["book_rotation"],
            book_scale=row["book_scale"],
        )
        for row in rows
    ]


def get_device_trading_seals(db: psycopg.Connection, device: Device) -> list[DeviceSeal]:
    """
    デバイスが交換に出しているシールを取得する。
    """

    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT 
                id,
                device_id,
                seal_id,
                status_id,
                book_page,
                book_x,
                book_y,
                book_rotation,
                book_scale
            FROM device_seals
            WHERE device_id = %s AND status_id = 2;
            """,
            (device.id,)
        )
        rows = cur.fetchall()
    
    return [
        DeviceSeal(
            id=str(row["id"]),
            device_id=str(row["device_id"]),
            seal_id=str(row["seal_id"]),
            status_id=row["status_id"],
            book_page=row["book_page"],
            book_x=row["book_x"],
            book_y=row["book_y"],
            book_rotation=row["book_rotation"],
            book_scale=row["book_scale"],
        )
        for row in rows
    ]


def add_notify_token(db: psycopg.Connection, token: str, user: User):
    """
    ユーザーにプッシュ通知用トークンを追加する。
    """

    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO user_notify_token (user_id, notify_token)
            VALUES (%s, %s)
            ON CONFLICT (notify_token) 
            DO UPDATE SET user_id = EXCLUDED.user_id;
            """,
            (user.id, token)
        )

    db.commit()


def delete_notify_token(db: psycopg.Connection, token: str, user: User):
    """
    ユーザーのプッシュ通知用トークンを削除する。
    """

    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            DELETE FROM user_notify_token
            WHERE user_id = %s AND notify_token = %s;
            """,
            (user.id, token)
        )

    db.commit()


def get_seals(db: psycopg.Connection) -> list[Seal]:
    """
    存在するシールの一覧を返す。
    """

    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT 
                id,
                name,
                description,
                rarity,
                image_path
            FROM seals;
            """
        )
        rows = cur.fetchall()

    return [
        Seal(
            id=str(row["id"]),
            name=row["name"],
            description=row["description"],
            rarity=row["rarity"],
            image_path=row["image_path"],
        )
        for row in rows
    ]