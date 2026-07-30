from sqlalchemy import ForeignKey, Integer, String, DateTime
from app.core.database import Base
from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
import uuid

class SimulationRun(Base):
    """用户成功创建的远端仿真记录"""

    __tablename__ = "simulation_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    platform_simulation_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="CREATED",
    )
    map_file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    signal_file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    stop_file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    order_file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    bus_file_path: Mapped[str] = mapped_column(String(1024), nullable=False)

    map_original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    signal_original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    stop_original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    order_original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    bus_original_name: Mapped[str] = mapped_column(String(255), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
