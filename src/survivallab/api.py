"""Local FastAPI service; public responses contain aggregate model outputs only."""

from __future__ import annotations

import hmac
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from survivallab.db.repository import (
    CorrectionError,
    ObservationConflict,
    Repository,
)
from survivallab.models import Observation
from survivallab.pipeline import RefreshFailure, run_refresh
from survivallab.stats import event_probability, survival_probability


class ObservationRequest(Observation):
    model_config = ConfigDict(extra="forbid", frozen=True)

    correction_reason: str | None = Field(default=None, min_length=1, max_length=1000)
    correction_of: UUID | None = None


class ObservationReceipt(BaseModel):
    observation_id: UUID
    status: str


class AggregateModelResponse(BaseModel):
    model_id: str
    snapshot_id: str
    published_at: datetime
    is_stale: bool
    result: dict[str, Any]
    provenance: dict[str, Any]


def _configured_repositories() -> tuple[Repository, Repository, Repository]:
    urls = {
        "ingest": os.environ.get("INGEST_DATABASE_URL"),
        "read": os.environ.get("READ_DATABASE_URL"),
        "pipeline": os.environ.get("PIPELINE_DATABASE_URL"),
    }
    if any(not value for value in urls.values()):
        raise RuntimeError(
            "INGEST_DATABASE_URL, READ_DATABASE_URL, and "
            "PIPELINE_DATABASE_URL are required"
        )
    ingest_url = urls["ingest"]
    read_url = urls["read"]
    pipeline_url = urls["pipeline"]
    assert ingest_url is not None and read_url is not None and pipeline_url is not None
    return (
        Repository(create_engine(ingest_url, pool_pre_ping=True)),
        Repository(create_engine(read_url, pool_pre_ping=True)),
        Repository(create_engine(pipeline_url, pool_pre_ping=True)),
    )


def _request_repository(request: Request, name: str) -> Repository:
    repository = getattr(request.app.state, f"{name}_repository", None)
    if not isinstance(repository, Repository):
        raise HTTPException(status_code=503, detail="database service is unavailable")
    return repository


def get_ingest_repository(request: Request) -> Repository:
    return _request_repository(request, "ingest")


def get_read_repository(request: Request) -> Repository:
    return _request_repository(request, "read")


def get_pipeline_repository(request: Request) -> Repository:
    return _request_repository(request, "pipeline")


