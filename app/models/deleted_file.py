import uuid
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import String,BigInteger
from sqlalchemy.orm import Mapped,mapped_column
from app.core.database import Base

class TrashEntry(Base):
    id:Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True
    )
    file_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    file_path: Mapped[str] = mapped_column(
        String(1024),
        nullable=False
    )
    timestamp: Mapped[str] = mapped_column(
        BigInteger,
        nullable=False,
    )
    user: Mapped[str] = mapped_column(
        String(64),
        nullable=False
    )
