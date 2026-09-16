from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

# 汎用

class SuccessResponse(BaseModel):
    success: bool
    description: Optional[str] = None

# 主にユーザーとの通信（Flutter）に使用される

class User(BaseModel):
    id: str
    display_name: str
    email: str
    firebase_uid: str
    notify_tokens: list[str]
    roll: int

class DeviceInfoUpdateRequest(BaseModel):
    device_id: str
    device_display_name: str

class UpdateUser(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    roll: Optional[int] = None


class DeviceSeal(BaseModel):
    id: str
    device_id: str
    seal_id: str
    status_id: int
    book_page: Optional[int] = None
    book_x: Optional[float] = None
    book_y: Optional[float] = None
    book_rotation: Optional[float] = None
    book_scale: Optional[float] = None



class SealPackRootTable(BaseModel):
    seal_id: str
    weight: float


class SealPackResponse(BaseModel):
    id: str
    name: str
    description: str
    once_price: int
    image_path: str
    root_table: list[SealPackRootTable]


class Seal(BaseModel):
    id: str
    name: str
    description: str
    rarity: int
    image_path: str


# 主に親機や子機との通信に使用される

class DeviceInitRequest(BaseModel):
    device_id: str = Field(..., description="デバイスのUUID")
    public_key: bytes = Field(..., description="公開鍵")
    name: Optional[str] = Field(None, description="デバイス名")


class GatewayInitRequest(BaseModel):
    id: str
    public_key: bytes
    name: Optional[str] = None

class Device(BaseModel):
    id: str
    owner: Optional[str]
    name: str
    public_key: bytes
    coins: int
    battery: float
    last_timestamp: datetime

class Gateway(BaseModel):
    id: str
    public_key: bytes
    name: str
    distribute_seal_id: Optional[str] = None
    user_id: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

"""
署名バイト列
{event_id}|{my_id}|{partner_id}|{partner_is_gateway}|{send_seal_id}|{receive_seal_id}|{timestamp_unix}
"""
class NearbyCommunication(BaseModel):
    event_id: str
    my_id: str
    partner_id: str
    partner_is_gateway: bool
    send_seal_id: Optional[str] = None
    receive_seal_id: Optional[str] = None
    timestamp: datetime
    signature: bytes # 送信元デバイスによる署名

class GetNearbyCommunicationsRequest(BaseModel):
    device_id: str
    start_at: datetime
    end_at: datetime

class DeviceUpdateRequest(BaseModel):
    device_id: str
    request_id: str
    timestamp: datetime
    nearby_communications: list[NearbyCommunication]

class SosReceiver(BaseModel):
    event_id: str
    gateway_id: str
    received_at: datetime

class SosInfo(BaseModel):
    event_id: str
    child_device_id: str
    trigger_timestamp: datetime
    receive_timestamp: datetime
    notified: bool
    receivers: list[SosReceiver]


"""
署名バイト列
{event_id}|{child_id}|{gateway_id}|{trigger_timestamp_unix}|{receive_timestamp_unix}
"""
class SosRequest(BaseModel):
    event_id: str
    child_id: str
    gateway_id: str
    trigger_timestamp: datetime
    receive_timestamp: datetime
    signature: bytes