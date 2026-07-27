from fastapi import APIRouter,Depends,HTTPException,status
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.user import UserPublic, UserCreate
from app.core.database import get_db
from app.services.user_service import UserService
from typing import Any
from fastapi.security import OAuth2PasswordRequestForm
from app.schemas.user import Token, UserCreate, UserPublic
from app.models.user import User
from app.api.deps import get_current_user

router = APIRouter()

@router.post("/register",response_model=UserPublic,status_code=status.HTTP_201_CREATED,)
async def register(user_data:UserCreate,db:AsyncSession = Depends(get_db),) -> Any:
    """注册新用户"""
    user_service = UserService(db)

    try:
        user = await user_service.register_user(user_data)
        return user

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        ) from e

@router.post("/login",response_model=Token)
async def login(
    from_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """登录并获取访问令牌"""
    user_service = UserService(db)

    try:
        return await user_service.login_user(
            from_data.username,
            from_data.password,
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

@router.get("/me", response_model=UserPublic)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
) -> User:
    """获取当前登录用户信息"""
    return current_user