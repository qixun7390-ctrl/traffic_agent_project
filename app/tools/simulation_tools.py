from langchain_core.tools import tool
from app.core.config import settings
from app.services.simulation_analysis_service import SimulationAnalysisService
from app.services.simulation_http_client import SimulationPlatformclient
from app.schemas.simulation import AnalyzeSimulationInput

def create_client() -> SimulationPlatformclient:
    return SimulationPlatformclient(
        base_url=settings.SIMULATION_PLATFORM_BASE_URL,
        token=settings.SIMULATION_PLATFORM_TOKEN,
    )

@tool(args_schema=AnalyzeSimulationInput)
async def get_simulation_duration(simulation_id: int) -> dict:
    """查询指定仿真运行了多久"""
    async with create_client() as client:
        service = SimulationAnalysisService(client)
        return await service.get_simulation_duration(
            simulation_id=simulation_id,
        )

@tool(args_schema=AnalyzeSimulationInput)
async def get_simulation_order_summary(simulation_id: int) -> dict:
    """查询指定的仿真的订单创建数，匹配数和匹配率"""
    async with create_client() as client:
        service = SimulationAnalysisService(client)
        return await service.get_order_summary(
            simulation_id=simulation_id,
        )

@tool(args_schema=AnalyzeSimulationInput)
async def get_simulation_vehicle_summary(simulation_id: int) -> dict:
    """查询指定仿真的车辆参与情况，空闲车辆数和车辆完成订单情况"""
    async with create_client() as client:
        service = SimulationAnalysisService(client)
        return await service.get_vehicle_summary(
            simulation_id=simulation_id,
        )

SIMULATION_TOOLS = [
    get_simulation_duration,
    get_simulation_order_summary,
    get_simulation_vehicle_summary,
]