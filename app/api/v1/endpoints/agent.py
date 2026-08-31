from datetime import datetime
from app.agent.agent import TrafficReActAgent, get_agent_runtime
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.schemas.agent import AgentResponse, AgentRunRequest, AgentResumeRequest
from app.models.user import User
from fastapi import APIRouter, Depends, UploadFile, File
from uuid import uuid4
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.uploadfile_service import UploadFileService
from app.services.agent_message_service import AgentMessageService
from fastapi.responses import StreamingResponse
import json

OPERATION_LABELS = {
    "create": "创建仿真",
    "delete": "删除仿真",
    "query": "查询仿真",
}
router = APIRouter()
def format_sse(event:str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data,ensure_ascii=False)}\n\n"

async def save_and_format_sse(
    *,
    message_service: AgentMessageService,
    user_id,
    thread_id: str,
    event_name: str,
    data: dict,
    role: str = "assistant",
) -> str:
    content = data.get("message") or event_name

    await message_service.create_message(
        user_id = user_id,
        thread_id = thread_id,
        role = role,
        event_type = event_name,
        content = content,
        payload = data,
    )

    return format_sse(event_name, data)

def translate_graph_event(event: dict, thread_id: str) -> tuple[str, dict]:
    if not isinstance(event,dict):
        return (
            "debug",
            {
                "thread_id": thread_id,
                "message": repr(event),
            }
        )

    if "__interrupt__" in event:
        interrupts = event.get("__interrupt__") or []
        interrupts_obj = interrupts[0] if interrupts else None
        interrupts_value = getattr(interrupts_obj, "value", None)

        return (
            "confirmation_required",
            {
                "status": "awaiting_confirmation",
                "thread_id": thread_id,
                "message": "创建仿真需要用户确认后再执行",
                "data": {
                    "interrupt": interrupts_value,
                }
            }
        )

    if "intent" in event:
        operation = event["intent"].get("operation")
        operation_label = {
            "create": "创建仿真",
            "delete": "删除仿真",
            "query": "查询仿真",
        }.get(operation,operation)

        return (
            "status",
            {
                "status": "running",
                "thread_id": thread_id,
                "stage": "intent",
                "message": f"经过Traffic Agent识别用户的意图为:{operation_label}",
            }
        )

    if "extract_create_params" in event:
        update = event["extract_create_params"]
        if update.get("error"):
            return (
                "error",
                {
                    "status": "failed",
                    "thread_id": thread_id,
                    "message": update["error"].get("message","创建参数校验失败"),
                    "data": update,
                },
            )

        return (
            "status",
            {
                "status": "running",
                "thread_id": thread_id,
                "stage": "extract_create_params",
                "message": "关于用户创建仿真的参数已提取，上传文件也校验通过",
            }
        )

    if "create_confirmation" in event:
        update = event["create_confirmation"]
        status = update.get("confirmation_status")

        if status == "rejected":
            return (
                "done",
                {
                    "status": "cancelled",
                    "thread_id": thread_id,
                    "stage": "create_confirmation",
                    "message": "用户已取消创建仿真",
                    "data": update,
                },
            )

        return (
            "status",
            {
                "status": "running",
                "thread_id": thread_id,
                "stage": "create_confirmation",
                "message": "用户已确认，开始创建仿真",
                "data": update.get("pending_action"),
            },
        )

    if "delete_confirmation" in event:
        update = event["delete_confirmation"]
        status = update.get("confirmation_status")

        if status == "rejected":
            return (
                "done",
                {
                    "status": "cancelled",
                    "thread_id": thread_id,
                    "stage": "delete_confirmation",
                    "message": "用户已取消创建仿真",
                    "data": update,
                },
            )

        return (
            "status",
            {
                "status": "running",
                "thread_id": thread_id,
                "stage": "delete_confirmation",
                "message": "用户已确认，开始删除仿真",
                "data": update.get("pending_action"),
            },
        )

    if "create_execute" in event:
        update = event["create_execute"]

        if update.get("error"):
            return (
                "error",
                {
                    "status": "failed",
                    "thread_id": thread_id,
                    "stage": "create_execute",
                    "message": update["error"].get("message","创建仿真失败"),
                    "data": update,
                },
            )

        return (
            "done",
            {
                "status": "completed",
                "thread_id": thread_id,
                "stage": "create_execute",
                "message": "仿真创建成功",
                "data": update.get("last_result"),
            },
        )

    if "delete_execute" in event:
        update = event["delete_execute"]
        if update.get("error"):
            return (
                "error",
                {
                    "status": "failed",
                    "thread_id": thread_id,
                    "stage": "delete_execute",
                    "message": update["error"].get("message", "删除仿真失败"),
                    "data": update,
                },
            )

        return (
            "done",
            {
                "status": "completed",
                "thread_id": thread_id,
                "stage": "delete_execute",
                "message": "仿真删除成功",
                "data": update.get("last_result"),
            },
        )

    return (
        "debug",
        {
            "thread_id": thread_id,
            "message": "收到未编译的图事件",
            "raw_event": repr(event)
        }
    )

