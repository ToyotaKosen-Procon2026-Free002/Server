import base64
from datetime import timezone
from typing import Annotated
import psycopg
import firebase_admin
from database.connection import get_connection, get_device, get_or_create_user, get_gateway
from fastapi import Depends, HTTPException, status, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth, credentials
from cryptography.exceptions import InvalidSignature
from models import Gateway, NearbyCommunication, SosRequest, User, Device
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes

firebase_admin.initialize_app(
    credentials.Certificate("serviceAccountKey.json")
)

firebase_scheme = HTTPBearer(
    scheme_name="Firebase Authentication",
    description="Firebase ID Token"
)

def validate_and_parse_p256_pubkey(pubkey_hex: str) -> bytes:
    """
    16進数文字列の公開鍵を検証し、非圧縮P-256 (65バイト, 先頭0x04) のバイト列として返す。
    アクティベート / 親機登録用。
    """
    try:
        pubkey_bytes = bytes.fromhex(pubkey_hex)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="public_key は有効な16進数文字列ではありません。"
        )

    if len(pubkey_bytes) != 65 or pubkey_bytes[0] != 0x04:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="public_key は先頭が 0x04 の 65 バイト非圧縮 P-256 形式である必要があります。"
        )

    try:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), pubkey_bytes)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"無効な P-256 公開鍵です: {str(e)}"
        )

    return pubkey_bytes


async def get_current_user(credentials: Annotated[HTTPAuthorizationCredentials, Depends(firebase_scheme)], db: Annotated[psycopg.Connection, Depends(get_connection)]) -> User:
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


async def get_current_gateway(request: Request, gateway_id: Annotated[str, Header(alias="X-Gateway-Id")], signature: Annotated[str, Header(alias="X-Gateway-Signature")], db: psycopg.Connection = Depends(get_connection)) -> Gateway:
    """
    親機のデバイス認証を行う。
    """
    gateway = get_gateway(db, gateway_id)
    if gateway is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="デバイスが見つからなかった、もしくはデータベースに登録されていません。")

    body = await request.body()
    message = gateway_id.encode() + body

    try:
        sig_bytes = bytes.fromhex(signature)
    except ValueError:
        try:
            sig_bytes = base64.b64decode(signature)
        except Exception:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="署名がエンコードできませんでした。")

    try:
        public_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), gateway.public_key)
        public_key.verify(sig_bytes, message, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="無効な署名です。")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"署名の検証に失敗しました: {str(e)}")

    return gateway


def build_comm_message(comm: NearbyCommunication) -> bytes:
    """
    NearbyCommunication から署名対象のバイト列を決定論的に生成する
    """
    event_id = comm.event_id.lower()
    my_id = comm.my_id.lower()
    partner_id = comm.partner_id.lower()
    
    gateway_flag = "1" if comm.partner_is_gateway else "0"
    
    send_seal = comm.send_seal_id.lower() if comm.send_seal_id else ""
    recv_seal = comm.receive_seal_id.lower() if comm.receive_seal_id else ""
    
    ts = comm.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    timestamp_unix = str(int(ts.timestamp()))

    raw_str = f"{event_id}|{my_id}|{partner_id}|{gateway_flag}|{send_seal}|{recv_seal}|{timestamp_unix}"
    return raw_str.encode("utf-8")


def verify_comm_event_signature(public_key_bytes: bytes, comm: NearbyCommunication) -> None:
    """
    発生元デバイスの公開鍵を使ってイベントデータの署名を検証する。
    """
    message = build_comm_message(comm)
    
    try:
        sig_bytes = bytes.fromhex(comm.signature)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"署名(Hex)のデコードに失敗しました: {comm.event_id}")

    try:
        public_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public_key_bytes)
        public_key.verify(sig_bytes, message, ec.ECDSA(hashes.SHA256()))
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

    t_trigger = request.trigger_timestamp
    if t_trigger.tzinfo is None:
        t_trigger = t_trigger.replace(tzinfo=timezone.utc)
    trigger_unix = str(int(t_trigger.timestamp()))

    t_receive = request.receive_timestamp
    if t_receive.tzinfo is None:
        t_receive = t_receive.replace(tzinfo=timezone.utc)

    raw_str = f"{event_id}|{child_id}|{trigger_unix}"
    return raw_str.encode("utf-8")


def verify_sos_signature(public_key_bytes: bytes, request: SosRequest) -> None:
    """
    発生元デバイス（child_id）の公開鍵を使ってSOSデータの署名を検証する。
    """
    message = build_sos_message(request)
    
    try:
        sig_bytes = bytes.fromhex(request.signature)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SOS署名(Hex)のデコードに失敗しました。")

    try:
        public_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public_key_bytes)
        public_key.verify(sig_bytes, message, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="SOSイベントの署名検証に失敗しました。")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"公開鍵または署名の形式エラー: {str(e)}")