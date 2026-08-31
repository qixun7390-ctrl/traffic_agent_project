import asyncio
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services.simulation_run_service import SimulationRunService
from app.services.simulation_operation_lock_service import (
    SimulationOperationLockedError,
    simulation_operation_locks,
)
from fastapi.responses import StreamingResponse

router = APIRouter()

DOWNLOAD_CHUNK_SIZE = 1024 * 1024


async def iter_locked_file(lock_context, file_path: Path):
    try:
        with file_path.open("rb") as file:
            while True:
                chunk = await asyncio.to_thread(
                    file.read,
                    DOWNLOAD_CHUNK_SIZE,
                )
                if not chunk:
                    break
                yield chunk
    finally:
        await lock_context.__aexit__(None, None, None)

@router.get("/my")
async def list_my_simulations(
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """仿真容器管理，仿真号，状态，创建时间，用户上传文件"""
    service = SimulationRunService(db)

    runs = await service.list_runs_for_user(
        user_id=current_user.id,
    )

    data = []
    for run in runs:
        data.append(
            {
                "simulation_id": run.platform_simulation_id,
                "status": run.status,
                "created_at": run.created_at,
                "files": {
                    "map_file": run.map_original_name,
                    "signal_file": run.signal_original_name,
                    "stop_file": run.stop_original_name,
                    "order_file": run.order_original_name,
                    "bus_file": run.bus_original_name,
                }
            }
        )

    return {
        "message": "Success",
        "data": data,
    }

@router.get("/{simulation_id}/files/{file_type}")
async def download_simulation_file(
    simulation_id: int,
    file_type: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """将文件返回给浏览器"""
    service = SimulationRunService(db)

    file_result = await service.get_file_for_user(
        user_id = current_user.id,
        simulation_id = simulation_id,
        file_type = file_type,
    )

    if file_result is None:
        raise HTTPException(
            status_code=404,
            detail="文件不存在或无权访问",
        )

    file_path, original_name = file_result

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="文件不存在",
        )

    lock_context = simulation_operation_locks.lock(
        user_id=str(current_user.id),
        simulation_id=simulation_id,
    )
    try:
        await lock_context.__aenter__()
    except SimulationOperationLockedError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    return StreamingResponse(
        iter_locked_file(lock_context, file_path),
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(original_name)}"
            ),
            "Content-Length": str(file_path.stat().st_size),
        },
    )

@router.delete("/{simulation_id}")
async def delete_my_simulation(
    simulation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """用户可以删除自己的仿真，包括这条创建成功的仿真所对应的json文件"""
    service = SimulationRunService(db)

    try:
        async with simulation_operation_locks.lock(
            user_id=str(current_user.id),
            simulation_id=simulation_id,
        ):
            deleted = await service.delete_run_for_user(
                user_id = current_user.id,
                simulation_id = simulation_id,
            )
    except SimulationOperationLockedError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="仿真不存在或者无权删除"
        )

    return {
        "message": "删除成功",
        "data": {
            "simulation_id": simulation_id
        }
    }
