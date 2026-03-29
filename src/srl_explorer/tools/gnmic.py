from __future__ import annotations

import asyncio
import json

from srl_explorer.config import CREDENTIALS, TOPOLOGY, Config


async def gnmic_get(
    config: Config,
    target: str,
    path: str,
    data_type: str = "ALL",
) -> dict | list:
    if target not in TOPOLOGY:
        raise ValueError(
            f"Unknown target '{target}'. Valid targets: {', '.join(TOPOLOGY)}"
        )

    address = TOPOLOGY[target]["address"]

    cmd = [
        "gnmic",
        "-a", address,
        "-u", CREDENTIALS["username"],
        "-p", CREDENTIALS["password"],
        "--skip-verify",
        "-e", "json_ietf",
        "get",
        "--path", path,
        "--type", data_type,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise TimeoutError(f"gnmic get timed out after 15s for {target}:{path}")

    if proc.returncode != 0:
        err = stderr.decode().strip()
        raise RuntimeError(f"gnmic get failed (rc={proc.returncode}): {err}")

    return json.loads(stdout.decode())
