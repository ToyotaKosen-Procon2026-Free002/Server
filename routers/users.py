from fastapi import APIRouter, Depends, HTTPException, status
from typing import Annotated
from auth import get_current_user
from models import Device, DeviceSeal, Gateway, Seal, SealPackResponse, SuccessResponse, User, UpdateUser
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
async def get_me(current_user: User = Depends(get_current_user)) -> User:
    """
    Firebase Authenticationで認証されたユーザーの情報を取得します。
    """
    return current_user



@router.patch(
    "/me",
    summary="現在ログイン中のユーザー情報を更新",
    response_model=User
)
async def update_me(_update_user: UpdateUser, current_user: User = Depends(get_current_user), db: psycopg.Connection = Depends(get_connection)) -> User:
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


@router.post(
    "/notify_token",
    summary="ユーザーのプッシュ通知用トークンを通知する",
    response_model=SuccessResponse
)
async def put_notify_token(token: str, current_user: User = Depends(get_current_user), db: psycopg.Connection = Depends(get_connection)) -> SuccessResponse:
    """
    ユーザーのプッシュ通知用トークンを通知する
    """

    connection.add_notify_token(db, token, current_user)
    return SuccessResponse(success=True)


@router.delete(
    "/notify_token",
    summary="ユーザーのプッシュ通知用トークンを削除する",
    response_model=SuccessResponse
)
async def delete_notify_token(token: str, current_user: User = Depends(get_current_user), db: psycopg.Connection = Depends(get_connection)) -> SuccessResponse:
    """
    ユーザーのプッシュ通知用トークンを削除する
    """

    connection.delete_notify_token(db, token, current_user)
    return SuccessResponse(success=True)



@router.get(
    "/seals",
    summary="存在するシールの一覧を返す",
    response_model=list[Seal]
)
async def get_seals(current_user: User =Depends(get_current_user), db: psycopg.Connection = Depends(get_connection)) -> list[Seal]:
    """
    存在するシールの一覧を返す
    """

    return connection.get_seals(db)



@router.post(
    "/device",
    summary="デバイスを登録",
    response_model=SuccessResponse
)
async def register_device(device_id: str, current_user: User = Depends(get_current_user), db: psycopg.Connection = Depends(get_connection)) -> SuccessResponse:
    """
    現在ログインしているユーザーにデバイスを登録する。
    デバイスIDがすでにサーバーに登録されていて、どのアカウントの所有物ではない必要がある。
    """

    device = connection.register_device(db, device_id, current_user)
    return SuccessResponse(success=True if device else False)


@router.get(
    "/devices",
    response_model=list[Device],
    summary="登録済みデバイス一覧を取得"
)
async def get_device(current_user: User = Depends(get_current_user), db: psycopg.Connection = Depends(get_connection)) -> list[Device]:
    """
    現在ログインしているユーザーに登録されているデバイスの一覧を取得します。
    """

    return connection.get_devices(db, current_user)


@router.post(
    "/gateway",
    summary="親機の登録を行う",
    response_model=SuccessResponse
)
async def register_gateway(gateway_id: str, current_user: User = Depends(get_current_user), db: psycopg.Connection = Depends(get_connection)) -> SuccessResponse:
    """
    現在ログインしているユーザーに親機を登録する。
    IDがすでにサーバーに登録されていて、どのアカウントの所有物でもない必要がある。
    """

    gateway = connection.register_gateway(db, gateway_id, current_user)
    return SuccessResponse(success=True if gateway else False)


@router.get(
    "/gateways",
    summary="登録済みの親機一覧を取得",
    response_model=list[Gateway]
)
async def get_gateways(current_user: User = Depends(get_current_user), db: psycopg.Connection = Depends(get_connection)) -> list[Gateway]:
    """
    現在ログインしているユーザーに登録されているデバイスの一覧を取得する。
    """

    return connection.get_gateways(db, current_user)


@router.get(
    "/all_gateways",
    summary="すべての親機の一覧を取得",
    response_model=list[Gateway]
)
async def get_all_gateways(current_user: User = Depends(get_current_user), db: psycopg.Connection = Depends(get_connection)) -> list[Gateway]:
    """
    データベースに登録されているすべての親機一覧を取得する。
    """

    return connection.get_all_gateways(db)