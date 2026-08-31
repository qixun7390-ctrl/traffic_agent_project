"""
用于身份验证和用户管理的用户模型
"""
import enum
import string
from app.models.base import BaseModel
from sqlalchemy import Column, String, Enum, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship,Mapped,mapped_column
import uuid
from uuid import UUID

class UserRole(str, enum.Enum):
    """用户角色枚举"""
    ADMIN = "admin"
    USER = "user"

class User(BaseModel):
    """用户模型"""
    __tablename__ = "users"

    #基础信息
    username: Mapped[str] = mapped_column(
        String(50),unique=True,index=True,nullable=False
    )

    hashed_password: Mapped[str] = mapped_column(
        String(255),nullable=False
    )