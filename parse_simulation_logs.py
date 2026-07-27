import json
import os
from typing import Any

import requests
from dotenv import load_dotenv


load_dotenv()

BASE_URL = "https://simvis.tsingtransit.com/api"
TOKEN = os.getenv("SIMULATION_PLATFORM_TOKEN")
SIMULATION_ID = 270

HEADERS = {
    "Authorization": f"Token {TOKEN}",
    "Accept": "application/json",
}


def fetch_log_pages(
    simulation_id: int,
    pages: list[int],
) -> dict[str, Any]:
    page_text = ",".join(str(page) for page in pages)

    response = requests.get(
        f"{BASE_URL}/logs/status/{simulation_id}/",
        headers=HEADERS,
        params={"pages": page_text},
        timeout=120,
    )

    print("HTTP状态码:", response.status_code)
    response.raise_for_status()

    result = response.json()

    if result.get("message") != "Success":
        raise RuntimeError(f"日志接口返回失败: {result}")

    return result


def parse_log_entry(entry: dict[str, Any]) -> dict[str, Any]:
    raw_args = entry.get("args", "{}")

    if isinstance(raw_args, str):
        try:
            parsed_args = json.loads(raw_args)
        except json.JSONDecodeError:
            parsed_args = {
                "_raw_args": raw_args,
                "_parse_error": True,
            }
    elif isinstance(raw_args, dict):
        parsed_args = raw_args
    else:
        parsed_args = {}

    return {
        "id": entry.get("id"),
        "simulation_id": entry.get("simulation_run_id"),
        "simulation_time": entry.get("simulation_time"),
        "level": entry.get("level"),
        "event_type": entry.get("event_type"),
        "event_name": entry.get("event_name"),
        "vehicle_id": entry.get("vehicle_id"),
        "args": parsed_args,
    }


def parse_log_response(
    response_data: dict[str, Any],
) -> list[dict[str, Any]]:
    parsed_logs: list[dict[str, Any]] = []

    for page in response_data.get("data", []):
        for entry in page.get("results", []):
            if isinstance(entry, dict):
                parsed_logs.append(
                    parse_log_entry(entry)
                )

    return parsed_logs


def summarize_logs(
    logs: list[dict[str, Any]],
) -> dict[str, Any]:
    event_counts: dict[str, int] = {}

    for log in logs:
        event_type = log.get("event_type") or "Unknown"
        event_counts[event_type] = (
            event_counts.get(event_type, 0) + 1
        )

    order_created = [
        log
        for log in logs
        if log.get("event_name")
        == "OrderCreatedEvent"
    ]

    passenger_events = [
        log
        for log in logs
        if log.get("event_type") == "Passenger"
    ]

    vehicle_events = [
        log
        for log in logs
        if log.get("event_type") == "Vehicle"
    ]

    return {
        "total_logs": len(logs),
        "event_counts": event_counts,
        "order_created_count": len(order_created),
        "passenger_event_count": len(passenger_events),
        "vehicle_event_count": len(vehicle_events),
    }


def main() -> None:
    if not TOKEN:
        raise RuntimeError(
            "未读取 SIMULATION_PLATFORM_TOKEN"
        )

    first_response = fetch_log_pages(
        SIMULATION_ID,
        [1],
    )

    first_page = first_response["data"][0]
    total_pages = first_page["total_pages"]

    print("总页数:", total_pages)
    print("第 1 页日志数:", first_page["count"])

    # 先测试前两页，确认格式
    pages = [1, 2]
    response_data = fetch_log_pages(
        SIMULATION_ID,
        pages,
    )

    logs = parse_log_response(response_data)
    summary = summarize_logs(logs)

    print(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        )
    )

    for log in logs[:5]:
        print(
            json.dumps(
                log,
                ensure_ascii=False,
                indent=2,
            )
        )

    with open(
        "simulation_270_parsed_logs.json",
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            logs,
            file,
            ensure_ascii=False,
            indent=2,
        )


if __name__ == "__main__":
    main()