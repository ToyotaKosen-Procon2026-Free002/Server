from firebase_admin import credentials, messaging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from routers import users, devices
from database.connection import get_connection

app = FastAPI(
    title="Coco Seal API",
    description="ココ・シール 防犯ブザーシステム API",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router)
app.include_router(devices.router)

get_connection()