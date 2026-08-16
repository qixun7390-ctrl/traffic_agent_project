import uuid
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import String, ForeignKey,DateTime,Integer
from sqlalchemy.orm import Mapped,mapped_column
from app.core.database import Base
from datetime import datetime

class FileTrash(Base):
    __tablename__ = "file_trash"

    id:Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    simulation_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True
    )
    file_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    original_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    original_path: Mapped[str] = mapped_column(
        String(1024),
        nullable=False
    )
    trash_path: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="MOVED",
    )
    deleted_at : Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )