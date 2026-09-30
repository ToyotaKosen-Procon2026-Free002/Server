from datetime import date, timedelta
import random
from fastapi import HTTPException, status
import psycopg
from psycopg.rows import dict_row
from config import settings
from models import Device, DeviceInfoPatchRequest, DeviceSeal, DeviceUpdateRequest, Gateway, GatewayInfoPatchRequest, GatewayInitRequest, GetNearbyCommunicationsRequest, GetSosRequest, NearbyCommunication, OriginalSealRequest, Seal, SealPackResponse, SealPackRootTable, SosInfo, SosReceiver, SosRequest, User, UpdateUser, WeeklyMissionItem
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
                email = COALESCE(%s, email),
                roll = COALESCE(%s, roll)
            WHERE firebase_uid = %s
            RETURNING id, firebase_uid, COALESCE(email, '') AS email, COALESCE(display_name, '') AS display_name, COALESCE(roll, 0) AS roll;
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
        id=str(user_row["id"]),
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


def init_new_gateway(db: psycopg.Connection, request: GatewayInitRequest) -> Gateway | None:
    """
    親機から送られてきた情報で初期登録する（既存の場合は最新の公開鍵・名前で更新して取得）。
    """

    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO gateways (id, public_key, name)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            RETURNING 
                id, 
                public_key, 
                name, 
                distribute_seal_id, 
                user_id,
                ST_Y(location::geometry) AS latitude,
                ST_X(location::geometry) AS longitude;
            """,
            (request.id, request.public_key, request.name)
        )
        row = cur.fetchone()
        db.commit()

    if row:
        return Gateway(
            id=str(row["id"]),
            public_key=bytes(row["public_key"]),
            name=row["name"],
            distribute_seal_id=str(row["distribute_seal_id"]) if row["distribute_seal_id"] else None,
            user_id=str(row["user_id"]) if row["user_id"] else None,
            latitude=row["latitude"],
            longitude=row["longitude"],
        )
    else: return None


def register_device(db: psycopg.Connection, device_id: str, user: User) -> Device | None:
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


def register_gateway(db: psycopg.Connection, gateway_id: str, user: User) -> Gateway | None:
    """
    初期登録のみされた親機をユーザーに割り当てる。
    """

    gateway = get_gateway(db, gateway_id)
    if gateway:
        with db.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE gateways
                SET user_id = %s
                WHERE id = %s AND user_id IS NULL
                RETURNING id, user_id, name, public_key, distribute_seal_id, ST_Y(location::geometry) AS latitude, ST_X(location::geometry) AS longitude;
                """,
                (user.id, gateway_id)
            )
            row = cur.fetchone()
        db.commit()

        if row:
            return Gateway(
                id=str(row["id"]),
                public_key=bytes(row["public_key"]),
                user_id=str(row["user_id"]),
                name=row["name"],
                distribute_seal_id=str(row["distribute_seal_id"]),
                latitude=row["latitude"],
                longitude=row["longitude"]
            )
        else: return None
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
                image_path,
                owner
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
            owner=row["owner"]
        )
        for row in rows
    ]


def get_gateway(db: psycopg.Connection, gateway_id: str) -> Gateway | None:
    """
    idから親機を取得する。
    """

    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, user_id, name, public_key, distribute_seal_id, ST_Y(location::geometry) AS latitude, ST_X(location::geometry) AS longitude
            FROM gateways
            WHERE id = %s;
            """,
            (gateway_id, )
        )
        row = cur.fetchone()

    if row:
        return Gateway(
            id=str(row["id"]),
            public_key=bytes(row["public_key"]),
            user_id=str(row["user_id"]),
            name=row["name"],
            distribute_seal_id=str(row["distribute_seal_id"]),
            latitude=row["latitude"],
            longitude=row["longitude"]
        )
    else: return None


def get_gateways(db: psycopg.Connection, user: User) -> list[Gateway]:
    """
    ユーザーの所有している親機一覧を返す。
    """

    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, user_id, name, public_key, distribute_seal_id, ST_Y(location::geometry) AS latitude, ST_X(location::geometry) AS longitude
            FROM gateways
            WHERE user_id = %s;
            """,
            (user.id, )
        )
        rows = cur.fetchall()

    return [
        Gateway(
            id=str(row["id"]),
            public_key=bytes(row["public_key"]),
            user_id=str(row["user_id"]),
            name=row["name"],
            distribute_seal_id=str(row["distribute_seal_id"]),
            latitude=row["latitude"],
            longitude=row["longitude"]
        )
        for row in rows
    ]


def get_all_gateways(db: psycopg.Connection) -> list[Gateway]:
    """
    データベースに登録されている親機一覧を返す。
    """

    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, user_id, name, public_key, distribute_seal_id, ST_Y(location::geometry) AS latitude, ST_X(location::geometry) AS longitude
            FROM gateways;
            """
        )
        rows = cur.fetchall()

    return [
        Gateway(
            id=str(row["id"]),
            public_key=bytes(row["public_key"]),
            user_id=str(row["user_id"]),
            name=row["name"],
            distribute_seal_id=str(row["distribute_seal_id"]),
            latitude=row["latitude"],
            longitude=row["longitude"]
        )
        for row in rows
    ]


def get_nearby_communications_log(db: psycopg.Connection, request: GetNearbyCommunicationsRequest) -> list[NearbyCommunication]:
    """
    指定されたデバイスの指定された期間のすれ違いログを返す。
    """

    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT 
                request_id,
                device_id,
                opponent_device_id,
                gateway_id,
                send_seal_id,
                receive_seal_id,
                detected_at
            FROM encounters
            WHERE device_id = %s AND detected_at BETWEEN %s AND %s
            ORDER BY detected_at DESC;
            """,
            (request.device_id, request.start_at, request.end_at)
        )
        rows = cur.fetchall()

    return [
        NearbyCommunication(
            event_id=str(row["request_id"]),
            my_id=str(row["device_id"]),
            partner_id=str(row["gateway_id"] or row["opponent_device_id"]),
            partner_is_gateway=row["gateway_id"] is not None,
            send_seal_id=str(row["send_seal_id"]) if row["send_seal_id"] else None,
            receive_seal_id=str(row["receive_seal_id"]) if row["receive_seal_id"] else None,
            timestamp=row["detected_at"],
            signature=b""  # 署名は検証用にのみ使用しDBに保存していないため空バイト列を返却
        )
        for row in rows
    ]


def get_sos_log(db: psycopg.Connection, request: GetSosRequest) -> list[SosInfo]:
    """
    指定されたデバイスの指定された期間のSOSログを返す。
    """
    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT 
                se.request_id,
                se.device_id,
                se.sos_at,
                COALESCE(MIN(sr.received_at), se.sos_at) AS receive_timestamp,
                se.notified,
                COALESCE(
                    json_agg(
                        json_build_object(
                            'event_id', se.request_id::text,
                            'gateway_id', sr.gateway_id::text,
                            'received_at', sr.received_at
                        )
                    ) FILTER (WHERE sr.id IS NOT NULL),
                    '[]'::json
                ) AS receivers
            FROM sos_events se
            LEFT JOIN sos_receivers sr ON se.id = sr.sos_id
            WHERE se.device_id = %s AND se.sos_at BETWEEN %s AND %s
            GROUP BY se.id, se.request_id, se.device_id, se.sos_at, se.notified
            ORDER BY se.sos_at DESC;
            """,
            (request.device_id, request.start_at, request.end_at)
        )
        rows = cur.fetchall()

    return [
        SosInfo(
            event_id=str(row["request_id"]),
            child_device_id=str(row["device_id"]),
            trigger_timestamp=row["sos_at"],
            receive_timestamp=row["receive_timestamp"],
            notified=row["notified"],
            receivers=[
                SosReceiver(
                    event_id=item["event_id"],
                    gateway_id=item["gateway_id"],
                    received_at=item["received_at"]
                )
                for item in row["receivers"]
            ]
        )
        for row in rows
    ]


def patch_device_info(db: psycopg.Connection, request: DeviceInfoPatchRequest) -> None:
    """
    指定したデバイスの情報を更新する。
    """

    with db.cursor() as cur:
        cur.execute(
            """
            UPDATE devices
            SET name = %s
            WHERE id = %s;
            """,
            (request.name, request.device_id)
        )
        db.commit()


def patch_gateway_info(db: psycopg.Connection, request: GatewayInfoPatchRequest) -> None:
    """
    指定した親機の情報を更新する。
    """
    with db.cursor() as cur:
        cur.execute(
            """
            UPDATE gateways
            SET 
                name = %s,
                distribute_seal_id = %s,
                location = ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography
            WHERE id = %s;
            """,
            (
                request.name,
                request.distribute_seal_id,
                request.longitude,  # PostGISのMakePointは (経度, 緯度) の順
                request.latitude,
                request.device_id,
            )
        )
        db.commit()


def get_current_week_start() -> date:
    """
    直前の月曜日の月日を取得する関数。
    """

    today = date.today()
    # today.weekday() は月曜=0, 日曜=6
    return today - timedelta(days=today.weekday())


def get_or_create_weekly_missions(db: psycopg.Connection, device_id: str) -> list[WeeklyMissionItem]:
    """
    指定したデバイスのウィークリーミッションを、取得する。
    なければ作成して返す。
    """

    week_start = get_current_week_start()

    with db.cursor(row_factory=dict_row) as cur:
        # 1. アクティブな全ミッションと、現在のデバイスの今週の進捗を LEFT JOIN で取得
        cur.execute(
            """
            SELECT 
                m.id AS mission_id,
                m.title,
                m.description,
                m.target_type,
                m.target_value,
                m.reward_coins,
                COALESCE(p.current_value, 0) AS current_value,
                COALESCE(p.is_completed, FALSE) AS is_completed,
                COALESCE(p.is_claimed, FALSE) AS is_claimed
            FROM weekly_missions m
            LEFT JOIN device_mission_progress p 
                ON m.id = p.mission_id 
                AND p.device_id = %s 
                AND p.week_start_date = %s
            WHERE m.is_active = TRUE;
            """,
            (device_id, week_start)
        )
        rows = cur.fetchall()

    return [
        WeeklyMissionItem(
            mission_id=str(row["mission_id"]),
            title=row["title"],
            description=row["description"],
            target_type=row["target_type"],
            target_value=row["target_value"],
            current_value=row["current_value"],
            reward_coins=row["reward_coins"],
            is_completed=row["is_completed"],
            is_claimed=row["is_claimed"],
        )
        for row in rows
    ]


def increment_mission_progress(db: psycopg.Connection, device_id: str, target_type: str, amount: int = 1):
    """
    ミッションの進捗更新を行う。
    """

    week_start = get_current_week_start()

    with db.cursor() as cur:
        # 該当するアクティブミッションを取得して進捗を更新（UPSERT）
        cur.execute(
            """
            INSERT INTO device_mission_progress (device_id, mission_id, week_start_date, current_value, is_completed)
            SELECT 
                %s, 
                m.id, 
                %s, 
                %s, 
                (%s >= m.target_value)
            FROM weekly_missions m
            WHERE m.target_type = %s AND m.is_active = TRUE
            ON CONFLICT (device_id, mission_id, week_start_date) 
            DO UPDATE SET 
                current_value = device_mission_progress.current_value + EXCLUDED.current_value,
                is_completed = (device_mission_progress.current_value + EXCLUDED.current_value) >= (
                    SELECT target_value FROM weekly_missions WHERE id = EXCLUDED.mission_id
                ),
                updated_at = NOW()
            WHERE device_mission_progress.is_completed = FALSE; -- 既に達成済みの場合は更新しない
            """,
            (device_id, week_start, amount, amount, target_type)
        )
        db.commit()


def claim_mission_reward(db: psycopg.Connection, device_id: str, mission_id: str, week_start_date: date) -> int:
    """
    ミッション報酬を受け取り、デバイスのコインを増やす。
    戻り値: 付与されたコイン数
    """
    with db.cursor(row_factory=dict_row) as cur:
        # 1. 進捗状況の確認と is_claimed のアトミック更新（行ロックを兼ねる）
        cur.execute(
            """
            UPDATE device_mission_progress p
            SET 
                is_claimed = TRUE,
                updated_at = NOW()
            FROM weekly_missions m
            WHERE p.mission_id = m.id
                AND p.device_id = %s
                AND p.mission_id = %s
                AND p.week_start_date = %s
                AND p.is_completed = TRUE
                AND p.is_claimed = FALSE
            RETURNING m.reward_coins;
            """,
            (device_id, mission_id, week_start_date)
        )
        row = cur.fetchone()

        # 条件を満たさない（未達成、受け取り済み、レコードが存在しない等）場合
        if not row:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="報酬を受け取ることができません。未達成であるか、既に受け取り済みです。"
            )

        reward_coins = row["reward_coins"]

        # 2. デバイスにコインを付与
        cur.execute(
            """
            UPDATE devices
            SET coins = coins + %s
            WHERE id = %s;
            """,
            (reward_coins, device_id)
        )

        # 3. トランザクションを確定
        db.commit()

    return reward_coins


import random
from fastapi import HTTPException, status
import psycopg
from psycopg.rows import dict_row


def play_seal_pack(
    db: psycopg.Connection, 
    device: Device, 
    pack_id: str, 
    count: int = 1
) -> list[Seal]:
    """
    指定されたデバイスとして、指定されたシールパックを、指定された回数引く
    （同じシールが重複した場合もそれぞれ新規レコードとして追加）
    """
    if count <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ガチャを引く回数は1以上を指定してください。"
        )

    with db.cursor(row_factory=dict_row) as cur:
        # 1. パックの存在と販売状態（is_opened）を確認
        cur.execute(
            """
            SELECT id, name, once_price, is_opened 
            FROM seal_packs 
            WHERE id = %s;
            """,
            (pack_id,)
        )
        pack = cur.fetchone()

        if not pack or not pack["is_opened"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="指定されたシールパックが存在しないか、現在販売されていません。"
            )

        total_cost = pack["once_price"] * count

        # 2. デバイスのコイン数をロックして取得（競合・連打防止）
        cur.execute(
            "SELECT coins FROM devices WHERE id = %s FOR UPDATE;",
            (device.id,)
        )
        dev_row = cur.fetchone()

        if not dev_row or dev_row["coins"] < total_cost:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"コインが足りません。（必要: {total_cost} コイン, 所持: {dev_row['coins'] if dev_row else 0} コイン）"
            )

        # 3. パックに登録されているシールと重み（weight）を取得
        cur.execute(
            """
            SELECT 
                s.id,
                s.name,
                s.description,
                s.rarity,
                s.image_path,
                rt.weight
            FROM seal_packs_root_tables rt
            JOIN seals s ON rt.seal_id = s.id
            WHERE rt.seal_pack_id = %s;
            """,
            (pack_id,)
        )
        candidates = cur.fetchall()

        if not candidates:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="このパックには排出対象のシールが設定されていません。"
            )

        # 4. コインを消費
        cur.execute(
            """
            UPDATE devices 
            SET coins = coins - %s 
            WHERE id = %s;
            """,
            (total_cost, device.id)
        )

        # 5. 重み付きランダム抽選 (Python の random.choices を使用)
        seals_pool = [
            Seal(
                id=str(c["id"]),
                name=c["name"],
                description=c["description"],
                rarity=c["rarity"],
                image_path=c["image_path"],
            )
            for c in candidates
        ]
        weights = [c["weight"] for c in candidates]

        drawn_seals = random.choices(seals_pool, weights=weights, k=count)

        # 6. 獲得したシールを個別のレコードとして一括追加（id は PostgreSQL 側で自動生成）
        insert_data = [(device.id, seal.id) for seal in drawn_seals]
        cur.executemany(
            """
            INSERT INTO device_seals (device_id, seal_id)
            VALUES (%s, %s);
            """,
            insert_data
        )

        # トランザクション確定
        db.commit()

    return drawn_seals


def add_original_seal(db: psycopg.Connection, request: OriginalSealRequest, relative_image_path: str) -> Seal:
    """
    オリジナルのシールをデータベースに追加する
    """

    with db.cursor(row_factory=dict_row) as cur:
        # レアリティの存在チェック
        cur.execute("SELECT id FROM seal_rarities WHERE id = %s;", (request.rarity,))
        if not cur.fetchone():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"指定されたレアリティID ({request.rarity}) は存在しません。"
            )

        # seals テーブルに挿入して作成結果を取得
        cur.execute(
            """
            INSERT INTO seals (name, description, rarity, image_path, owner)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, name, description, rarity, image_path, owner;
            """,
            (request.name, request.description, request.rarity, relative_image_path, request.owner)
        )
        new_seal = cur.fetchone()
        db.commit()

    if new_seal :
        return Seal(
            id=str(new_seal["id"]),
            name=new_seal["name"],
            description=new_seal["description"],
            rarity=new_seal["rarity"],
            image_path=new_seal["image_path"],
            owner=new_seal["owner"]
        )
    else:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="シールのデータベースへの追加に失敗しました")
