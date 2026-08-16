import logging
from datetime import timedelta
from app.core.config import settings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from app.schemas.user import UserCreate
from typing import Optional
from app.core.security import get_password_hash,verify_password,create_access_token

logger = logging.getLogger(__name__)

class UserService:
    """用于管理用户的服务"""

    def __init__(self,db: AsyncSession):
        """
        初始化UserService实例
        Args:
             db： 数据库会话实例
        """
        self.db = db

    async def register_user(self, user_data: UserCreate) -> User:
        """
        注册新用户
        Args:
            user_data: 用户创建数据
        Returns:
             创建的用户对象
        Raises:
            ValueError: 用户已存在
        """
        #检查用户是否存在
        existing_user = await self.get_user_by_username(user_data.username)
        if existing_user:
            raise ValueError("用户名已被占用")

        #创建新用户
        return await self.create_user(user_data)

    async def get_user_by_username(self,username):
        """通过username获取用户"""
        try:
            query = select(User).where(User.username == username, User.is_active == True)
            result = await self.db.execute(query)
            return result.scalar_one_or_none()

        except Exception as e:
            logger.error(f"通过用户名{username}获取用户出错:{e}")
            raise

    async def create_user(self,user_data: UserCreate) -> User:
        """创建新用户"""
        try:
            # 将明文密码转换为 Argon2id哈希
            hash_password = get_password_hash(user_data.password)

            # 构造数据库用户对象
            user = User(
                username=user_data.username,
                hashed_password=hash_password,
            )

            # 添加用户对象到数据库会话中
            self.db.add(user)
            # 提交事务,写入数据库
            await self.db.commit()
            #从数据库刷新对象
            await self.db.refresh(user)
            return user
        except Exception as e:
            await self.db.rollback()
            logger.error(f"创建用户时出错:{e}")
            raise

    async def authenticate(self,username: str,password: str) -> Optional[User]:
        """
        通过用户名或邮箱验证用户
        Args:
            username: 用户名或邮箱
            password: 密码
        Returns:
            验证成功的用户对象，失败则返回None
        """
        try:
            user = await self.get_user_by_username(username)

            if not user:
                return None

            if not verify_password(password,user.hashed_password):
                return None

            return user

        except Exception as e:
            logger.error(f"验证用户时出错：{e}")
            return None

    async def login_user(
        self,
        username: str,
        password: str
    ) -> dict:
        """登录用户并生成访问令牌"""

        user = await self.authenticate(username, password)

        if not user:
            raise ValueError("用户名或密码错误")

        access_token_expires = timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

        access_token = create_access_token(
            data={"sub": str(user.id)},
            expires_delta = access_token_expires,
        )

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }
