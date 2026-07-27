from app.core.config import settings
from app.services.simulation_http_client import SimulationPlatformclient
import json
from pathlib import Path
from typing import Any

from tests.test2 import total_pages


class SimulationLogService:
    """获取完整仿真日志并保存为.log文件"""
    def __init__(
        self,
        client: SimulationPlatformclient,
        artifact_root,
        PAGE_BATCH_SIZE=10,
    ):
        self.client = client
        self.artifact_foot = artifact_root
        self.PAGE_BATCH_SIZE = PAGE_BATCH_SIZE

    @staticmethod
    def _get_total_pages(response: dict[str,Any]) -> int:
        """
        从第一页响应中读取总页数
        """
        data = response.get("data")
        if not isinstance(data, list) or not data:
            return 0
        first_page = data[0]
        if not isinstance(first_page,dict):
            return 0
        total_pages = first_page.get("total_pages", 0)
        try:
            return int(total_pages)
        except (TypeError,ValueError):
            return 0

    @staticmethod
    def _flatten_results(
        response: dict[str,Any],
    ) -> list[dict[str, Any]]:
        """
        将接口返回的多页数据展开成日志记录列表
        """
        data = response.get("data")
        if not isinstance(data,list):
            return []

        all_results: list[dict[str, Any]] = []

        for page_data in data:
            if not isinstance(page_data, dict):
                continue

            results = page_data.get("results", [])

            if not isinstance(results, list):
                continue

            for item in results:
                if isinstance(item,dict):
                    all_results.append(item)

        return all_results

    @staticmethod
    def _flatten_postion_results(
        response: dict[str, Any],
    ) -> list[dict[str,Any]]:
        data = response.get("data")
        if not isinstance(data,list):
            return []

        records = []
        for page_data in data:
            if not isinstance(page_data,dict):
                continue
            groups = page_data.get("results",[])
            if not isinstance(groups,list):
                continue
            for group in groups:
                if not isinstance(group,dict):
                    continue
                vehicle_id = group.get("vehicle_id")
                positions = group.get("position",[])
                if not isinstance(positions,list):
                    continue
                for position in positions:
                    if not isinstance(position,dict):
                        continue
                    record = position.copy()
                    record["vehicle_id"] = vehicle_id
                    records.append(record)
        return records

    @staticmethod
    def _write_json_lines(
        file_path: Path,
        records: list[dict[str, Any]]
    ) -> Path:
        """
        将每条日志写成一行 JSON
        """
        file_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        with file_path.open("w",encoding="utf-8") as file_object:
            for record in records:
                file_object.write(
                    json.dumps(
                        record,
                        ensure_ascii=False,
                    )
                )
                file_object.write("\n")
        return file_path

    async def download_status_log(
        self,
        simulation_id: int,
        user_id: str = "manual-test-user",
        task_id: str | None = None
    ) -> dict[str,Any]:
        """
        获取完整日志并保存
        """
        if task_id is None:
            task_id = f"simulation-{simulation_id}"
        #请求第一页，获取总页数
        first_response = await self.client.get_status_logs(
            simulation_id=simulation_id,
            pages=[1],
        )
        total_pages = self._get_total_pages(first_response)

        if total_pages <= 0:
            records = self._flatten_results(
                first_response
            )
        else:
            records = await self._collect_all_pages(
                simulation_id=simulation_id,
                total_pages=total_pages,
                getter=(
                    self.client.get_status_logs
                ),
                flatten=self._flatten_results,
            )
        file_path = (
            self.artifact_foot
            / user_id
            / task_id
            / "logs"
            / f"{simulation_id}_status.log"
        )
        self._write_json_lines(file_path=file_path,records=records)
        return {
            "simulation_id": simulation_id,
            "log_type": "status",
            "total_pages": total_pages,
            "record_count": len(records),
            "file_path": str(file_path)
        }

    async def download_position_log(
        self,
        simulation_id: int,
        user_id: str = "manual-test-user",
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """
        获取完整车辆位置日志并保存
        """
        if task_id is None:
            task_id = f"simulation-{simulation_id}"
        # 先请求第一页，获取 total_pages
        first_response = await self.client.get_position_logs(
            simulation_id=simulation_id,
            pages=[1],
        )
        total_pages = self._get_total_pages(first_response)
        if total_pages <= 0:
            records = (
                self._flatten_postion_results(
                    first_response
                )
            )
        else:
            records = await self._collect_all_pages(
                simulation_id=simulation_id,
                total_pages=total_pages,
                getter=(
                    self.client.get_position_logs
                ),
                flatten=(
                    self._flatten_postion_results
                ),
            )

        file_path = (
            self.artifact_foot
            / user_id
            / task_id
            / "logs"
            / f"{simulation_id}_position.log"
        )

        self._write_json_lines(
            file_path=file_path,
            records=records
        )

        # 在 write_json_lines 之后，return 之前添加
        if records:
            from collections import Counter
            vehicle_counts = Counter(record.get("vehicle_id") for record in records)
            print("\n📊 Position 日志统计:")
            print(f"  总记录数: {len(records)}")
            print(f"  车辆ID分布: {dict(vehicle_counts)}")
            # 检查是否所有记录的坐标都相同
            first_lng = records[0].get("lng")
            first_lat = records[0].get("lat")
            all_same = all(
                r.get("lng") == first_lng and r.get("lat") == first_lat
                for r in records
            )
            if all_same:
                print("  ⚠️ 警告: 所有轨迹点的经纬度完全相同，车辆可能全程静止或数据异常。")
        else:
            print("❌ 未获取到任何 position 记录。")

        return {
            "simulation_id": simulation_id,
            "log_type": "position",
            "total_pages": total_pages,
            "record_count": len(records),
            "file_path": str(file_path)
        }

    async def download_all_logs(
        self,
        simulation_id: int,
        user_id: str = "manual-test-user",
        task_id: str | None = None,
    ) -> dict[str,Any]:
        """
        同时下载状态日志和车辆位置日志
        """
        status_result = await self.download_status_log(
            simulation_id=simulation_id,
            user_id=user_id,
            task_id=task_id,
        )
        position_result = await self.download_position_log(
            simulation_id=simulation_id,
            user_id=user_id,
            task_id=task_id,
        )
        return {
            "simulation_id": simulation_id,
            "status_log": status_result,
            "position_log": position_result,
        }
    #ai
    async def _collect_all_pages(
            self,
            simulation_id: int,
            total_pages: int,
            getter,
            flatten,
    ) -> list[dict[str, Any]]:
        """
        分批获取全部页面。

        如果平台批量请求时漏掉部分页面，
        自动逐页补取。
        """
        all_records: list[
            dict[str, Any]
        ] = []

        collected_pages: set[int] = set()

        for start in range(
                1,
                total_pages + 1,
                self.PAGE_BATCH_SIZE,
        ):
            requested_pages = list(range(
                start,
                min(
                    start
                    + self.PAGE_BATCH_SIZE,
                    total_pages + 1,
                ),
            ))

            response = await getter(
                simulation_id=simulation_id,
                pages=requested_pages,
            )

            data = response.get("data", [])

            if not isinstance(data, list):
                data = []

            returned_pages: set[int] = set()

            for page_data in data:
                if not isinstance(
                        page_data,
                        dict,
                ):
                    continue

                try:
                    page_number = int(
                        page_data.get("page")
                    )
                except (
                        TypeError,
                        ValueError,
                ):
                    continue

                returned_pages.add(
                    page_number
                )

                if page_number in collected_pages:
                    continue

                page_response = {
                    "data": [page_data]
                }

                all_records.extend(
                    flatten(page_response)
                )

                collected_pages.add(
                    page_number
                )

            missing_pages = (
                    set(requested_pages)
                    - returned_pages
            )

            # 如果批量接口漏页，逐页补取
            for page_number in sorted(
                    missing_pages
            ):
                page_response = await getter(
                    simulation_id=simulation_id,
                    pages=[page_number],
                )

                page_data_list = (
                    page_response.get(
                        "data",
                        [],
                    )
                )

                if not isinstance(
                        page_data_list,
                        list,
                ):
                    continue

                all_records.extend(
                    flatten(page_response)
                )

                collected_pages.add(
                    page_number
                )

            print(
                f"日志下载进度: "
                f"{len(collected_pages)}/"
                f"{total_pages}页, "
                f"累计记录="
                f"{len(all_records)}"
            )

        missing_after_download = (
                set(
                    range(
                        1,
                        total_pages + 1,
                    )
                )
                - collected_pages
        )

        if missing_after_download:
            raise RuntimeError(
                "日志下载完成后仍有缺失页面: "
                f"{sorted(missing_after_download)}"
            )

        return all_records