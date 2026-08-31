from typing import Literal, Any
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

AgentOperation = Literal[
    "create",
    "query",
    "delete",
    "chat",
]

AgentRunStatus = Literal[
    "completed",
    "awaiting_confirmation",
    "missing_attachments",
    "failed",
    "cancelled",
]

QueryMetric = Literal[
    "duration",
    "order_summary",
    "vehicle_summary",
]

#用户文件附件
class AttachmentManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    map_file: str | None = None
    signal_file: str | None = None
    stop_file: str | None = None
    order_file: str | None = None
    bus_file: str | None = None
    border_file: str | None = None

    def missing_required_files(self) -> list[str]:
        required = [
            "map_file",
            "signal_file",
            "order_file",
            "bus_file",
            "stop_file",
        ]
        return [
            name for name in required if not getattr(self,name)
        ]

    def uploaded_files(self) -> dict[str,str]:
        """ 返回附件清单中已存在的文件路径"""
        return self.model_dump(exclude_none=True)

#用户输入
class AgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(
        min_length = 1,
        max_length = 4000
    )
    thread_id: str | None = Field(
        default = None,
        min_length = 1,
        max_length = 200,
    )
    upload_batch_id: UUID | None = None

class QueryParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    simulation_id: int = Field(gt=0)
    metrics: list[QueryMetric] = Field(
        default_factory=list,
    )

class CreateParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    running_time_step: int = Field(
        default=3600,
        gt=0,
    )
    description: str = ""
    use_random_match: bool = True
    use_cost: bool = True
    attachments: dict[str,str] = Field(
        default_factory=dict,
    )

class DeleteParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    simulation_id: int = Field(gt=0)

#人机交互之待审批的操作
class PendingAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal[
        "create",
        "delete",
    ]
    summary: str
    arguments: dict[str, Any]

#恢复Agent的请求 - 前端->后端(发送审批决定)
class AgentResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: str = Field(
        min_length=1,
        max_length=200,
    )
    approved: bool

#Agent的响应
class AgentResponse(BaseModel):
    """
    Agent API的统一输出
    """
    model_config = ConfigDict(extra="forbid")
    status: AgentRunStatus
    thread_id: str
    message: str
    data: dict[str, Any] | None = None
    confirmation: PendingAction | None = None

    @model_validator(mode="after")
    def validate_confirmation(self):
        if self.status == "awaiting_confirmation" and self.confirmation is None:
            raise ValueError(
                "confirmation is required"
            )

        return self
