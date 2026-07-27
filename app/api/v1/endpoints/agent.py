from app.agent.agent import TrafficReActAgent
from app.api.deps import get_current_user
from app.schemas.agent import AgentResponse, AgentRunRequest, AgentResumeRequest
from app.models.user import User
from fastapi import APIRouter, Depends, UploadFile, File
from uuid import uuid4
from pathlib import Path

router = APIRouter()

_agent_runtime: TrafficReActAgent | None = None
def get_agent_runtime() -> TrafficReActAgent:
    """创建Agent单例 避免请求初始化失去之前状态"""
    global _agent_runtime
    if _agent_runtime is None:
        _agent_runtime = TrafficReActAgent()
    return _agent_runtime

async def save_upload_file(file: UploadFile, target_dir: Path) -> str:
    target_dir.mkdir(parents=True,exist_ok=True)
    file_path = target_dir / file.filename
    content = await file.read()
    file_path.write_bytes(content)
    return str(file_path)

@router.post("/upload-files")
async def upload_agent_files(
    map_file: UploadFile = File(...),
    signal_file: UploadFile = File(...),
    stop_file: UploadFile = File(...),
    order_file: UploadFile = File(...),
    bus_file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    upload_dir = Path("storage") / "agent-uploads" / str(current_user.id) / str(uuid4())

    attachments = {
        "map_file": await save_upload_file(map_file, upload_dir),
        "signal_file": await save_upload_file(signal_file, upload_dir),
        "stop_file": await save_upload_file(stop_file, upload_dir),
        "order_file": await save_upload_file(order_file, upload_dir),
        "bus_file": await save_upload_file(bus_file, upload_dir),
    }

    return {
        "message": "文件上传成功",
        "attachments": attachments,
    }

@router.post("/run",response_model=AgentResponse)
async def run_agent(
    request: AgentRunRequest,
    current_user: User = Depends(get_current_user),
    agent_runtime: TrafficReActAgent = Depends(get_agent_runtime)
) -> AgentResponse:
    thread_id = (
        request.thread_id or f"user-{current_user.id}-{uuid4()}"
    )
    attachments = (
        request.attachments.uploaded_files() if request.attachments else {}
    )
    result = await agent_runtime.ainvoke(
        message=request.message,
        thread_id=thread_id,
        attachments=attachments,
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

@router.post("/resume", response_model=AgentResponse)
async def resume_agent(
    request: AgentResumeRequest,
    current_user: User = Depends(get_current_user),
    agent_runtime: TrafficReActAgent = Depends(get_agent_runtime),
) -> AgentResponse:
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