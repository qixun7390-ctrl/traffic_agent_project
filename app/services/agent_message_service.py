from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Any
from app.models.agent_message import AgentMessage
from sqlalchemy import select, delete
from datetime import datetime
from app.core.config import settings


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
        limit: int | None = None,
    ) -> list[AgentMessage]:
        if limit is None:
            limit = settings.AGENT_EPISODIC_CONTEXT_LIMIT

        result = await self.db.execute(
            select(AgentMessage)
            .where(AgentMessage.user_id == user_id)
            .order_by(AgentMessage.created_at.desc())
            .limit(limit)
        )

        messages = list(result.scalars().all())
        return list(reversed(messages))

    def build_history_context(self, messages: list[AgentMessage]) -> str | None:
        return self.build_episodic_context(messages)

    def build_episodic_context(self, messages: list[AgentMessage]) -> str | None:
        if not messages:
            return None

        recent_successful_simulations = self._collect_recent_successful_simulations(
            messages
        )
        recent_events = self._collect_recent_structured_events(messages)

        lines = [
            "情景记忆摘要：仅用于解析用户明确的指代词，例如“刚刚那个 / 上一个 / 这个仿真”。",
            "如果用户当前输入明确给出 simulation_id，必须以当前输入为准。",
            "recent_successful_simulations 数组按时间从近到远排列，第一条就是最近一次成功创建的仿真。",
        ]

        if recent_successful_simulations:
            lines.append(
                "recent_successful_simulations="
                + json_safe_dumps(recent_successful_simulations)
            )

        if recent_events:
            lines.append("recent_events=" + json_safe_dumps(recent_events))

        context = "\n".join(lines)
        max_chars = settings.AGENT_EPISODIC_CONTEXT_MAX_CHARS
        if len(context) > max_chars:
            context = context[:max_chars] + "\n...情景记忆已截断"

        return context

    def _format_context_line(self, message: AgentMessage) -> str:
        line = (
            f"- role={message.role}, "
            f"event_type={message.event_type}, "
            f"content={message.content}"
        )

        payload = message.payload or {}
        if isinstance(payload, dict):
            stage = payload.get("stage")
            if stage:
                line += f", stage={stage}"
            status = payload.get("status")
            if status:
                line += f", status={status}"

            data = payload.get("data")
            if isinstance(data, dict):
                simulation_id = data.get("simulation_id")
                if simulation_id:
                    line += f", simulation_id={simulation_id}"

        return line

    def _collect_recent_successful_simulations(
        self,
        messages: list[AgentMessage],
    ) -> list[dict[str, Any]]:
        """从历史消息的数据库中查找，只有role: assistant,然后是状态是done,同时是在creeate_execute节点创建并状态为completed的才可以算做一次创建完成的仿真"""
        simulations: list[dict[str, Any]] = []

        for message in reversed(messages):
            if message.role != "assistant":
                continue
            if message.event_type != "done":
                continue

            payload = message.payload or {}
            if not isinstance(payload, dict):
                continue

            if payload.get("stage") != "create_execute":
                continue

            if payload.get("status") != "completed":
                continue

            data = payload.get("data")
            if not isinstance(data, dict):
                continue

            simulation_id = data.get("simulation_id")
            if simulation_id is None:
                continue

            create_params = data.get("create_params")
            if not isinstance(create_params, dict):
                create_params = {}

            simulation = {
                "simulation_id": simulation_id,
                "operation": "create",
                "thread_id": message.thread_id,
                "status": payload.get("status"),
                "stage": payload.get("stage"),
                "created_at": message.created_at.isoformat(),
                "summary": message.content,
            }

            name = create_params.get("name")
            if name is not None:
                simulation["name"] = name

            running_time_step = create_params.get("running_time_step")
            if running_time_step is not None:
                simulation["running_time_step"] = running_time_step

            description = create_params.get("description")
            if description:
                simulation["description"] = description

            simulations.append(simulation)

            if len(simulations) >= settings.AGENT_EPISODIC_SIMULATION_LIMIT:
                break

        return simulations

    def _collect_recent_structured_events(
        self,
        messages: list[AgentMessage],
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []

        for message in reversed(messages):
            if message.role != "assistant":
                continue

            payload = message.payload or {}
            if not isinstance(payload, dict):
                payload = {}

            event = {
                "event_type": message.event_type,
                "thread_id": message.thread_id,
                "stage": payload.get("stage"),
                "status": payload.get("status"),
                "message": message.content,
                "created_at": message.created_at.isoformat(),
            }

            data = payload.get("data")
            if isinstance(data, dict):
                simulation_id = data.get("simulation_id")
                if simulation_id is not None:
                    event["simulation_id"] = simulation_id

            events.append(
                {
                    key: value
                    for key, value in event.items()
                    if value is not None
                }
            )

            if len(events) >= settings.AGENT_EPISODIC_EVENT_LIMIT:
                break

        return list(reversed(events))


def json_safe_dumps(data: Any) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
