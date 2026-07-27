from sqlalchemy import UUID as SA_UUID, DateTime, Boolean
from sqlalchemy.orm import declared_attr
import uuid
from app.core.database import Base
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
from sqlalchemy.orm import Mapped,mapped_column


class BaseModel(Base):
    """Base model: 定义公共字段，其他模型继承BaseModel"""

    __abstract__ = True

    #自动生成__tablename__
    @declared_attr
    def __tablename__(cls) -> str:
        return cls.__name__.lower()

    id: Mapped[uuid.UUID] = mapped_column(
        SA_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    create_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable= False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        SA_UUID(as_uuid=True),nullable=True
    )
    updated_by: Mapped[uuid.UUID] = mapped_column(
        SA_UUID(as_uuid=True),nullable=True
    )