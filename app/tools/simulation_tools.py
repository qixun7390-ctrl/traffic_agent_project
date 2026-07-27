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
async def get_created_order_count(simulation_id: int) -> dict:
    """查询指定仿真创建了多少订单"""
    async with create_client() as client:
        service = SimulationAnalysisService(client)
        return await service.get_created_order_count(simulation_id=simulation_id)

@tool(args_schema=AnalyzeSimulationInput)
async def get_completed_order_count(simulation_id: int) -> dict:
    """查询指定仿真完成了多少订单"""
    async with create_client() as client:
        service = SimulationAnalysisService(client)
        return await service.get_completed_order_count(simulation_id=simulation_id)

@tool
async def create_offline_simulation(
    name: str,
    running_time_step: int,
    area_id: int,
    stop_data_id: int,
    order_data_id: int,
    bus_data_id: int,
    description: str = "",
    use_random_match: bool = True,
    use_cost: bool = True,
) -> dict:
    """使用平台已有数据id创建离线仿真"""
    async with create_client() as client:
        simulation_id = (
            await client.create_offline_simulation(
                name=name,
                running_time_step=running_time_step,
                area_id=area_id,
                stop_data_id=stop_data_id,
                order_data_id=order_data_id,
                bus_data_id=bus_data_id,
                description=description,
                use_random_match=use_random_match,
                use_cost=use_cost
            )
        )

    return {
        "simulation_id": simulation_id,
        "status": "PENDING"
    }

@tool
async def delete_simulation(
    simulation_id: int,
    confirmed: bool = False,
) -> dict:
    """删除指定仿真，且需要用户明确确认"""
    if not confirmed:
        return {
            "simulation_id": simulation_id,
            "status": "confirmation_required",
            "message": f"需要删除仿真{simulation_id},需要用户确认"
        }

    async with create_client() as client:
        platform_response = await client.delete_simulation(
            simulation_id = simulation_id
        )

    return {
        "simulation_id": simulation_id,
        "status": "deleted",
        "platform_response": platform_response
    }

SIMULATION_TOOLS = [
    create_offline_simulation,
    delete_simulation,
    get_simulation_duration,
    get_created_order_count,
    get_completed_order_count
]