from datetime import UTC, datetime

import pytest
import requests

from survivallab.dashboard import (
    ApiClient,
    ApiError,
    ApiUnavailableError,
    build_observation_payload,
    publication_state,
)


class FakeResponse:
    def __init__(self, body, status_code=200):
        self.body = body
        self.status_code = status_code
        self.ok = status_code < 400

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response or FakeResponse({"ok": True})
        self.error = error
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.error is not None:
            raise self.error
        return self.response


def test_observation_payload_and_correction_metadata():
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    payload = build_observation_payload(
        patient_id=" synthetic-1 ",
        version=2,
        duration_months=16,
        event_observed=0,
        correction_reason="synthetic correction",
        correction_of="4de65d72-27a7-4304-b64d-5b0202042fbe",
        observed_at=stamp,
    )
    assert payload["patient_id"] == "synthetic-1"
    assert payload["duration_months"] == 16
    assert payload["event_observed"] == 0
    assert payload["correction_reason"] == "synthetic correction"
    assert payload["observed_at"] == "2026-01-01T00:00:00+00:00"
    with pytest.raises(ValueError):
        build_observation_payload(
            patient_id="",
            version=1,
            duration_months=12,
            event_observed=0,
        )
    with pytest.raises(ValueError):
        build_observation_payload(
            patient_id="synthetic-2",
            version=1,
            duration_months=float("inf"),
            event_observed=0,
        )
    with pytest.raises(ValueError):
        build_observation_payload(
            patient_id="synthetic-2",
            version=1,
            duration_months=12,
            event_observed=0,
            correction_of="4de65d72-27a7-4304-b64d-5b0202042fbe",
        )


def test_client_sends_write_key_and_bounded_timeout():
    session = FakeSession(FakeResponse({"observation_id": "id", "status": "created"}))
    client = ApiClient("http://api.local/", "secret-for-test", session=session)
    result = client.save_observation({"patient_id": "synthetic-only"})
    assert result["status"] == "created"
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url == "http://api.local/observations"
    assert kwargs["headers"] == {"X-API-Key": "secret-for-test"}
    assert kwargs["timeout"] == (3.0, 10.0)


def test_prediction_horizon_and_api_error_states():
    session = FakeSession(FakeResponse({"survival_probability": 0.5}))
    client = ApiClient("http://api.local", session=session)
    result = client.survival(24, "model-123")
    assert result["survival_probability"] == 0.5
    assert session.calls[0][2]["params"] == {"months": 24, "model_id": "model-123"}
    invalid = ApiClient(
        "http://api.local",
        session=FakeSession(FakeResponse({"detail": "invalid horizon"}, 422)),
    )
    with pytest.raises(ApiError) as error:
        invalid.survival(-1)
    assert error.value.status_code == 422


def test_api_down_and_visible_publication_states():
    unavailable = ApiClient(
        "http://api.local",
        session=FakeSession(error=requests.ConnectionError("offline")),
    )
    with pytest.raises(ApiUnavailableError):
        unavailable.pipeline_status()
    assert publication_state(False, "succeeded") == "current"
    assert publication_state(True, "succeeded") == "stale"
    assert publication_state(True, "failed") == "failed"


def test_curve_cache_is_short_and_model_aware(monkeypatch):
    from survivallab.dashboard_app import cached_curve

    calls = []

    def request(session, method, url, **kwargs):
        calls.append((url, kwargs.get("params")))
        return FakeResponse({"model_id": kwargs["params"]["model_id"], "curve": []})

    monkeypatch.setenv("API_KEY", "cache-test-key")
    monkeypatch.setattr(requests.Session, "request", request)
    cached_curve.clear()
    first = cached_curve("http://api.local", "model-a")
    again = cached_curve("http://api.local", "model-a")
    second = cached_curve("http://api.local", "model-b")
    cached_curve.clear()
    assert first == again
    assert first["model_id"] == "model-a"
    assert second["model_id"] == "model-b"
    assert len(calls) == 2
    assert calls[0][1] == {"model_id": "model-a"}
    assert calls[1][1] == {"model_id": "model-b"}


def test_streamlit_shows_api_unavailable_without_a_model(monkeypatch):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("SURVIVALLAB_API_URL", "http://127.0.0.1:1")
    app_path = Path(__file__).parents[1] / "src" / "survivallab" / "dashboard_app.py"
    result = AppTest.from_file(str(app_path)).run(timeout=20)
    assert any("API unavailable" in message.value for message in result.error)