@router.post("/upload-files")
async def upload_agent_files(
    map_file: UploadFile = File(...),
    signal_file: UploadFile = File(...),
    stop_file: UploadFile = File(...),
    order_file: UploadFile = File(...),
    bus_file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    batch_id = uuid4()
    upload_dir = (
        Path(settings.SIMULATION_ARTIFACT_ROOT)
        / "agent_uploads"
        / str(current_user.id)
        / str(batch_id)
    )

    service = UploadFileService(db)

    upload_items = {
        "map_file": map_file,
        "bus_file": bus_file,
        "stop_file": stop_file,
        "order_file": order_file,
        "signal_file": signal_file,
    }

    attachments = {}
    files = {}

    try:
        for file_type,upload_file in upload_items.items():
            file_info = await service.save_upload_file(
                file = upload_file,
                target_dir = upload_dir,
                file_type = file_type,
            )

            await service.create_file_record(
                batch_id = batch_id,
                user_id = current_user.id,
                file_type = file_info.get("file_type"),
                original_name = file_info.get("original_name"),
                stored_name = file_info.get("stored_name"),
                file_path = file_info.get("file_path"),
                mime_type = file_info.get("mime_type"),
                file_size = file_info.get("file_size"),
            )

            attachments[file_type] = file_info["file_path"]
            files[file_type] = file_info["original_name"]
        await db.commit()

    except Exception as e:
        await db.rollback()
        return {
            "message": "文件校验失败",
            "validation_status": "FAILED",
            "error": str(e)
        }

    return {
        "message": "文件上传并校验成功",
        "validation_status": "PASSED",
        "batch_id": str(batch_id),
        "attachments": attachments,
        "files": files
    }

@router.post("/run",response_model=AgentResponse)
async def run_agent(
    request: AgentRunRequest,
    current_user: User = Depends(get_current_user),
    agent_runtime: TrafficReActAgent = Depends(get_agent_runtime),
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    thread_id = (
        request.thread_id or f"user-{current_user.id}-{uuid4()}"
    )
    attachments: dict[str, str] = {}
    upload_batch_id = None

    if request.upload_batch_id:
        service = UploadFileService(db)

        batch_attachments = await service.get_attachments_for_batch(
            user_id=current_user.id,
            batch_id=request.upload_batch_id,
        )

        if batch_attachments is None:
            return AgentResponse(
                status="missing_attachments",
                thread_id=thread_id,
                message="上传批次不存在或缺少文件",
                data = {
                    "missing_attachments": [
                        "map_file",
                        "signal_file",
                        "stop_file",
                        "order_file",
                        "bus_file",
                    ]
                },
            )

        attachments = batch_attachments
        upload_batch_id = str(request.upload_batch_id)

    result = await agent_runtime.ainvoke(
        message=request.message,
        thread_id=thread_id,
        user_id=str(current_user.id),
        attachments=attachments,
        upload_batch_id=upload_batch_id,
    )
    #创建或删除达到interrupt时，等待用户确认
    if "__interrupt__" in result:
        interrupt_payload = result["__interrupt__"][0].value
        return AgentResponse(
            status="awaiting_confirmation",
            thread_id=thread_id,
            message=interrupt_payload["question"],
            confirmation=interrupt_payload["pending_action"],
            data={"interrupt": interrupt_payload},
        )
    if result.get("error"):
        status = (
            "missing_attachments"
            if result.get("missing_attachments") else "failed"
        )
        return AgentResponse(
            status = status,
            thread_id = thread_id,
            message=result["error"]["message"],
            data={
                "error": result["error"],
                "missing_attachments": result.get(
                    "missing_attachments",
                    []
                )
            }
        )

    #创建或删除执行成功
    if result.get("last_result") is not None:
        return AgentResponse(
            status = "completed",
            thread_id= thread_id,
            message="操作已完成",
            data=result["last_result"],
        )

    # 查询 ReAct 的最终答案在最后一条 AIMessage 中。
    messages = result.get("messages", [])
    final_message = (
        str(messages[-1].content)
        if messages
        else "查询完成"
    )

    return AgentResponse(
        status="completed",
        thread_id=thread_id,
        message=final_message,
    )

@router.post("/run/stream")
async def run_agent_stream(
    request: AgentRunRequest,
    current_user: User = Depends(get_current_user),
    agent_runtime: TrafficReActAgent = Depends(get_agent_runtime),
    db: AsyncSession = Depends(get_db),
):
    thread_id = (
        request.thread_id or f"user-{current_user.id}-{uuid4()}"
    )
    message_service = AgentMessageService(db)
    recent_messages = await message_service.list_recent_messages_for_context(
        user_id=current_user.id,
        limit=20,
    )
    history_context = message_service.build_history_context(recent_messages)

    await message_service.create_message(
        user_id=current_user.id,
        thread_id=thread_id,
        role="user",
        event_type="user_message",
        content=request.message,
        payload={
            "upload_batch_id": str(request.upload_batch_id) if request.upload_batch_id else None
        }
    )

    attachments: dict[str,str] = {}
    upload_batch_id = None
    if request.upload_batch_id:
        service = UploadFileService(db)
        batch_attachments = await service.get_attachments_for_batch(
            user_id=current_user.id,
            batch_id=request.upload_batch_id,
        )

        if batch_attachments is None:
            async def missing_event_generator():
                data = {
                    "status": "missing_attachments",
                    "thread_id": thread_id,
                    "message": "上传批次不存在或缺少文件",
                    "missing_attachments": [
                        "map_file",
                        "bus_file",
                        "stop_file",
                        "order_file",
                        "signal_file",
                    ],
                }
                yield await save_and_format_sse(
                    message_service=message_service,
                    user_id=current_user.id,
                    thread_id=thread_id,
                    event_name="error",
                    data=data,
                )
            return StreamingResponse(
                missing_event_generator(),
                media_type="text/event-stream",
            )

        attachments = batch_attachments
        upload_batch_id = str(request.upload_batch_id)
    async def event_generator():
        has_terminal_event = False
        start_data = {
            "status": "started",
            "thread_id": thread_id,
            "message": "智能体开始处理请求",
        }
        yield await save_and_format_sse(
            message_service=message_service,
            user_id=current_user.id,
            thread_id=thread_id,
            event_name="status",
            data=start_data
        )

        async for event in agent_runtime.astream(
            message=request.message,
            thread_id=thread_id,
            user_id=str(current_user.id),
            attachments=attachments,
            upload_batch_id=upload_batch_id,
            history_context=history_context,
        ):
            event_name, data = translate_graph_event(event, thread_id)
            yield await save_and_format_sse(
                message_service=message_service,
                user_id=current_user.id,
                thread_id=thread_id,
                event_name=event_name,
                data=data,
            )

            if event_name in {"confirmation_required", "error", "done"}:
                has_terminal_event = True

        if not has_terminal_event:
            done_data = {
                "status": "done",
                "thread_id": thread_id,
                "message": "智能体处理完成",
            }
            yield await save_and_format_sse(
                message_service=message_service,
                user_id=current_user.id,
                thread_id=thread_id,
                event_name="done",
                data=done_data,
            )
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )

@router.get("/messages")
async def list_agent_messages(
    limit: int = 50,
    before: datetime | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    limit = min(max(limit, 1), 50)

    service = AgentMessageService(db)

    messages = await service.list_messages_for_user(
        user_id=current_user.id,
        limit=limit,
        before=before,
    )

    return {
        "message": "Success",
        "data": [
            {
                "id": str(message.id),
                "thread_id": message.thread_id,
                "role": message.role,
                "event_type": message.event_type,
                "content": message.content,
                "payload": message.payload,
                "created_at": message.created_at,
            }
            for message in messages
        ],
        "pagination": {
            "limit": limit,
            "next_before": (
                messages[0].created_at if messages else None
            ),
            "has_more": len(messages) == limit,
        },
    }

@router.delete("/messages")
async def clear_agent_messages(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = AgentMessageService(db)
    deleted_count = await service.clear_messages_for_user(
        user_id = current_user.id,
    )
    return {
        "message": "历史记录已被清空",
        "data": {
            "deleted_count": deleted_count
        }
    }

@router.post("/resume", response_model=AgentResponse)
async def resume_agent(
    request: AgentResumeRequest,
    current_user: User = Depends(get_current_user),
    agent_runtime: TrafficReActAgent = Depends(get_agent_runtime),
) -> AgentResponse:
    expected_prefix = f"user-{current_user.id}-"

    if not request.thread_id.startswith(expected_prefix):
        return AgentResponse(
            status="failed",
            thread_id=request.thread_id,
            message="无权恢复该任务",
            data= {
                "error": {
                    "node": "resume_agent",
                    "message": "thread_id 不属于当前用户",
                }
            },
        )

    result = await agent_runtime.resume(
        thread_id=request.thread_id,
        approved=request.approved,
    )

    if result.get("confirmation_status") == "rejected":
        return AgentResponse(
            status="cancelled",
            thread_id=request.thread_id,
            message="用户已取消操作",
        )

    if result.get("error"):
        return AgentResponse(
            status="failed",
            thread_id=request.thread_id,
            message=result["error"]["message"],
            data={"error": result["error"]},
        )

    return AgentResponse(
        status="completed",
        thread_id=request.thread_id,
        message="操作已完成",
        data=result.get("last_result"),
    )

@router.post("/resume/stream")
async def resume_agent_stream(
    request: AgentResumeRequest,
    current_user: User = Depends(get_current_user),
    agent_runtime: TrafficReActAgent = Depends(get_agent_runtime),
    db: AsyncSession = Depends(get_db),
):
    expected_prefix = f"user-{current_user.id}-"
    message_service = AgentMessageService(db)
    if not request.thread_id.startswith(expected_prefix):
        async def forbidden_event_generator():
            data = {
                "status": "failed",
                "thread_id": request.thread_id,
                "message": "无权恢复该任务",
            }
            yield await save_and_format_sse(
                message_service=message_service,
                user_id=current_user.id,
                thread_id=request.thread_id,
                event_name="error",
                data=data,
            )
        return StreamingResponse(
            forbidden_event_generator(),
            media_type="text/event-stream"
        )
    await message_service.create_message(
        user_id=current_user.id,
        thread_id=request.thread_id,
        role="user",
        event_type="resume_decision",
        content="用户确认继续执行" if request.approved else "用户取消执行",
        payload={
            "approved": request.approved,
        }
    )

    async def event_generator():
        has_terminal_event = False
        start_data = {
            "status": "started",
            "thread_id": request.thread_id,
            "message": "正在恢复智能体任务",
        }
        yield await save_and_format_sse(
            message_service=message_service,
            user_id=current_user.id,
            thread_id=request.thread_id,
            event_name="status",
            data=start_data,
        )

        async for event in agent_runtime.resume_stream(
            thread_id = request.thread_id,
            approved=request.approved,
        ):
            event_name, data = translate_graph_event(
                event = event,
                thread_id = request.thread_id
            )
            yield await save_and_format_sse(
                message_service=message_service,
                user_id=current_user.id,
                thread_id=request.thread_id,
                event_name=event_name,
                data=data,
            )

            if event_name in {"confirmation_required", "error", "done"}:
                has_terminal_event = True

        if not has_terminal_event:
            done_data = {
                "status": "done",
                "thread_id": request.thread_id,
                "message": "智能体恢复执行完成",
            }
            yield await save_and_format_sse(
                message_service=message_service,
                user_id=current_user.id,
                thread_id=request.thread_id,
                event_name="done",
                data=done_data,
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )