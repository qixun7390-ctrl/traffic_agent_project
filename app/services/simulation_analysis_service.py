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

    async def get_order_summary(
        self,
        simulation_id: int,
    ) -> dict:
        order_log = await self.client.get_order_logs(
            simulation_id=simulation_id,
        )
        order_data = order_log.get("order_data",[])

        created_order_count = len(order_data)
        matched_order_count = sum(
            1 for item in order_data
            if item.get("matched_time") is not None
        )

        picked_order_count = sum(
            1 for item in order_data
            if item.get("pickup_time") is not None
        )

        completed_order_count = sum(
            1 for item in order_data
            if item.get("dropoff_time") is not None
        )

        match_rate = (
            matched_order_count / created_order_count
            if created_order_count
            else 0
        )

        completion_rate = (
            completed_order_count / created_order_count
            if matched_order_count
            else 0
        )

        return {
            "simulation_id": simulation_id,
            "created_order_count": created_order_count,
            "matched_order_count": matched_order_count,
            "picked_order_count": picked_order_count,
            "completed_order_count": completed_order_count,
            "match_rate": match_rate,
            "completion_rate": completion_rate,
            "total_revenue": order_log.get("total_revenue", 0),
        }

    async def get_vehicle_summary(
        self,
        simulation_id: int,
        time: int | None = None,
    ) -> dict:
        simulation_info = await self.client.get_simulation_info(
            simulation_id=simulation_id,
        )
        vehicle_data = await self.client.get_vehicle_order_logs(
            simulation_id=simulation_id,
            time=time,
        )
        total_vehicles = simulation_info.get("total_vehicles") or len(vehicle_data)
        active_vehicle_count = len(vehicle_data)

        vehicle_with_completed_order_count = sum(
            1 for item in vehicle_data
            if item.get("orders_finished")
        )

        total_finished_orders = sum(
            len(item.get("orders_finished") or [])
            for item in vehicle_data
        )

        average_finished_orders_per_active_vehicle = (
            total_finished_orders / active_vehicle_count
            if active_vehicle_count else 0
        )

        return {
            "simulation_id": simulation_id,
            "time": time,
            "total_vehicles": total_vehicles,
            "active_vehicle_count": active_vehicle_count,
            "idle_vehicle_count": max(total_vehicles - active_vehicle_count, 0),
            "vehicles_with_completed_order_count": vehicle_with_completed_order_count,
            "total_finished_orders": total_finished_orders,
            "average_finished_orders_per_active_vehicle": average_finished_orders_per_active_vehicle,
        }