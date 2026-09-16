from fastapi import APIRouter, Depends, HTTPException, status
import psycopg
from auth import get_current_device, get_current_user, verify_comm_event_signature, verify_sos_signature
from database.connection import get_connection, init_new_device, received_sos, update_device_status
from database import connection
from models import DeviceInitRequest, DeviceSeal, User, Device, SuccessResponse, SosRequest, DeviceUpdateRequest


router = APIRouter(
    prefix="/devices",
    tags=["Devices"]
)


@router.post(
    "",
    summary="デバイスを登録"
)
async def register_device(device_id: str, current_user: User = Depends(get_current_user), db: psycopg.Connection = Depends(get_connection)) -> SuccessResponse:
    """
    現在ログインしているユーザーにデバイスを登録する。
    デバイスIDがすでにサーバーに登録されていて、どのアカウントの所有物ではない必要がある。
    """

    device = connection.register_device(db, device_id, current_user)
    return SuccessResponse(success=True if device else False)


@router.get(
    "",
    response_model=list[Device],
    summary="登録済みデバイス一覧を取得"
)
async def get_device(current_user: User = Depends(get_current_user), db: psycopg.Connection = Depends(get_connection)) -> list[Device]:
    """
    現在ログインしているユーザーに登録されているデバイスの一覧を取得します。
    """

    return connection.get_devices(db, current_user)


@router.post(
    "/activate",
    response_model=SuccessResponse,
    summary="新しいデバイスをサーバーに初回登録する"
)
async def register_new_device(req: DeviceInitRequest, db: psycopg.Connection = Depends(get_connection)) -> SuccessResponse:
    """
    新しいデバイスをサーバーに初回登録するための関数。
    """

    device = init_new_device(db, req.device_id, req.public_key, req.name)
    return SuccessResponse(success=True if device else False)


@router.post(
    "/status",
    response_model=SuccessResponse,
    summary="デバイスの現在情報、すれ違い情報などを更新"
)
async def update(request: DeviceUpdateRequest, current_device: Device = Depends(get_current_device), db: psycopg.Connection = Depends(get_connection)) -> SuccessResponse:
    """
    デバイスの現在情報、すれ違い情報などを更新する
    """

    origin_device = connection.get_device(db, request.device_id)
    if origin_device is None: 
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"送信元デバイス '{request.device_id}' は見つかりませんでした。")

    for comm in request.nearby_communications:
        if comm.my_id != request.device_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"my_id '{comm.my_id}' はdevice_id '{request.device_id}' と一致しません。")
        verify_comm_event_signature(origin_device.public_key, comm)

    update_device_status(db, request, origin_device)

    return SuccessResponse(success=True)


@router.post(
    "/sos",
    response_model=SuccessResponse,
    summary="SOSを送信する"
)
async def sos(request: SosRequest, current_device: Device = Depends(get_current_device), db: psycopg.Connection = Depends(get_connection)) -> SuccessResponse:
    """
    SOSを送信する
    """

    child_device = connection.get_device(db, request.child_id)
    if child_device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"子機 '{request.child_id}' が見つかりません。")
    verify_sos_signature(child_device.public_key, request)

    received_sos(db, request, child_device)

    return SuccessResponse(success=True)


@router.get(
    "/trading_seals",
    summary="デバイスが交換に出されているシールを取得する"
)
async def get_trading_seals(current_device: Device = Depends(get_current_device), db: psycopg.Connection = Depends(get_connection)) -> list[DeviceSeal]:
    """
    デバイスが交換に出されているシールを取得する
    """

    return connection.get_device_trading_seals(db, current_device)