from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Literal
from pathlib import Path

class SimulationResult(BaseModel):
    """仿真结果"""
    simulation_id: int
    name: str
    type: str
    area: str
    status: str
    created_time: str
    end_time: str | None = None
    simulation_duration: float = 0

class CreateSimulationFromFilesInput(
    BaseModel,
):
    """
    使用一套全新的 JSON 文件创建离线仿真。
    """

    model_config = ConfigDict(
        extra="forbid"
    )

    name: str = Field(
        min_length=1,
        max_length=200,
    )

    area_name: str = Field(
        min_length=1,
        max_length=100,
    )

    running_time_step: int = Field(
        default=3600,
        gt=0,
    )

    description: str = ""

    map_file: Path
    signal_file: Path
    stop_file: Path
    order_file: Path
    bus_file: Path

    use_random_match: bool = True
    use_cost: bool = True

class AnalyzeSimulationInput(BaseModel):
    """
    查询并分析一个指定的离线仿真
    """
    model_config = ConfigDict(
        extra="forbid"
    )
    simulation_id: int = Field(
        gt = 0,
        description = "需要查询和分析的仿真ID"
    )

class SimulationAnalysisResult(BaseModel):
    """
    指定仿真的运行和订单统计结果
    """
    model_config = ConfigDict(
        extra="forbid"
    )

    simulation_id: int
    status: str
    simulation_duration: float | None = Field(
        default=None,
        ge=0,
    )
    created_order_count: int | None = Field(
        default=None,
        ge=0,
    )
    completed_order_count: int | None = Field(
        default = None,
        ge=0,
    )
