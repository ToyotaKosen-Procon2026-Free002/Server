from typing import Annotated
import psycopg
import firebase_admin
from database.connection import get_connection, get_or_create_user
from fastapi import Depends, HTTPException, status, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth, credentials
from cryptography.exceptions import InvalidSignature
from models import User, Device

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


async def get_current_device(request: Request, device_id: Annotated[str, Header(alias="X-Device-Id")], signature: Annotated[str, Header(alias="X-Device-Signature")]) -> Device:
    """
    デバイス認証を行う。

    TODO:
        signatureを検証し、Device情報を返す。
    """

    body = await request.body()
    message = device_id.encode() + body

    raise NotImplementedError