from datetime import datetime
import uuid
from sqlalchemy import ForeignKey,DateTime,String,Integer,UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base
from sqlalchemy.orm import Mapped,mapped_column

class UploadFileRecord(Base):
    __tablename__ = "upload_files"
    __table_args__ = (
        UniqueConstraint(
            "batch_id",
            "file_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    file_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    original_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    stored_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    file_path: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
    )

    mime_type: Mapped[str] = mapped_column(
        String(128),
        nullable=True,
    )

    file_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )