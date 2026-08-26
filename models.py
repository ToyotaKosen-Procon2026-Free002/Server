from pydantic import BaseModel
from datetime import datetime

# 汎用

class SuccessResponse(BaseModel):
    success: bool

# 主にユーザーとの通信（Flutter）に使用される

class User(BaseModel):
    display_name: str
    email: str
    firebase_uid: str
    notify_tokens: list[str]

class DeviceInfoUpdateRequest(BaseModel):
    device_id: str
    device_display_name: str


# 主に親機や子機との通信に使用される

class Device(BaseModel):
    id: str
    owner: str | None
    display_name: str

class NearbyCommunication(BaseModel):
    my_id: str
    partner_id: str
    send_seal_id: str
    receive_seal_id: str

class DeviceUpdateRequest(BaseModel):
    parent_device_id: str
    time_stamp: datetime
    nearby_communications: list[NearbyCommunication]

class SosRequest(BaseModel):
    parent_device_id: str
    trigger_time_stamp: datetime
    receive_time_stamp: datetime