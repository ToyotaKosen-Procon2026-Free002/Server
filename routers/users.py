from fastapi import APIRouter, Depends
from auth import User, get_current_user


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
    raise NotImplementedError()



@router.patch(
    "/me",
    summary="現在ログイン中のユーザー情報を更新",
    response_model=User
)
async def update_me(update_user: User, current_user: User = Depends(get_current_user)):
    """
    Firebase Authenticationで認証されたユーザーの情報を更新します。
    """
    raise NotImplementedError()