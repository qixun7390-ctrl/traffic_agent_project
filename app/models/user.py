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
    email: Mapped[str] = mapped_column(
        String(255),unique=True,index=True,nullable=False
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255),nullable=False
    )

    #用户和权限
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole),default=UserRole.USER,nullable=False
    )
    is_superuser: Mapped[bool] = mapped_column(
        Boolean,default=False,nullable=False
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean,default=False,nullable=False
    )
    # 关系
    roles = relationship("Role",secondary="user_role",back_populates="users")

class Role(BaseModel):
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(
        String(50),unique=True,index=True,nullable=False
    )
    description: Mapped[str] = mapped_column(
        String(255),nullable=True,index=True
    )
    is_builtin: Mapped[bool] = mapped_column(
        Boolean,nullable=False,default=False
    )
    #关系
    users = relationship("User",secondary="user_role",back_populates="roles")

class UserRoleAssociation(BaseModel):
    __tablename__ = "user_role"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id",ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    role_id: Mapped[UUID] = mapped_column(
        ForeignKey("roles.id",ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    __table_args__ = (
        UniqueConstraint("user_id","role_id",name="uq_user_role_user_id_role_id"),
    )
