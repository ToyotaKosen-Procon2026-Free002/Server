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

class DeviceInfoUpdateRequest(BaseModel):
    device_id: str
    device_display_name: str

class UpdateUser(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None


# 主に親機や子機との通信に使用される

class DeviceInitRequest(BaseModel):
    device_id: str = Field(..., description="デバイスのUUID")
    public_key: bytes = Field(..., description="公開鍵")
    name: Optional[str] = Field(None, description="デバイス名")

class Device(BaseModel):
    id: str
    owner: Optional[str]
    name: str
    public_key: bytes
    coins: int

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
    time_stamp: datetime
    signature: bytes # 送信元デバイスによる署名

class DeviceUpdateRequest(BaseModel):
    device_id: str
    request_id: str
    time_stamp: datetime
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