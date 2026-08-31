import shutil
from pathlib import Path
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UploadFileRecord
from app.core.config import settings
from app.models.simulation_run import SimulationRun
from app.services.simulation_http_client import SimulationPlatformclient
from app.services.uploadfile_service import UploadFileService
from app.models.deleted_file import FileTrash
import logging

logger = logging.getLogger(__name__)


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
        upload_batch_id: UUID,
    ) -> SimulationRun:
        """创建成功后保存记录"""
        run = SimulationRun(
            user_id = user_id,
            platform_simulation_id = platform_simulation_id,
            status = "CREATED",
            upload_batch_id=upload_batch_id,

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
        """获取前文件，同时用户只能获取自己的文件"""
        if file_type not in ALLOWED_FILE_TYPES:
            return None
        run = await self.get_run_for_user(
            user_id=user_id,
            simulation_id=simulation_id,
        )
        if run is None or run.upload_batch_id is None:
            return None
        upload_file_service = UploadFileService(self.db)
        file_record = await upload_file_service.get_file_batch(
            user_id=user_id,
            batch_id=run.upload_batch_id,
            file_type=file_type,
        )
        if file_record is None:
            return None
        return Path(file_record.file_path), file_record.original_name

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

        if run is None or run.upload_batch_id is None:
            return False

        max_attempts = 3

        upload_file_service = UploadFileService(self.db)
        trash_service = FileTrashService(self.db)

        try:
            await trash_service.move_batch_to_trash(
                user_id=user_id,
                batch_id=run.upload_batch_id,
                simulation_id=simulation_id
            )
            await self.db.commit()

            async with SimulationPlatformclient(
                base_url=settings.SIMULATION_PLATFORM_BASE_URL,
                token=settings.SIMULATION_PLATFORM_TOKEN,
            ) as client:
                for attempt in range(1,max_attempts + 1):
                    try:
                        await client.delete_simulation(simulation_id=simulation_id)
                        logger.info(f"已成功删除远端仿真平台的仿真记录")
                        break
                    except Exception as e:
                        if attempt == max_attempts:
                            logger.error(f"已经达到最大尝试次数，但仍然无法删除仿真平台的仿真记录")
                            raise RuntimeError(f"已经达到了最大尝试次数，无法删除仿真平台仿真")

            await upload_file_service.delete_files_for_batch(
                user_id=user_id,
                batch_id=run.upload_batch_id
            )

            await self.db.delete(run)
            await self.db.commit()

        except Exception as e:
            await self.db.rollback()

            await trash_service.restore_batch_from_trash(
                user_id = user_id,
                batch_id = run.upload_batch_id,
            )
            await self.db.commit()

            raise
        try:
            await trash_service.cleanup_batch_trash(
                user_id=user_id,
                batch_id=run.upload_batch_id,
            )
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            logger.error(
                "仿真删除已完成，但是回收站清理失败，需要后续人工或定时清理",
                exc_info=True,
            )
        return True

class FileTrashService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def build_trash_path(
        self,
        *,
        user_id: UUID,
        batch_id: UUID,
        stored_name: str,
    ) -> Path:
        return (
            Path(settings.SIMULATION_ARTIFACT_ROOT)
            / ".trash"
            / str(user_id)
            / str(batch_id)
            / stored_name
        )

    async def move_batch_to_trash(
        self,
        *,
        user_id: UUID,
        batch_id: UUID,
        simulation_id: int,
    ) -> list[FileTrash]:
        """将待删除的仿真文件存放到回收站中，如果遇到过程错误，触发回滚和清理缓存等机制"""
        result = await self.db.execute(
            select(UploadFileRecord)
            .where(UploadFileRecord.user_id == user_id)
            .where(UploadFileRecord.batch_id == batch_id)
        )

        records = list(result.scalars().all())

        if not records:
            logger.info(f"用户{user_id}的批次{batch_id}没有文件需要移动")
            return []

        trash_entries: list[FileTrash] = []
        moved_pairs: list[tuple[Path, Path]] = []
        move_failed = False

        try:
            for record in records:
                original_path = Path(record.file_path)
                trash_path = self.build_trash_path(
                    user_id = user_id,
                    batch_id = batch_id,
                    stored_name = record.stored_name,
                )
                trash_path.parent.mkdir(parents=True,exist_ok=True)

                if not original_path.exists():
                    logger.warning(f"源文件不存在：{original_path},跳过")
                    continue

                #尝试移动文件
                trash_entry = None
                try:
                    trash_entry = FileTrash(
                        user_id=user_id,
                        batch_id=batch_id,
                        simulation_id=simulation_id,
                        file_type=record.file_type,
                        original_name=record.original_name,
                        original_path=str(original_path),
                        trash_path=str(trash_path),
                        status="MOVED",
                    )

                    self.db.add(trash_entry)
                    await self.db.flush()

                    shutil.move(str(original_path), str(trash_path))

                    if original_path.exists() or not trash_path.exists():
                        logger.error(
                            f"文件移动到回收站后状态异常: "
                            f"original_exists={original_path.exists()}, "
                            f"trash_exists={trash_path.exists()}, "
                            f"original_path={original_path}, "
                            f"trash_path={trash_path}"
                        )

                        if trash_path.exists():
                            if trash_path.is_dir():
                                shutil.rmtree(trash_path)
                            else:
                                trash_path.unlink()
                        if trash_entry is not None:
                            await self.db.delete(trash_entry)
                            await self.db.flush()

                        move_failed = True
                        break

                    moved_pairs.append((original_path,trash_path))
                    trash_entries.append(trash_entry)

                    logger.info(f"文件已移动到回收站: {original_path} -> {trash_path}")

                except Exception as e:
                    #移动失败并记录错误日志
                    logger.error(
                        f"无法移动文件 {original_path} 到回收站: {e}",
                        exc_info=True
                    )

                    #清理回收站残留文件
                    if trash_path.exists():
                        try:
                            if trash_path.is_dir():
                                shutil.rmtree(trash_path)
                            else:
                                trash_path.unlink()
                            logger.info(f"已清理回收站残留文件: {trash_path}")
                        except Exception as cleanup_error:
                            logger.error(
                                f"清理回收站残留文件失败: {cleanup_error}",
                                exc_info=True,
                            )
                    try:
                        if trash_entry is not None:
                            await self.db.delete(trash_entry)
                            await self.db.flush()
                    except Exception as db_cleanup_error:
                        logger.error(
                            f"清理回收站数据库记录失败:{db_cleanup_error}",
                            exc_info=True,
                        )
                    move_failed = True
                    break

            if move_failed:
                restored_failed = False

                for original_path,trash_path in reversed(moved_pairs):
                    try:
                        if trash_path.exists():
                            original_path.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(trash_path), str(original_path))
                            logger.info(
                                f"已将文件从回收站恢复: {trash_path} -> {original_path}"
                            )
                    except Exception as restore_error:
                        restored_failed = True
                        logger.error(
                            f"恢复文件失败,需要人工处理: {trash_path} -> {original_path}",
                            exc_info=True,
                        )
                if restored_failed:
                    raise RuntimeError(f"移动文件到回收站失败，且部分文件恢复失败，需要人工处理")

                raise RuntimeError(f"移动文件到回收站失败，已尝试恢复已移动文件")
            await self.db.flush()
            return trash_entries

        except Exception:
            raise

    async def restore_batch_from_trash(
        self,
        *,
        user_id: UUID,
        batch_id: UUID,
    ) -> None:
        """用于删除文件之后，如果删除仿真链路出错，从回收站恢复原始json文件"""
        result = await self.db.execute(
            select(FileTrash)
            .where(FileTrash.user_id == user_id)
            .where(FileTrash.batch_id == batch_id)
            .where(FileTrash.status == "MOVED")
        )

        entries = list(result.scalars().all())
        restored_failed = False

        for entry in entries:
            trash_path = Path(entry.trash_path)
            original_path = Path(entry.original_path)

            try:
                if trash_path.exists():
                    original_path.parent.mkdir(parents=True,exist_ok=True)
                    shutil.move(str(trash_path), str(original_path))

                entry.status = "RESTORED"

            except Exception as e:
                restored_failed = True
                logger.error(
                    f"从回收站恢复文件夹:{trash_path} -> {original_path}, error={e}",
                    exc_info=True,
                )

        await self.db.flush()

        if restored_failed:
            raise RuntimeError("部分文件从回收站恢复失败，需要人工处理")

    async def cleanup_batch_trash(
        self,
        *,
        user_id: UUID,
        batch_id: UUID,
    ) -> None:
        """永久清除回收站"""
        result = await self.db.execute(
            select(FileTrash)
            .where(FileTrash.user_id == user_id)
            .where(FileTrash.batch_id == batch_id)
            .where(FileTrash.status == "MOVED")
        )

        entries = list(result.scalars().all())
        cleanup_failed = False

        for entry in entries:
            trash_path = Path(entry.trash_path)

            try:
                if trash_path.exists():
                    if trash_path.is_dir():
                        shutil.rmtree(trash_path)
                    else:
                        trash_path.unlink()

                entry.status = "CLEANED"

            except Exception as e:
                cleanup_failed = True
                logger.error(
                    f"永久清理回收站文件失败: {trash_path},error={e}",
                    exc_info=True,
                )
        await self.db.flush()
        if cleanup_failed:
            raise RuntimeError(f"部分回收站文件永久清理失败,需要人工处理")
