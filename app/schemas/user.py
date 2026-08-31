from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, field_validator


class UserBase(BaseModel):
    """ 用户的基本属性 """
    username: str = Field(...,min_length=3,max_length=50)

class UserCreate(UserBase):
    """注册时允许客户端提交的数据"""
    #客户端提交未定义字段时拒绝
    model_config = ConfigDict(extra="forbid")
    password: str = Field(...,min_length=8,max_length=128)

    @field_validator("username")
    def validate_username(cls,v: str) -> str:
        if not v or not v.strip() or ' ' in v:
            raise ValueError("用户名不能包含空格")
        return v

    @field_validator("password")
    def validate_password(cls, v: str) -> str:
        if not v or not v.strip() or ' ' in v:
            raise ValueError("密码中不能包含空格")
        return v

class UserPublic(UserBase):
    """允许服务器返回给客户端的用户信息"""
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    is_active: bool
    create_at: datetime
    updated_at: datetime

#输出验证
class Token(BaseModel):
    """登录成功之后的令牌响应"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int