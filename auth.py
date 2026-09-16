import base64
from datetime import timezone
from typing import Annotated
import psycopg
import firebase_admin
from database.connection import get_connection, get_device, get_or_create_user
from fastapi import Depends, HTTPException, status, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth, credentials
from cryptography.exceptions import InvalidSignature
from models import NearbyCommunication, SosRequest, User, Device
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes

firebase_admin.initialize_app(
    credentials.Certificate("serviceAccountKey.json")
)

firebase_scheme = HTTPBearer(
    scheme_name="Firebase Authentication",
    description="Firebase ID Token"
)

async def get_current_user(credentials: Annotated[HTTPAuthorizationCredentials, Depends(firebase_scheme)], db:Annotated[psycopg.Connection, Depends(get_connection)]) -> User:
    """
    Firebase ID Tokenを検証し、認証済みユーザーを返す。
    """

    try:
        decoded = auth.verify_id_token(credentials.credentials)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Firebase Token")

    uid: str = decoded["uid"]
    email: str = decoded.get("email")
    name: str = decoded.get("name")

    return get_or_create_user(db, uid, email, name)


async def get_current_device(request: Request, device_id: Annotated[str, Header(alias="X-Device-Id")], signature: Annotated[str, Header(alias="X-Device-Signature")], db: psycopg.Connection = Depends(get_connection)) -> Device:
    """
    デバイス認証を行う。
    """

    device = get_device(db, device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="デバイスが見つからなかった、もしくはデータベースに登録されていません。")

    body = await request.body()
    message = device_id.encode() + body

    try:
        sig_bytes = bytes.fromhex(signature)
    except ValueError:
        try:
            sig_bytes = base64.b64decode(signature)
        except Exception:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="署名がエンコードできませんでした。")

    try:
        public_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), device.public_key)
        public_key.verify(sig_bytes, message, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="無効な署名です。")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"署名の検証に失敗しました: {str(e)}")

    return device


def build_comm_message(comm: NearbyCommunication) -> bytes:
    """
    NearbyCommunication から署名対象のバイト列を決定論的に生成する
    """
    # 1. UUIDの小文字化
    event_id = comm.event_id.lower()
    my_id = comm.my_id.lower()
    partner_id = comm.partner_id.lower()
    
    # 2. フラグの 0/1 変換
    gateway_flag = "1" if comm.partner_is_gateway else "0"
    
    # 3. Optional フィールドの空文字処理
    send_seal = comm.send_seal_id.lower() if comm.send_seal_id else ""
    recv_seal = comm.receive_seal_id.lower() if comm.receive_seal_id else ""
    
    # 4. UNIXタイムスタンプ（秒単位整数）
    # time_stamp が timezone 無しの場合は UTC として扱う
    ts = comm.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    timestamp_unix = str(int(ts.timestamp()))

    # 5. パイプ区切りで連結
    raw_str = f"{event_id}|{my_id}|{partner_id}|{gateway_flag}|{send_seal}|{recv_seal}|{timestamp_unix}"
    
    # UTF-8 バイト列として返却
    return raw_str.encode("utf-8")


def verify_comm_event_signature(public_key_bytes: bytes, comm: NearbyCommunication) -> None:
    """
    発生元デバイスの公開鍵を使ってイベントデータの署名を検証する。
    """
    message = build_comm_message(comm)
    try:
        public_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public_key_bytes)
        public_key.verify(comm.signature, message, ec.ECDSA(hashes.SHA256()))
    
    except InvalidSignature:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"イベントの認証に失敗しました: {comm.event_id}")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"公開鍵、もしくは署名のフォーマットが不正です: {str(e)}")


def build_sos_message(request: SosRequest) -> bytes:
    """
    SOSリクエストから署名対象のバイト列を決定論的に生成する。
    """
    event_id = request.event_id.lower()
    child_id = request.child_id.lower()
    gateway_id = request.gateway_id.lower()

    # タイムスタンプを UTC UNIX秒（整数）に変換
    t_trigger = request.trigger_timestamp
    if t_trigger.tzinfo is None:
        t_trigger = t_trigger.replace(tzinfo=timezone.utc)
    trigger_unix = str(int(t_trigger.timestamp()))

    t_receive = request.receive_timestamp
    if t_receive.tzinfo is None:
        t_receive = t_receive.replace(tzinfo=timezone.utc)
    receive_unix = str(int(t_receive.timestamp()))

    raw_str = f"{event_id}|{child_id}|{gateway_id}|{trigger_unix}|{receive_unix}"
    return raw_str.encode("utf-8")


def verify_sos_signature(public_key_bytes: bytes, request: SosRequest) -> None:
    """
    発生元デバイス（child_id）の公開鍵を使ってSOSデータの署名を検証する。
    """
    message = build_sos_message(request)
    try:
        public_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public_key_bytes)
        public_key.verify(request.signature, message, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="SOSイベントの署名検証に失敗しました。")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"公開鍵または署名の形式エラー: {str(e)}")