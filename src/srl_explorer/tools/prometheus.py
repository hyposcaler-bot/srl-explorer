from __future__ import annotations

import httpx

from srl_explorer.config import Config


async def prometheus_query(
    config: Config,
    query: str,
    time: str | None = None,
) -> dict:
    params: dict[str, str] = {"query": query}
    if time:
        params["time"] = time

    async with httpx.AsyncClient(base_url=config.prometheus_url) as client:
        resp = await client.get("/api/v1/query", params=params, timeout=15)
        resp.raise_for_status()
        body = resp.json()

    if body.get("status") != "success":
        raise RuntimeError(f"Prometheus query failed: {body.get('error', body)}")

    return body["data"]


async def prometheus_query_range(
    config: Config,
    query: str,
    start: str,
    end: str,
    step: str = "15s",
) -> dict:
    params = {
        "query": query,
        "start": start,
        "end": end,
        "step": step,
    }

    async with httpx.AsyncClient(base_url=config.prometheus_url) as client:
        resp = await client.get("/api/v1/query_range", params=params, timeout=15)
        resp.raise_for_status()
        body = resp.json()

    if body.get("status") != "success":
        raise RuntimeError(f"Prometheus range query failed: {body.get('error', body)}")

    return body["data"]
