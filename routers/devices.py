from fastapi import APIRouter, Depends
from auth import get_current_device, get_current_user
from models import User, Device, SuccessResponse, SosRequest, DeviceUpdateRequest

router = APIRouter(
    prefix="/devices",
    tags=["Devices"]
)


@router.post(
    "",
    summary="デバイスを登録"
)
async def register_device(device_id: str, current_user: User = Depends(get_current_user)):
    """
    現在ログインしているユーザーにデバイスを登録する。
    デバイスIDがすでにサーバーに登録されていて、どのアカウントの所有物ではない必要がある。
    """
    raise NotImplementedError()


@router.get(
    "",
    response_model=list[Device],
    summary="登録済みデバイス一覧を取得"
)
async def get_device(current_user: User = Depends(get_current_user)) -> list[Device]:
    """
    現在ログインしているユーザーに登録されているデバイスの一覧を取得します。
    """
    raise NotImplementedError()


@router.post(
    "/activate",
    response_model=SuccessResponse,
    summary="新しいデバイスをサーバーに初回登録する"
)
async def register_new_device(device_id: str, device_secret: str) -> SuccessResponse:
    """
    新しいデバイスをサーバーに初回登録するための関数。
    """
    raise NotImplementedError()


@router.post(
    "/status",
    response_model=SuccessResponse,
    summary="デバイスの現在情報を更新"
)
async def update(request: DeviceUpdateRequest ,current_device: Device = Depends(get_current_device)) -> SuccessResponse:
    """
    デバイスの現在情報、位置情報などを更新する
    """
    raise NotImplementedError


@router.post(
    "/sos",
    response_model=SuccessResponse,
    summary="SOSを送信する"
)
async def sos(request: SosRequest, current_device: Device = Depends(get_current_device)) -> SuccessResponse:
    """
    SOSを送信する
    """
    raise NotImplementedError