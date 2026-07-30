from pathlib import Path
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.simulation_run import SimulationRun
from app.services.simulation_http_client import SimulationPlatformclient

#允许用户上传的文件类型
ALLOWED_FILE_TYPES = {
    "map_file",
    "signal_file",
    "stop_file",
    "order_file",
    "bus_file",
}

class SimulationRunService:
    """用户仿真记录服务"""

    def __init__(self, db:AsyncSession):
        self.db = db

    async def create_run_for_user(
        self,
        user_id: UUID,
        platform_simulation_id: int,
        attachments: dict[str,str],
    ) -> SimulationRun:
        """创建成功后保存记录"""
        run = SimulationRun(
            user_id = user_id,
            platform_simulation_id = platform_simulation_id,
            status = "CREATED",

            map_file_path = attachments["map_file"],
            signal_file_path = attachments["signal_file"],
            bus_file_path = attachments["bus_file"],
            order_file_path = attachments["order_file"],
            stop_file_path = attachments["stop_file"],

            map_original_name = Path(attachments["map_file"]).name,
            signal_original_name = Path(attachments["signal_file"]).name,
            bus_original_name = Path(attachments["bus_file"]).name,
            order_original_name = Path(attachments["order_file"]).name,
            stop_original_name = Path(attachments["stop_file"]).name,
        )

        self.db.add(run)
        await self.db.commit()
        await self.db.refresh(run)

        return run

    async def list_runs_for_user(
        self,
        user_id: UUID,
    ) -> list[SimulationRun]:
        """查询当前用户自己的仿真列表"""

        result = await self.db.execute(
            select(SimulationRun)
            .where(SimulationRun.user_id == user_id)
            .order_by(SimulationRun.created_at.desc())
        )

        return list(result.scalars().all())

    async def get_run_for_user(
        self,
        user_id: UUID,
        simulation_id: int,
    ) -> SimulationRun | None:
        """根据当前用户和远端 simulation_id 查询记录"""

        result = await self.db.execute(
            select(SimulationRun)
            .where(SimulationRun.user_id == user_id)
            .where(SimulationRun.platform_simulation_id == simulation_id)
        )

        return result.scalar_one_or_none()

    async def get_file_for_user(
        self,
        user_id: UUID,
        simulation_id: int,
        file_type: str,
    ) -> tuple[Path, str] | None:
        """下载前文件，同时用户只能下载自己的文件"""
        if file_type not in ALLOWED_FILE_TYPES:
            return None

        run = await self.get_run_for_user(
            user_id = user_id,
            simulation_id = simulation_id,
        )

        if run is None:
            return None

        file_path_map = {
            "map_file": run.map_file_path,
            "signal_file": run.signal_file_path,
            "stop_file": run.stop_file_path,
            "order_file": run.order_file_path,
            "bus_file": run.bus_file_path,
        }

        original_name_map = {
            "map_file": run.map_original_name,
            "signal_file": run.signal_original_name,
            "stop_file": run.stop_original_name,
            "order_file": run.order_original_name,
            "bus_file": run.bus_original_name,
        }

        file_path = Path(file_path_map[file_type])
        original_name = original_name_map[file_type]

        return file_path, original_name

    async def delete_run_for_user(
        self,
        user_id: UUID,
        simulation_id: int,
    ) -> bool:
        """删除远端仿真，本地 JSON文件，数据库记录"""
        run = await self.get_run_for_user(
            user_id = user_id,
            simulation_id = simulation_id
        )

        if run is None:
            return False

        async with SimulationPlatformclient(
            base_url = settings.SIMULATION_PLATFORM_BASE_URL,
            token = settings.SIMULATION_PLATFORM_TOKEN,
        ) as client:
            await client.delete_simulation(
                simulation_id=simulation_id,
            )

        file_paths = [
            run.map_file_path,
            run.signal_file_path,
            run.stop_file_path,
            run.order_file_path,
            run.bus_file_path,
        ]

        for file_path in file_paths:
            path = Path(file_path)
            if path.exists() and path.is_file():
                path.unlink()

        await self.db.delete(run)
        await self.db.commit()

        return True