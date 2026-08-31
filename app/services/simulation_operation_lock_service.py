import asyncio
from contextlib import asynccontextmanager


class SimulationOperationLockedError(RuntimeError):
    """同一用户的同一仿真正被其他操作处理。"""


class SimulationOperationLockService:
    """单进程内的异步仿真操作锁管理器。"""

    def __init__(self):
        self._locks = {}
        self._guard = asyncio.Lock()

    async def _get_lock(self, key: str):
        async with self._guard:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            return self._locks[key]

    async def _release_lock_key(self, key: str, lock: asyncio.Lock) -> None:
        async with self._guard:
            if self._locks.get(key) is lock and not lock.locked():
                self._locks.pop(key, None)

    @asynccontextmanager
    async def lock(self, user_id: str, simulation_id: int):
        key = f"{user_id}:{simulation_id}"
        lock = await self._get_lock(key)

        if lock.locked():
            raise SimulationOperationLockedError(
                "当前仿真正在被其他操作处理，请稍后再试"
            )

        try:
            async with lock:
                yield
        finally:
            await self._release_lock_key(key, lock)


simulation_operation_locks = SimulationOperationLockService()