from app.services.simulation_http_client import SimulationPlatformclient


class SimulationAnalysisService:
    """
    仿真查询分析服务
    """
    def __init__(
        self,
        client: SimulationPlatformclient
    ):
        self.client = client

    async def get_simulation_duration(
        self,
        simulation_id: int,
    ) -> dict:
        simulation_info = await self.client.get_simulation_info(
            simulation_id=simulation_id,
        )
        return {
            "simulation_id": simulation_id,
            "simulation_duration": simulation_info.get("simulation_duration")
        }

    async def get_created_order_count(
        self,
        simulation_id: int,
    ) -> dict:
         order_response = await self.client.get_order_logs(
            simulation_id=simulation_id,
    )
         order_data = (
             order_response.get("data",{}).get("order_data",{})
         )

         created_order_ids = {
             int(order.get("order_id"))
             for order in order_data
             if order.get("order_id") is not None
             and order.get("created_time") is not None
         }

         return {
             "simulation_id": simulation_id,
             "created_order_count": len(created_order_ids)
         }

    async def get_completed_order_count(
        self,
        simulation_id: int,
    ) -> dict:
        order_response = await self.client.get_order_logs(
            simulation_id=simulation_id,
        )
        order_data = order_response.get("data",{}).get("order_data",{})
        completed_orders = {
            int(order.get("order_id"))
            for order in order_data
            if order.get("order_id") is not None
            and order.get("dropoff_time") is not None
        }

        return {
            "simulation_id": simulation_id,
            "completed_order_count": len(completed_orders),
        }