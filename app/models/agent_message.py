from sqlalchemy.orm import Mapped,mapped_column
from app.core.database import Base
from sqlalchemy.dialects.postgresql import UUID, JSONB
import uuid
from sqlalchemy import DateTime, ForeignKey, String, Text
from datetime import datetime

class AgentMessage(Base):
    """交通仿真智能体工作台历史消息"""
    __tablename__ = "agent_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    thread_id: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        index=True,
    )

    role: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    payload: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        index=True
    )