from langchain_core.tools import tool
from app.core.config import settings
from app.services.simulation_analysis_service import (
    SimulationAnalysisService,
    SimulationDataUnavailableError,
)
from app.services.simulation_http_client import SimulationPlatformclient
from app.schemas.simulation import AnalyzeSimulationInput

def create_client() -> SimulationPlatformclient:
    return SimulationPlatformclient(
        base_url=settings.SIMULATION_PLATFORM_BASE_URL,
        token=settings.SIMULATION_PLATFORM_TOKEN,
    )

@tool(args_schema=AnalyzeSimulationInput)
async def get_simulation_duration(simulation_id: int) -> dict:
    """
    查询指定仿真的运行时长。

    当用户询问某个仿真跑了多久、运行了多长时间、仿真时长、实际运行秒数时使用本工具。

    返回字段含义：
    - simulation_id：被查询的仿真 ID。
    - simulation_duration：仿真平台记录的运行时长，单位通常为秒。

    不适合回答订单数量、订单完成率、车辆利用率、活跃车辆数等问题。
    """
    try:
        async with create_client() as client:
            service = SimulationAnalysisService(client)
            return await service.get_simulation_duration(
                simulation_id=simulation_id,
            )
    except SimulationDataUnavailableError as exc:
        return {"simulation_id": simulation_id, "error": str(exc)}

@tool(args_schema=AnalyzeSimulationInput)
async def get_simulation_order_summary(simulation_id: int) -> dict:
    """
    查询指定仿真的订单统计指标。

    当用户询问订单创建数、订单匹配数、乘客上车数、订单完成数、匹配率、完成率、订单整体情况时使用本工具。

    返回字段含义：
    - simulation_id：被查询的仿真 ID。
    - created_order_count：创建订单数。
    - matched_order_count：成功匹配车辆的订单数。
    - picked_order_count：乘客已经上车的订单数。
    - completed_order_count：乘客已经下车或订单完成的订单数。
    - match_rate：订单匹配率，计算方式为 matched_order_count / created_order_count。
    - completion_rate：订单完成率，计算方式为 completed_order_count / created_order_count。
    - total_revenue：订单总收益。

    不适合回答车辆利用率、活跃车辆数、空闲车辆数、单车完成订单数等车辆维度问题。
    """
    try:
        async with create_client() as client:
            service = SimulationAnalysisService(client)
            return await service.get_order_summary(
                simulation_id=simulation_id,
            )
    except SimulationDataUnavailableError as exc:
        return {"simulation_id": simulation_id, "error": str(exc)}

@tool(args_schema=AnalyzeSimulationInput)
async def get_simulation_vehicle_summary(simulation_id: int) -> dict:
    """
    查询指定仿真的车辆统计指标。

    当用户询问车辆利用率、活跃车辆数、接单车辆数、空闲车辆数、完成过订单的车辆数、平均每辆活跃车完成订单数时使用本工具。

    返回字段含义：
    - simulation_id：被查询的仿真 ID。
    - total_vehicles：仿真配置中的总车辆数。
    - active_vehicle_count：接过至少一个订单的车辆数，也就是有历史匹配订单的车辆数。
    - idle_vehicle_count：没有接过订单的车辆数。
    - vehicles_with_completed_order_count：完成过至少一个订单的车辆数。
    - total_finished_orders：车辆侧统计到的完成订单总数。
    - average_finished_orders_per_active_vehicle：平均每辆活跃车完成订单数，计算方式为 total_finished_orders / active_vehicle_count。

    注意：
    - 车辆利用率应理解为 active_vehicle_count / total_vehicles。
    - active_vehicle_count 表示接过订单，不等于完成过订单。
    - 如果用户关心完成效果，应同时说明 vehicles_with_completed_order_count。
    - 不适合回答订单创建数、订单匹配率、订单完成率等订单整体问题。
    """
    try:
        async with create_client() as client:
            service = SimulationAnalysisService(client)
            return await service.get_vehicle_summary(
                simulation_id=simulation_id,
            )
    except SimulationDataUnavailableError as exc:
        return {"simulation_id": simulation_id, "error": str(exc)}

SIMULATION_TOOLS = [
    get_simulation_duration,
    get_simulation_order_summary,
    get_simulation_vehicle_summary,
]
