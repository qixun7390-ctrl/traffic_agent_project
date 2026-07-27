from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from app.models.user import UserRole


class UserBase(BaseModel):
    """ 用户的基本属性 """
    username: str = Field(...,min_length=3,max_length=50)
    email: EmailStr

class UserCreate(UserBase):
    """注册时允许客户端提交的数据"""
    #客户端提交未定义字段时拒绝
    model_config = ConfigDict(extra="forbid")
    password: str = Field(...,min_length=8,max_length=128)

class UserPublic(UserBase):
    """允许服务器返回给客户端的用户信息"""
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    role: UserRole
    is_active: bool
    is_verified: bool
    create_at: datetime
    updated_at: datetime

#输出验证
class Token(BaseModel):
    """登录成功之后的令牌响应"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int