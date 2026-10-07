from datetime import date, timedelta
import random
from fastapi import HTTPException, status
import psycopg
from psycopg.rows import dict_row
from config import settings
from models import Device, DeviceInfoPatchRequest, DeviceSeal, DeviceUpdateRequest, Gateway, GatewayInfoPatchRequest, GatewayInitRequest, GetNearbyCommunicationsRequest, GetSosRequest, NearbyCommunication, OriginalSealRequest, PatchDeviceSealRequest, Seal, SealPackResponse, SealPackRootTable, SosInfo, SosReceiver, SosRequest, User, UpdateUser, WeeklyMissionItem
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
        # 新規登録を試行
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

        # 既に登録済みのデバイスが存在する場合 (ON CONFLICT)
        if device is None:
            cur.execute(
                """
                SELECT id, user_id, name, public_key, coins, battery, last_timestamp 
                FROM devices 
                WHERE id = %s;
                """, 
                (device_id,)
            )
            device = cur.fetchone()

            if device:
                # 既存公開鍵との一致確認（不一致の場合はエラー）
                saved_pubkey = bytes(device["public_key"])
                if saved_pubkey != public_key:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="デバイスは既に登録されていますが、公開鍵が一致しません。"
                    )

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
    else:
        return None


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
                ON CONFLICT (request_id) DO NOTHING
                RETURNING *;
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

                    cur.execute(
                        """
                        UPDATE devices
                        SET coins = coins + 5
                        WHERE id = %s;
                        """,
                        (origin_device.id)
                    )

                    cur.execute(
                        """
                        INSERT INTO device_seal_book (device_id, seal_id)
                        VALUES (%s, %s)
                        ON CONFLICT (device_id, seal_id) DO NOTHING;
                        """,
                        (origin_device.id, comm.receive_seal_id)
                    )

                if comm.partner_is_gateway:
                    increment_mission_progress(db, comm.my_id, "ENCOUNTER_GATEWAY")
                else:
                    increment_mission_progress(db, comm.my_id, "ENCOUNTER_DEVICE")

                if comm.receive_seal_id:
                    increment_mission_progress(db, comm.my_id, "GET_SEAL")
                
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
            owner=str(row["owner"]) if row["owner"] is not None else None
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
                e.request_id,
                e.device_id,
                e.opponent_device_id,
                e.gateway_id,
                COALESCE(g.name, d.name) AS partner_name,
                e.send_seal_id,
                e.receive_seal_id,
                e.detected_at
            FROM encounters e
            LEFT JOIN devices d ON e.opponent_device_id = d.id
            LEFT JOIN gateways g ON e.gateway_id = g.id
            WHERE e.device_id = %s AND e.detected_at BETWEEN %s AND %s
            ORDER BY e.detected_at DESC;
            """,
            (request.device_id, request.start_at, request.end_at),
        )
        rows = cur.fetchall()

    return [
        NearbyCommunication(
            event_id=str(row["request_id"]),
            my_id=str(row["device_id"]),
            partner_id=str(row["gateway_id"] or row["opponent_device_id"]),
            partner_name=row["partner_name"],
            partner_is_gateway=row["gateway_id"] is not None,
            send_seal_id=str(row["send_seal_id"])
            if row["send_seal_id"]
            else None,
            receive_seal_id=str(row["receive_seal_id"])
            if row["receive_seal_id"]
            else None,
            timestamp=row["detected_at"],
            signature="",
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


def get_or_create_weekly_missions(
    db: psycopg.Connection, device_id: str
) -> list[WeeklyMissionItem]:
    """
    指定したデバイスの今週のウィークリーミッションを取得する。
    まだ無ければアクティブなものからランダムに3つ選んで作成・保存する。
    """

    week_start = get_current_week_start()

    with db.cursor(row_factory=dict_row) as cur:
        # 1. すでに今週分として保存されているミッション進捗を取得
        cur.execute(
            """
            SELECT 
                m.id AS mission_id,
                m.title,
                m.description,
                m.target_type,
                m.target_value,
                m.reward_coins,
                p.current_value,
                p.is_completed,
                p.is_claimed
            FROM device_mission_progress p
            JOIN weekly_missions m ON p.mission_id = m.id
            WHERE p.device_id = %s 
                AND p.week_start_date = %s
                AND m.is_active = TRUE;
            """,
            (device_id, week_start),
        )
        existing_rows = cur.fetchall()

        # すでにミッションが割り振られていればそれを返す
        if existing_rows:
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
                for row in existing_rows
            ]

        # 2. まだ割り振られていない場合、アクティブなミッションからランダムに3つ取得
        cur.execute(
            """
            SELECT id, title, description, target_type, target_value, reward_coins
            FROM weekly_missions
            WHERE is_active = TRUE
            ORDER BY RANDOM()
            LIMIT 3;
            """
        )
        selected_missions = cur.fetchall()

        if not selected_missions:
            return []

        # 3. 選定した3つのミッションを進捗テーブル（device_mission_progress）に一括登録
        insert_data = [
            (device_id, m["id"], week_start, 0, False, False)
            for m in selected_missions
        ]
        cur.executemany(
            """
            INSERT INTO device_mission_progress (
                device_id, mission_id, week_start_date, current_value, is_completed, is_claimed
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (device_id, mission_id, week_start_date) DO NOTHING;
            """,
            insert_data,
        )
        db.commit()

        # 4. レスポンス用のリストにして返す
        return [
            WeeklyMissionItem(
                mission_id=str(m["id"]),
                title=m["title"],
                description=m["description"],
                target_type=m["target_type"],
                target_value=m["target_value"],
                current_value=0,
                reward_coins=m["reward_coins"],
                is_completed=False,
                is_claimed=False,
            )
            for m in selected_missions
        ]


def increment_mission_progress(db: psycopg.Connection, device_id: str, target_type: str, increment: int = 1) -> None:
    """指定された target_type の今週のミッション進捗を加算・更新する"""
    week_start = get_current_week_start()

    # 割り当てがまだなら自動で作成
    get_or_create_weekly_missions(db, device_id)

    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            UPDATE device_mission_progress p
            SET 
                current_value = LEAST(p.current_value + %s, m.target_value),
                is_completed = (p.current_value + %s) >= m.target_value,
                updated_at = NOW()
            FROM weekly_missions m
            WHERE p.mission_id = m.id
                AND p.device_id = %s
                AND p.week_start_date = %s
                AND m.target_type = %s
                AND p.is_completed = FALSE;
            """,
            (increment, increment, device_id, week_start, target_type),
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


def play_seal_pack(db: psycopg.Connection, device: Device, pack_id: str, count: int = 1) -> list[Seal]:
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

        cur.executemany(
            """
            INSERT INTO device_seal_book (device_id, seal_id)
            VALUES (%s, %s)
            ON CONFLICT (device_id, seal_id) DO NOTHING;
            """,
            insert_data
        )

        increment_mission_progress(db, device.id, "PLAY_GACHA", count)
        increment_mission_progress(db, device.id, "GET_SEAL", count)

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
            owner=str(new_seal["owner"]) if new_seal["owner"] is not None else None
        )
    else:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="シールのデータベースへの追加に失敗しました")


def get_original_seals(db: psycopg.Connection, gateway_id: str) -> list[Seal]:
    """
    親機が作成したオリジナルシールの一覧を取得する
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
            FROM seals 
            WHERE owner = %s
            ORDER BY "order" ASC, name ASC;
            """,
            (gateway_id,)
        )
        rows = cur.fetchall()

    return [
        Seal(
            id=str(row["id"]),
            name=row["name"],
            description=row["description"],
            rarity=row["rarity"],
            image_path=row["image_path"],
            owner=str(row["owner"]) if row["owner"] is not None else None,
        )
        for row in rows
    ]



def patch_device_seal(db: psycopg.Connection, request: PatchDeviceSealRequest) -> DeviceSeal:
    """
    指定したデバイスのシールの状態を更新する
    """
    # 1. DBのCHECK制約に合わせたバリデーション (status_id=1 のときは配置座標が必須)
    if request.status_id == 1:
        if request.book_page is None or request.book_x is None or request.book_y is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="シール帳に配置状態(status_id=1)にする場合は、book_page, book_x, book_y が必須です。"
            )

    with db.cursor(row_factory=dict_row) as cur:
        # 2. レコードの更新と所有権のチェック（device_id と id の一致確認）
        cur.execute(
            """
            UPDATE device_seals
            SET 
                status_id = %s,
                book_page = %s,
                book_x = %s,
                book_y = %s,
                book_rotation = %s,
                book_scale = %s
            WHERE id = %s AND device_id = %s
            RETURNING 
                id, 
                device_id, 
                seal_id, 
                status_id, 
                book_page, 
                book_x, 
                book_y, 
                book_rotation, 
                book_scale;
            """,
            (
                request.status_id,
                request.book_page,
                request.book_x,
                request.book_y,
                request.book_rotation,
                request.book_scale,
                request.id,
                request.device_id,
            )
        )
        updated_row = cur.fetchone()

        # 指定された所持シールが存在しない、または端末の所有権が異なる場合
        if not updated_row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="指定された所持シールが見つからないか、デバイスの所有権が不一致です。"
            )

        if request.status_id == 1:
            increment_mission_progress(db, request.device_id, "PLACE_SEAL")

        db.commit()

    return DeviceSeal(
        id=str(updated_row["id"]),
        device_id=str(updated_row["device_id"]),
        seal_id=str(updated_row["seal_id"]),
        status_id=updated_row["status_id"],
        book_page=updated_row["book_page"],
        book_x=updated_row["book_x"],
        book_y=updated_row["book_y"],
        book_rotation=updated_row["book_rotation"],
        book_scale=updated_row["book_scale"],
    )


def get_device_seal_book(db: psycopg.Connection, device_id: str) -> list[Seal]:
    """
    指定されたデバイスのシール図鑑に登録されているシールを返す。
    一度でも所持したものは返される。
    """

    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT 
                s.id,
                s.name,
                s.description,
                s.rarity,
                s.image_path,
                s.owner
            FROM device_seal_book dsb
            JOIN seals s ON dsb.seal_id = s.id
            WHERE dsb.device_id = %s
            ORDER BY s."order" ASC, s.name ASC;
            """,
            (device_id,)
        )
        rows = cur.fetchall()

    return [
        Seal(
            id=str(row["id"]),
            name=row["name"],
            description=row["description"],
            rarity=row["rarity"],
            image_path=row["image_path"],
            owner=str(row["owner"]) if row["owner"] is not None else None,
        )
        for row in rows
    ]