def create_app(
    *,
    ingest_repository: Repository | None = None,
    read_repository: Repository | None = None,
    pipeline_repository: Repository | None = None,
) -> FastAPI:
    repositories = [ingest_repository, read_repository, pipeline_repository]

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if any(repository is None for repository in repositories):
            configured = _configured_repositories()
            app.state.ingest_repository = ingest_repository or configured[0]
            app.state.read_repository = read_repository or configured[1]
            app.state.pipeline_repository = pipeline_repository or configured[2]
        else:
            app.state.ingest_repository = ingest_repository
            app.state.read_repository = read_repository
            app.state.pipeline_repository = pipeline_repository
        yield

    app = FastAPI(
        title="SurvivalLab API",
        version="0.1.0",
        description="Synthetic-data survival analysis; aggregate outputs only.",
        lifespan=lifespan,
    )

    def api_key(
        supplied: Annotated[str | None, Header(alias="X-API-Key")] = None,
    ) -> None:
        expected = os.environ.get("API_KEY")
        if not expected:
            raise HTTPException(
                status_code=503, detail="write authorization is not configured"
            )
        if supplied is None or not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="invalid API key")

    def latest_model(read_repo: Repository) -> dict[str, Any]:
        model = read_repo.latest_model()
        if model is None:
            raise HTTPException(
                status_code=503, detail="no valid model has been published"
            )
        return model

    def stale_status(model: dict[str, Any], ingest_repo: Repository) -> bool:
        latest_ingest = ingest_repo.data_updated_at()
        published = model.get("published_at")
        return bool(
            latest_ingest is not None
            and published is not None
            and latest_ingest > published
        )

    def model_response(
        model: dict[str, Any], ingest_repo: Repository
    ) -> dict[str, Any]:
        return {
            "model_id": model["model_id"],
            "snapshot_id": model["snapshot_id"],
            "published_at": model["published_at"],
            "is_stale": stale_status(model, ingest_repo),
            "result": model["result"],
            "provenance": model["provenance"],
        }

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready(
        read_repo: Annotated[Repository, Depends(get_read_repository)],
    ) -> dict[str, str]:
        try:
            read_repo.healthcheck()
        except SQLAlchemyError as error:
            raise HTTPException(
                status_code=503, detail="database service is unavailable"
            ) from error
        return {"status": "ready"}

    @app.post(
        "/observations",
        response_model=ObservationReceipt,
        status_code=201,
        dependencies=[Depends(api_key)],
    )
    def save_observation(
        request: ObservationRequest,
        response: Response,
        ingest_repo: Annotated[Repository, Depends(get_ingest_repository)],
    ) -> ObservationReceipt:
        observation = Observation.model_validate(
            request.model_dump(exclude={"correction_reason", "correction_of"})
        )
        try:
            stored, duplicate = ingest_repo.ingest(
                observation,
                correction_reason=request.correction_reason,
                correction_of=str(request.correction_of)
                if request.correction_of
                else None,
            )
        except ObservationConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except CorrectionError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except SQLAlchemyError as error:
            raise HTTPException(
                status_code=503, detail="observation storage is unavailable"
            ) from error
        response.status_code = 200 if duplicate else 201
        return ObservationReceipt(
            observation_id=stored.observation_id,
            status="idempotent" if duplicate else "created",
        )

    @app.get("/models/latest", response_model=AggregateModelResponse)
    def get_latest_model(
        read_repo: Annotated[Repository, Depends(get_read_repository)],
        ingest_repo: Annotated[Repository, Depends(get_ingest_repository)],
    ) -> dict[str, Any]:
        return model_response(latest_model(read_repo), ingest_repo)

    @app.get("/models/history")
    def get_model_history(
        read_repo: Annotated[Repository, Depends(get_read_repository)],
    ) -> list[dict[str, Any]]:
        return [
            {
                "model_id": row["model_id"],
                "snapshot_id": row["snapshot_id"],
                "created_at": row["created_at"],
                "result": row["result"],
                "provenance": row["provenance"],
            }
            for row in read_repo.model_history()
        ]

    @app.get("/models/{model_id}")
    def get_historical_model(
        model_id: UUID,
        read_repo: Annotated[Repository, Depends(get_read_repository)],
    ) -> dict[str, Any]:
        model = read_repo.get_model(str(model_id))
        if model is None:
            raise HTTPException(status_code=404, detail="model not found")
        return {
            "model_id": model["model_id"],
            "snapshot_id": model["snapshot_id"],
            "created_at": model["created_at"],
            "result": model["result"],
            "provenance": model["provenance"],
        }

    @app.get("/survival")
    def calculate_survival(
        months: Annotated[float, Query(ge=0, allow_inf_nan=False)],
        read_repo: Annotated[Repository, Depends(get_read_repository)],
        ingest_repo: Annotated[Repository, Depends(get_ingest_repository)],
        model_id: UUID | None = None,
    ) -> dict[str, Any]:
        model = (
            read_repo.get_model(str(model_id))
            if model_id is not None
            else latest_model(read_repo)
        )
        if model is None:
            raise HTTPException(status_code=404, detail="model not found")
        result = model["result"]
        rate = result.get("rate")
        if result.get("status") != "fitted" or rate is None:
            raise HTTPException(status_code=503, detail="no fitted model is available")
        return {
            "model_id": model["model_id"],
            "snapshot_id": model["snapshot_id"],
            "months": months,
            "survival_probability": survival_probability(rate, months),
            "event_probability": event_probability(rate, months),
            "is_stale": stale_status(model, ingest_repo),
            "n": result["n"],
            "events": result["events"],
            "person_time": result["person_time"],
            "rate": rate,
            "mean_months": result["mean_months"],
            "median_months": result["median_months"],
            "interval_method": result["interval_method"],
            "intervals": result["intervals"],
            "published_at": model["published_at"],
            "fit_started_at": model["provenance"]["fit_started_at"],
        }

    @app.get("/curves/exponential")
    def exponential_curve(
        read_repo: Annotated[Repository, Depends(get_read_repository)],
        model_id: UUID | None = None,
        points: Annotated[int, Query(ge=2, le=500)] = 101,
    ) -> dict[str, Any]:
        model = (
            read_repo.get_model(str(model_id))
            if model_id is not None
            else latest_model(read_repo)
        )
        if model is None:
            raise HTTPException(status_code=404, detail="model not found")
        result = model["result"]
        rate = result.get("rate")
        if rate is None or result.get("status") != "fitted":
            raise HTTPException(status_code=503, detail="no fitted model is available")
        end = float(result["maximum_followup_months"])
        lower_rate = result["intervals"]["likelihood_ratio"]["lower"]
        upper_rate = result["intervals"]["likelihood_ratio"]["upper"]
        curve = []
        for index in range(points):
            months = end * index / (points - 1)
            curve.append(
                {
                    "months": months,
                    "survival": survival_probability(rate, months),
                    "lower": survival_probability(upper_rate, months),
                    "upper": survival_probability(lower_rate, months),
                }
            )
        return {
            "model_id": model["model_id"],
            "snapshot_id": model["snapshot_id"],
            "observed_followup_max_months": end,
            "curve": curve,
            "kaplan_meier": result["kaplan_meier"],
            "interval_method": (
                "pointwise transformed asymptotic likelihood-ratio interval"
            ),
        }

    @app.get("/pipeline/status")
    def pipeline_status(
        read_repo: Annotated[Repository, Depends(get_read_repository)],
        ingest_repo: Annotated[Repository, Depends(get_ingest_repository)],
    ) -> dict[str, Any]:
        status = read_repo.status()
        model = read_repo.latest_model()
        return {
            "pipeline": status,
            "model_id": model["model_id"] if model else None,
            "is_stale": stale_status(model, ingest_repo) if model else None,
        }

    @app.post("/pipeline/refresh", dependencies=[Depends(api_key)])
    def refresh(
        pipeline_repo: Annotated[Repository, Depends(get_pipeline_repository)],
    ) -> dict[str, Any]:
        try:
            return run_refresh(pipeline_repo)
        except RefreshFailure as error:
            raise HTTPException(
                status_code=409 if error.code == "zero_events" else 503,
                detail={
                    "error_code": error.code,
                    "run_id": error.run_id,
                    "message": str(error),
                },
            ) from error

    return app


app = create_app()
