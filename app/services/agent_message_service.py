from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Any
from app.models.agent_message import AgentMessage
from sqlalchemy import select, delete
from datetime import datetime


class AgentMessageService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_message(
        self,
        *,
        user_id: UUID,
        thread_id: str,
        role: str,
        event_type: str,
        content: str,
        payload: dict[str, Any] | None = None,
    ) -> AgentMessage:
        message = AgentMessage(
            user_id=user_id,
            thread_id=thread_id,
            role=role,
            event_type=event_type,
            content=content,
            payload=payload,
        )

        self.db.add(message)
        await self.db.commit()
        await self.db.refresh(message)
        return message

    async def list_messages_for_user(
        self,
        *,
        user_id: UUID,
        limit: int = 200,
        before: datetime | None = None,
    ) -> list[AgentMessage]:
        stmt = select(AgentMessage).where(AgentMessage.user_id == user_id)

        if before is not None:
            stmt = stmt.where(AgentMessage.created_at < before)

        stmt = stmt.order_by(AgentMessage.created_at.desc()).limit(limit)

        result = await self.db.execute(stmt)
        messages = list(result.scalars().all())
        return list(reversed(messages))

    async def clear_messages_for_user(
        self,
        *,
        user_id: UUID,
    ) -> int:
        result = await self.db.execute(
            delete(AgentMessage).where(AgentMessage.user_id == user_id)
        )
        await self.db.commit()
        return result.rowcount or 0

    async def list_recent_messages_for_context(
        self,
        *,
        user_id: UUID,
        limit: int = 20,
    ) -> list[AgentMessage]:
        result = await self.db.execute(
            select(AgentMessage)
            .where(AgentMessage.user_id == user_id)
            .order_by(AgentMessage.created_at.desc())
            .limit(limit)
        )

        messages = list(result.scalars().all())
        return list(reversed(messages))

    def _format_context_line(self, message: AgentMessage) -> str:
        line = (
            f"- role={message.role}, "
            f"event_type={message.event_type}, "
            f"content={message.content}"
        )

        payload = message.payload or {}
        data = payload.get("data") if isinstance(payload, dict) else None

        if isinstance(data, dict):
            simulation_id = data.get("simulation_id")
            if simulation_id:
                line += f", simulation_id={simulation_id}"
            stage = data.get("stage")
            if stage:
                line += f", stage={stage}"
            status = data.get("status")
            if status:
                line += f", status={status}"

        return line

    def _find_latest_successful_simulation(
            self,
            messages: list[AgentMessage],
    ) -> dict[str, Any] | None:
        for message in reversed(messages):
            if message.role != "assistant":
                continue
            if message.event_type != "done":
                continue

            payload = message.payload or {}
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, dict):
                continue

            simulation_id = data.get("simulation_id")
            if simulation_id is None and isinstance(data.get("last_result"), dict):
                simulation_id = data["last_result"].get("simulation_id")

            if simulation_id is None:
                continue

            return {
                "simulation_id": simulation_id,
                "operation": data.get("stage") or data.get("operation"),
                "thread_id": message.thread_id,
                "content": message.content,
            }

        return None

    def build_history_context(self, messages: list[AgentMessage]) -> str | None:
        if not messages:
            return None

        latest_success = self._find_latest_successful_simulation(messages)

        lines = [
            "你现在看到的是当前用户最近的交通仿真工作台历史摘要，用于理解用户说的“刚刚那个 / 上一个 / 这个”通常指哪条仿真。",
            "你仍然要按自然语言理解用户意图，不要硬编码业务规则；但如果历史里明确出现了最近一次成功仿真，请优先使用那条仿真的 simulation_id。",
        ]

        if latest_success is not None:
            lines.append("最近一次成功完成的仿真：")
            lines.append(f"- simulation_id={latest_success.get('simulation_id')}")
            if latest_success.get("operation"):
                lines.append(f"- operation={latest_success.get('operation')}")
            if latest_success.get("thread_id"):
                lines.append(f"- thread_id={latest_success.get('thread_id')}")
            if latest_success.get("content"):
                lines.append(f"- summary={latest_success.get('content')}")
            lines.append("- 当用户说“刚刚那个仿真”时，默认指这一条。")

        lines.append("最近历史消息：")
        for message in messages[-12:]:
            lines.append(self._format_context_line(message))

        return "\n".join(lines)

    def _format_context_line(self, message: AgentMessage) -> str:
        line = (
            f"- role={message.role}, "
            f"event_type={message.event_type}, "
            f"content={message.content}"
        )

        payload = message.payload or {}
        data = payload.get("data") if isinstance(payload, dict) else None

        if isinstance(data, dict):
            simulation_id = data.get("simulation_id")
            if simulation_id:
                line += f", simulation_id={simulation_id}"
            stage = data.get("stage")
            if stage:
                line += f", stage={stage}"
            status = data.get("status")
            if status:
                line += f", status={status}"

        return line

    def _find_latest_successful_simulation(
        self,
        messages: list[AgentMessage],
    ) -> dict[str, Any] | None:
        for message in reversed(messages):
            if message.role != "assistant":
                continue
            if message.event_type != "done":
                continue

            payload = message.payload or {}
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, dict):
                continue

            simulation_id = data.get("simulation_id")
            if simulation_id is None and isinstance(data.get("last_result"), dict):
                simulation_id = data["last_result"].get("simulation_id")

            if simulation_id is None:
                continue

            return {
                "simulation_id": simulation_id,
                "operation": data.get("stage") or data.get("operation"),
                "thread_id": message.thread_id,
                "content": message.content,
            }

        return None
