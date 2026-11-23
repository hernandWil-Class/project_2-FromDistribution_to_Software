"""Insert the fixed synthetic fixture through the authenticated API."""

from __future__ import annotations

import json
import os
import sys

import httpx

from survivallab.data import fixed_fixture


def main() -> int:
    api_base = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    api_key = os.environ.get("API_KEY")
    if not api_key:
        print("API_KEY is required", file=sys.stderr)
        return 2
    created = 0
    repeated = 0
    with httpx.Client(timeout=10) as client:
        for observation in fixed_fixture():
            response = client.post(
                f"{api_base}/observations",
                headers={"X-API-Key": api_key},
                json=observation.model_dump(mode="json"),
            )
            response.raise_for_status()
            status = response.json()["status"]
            created += status == "created"
            repeated += status == "idempotent"
    print(json.dumps({"created": created, "idempotent": repeated}, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
