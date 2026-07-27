"""
认证和授权
"""
import jwt
from fastapi.security import OAuth2PasswordBearer
from app.core.config import settings
from fastapi import Depends, status, HTTPException
from app.core.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from app.core.security import decode_access_token
from uuid import UUID

oauth2_schema = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login"
)

async def get_current_user(
    token: str = Depends(oauth2_schema),
    db: AsyncSession = Depends(get_db)
) -> User:
    """获取当前认证用户"""
    payload = decode_access_token(token)

    credentials_exception = HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail = "无法验证身份",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if payload is None:
        raise credentials_exception

    try:
        user_id = UUID(payload["sub"])
    except (KeyError, ValueError, TypeError):
        raise credentials_exception

    user = await db.get(User, user_id)

    if user is None or not user.is_active:
        raise credentials_exception

    return user

