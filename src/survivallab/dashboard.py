"""Small HTTP client used by Streamlit; no database connection exists here."""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from numbers import Real
from typing import Any, Literal, cast
from urllib.parse import urljoin

import requests


class ApiUnavailableError(RuntimeError):
    """Raised when the API cannot be reached."""


class ApiError(RuntimeError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code


def build_observation_payload(
    *,
    patient_id: str,
    version: int,
    duration_months: float,
    event_observed: int,
    correction_reason: str | None = None,
    correction_of: str | None = None,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    patient = patient_id.strip()
    if not patient or len(patient) > 128:
        raise ValueError("patient ID must contain 1 to 128 characters")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("version must be a positive integer")
    if isinstance(duration_months, bool) or not isinstance(duration_months, Real):
        raise ValueError("follow-up must be finite and positive")
    if not math.isfinite(float(duration_months)) or duration_months <= 0:
        raise ValueError("follow-up must be finite and positive")
    if (
        isinstance(event_observed, bool)
        or not isinstance(event_observed, int)
        or event_observed not in (0, 1)
    ):
        raise ValueError("event_observed must be 0 or 1")
    if (correction_reason is None) != (correction_of is None):
        raise ValueError(
            "correction reason and prior observation UUID are both required"
        )
    if correction_of is not None:
        try:
            uuid.UUID(correction_of)
        except ValueError as error:
            raise ValueError("correction reference must be a UUID") from error
        if not correction_reason or not correction_reason.strip():
            raise ValueError("correction reason is required")
    timestamp = observed_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("observation time must be timezone-aware UTC")
    if timestamp.utcoffset().total_seconds() != 0:
        raise ValueError("observation time must be UTC")
    payload: dict[str, Any] = {
        "patient_id": patient,
        "version": version,
        "duration_months": float(duration_months),
        "event_observed": event_observed,
        "observed_at": timestamp.astimezone(UTC).isoformat(),
    }
    if correction_of is not None and correction_reason is not None:
        payload["correction_of"] = correction_of
        payload["correction_reason"] = correction_reason.strip()
    return payload


def publication_state(
    is_stale: bool, pipeline_status: str
) -> Literal["failed", "stale", "current"]:
    if pipeline_status == "failed":
        return "failed"
    return "stale" if is_stale else "current"


class ApiClient:
    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        *,
        session: requests.Session | None = None,
        timeout: tuple[float, float] = (3.0, 10.0),
    ):
        self.base_url = base_url.rstrip("/") + "/"
        self.api_key = api_key
        self.session = session or requests.Session()
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        write: bool = False,
    ) -> Any:
        headers = {"X-API-Key": self.api_key} if write and self.api_key else {}
        try:
            response = self.session.request(
                method,
                urljoin(self.base_url, path.lstrip("/")),
                params=params,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise ApiUnavailableError("SurvivalLab API is unavailable") from error
        if not response.ok:
            try:
                body = response.json()
                detail = body.get("detail", "API request failed")
                if isinstance(detail, dict):
                    detail = detail.get("message", "API request failed")
            except ValueError:
                detail = "API request failed"
            raise ApiError(response.status_code, str(detail))
        return response.json()

    def save_observation(self, payload: dict[str, Any]) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._request("POST", "/observations", payload=payload, write=True),
        )

    def refresh(self) -> dict[str, Any]:
        return cast(
            dict[str, Any], self._request("POST", "/pipeline/refresh", write=True)
        )

    def pipeline_status(self) -> dict[str, Any]:
        return cast(dict[str, Any], self._request("GET", "/pipeline/status"))

    def latest_model(self) -> dict[str, Any]:
        return cast(dict[str, Any], self._request("GET", "/models/latest"))

    def model_history(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self._request("GET", "/models/history"))

    def model(self, model_id: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._request("GET", f"/models/{model_id}"))

    def survival(self, months: float, model_id: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"months": months}
        if model_id is not None:
            params["model_id"] = model_id
        return cast(dict[str, Any], self._request("GET", "/survival", params=params))

    def exponential_curve(self, model_id: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._request("GET", "/curves/exponential", params={"model_id": model_id}),
        )
