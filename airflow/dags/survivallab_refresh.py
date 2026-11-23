"""Minute schedule that delegates refresh work to the secured SurvivalLab API."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from airflow.sdk import dag, task


@dag(
    dag_id="survivallab_refresh",
    schedule="* * * * *",
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(seconds=30)},
    tags=["survivallab", "synthetic-data"],
)
def survivallab_refresh():
    @task
    def request_refresh() -> dict[str, str]:
        api_url = os.environ.get(
            "SURVIVALLAB_REFRESH_URL",
            "http://api:8000/pipeline/refresh",
        )
        api_key = os.environ.get("SURVIVALLAB_API_KEY")
        if not api_key:
            raise RuntimeError("SURVIVALLAB_API_KEY is not configured")
        request = Request(
            api_url,
            data=b"",
            method="POST",
            headers={"X-API-Key": api_key},
        )
        try:
            with urlopen(request, timeout=30) as response:
                body = json.loads(response.read())
        except HTTPError as error:
            raise RuntimeError(f"refresh API returned HTTP {error.code}") from error
        except URLError as error:
            raise RuntimeError("refresh API is unavailable") from error
        status = body.get("status")
        run_id = body.get("run_id")
        if status not in {"succeeded", "skipped"} or not isinstance(run_id, str):
            raise RuntimeError("refresh API returned an unsuccessful result")
        return {"run_id": run_id, "status": status}

    request_refresh()


survivallab_refresh()
