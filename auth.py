from typing import Annotated

import firebase_admin
from fastapi import Depends, HTTPException, status, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth, credentials

from models import User, Device

firebase_admin.initialize_app(
    credentials.Certificate("serviceAccountKey.json")
)

firebase_scheme = HTTPBearer(
    scheme_name="Firebase Authentication",
    description="Firebase ID Token"
)

async def get_current_user(credentials: Annotated[HTTPAuthorizationCredentials, Depends(firebase_scheme)]) -> User:
    """
    Firebase ID Tokenを検証し、認証済みユーザーを返す。

    Returns:
        Firebase UID
    """
    raise NotImplementedError


async def get_current_device(device_id: Annotated[str, Header(alias="X-Device-Id")], device_secret: Annotated[str, Header(alias="X-Device-Secret")]) -> Device:
    """
    デバイス認証を行う。

    TODO:
        Device Tokenを検証し、Device情報を返す。
    """
    raise NotImplementedError