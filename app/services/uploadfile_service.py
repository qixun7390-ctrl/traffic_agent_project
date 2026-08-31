import json

from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.core.config import settings
from app.models import UploadFileRecord
from sqlalchemy import select, delete
from pathlib import Path
from fastapi import UploadFile
from uuid import uuid4

REQUIRED_FILE_TYPE = {
    "map_file",
    "signal_file",
    "stop_file",
    "order_file",
    "bus_file",
}

LIST_JSON_FILE_TYPES = {
    "map_file",
    "stop_file",
    "order_file",
    "bus_file",
}

DICT_JSON_FILE_TYPES = {
    "signal_file",
}

REQUIRED_ITEM_KEYS = {
    "map_file": {"nds_id", "link_id", "link_coors", "start_coor", "end_coor"},
    "stop_file": {"stop_id", "poi_id", "poi_lng", "poi_lat", "nds_id"},
    "order_file": {
        "device_id",
        "available_pickup_stop_ids",
        "available_dropoff_stop_ids",
        "o_relative_time",
        "passengers",
    },
    "bus_file": {
        "vehicle_id",
        "vehicle_speed",
        "vehicle_capacity",
        "vehicle_init_stop_id",
    },
}

REQUIRED_SIGNAL_ITEM_KEYS = {"nds_id", "inter_id", "lights"}
VALIDATION_SAMPLE_SIZE = 20


def format_missing_keys(missing_keys: set[str]) -> str:
    return ", ".join(sorted(missing_keys))


def validate_list_items(file_type: str, payload: list) -> None:
    required_keys = REQUIRED_ITEM_KEYS[file_type]

    for index, item in enumerate(payload[:VALIDATION_SAMPLE_SIZE], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{file_type} 第 {index} 条数据必须是 JSON 对象")

        missing_keys = required_keys - item.keys()
        if missing_keys:
            raise ValueError(
                f"{file_type} 内容结构不正确，缺少字段: {format_missing_keys(missing_keys)}"
            )


def validate_signal_items(payload: dict) -> None:
    for key, item in list(payload.items())[:VALIDATION_SAMPLE_SIZE]:
        if not isinstance(item, dict):
            raise ValueError(f"signal_file 中 {key} 对应的数据必须是 JSON 对象")

        missing_keys = REQUIRED_SIGNAL_ITEM_KEYS - item.keys()
        if missing_keys:
            raise ValueError(
                f"signal_file 内容结构不正确，缺少字段: {format_missing_keys(missing_keys)}"
            )


def validate_json_payload(file_type: str, payload) -> None:
    if file_type in LIST_JSON_FILE_TYPES:
        if not isinstance(payload, list) or not payload:
            raise ValueError(f"{file_type} 内容结构不正确，应为非空 JSON 数组")
        validate_list_items(file_type, payload)
        return

    if file_type in DICT_JSON_FILE_TYPES:
        if not isinstance(payload, dict) or not payload:
            raise ValueError(f"{file_type} 内容结构不正确，应为非空 JSON 对象")
        validate_signal_items(payload)
        return

    raise ValueError(f"不支持的文件类型: {file_type}")

class UploadFileService:
    def __init__(self, db:AsyncSession):
        self.db = db

    async def create_file_record(
        self,
        *,
        batch_id: UUID,
        user_id: UUID,
        file_type: str,
        original_name: str,
        stored_name: str,
        file_path: str,
        mime_type: str | None,
        file_size: int,
    ) -> UploadFileRecord:
        record = UploadFileRecord(
            batch_id=batch_id,
            user_id=user_id,
            file_type=file_type,
            original_name=original_name,
            stored_name=stored_name,
            file_path=file_path,
            mime_type=mime_type,
            file_size=file_size,
        )
        self.db.add(record)
        return record

    async def list_files_for_batch(
        self,
        *,
        batch_id: UUID,
        user_id: UUID,
    ) -> list[UploadFileRecord]:
        result = await self.db.execute(
            select(UploadFileRecord)
            .where(UploadFileRecord.user_id == user_id)
            .where(UploadFileRecord.batch_id == batch_id)
        )

        return list(result.scalars().all())

    async def get_attachments_for_batch(
        self,
        *,
        user_id: UUID,
        batch_id: UUID,
    ) -> dict[str, str] | None:
        """前端一次性了解某批次所有文件状态,进行文件完整性校验"""
        records = await self.list_files_for_batch(
            user_id=user_id,
            batch_id=batch_id,
        )

        attachments = {
            record.file_type: record.file_path
            for record in records
        }

        if not REQUIRED_FILE_TYPE.issubset(attachments.keys()):
            return None

        return attachments

    async def get_file_batch(
        self,
        *,
        user_id: UUID,
        batch_id: UUID,
        file_type: str,
    ) -> UploadFileRecord | None:
        """获取具体的json文件"""
        result = await self.db.execute(
            select(UploadFileRecord)
            .where(UploadFileRecord.user_id == user_id)
            .where(UploadFileRecord.batch_id == batch_id)
            .where(UploadFileRecord.file_type == file_type)
        )
        return result.scalar_one_or_none()

    async def delete_files_for_batch(
        self,
        *,
        user_id: UUID,
        batch_id: UUID,
    ) -> list[str]:
        """用batch_id管理删除某个上传批次的文件记录，并返回对应的文件路径"""
        records = await self.list_files_for_batch(
            user_id=user_id,
            batch_id=batch_id,
        )
        file_paths = [
            record.file_path
            for record in records
        ]
        await self.db.execute(
            delete(UploadFileRecord)
            .where(UploadFileRecord.user_id == user_id)
            .where(UploadFileRecord.batch_id == batch_id)
        )

        return file_paths

    async def save_upload_file(
        self,
        file: UploadFile,
        target_dir: Path,
        file_type: str,
    ) -> dict:
        """存储用户上传json文件"""
        target_dir.mkdir(parents=True, exist_ok=True)

        if not file.filename:
            raise ValueError("上传文件缺少文件名")
        original_name = Path(file.filename).name
        suffix = Path(original_name).suffix.lower()

        if suffix != ".json":
            raise ValueError(f"{original_name} 不是json文件")

        stored_name = f"{file_type}_{uuid4().hex}{suffix}"
        file_path = target_dir / stored_name

        content = await file.read()
        if len(content) > settings.MAX_UPLOAD_FILE_SIZE:
            raise ValueError(f"{original_name} 文件过大，请检查上传文件是否正确")
        try:
            payload = json.loads(content.decode("utf-8"))
            validate_json_payload(file_type, payload)
        except UnicodeDecodeError:
            raise ValueError(f"{original_name} 不是 UTF-8 编码文件")
        except json.JSONDecodeError:
            raise ValueError(f"{original_name} 不是合法 JSON文件")

        file_path.write_bytes(content)

        return {
            "file_type": file_type,
            "original_name": original_name,
            "stored_name": stored_name,
            "file_path": str(file_path),
            "mime_type": file.content_type,
            "file_size": len(content),
        }
