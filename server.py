import firebase_admin
from firebase_admin import credentials, messaging
from fastapi import FastAPI
from pydantic import BaseModel
from routers import users, devices
from database.connection import get_connection

app = FastAPI(
    title="Coco Seal API",
    description="ココ・シール 防犯ブザーシステム API",
    version="1.0.0"
)

app.include_router(users.router)
app.include_router(devices.router)

get_connection()