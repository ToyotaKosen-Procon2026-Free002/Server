from fastapi import APIRouter, Depends, HTTPException, status
from typing import Annotated
from auth import get_current_user
from models import DeviceSeal, SealPackResponse, User, UpdateUser
from database.connection import get_connection, update_user
from database import connection
import psycopg

router = APIRouter(
    prefix="/users",
    tags=["Users"]
)



@router.get(
    "/me",
    response_model=User,
    summary="現在ログイン中のユーザー情報を取得",
    response_description="プロフィール情報",
)
async def get_me(current_user: User = Depends(get_current_user)):
    """
    Firebase Authenticationで認証されたユーザーの情報を取得します。
    """
    return current_user



@router.patch(
    "/me",
    summary="現在ログイン中のユーザー情報を更新",
    response_model=User
)
async def update_me(_update_user: UpdateUser, current_user: User = Depends(get_current_user), db: psycopg.Connection = Depends(get_connection)):
    """
    Firebase Authenticationで認証されたユーザーの情報を更新します。
    """

    return update_user(db, _update_user, current_user)



@router.get(
    "/seal_packs",
    summary="現在開催中のシールパック一覧を返す",
    response_model=list[SealPackResponse]
)
async def get_seal_packs(current_user: User = Depends(get_current_user), db: psycopg.Connection = Depends(get_connection)) -> list[SealPackResponse]:
    """
    現在開催中のシールパック一覧を返す
    """

    return connection.get_seal_packs(db)



@router.get(
    "/my_seals",
    summary="ユーザーが指定したデバイスが所持しているシール一覧を返す",
    response_model=list[DeviceSeal]
)
async def get_device_seals(device_id: str, current_user: User = Depends(get_current_user), db: psycopg.Connection = Depends(get_connection)) -> list[DeviceSeal]:
    """
    ユーザーが指定したデバイスが所持しているシール一覧を返す
    """

    device = connection.get_device(db, device_id)
    if device and device.owner == current_user.id:
        return connection.get_device_seals(db, device)
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="指定されたデバイスが存在しないか、ユーザーが所持していないデバイスです。")
