import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from survivallab.api import create_app
from survivallab.data import fixed_fixture
from survivallab.db.repository import Repository
from survivallab.stats import (
    fit_exponential,
    kaplan_meier,
    mean_survival_time,
    median_survival_time,
    rate_intervals,
)

API_KEY = "test-api-key"


@pytest.fixture
def api_client(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    ).execution_options(schema_translate_map={"raw": None, "meta": None, "model": None})
    repository = Repository(engine)
    repository.create_tables()
    monkeypatch.setenv("API_KEY", API_KEY)
    app = create_app(
        ingest_repository=repository,
        read_repository=repository,
        pipeline_repository=repository,
    )
    with TestClient(app) as client:
        yield client, repository
    engine.dispose()


def publish_fixture(repository: Repository) -> dict[str, float | int]:
    rows = fixed_fixture()
    for row in rows:
        repository.ingest(row)
    snapshot_id, _ = repository.create_snapshot()
    fit = fit_exponential(
        [row.duration_months for row in rows],
        [row.event_observed for row in rows],
    )
    assert fit.rate is not None
    intervals = rate_intervals(fit)
    result = {
        **fit.to_dict(),
        "mean_months": mean_survival_time(fit.rate),
        "median_months": median_survival_time(fit.rate),
        "interval_method": "asymptotic",
        "intervals": {
            key: {"lower": value[0], "upper": value[1]}
            for key, value in intervals.items()
        },
        "minimum_followup_months": min(row.duration_months for row in rows),
        "maximum_followup_months": max(row.duration_months for row in rows),
        "kaplan_meier": kaplan_meier(
            [row.duration_months for row in rows],
            [row.event_observed for row in rows],
        ),
        "assumptions": [
            "independent subjects",
            "independent right censoring",
            "one constant common hazard",
        ],
        "time_unit": "months",
    }
    repository.publish(
        model_id=str(uuid.uuid4()),
        snapshot_id=snapshot_id,
        method="exponential-rate-mle-v1",
        code_hash="a" * 64,
        config_hash="b" * 64,
        result=result,
        provenance={
            "fit_started_at": datetime.now(UTC).isoformat(),
            "snapshot_id": snapshot_id,
        },
        created_at=datetime.now(UTC),
    )
    return result


def observation_payload(
    patient_id: str,
    version: int,
    duration: float,
    event: int,
) -> dict[str, object]:
    return {
        "patient_id": patient_id,
        "version": version,
        "duration_months": duration,
        "event_observed": event,
        "observed_at": "2026-01-01T00:00:00Z",
    }


def test_api_write_prediction_and_staleness(api_client):
    client, repository = api_client
    result = publish_fixture(repository)
    response = client.get("/survival", params={"months": 24})
    assert response.status_code == 200
    assert response.json()["survival_probability"] == pytest.approx(0.4910982295)
    assert response.json()["is_stale"] is False

    payload = observation_payload("P009", 1, 36, 0)
    saved = client.post(
        "/observations",
        json=payload,
        headers={"X-API-Key": API_KEY},
    )
    assert saved.status_code == 201
    assert set(saved.json()) == {"observation_id", "status"}
    assert saved.json()["status"] == "created"

    stale = client.get("/models/latest")
    assert stale.status_code == 200
    assert stale.json()["is_stale"] is True
    assert stale.json()["result"]["rate"] == result["rate"]
    retry = client.post(
        "/observations",
        json=payload,
        headers={"X-API-Key": API_KEY},
    )
    assert retry.status_code == 200
    assert retry.json()["status"] == "idempotent"

    conflict = client.post(
        "/observations",
        json=observation_payload("P009", 1, 37, 0),
        headers={"X-API-Key": API_KEY},
    )
    assert conflict.status_code == 409
    assert "patient_id" not in stale.text
    assert "duration_months" not in stale.text


def test_api_authorization_validation_and_aggregate_curves(api_client):
    client, repository = api_client
    publish_fixture(repository)
    assert (
        client.post(
            "/observations",
            json=observation_payload("P010", 1, 10, 0),
        ).status_code
        == 401
    )
    assert client.get("/survival", params={"months": -1}).status_code == 422
    assert client.get("/survival", params={"months": "nan"}).status_code == 422
    curve = client.get("/curves/exponential", params={"points": 5})
    assert curve.status_code == 200
    assert len(curve.json()["curve"]) == 5
    assert curve.json()["curve"][0]["survival"] == 1
    assert len(client.get("/models/history").json()) == 1


def test_api_requires_correction_metadata_and_returns_no_patient_row(api_client):
    client, _ = api_client
    headers = {"X-API-Key": API_KEY}
    first = client.post(
        "/observations",
        json=observation_payload("P020", 1, 10, 1),
        headers=headers,
    )
    assert first.status_code == 201
    updated = observation_payload("P020", 2, 8, 0)
    assert (
        client.post("/observations", json=updated, headers=headers).status_code == 422
    )
    updated["correction_reason"] = "synthetic correction"
    updated["correction_of"] = first.json()["observation_id"]
    corrected = client.post("/observations", json=updated, headers=headers)
    assert corrected.status_code == 201
    assert set(corrected.json()) == {"observation_id", "status"}
