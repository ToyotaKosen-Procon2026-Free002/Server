import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from typing import Annotated

from fastapi.responses import FileResponse
from auth import get_current_user
from models import ClaimRewardRequest, ClaimRewardResponse, Device, DeviceInfoPatchRequest, DeviceSeal, Gateway, GatewayInfoPatchRequest, GetNearbyCommunicationsRequest, GetSosRequest, NearbyCommunication, Seal, SealPackResponse, SosInfo, SuccessResponse, User, UpdateUser, WeeklyMissionItem
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


@router.get(
    "/nearby_communications_log",
    summary="指定したデバイスの、指定した期間のすれ違いログを取得する",
    response_model=list[NearbyCommunication]
)
async def get_nearby_communications_log(request: GetNearbyCommunicationsRequest, db: psycopg.Connection = Depends(get_connection), current_user: User = Depends(get_current_user)) -> list[NearbyCommunication]:
    """
    指定したデバイスの、指定した期間のすれ違いログを取得する
    """

    device = connection.get_device(db, request.device_id)
    if device and current_user.id == device.owner:
        return connection.get_nearby_communications_log(db, request)
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="存在しないデバイスを指定しているか、所持していないデバイスを指定しています。")


@router.get(
    "/sos_log",
    summary="指定したデバイスの、指定した期間のSOSログを取得する",
    response_model=list[SosInfo]
)
async def get_sos_log(request: GetSosRequest, db: psycopg.Connection = Depends(get_connection), current_user: User = Depends(get_current_user)) -> list[SosInfo]:
    """
    指定したデバイスの、指定した期間のSOSログを取得する
    """

    device = connection.get_device(db, request.device_id)
    if device and current_user.id == device.owner:
        return connection.get_sos_log(db, request)
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="存在しないデバイスを指定しているか、所持していないデバイスを指定しています。")


@router.patch(
    "/device",
    summary="指定したIDのデバイスの情報を更新する",
    response_model=SuccessResponse
)
async def patch_device_info(request: DeviceInfoPatchRequest, db: psycopg.Connection = Depends(get_connection), current_user: User = Depends(get_current_user)) -> SuccessResponse:
    """
    指定したデバイスの情報を更新する
    """

    device = connection.get_device(db, request.device_id)
    if device and current_user.id == device.owner:
        connection.patch_device_info(db, request)
        return SuccessResponse(success=True)
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="存在しないデバイスを指定しているか、所持していないデバイスを指定しています。")


@router.patch(
    "/gateway",
    summary="指定したIDの親機の情報を更新する",
    response_model=SuccessResponse
)
async def patch_gateway_info(request: GatewayInfoPatchRequest, db: psycopg.Connection = Depends(get_connection), current_user: User = Depends(get_current_user)) -> SuccessResponse:
    """
    指定した親機の情報を更新する
    """

    gateway = connection.get_gateway(db, request.device_id)
    if gateway and current_user.id == gateway.user_id:
        connection.patch_gateway_info(db, request)
        return SuccessResponse(success=True)
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="存在しない親機を指定しているか、所持していない親機を指定しています。")


@router.post(
    "/missions/claim",
    summary="ミッション報酬を受け取る",
    response_model=ClaimRewardResponse
)
async def claim_reward(request: ClaimRewardRequest, db: psycopg.Connection = Depends(get_connection), current_user: User = Depends(get_current_user)):
    """
    ミッションの報酬を受け取る
    """

    device = connection.get_device(db, request.device_id)
    if not device or device.owner != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="存在しないデバイスを指定しているか、所持していないデバイスを指定しています。"
        )

    week_start = connection.get_current_week_start()
    claimed_coins = connection.claim_mission_reward(
        db, request.device_id, request.mission_id, week_start
    )

    return ClaimRewardResponse(
        claimed_coins=claimed_coins,
        message=f"{claimed_coins} コインを獲得しました！"
    )


@router.get(
    "/missions/weekly",
    summary="指定したデバイスの今週のウィークリーミッション一覧を取得する",
    response_model=list[WeeklyMissionItem]
)
async def get_weekly_missions(device_id: str, db: psycopg.Connection = Depends(get_connection), current_user: User = Depends(get_current_user)) -> list[WeeklyMissionItem]:
    """
    指定されたデバイスの現在の週のウィークリーミッション一覧と進捗状況を取得します。
    """
    
    device = connection.get_device(db, device_id)
    if not device or device.owner != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="存在しないデバイスを指定しているか、所持していないデバイスを指定しています。"
        )

    return connection.get_or_create_weekly_missions(db, device_id)


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

@router.get(
    "/images/{image_path}",
    summary="画像を取得する",
    response_class=FileResponse
)
async def get_image(image_path: str) -> FileResponse:
    file_path = STATIC_DIR / "images" / image_path

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(
            status_code=404, 
            detail=f"Image not found"
        )

    return FileResponse(file_path)