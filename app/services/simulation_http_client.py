import httpx
from typing import Any, Optional, Dict, List
import logging
from app.schemas.simulation import SimulationResult
from pathlib import Path
import json

logger = logging.getLogger(__name__)

class simulationPlatformError(RuntimeError):
    """调用远端仿真平台失败"""

class SimulationPlatformclient:
    """远端服务HTTP客户端工具类"""
    def __init__(self, base_url: str, token: Optional[str] = None):
        self.base_url = base_url
        self.token = token
        self.client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        """async with自动开启上下文管理"""
        headers = {}
        if self.token :
            headers["Authorization"] = f"Token {self.token}"

        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            trust_env=False
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        if self.client:
            await self.client.aclose()

    async def make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        files: Optional[Dict] = None,
        data: Optional[Dict] = None,
    ) -> dict[str,Any]:
        """统一发送异步HTTP请求"""
        if not self.client:
            raise RuntimeError("客户端需要初始化")

        url = f"{self.base_url.rstrip('/')}{endpoint}"

        try:
            if method.upper() == "GET":
                response = await self.client.get(
                    url,
                    params=params,
                )

                return response.json()

            elif method.upper() == 'POST':
               if files:
                   response = await self.client.post(
                       url,
                       params=params,
                       data = data,
                       files = files,
                   )
               else:
                   response = await self.client.post(
                       url,
                       data = data,
                       params=params
                   )

            elif method.upper() == "DELETE":
                response = await self.client.delete(
                    url,
                    params=params,
                    follow_redirects=True
                )

            else:
                raise ValueError(f"不支持的HTTP方法:{method}")
            #检查HTTP响应码
            response.raise_for_status()
            if not response.text:
                return {}
            return response.json()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            error_body = e.response.text[:500]
            logger.error(f"HTTP{status}错误: {error_body}")
            raise simulationPlatformError(
                f"请求失败[{status}]: {error_body}"
            ) from e
        except json.JSONDecodeError as e:
            # 响应不是合法的 JSON
            logger.error(f"响应非 JSON: {response.text[:500]}")
            raise simulationPlatformError(
                f"服务器返回了非 JSON 数据: {response.text[:200]}"
            ) from e
        except httpx.HTTPError as e:
            logger.error(f"HTTP请求失败:{e}")
            raise simulationPlatformError(
                f"网络异常:{e}"
            )
        except Exception as e:
            logger.error(f"请求处理失败:{e}")
            raise simulationPlatformError(
                f"请求处理失败:{e}"
            )

    async def get_simulation_info(
        self,
        simulation_id: int,
        sim_type: str = "offline",
        interval: Optional[int] = None,
    ):
        """获取仿真信息(离线仿真可以指定分包时长)"""
        params = {"type": sim_type}
        if interval:
            params["interval"] = str(interval)

        response = await self.make_request(
            "GET",
            f"/simulation/simulation/{simulation_id}/",
            params=params,
        )

        if response.get("message") == "Success":
            return response.get("data",{})
        else:
            logger.error(f"获取仿真信息失败:{response}")
            return {}

    async def get_order_logs(
        self,
        simulation_id: int,
        time: Optional[int] = None,
    ) -> dict[str , Any]:
        """获取指定仿真的订单信息"""
        params = {}
        if time is not None:
            params["time"] = time

        response = await self.make_request(
            "GET",
            f"/logs/order/{simulation_id}/",
            params=params,
        )

        if response.get("message") == "Success":
            return response.get("data", {})
        logger.error(f"获取订单信息失败:{response}")
        return {}

    async def get_vehicle_order_logs(
        self,
        simulation_id: int,
        time: Optional[int] = None,
    ) -> list[dict[str , Any]]:
        """获取所有车辆的订单情况"""
        params = {}
        if time is not None:
            params["time"] = time

        response = await self.make_request(
            "GET",
            f"/logs/vehicle/order/{simulation_id}/",
            params=params,
        )

        if response.get("message") in {"Success", "查询成功"}:
            data = response.get("data", [])
            return data if isinstance(data, list) else []

        logger.error(f"获取车辆订单完成情况失败: {response}")
        return []

    async def get_vehicle_order_detail(
        self,
        simulation_id: int,
        vehicle_id: int,
        time: Optional[int] = None,
    ) -> dict[str, Any]:
        """获取单个车辆的订单完成情况"""
        params = {}
        if time is not None:
            params["time"] = time

        response = await self.make_request(
            "GET",
            f"/logs/vehicle/order/{simulation_id}/{vehicle_id}",
            params=params,
        )

        if response.get("message") in {"Success", "查询成功"}:
            data = response.get("data", {})
            return data if isinstance(data, dict) else {}

        logger.error(f"获取单个车辆的订单完成情况失败: {response}")
        return {}

    async def create_area(
        self,
        name: str,
        map_file: Path,
        signal_file: Path,
        description: str = "",
        border_file: Path | None = None,
    ):
        """上传地图和信号文件,创建区域"""
        if not map_file.is_file():
            raise FileNotFoundError(
                f"地图文件不存在:{map_file}"
            )

        if not signal_file.is_file():
            raise FileNotFoundError(
                f"信号文件不存在: {signal_file}"
            )
        form_data = {
            "name": name,
            "description": description
        }

        with (
            map_file.open("rb") as map_object,
            signal_file.open("rb") as signal_object
        ):
            files = {
            "map_file": map_object,
            "signal_file": signal_object
        }
            if border_file is not None:
                if not border_file.is_file():
                    raise FileNotFoundError(
                        f"边界文件不存在: {border_file}"
                    )
                with border_file.open("rb") as border_file:
                    files["border_file"] = border_file
                response = await self.make_request(
                    "POST",
                    "/datamanager/area/",
                    data = form_data,
                    files = files
                )
            else:
                response = await self.make_request(
                    "POST",
                    "/datamanager/area/",
                    data=form_data,
                    files=files
                )

            area_id = response.get("id")

            if area_id is None:
                raise simulationPlatformError(
                    f"创建区域响应缺少id:{response}"
                )

            return int(area_id)

    async def upload_stop_data(
        self,
        area_id: int | str,
        name: str,
        file_path: Path,
        description: str = "",
    ):
        """上传站点数据，返回stop_data ID"""
        if not file_path.is_file():
            raise FileNotFoundError(
                f"站点数据文件不存在: {file_path}"
            )
        form_data = {
            "area": str(area_id),
            "name": name,
            "description": description,
        }

        with file_path.open("rb") as file_object:
            response = await self.make_request(
                "POST",
                "/datamanager/stop/",
                data = form_data,
                files = {"file":file_object}
            )
        stop_data_id = response.get("id")
        if stop_data_id is None:
            raise simulationPlatformError(
                f"上传站点数据成功响应中缺少id:{response}"
            )
        return int(stop_data_id)

    async def upload_order_data(
        self,
        name: str,
        area_id: int | str,
        stop_data_id: int,
        file_path: Path,
        description: str = "",
    ):
        """上传订单数据并返回 order_data ID"""
        if not file_path.is_file():
            raise FileNotFoundError(
                f"订单数据文件不存在:{file_path}"
            )

        form_data = {
            "area": str(area_id),
            "name": name,
            "linked_stops": str(stop_data_id),
            "description": description,
        }

        with file_path.open("rb") as file_object:
            response = await self.make_request(
                "POST",
                "/datamanager/order/",
                data = form_data,
                files = {"file":file_object}
            )
        order_data_id = response.get("id")

        if order_data_id is None:
            raise simulationPlatformError(
                f"上传订单数据响应中缺少id: {response}"
            )
        return int(order_data_id)

    async def upload_bus_data(
        self,
        area_id: int | str,
        name: str,
        file_path: Path,
        description: str = "",
    ):
        """上传公交数据并返回bus_data ID"""
        if not file_path.is_file():
            raise FileNotFoundError(
                f"公交数据文件不存在:{file_path}"
            )
        form_data = {
            "area": str(area_id),
            "name": name,
            "description": description,
        }

        with file_path.open("rb") as file_object:
            response = await self.make_request(
                "POST",
                "/datamanager/bus/",
                data = form_data,
                files = {"file":file_object}
            )
        bus_data_id = response.get("id")

        if bus_data_id is None:
            raise simulationPlatformError(
                f"上传公交数据响应缺少id:{response}"
            )
        return int(bus_data_id)

    async def create_offline_simulation(
        self,
        name: str,
        running_time_step: int,
        area_id: int,
        stop_data_id: int,
        order_data_id: int,
        bus_data_id: int,
        description: str = "",
        use_random_match: bool = True,
        use_cost: bool = True,
    ):
        """创建并运行离线仿真,返回simulation_id"""
        form_data = {
            "name": name,
            "type": "offline",
            "running_time_step": int(
                running_time_step
            ),
            "description": description,
            "area": str(area_id),
            "stop_data": int(stop_data_id),
            "order_data": int(order_data_id),
            "bus_data": int(bus_data_id),
            "use_random_match": str(use_random_match).lower(),
            "use_cost": str(use_cost).lower(),
        }

        print(
            "创建仿真实际发送参数:"
        )

        print(
            json.dumps(
                form_data,
                ensure_ascii=False,
                indent=2,
            )
        )

        response = await self.make_request(
            "POST",
            "/simulation/simulation/",
            data = form_data,
        )

        data = response.get("data")
        if not isinstance(data,dict):
            raise simulationPlatformError(
                "创建仿真响应缺少data对象",
                f"{response}"
            )
        simulation_id = data.get("simulation_id")
        if simulation_id is None:
            raise simulationPlatformError(
                f"创建仿真响应缺少data.simulation_id对象:{response}"
            )
        return int(simulation_id)

    async def delete_simulation(
        self,
        simulation_id: str
    ) -> None:
        """删除仿真"""
        try:
            sim_id = int(simulation_id)
            if sim_id <= 0:
                raise ValueError(
                    "simulation_id必须大于0"
            )
        except ValueError as e:
            if "int()" in str(e):
                raise ValueError("simulation_id必须是有效的数字")
            raise

        #远端仿真平台发送删除请求
        response = await self.make_request(
            "DELETE",
            f"/simulation/simulation/{simulation_id}/"
        )
        return response

