"""Synchronous, locked refresh pipeline shared by API and manual operations."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import platform
import shlex
import subprocess
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from survivallab import __version__
from survivallab.db.repository import Repository
from survivallab.stats import (
    FitResult,
    fit_exponential,
    kaplan_meier,
    mean_survival_time,
    median_survival_time,
    rate_intervals,
)

METHOD = "exponential-rate-mle-v1"
ASSUMPTIONS = [
    "independent subjects",
    "independent right censoring",
    "one constant common hazard",
]


class RefreshFailure(RuntimeError):
    def __init__(self, code: str, message: str, run_id: str):
        super().__init__(message)
        self.code = code
        self.run_id = run_id


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _hash_files(paths: Sequence[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: str(item)):
        digest.update(str(path.relative_to(_project_root())).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _code_hash() -> str:
    root = _project_root()
    candidates: list[Path] = []
    for folder in (root / "src", root / "dbt" / "models", root / "dbt" / "macros"):
        if folder.exists():
            candidates.extend(folder.rglob("*.py"))
            candidates.extend(folder.rglob("*.sql"))
            candidates.extend(folder.rglob("*.yml"))
    candidates.extend(
        path for path in (root / "pyproject.toml", root / "uv.lock") if path.exists()
    )
    return _hash_files(candidates)


def _config_hash() -> str:
    configuration = {
        "method": METHOD,
        "time_unit": "months",
        "intervals": ["log_wald", "likelihood_ratio"],
        "interval_z": 1.96,
        "fit_on_zero_events": False,
    }
    return hashlib.sha256(
        json.dumps(configuration, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _dbt_command() -> list[str]:
    configured = os.environ.get("SURVIVALLAB_DBT_COMMAND", "dbt")
    return shlex.split(configured)


def _run_dbt() -> str:
    command = _dbt_command()
    root = _project_root()
    try:
        version = subprocess.run(
            [*command, "--version"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        build = subprocess.run(
            [
                *command,
                "build",
                "--project-dir",
                str(root / "dbt"),
                "--profiles-dir",
                str(root / "dbt"),
            ],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise RefreshFailure(
            "dbt_unavailable",
            "dbt executable is unavailable; install the locked dbt environment",
            "",
        ) from error
    except subprocess.CalledProcessError as error:
        raise RefreshFailure(
            "dbt_version_failed", "dbt version check failed", ""
        ) from error
    if build.returncode != 0:
        raise RefreshFailure(
            "dbt_build_failed",
            "dbt build or source tests failed; inspect the local dbt command output",
            "",
        )
    return version.stdout.strip()


def _result(fit: FitResult, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if fit.rate is None:
        return {
            **fit.to_dict(),
            "assumptions": ASSUMPTIONS,
            "time_unit": "months",
            "interval_method": "asymptotic",
        }
    rate = fit.rate
    interval_values = rate_intervals(fit)
    return {
        **fit.to_dict(),
        "mean_months": mean_survival_time(rate),
        "median_months": median_survival_time(rate),
        "interval_method": "asymptotic",
        "intervals": {
            key: {"lower": values[0], "upper": values[1]}
            for key, values in interval_values.items()
        },
        "minimum_followup_months": min(row["duration_months"] for row in rows),
        "maximum_followup_months": max(row["duration_months"] for row in rows),
        "kaplan_meier": kaplan_meier(
            [row["duration_months"] for row in rows],
            [row["event_observed"] for row in rows],
        ),
        "assumptions": ASSUMPTIONS,
        "time_unit": "months",
    }


def run_refresh(
    repository: Repository,
    *,
    dbt_runner: Callable[[], str] | None = None,
) -> dict[str, Any]:
    """Create/reuse a snapshot, validate it with dbt, fit, and atomically publish."""
    run_id = str(uuid.uuid4())
    started_at = datetime.now(UTC)
    repository.start_run(run_id, started_at)
    snapshot_id: str | None = None
    try:
        with repository.refresh_lock():
            snapshot_id, reused_snapshot = repository.create_snapshot()
            code_hash = _code_hash()
            config_hash = _config_hash()
            existing = repository.has_candidate(
                snapshot_id, code_hash, config_hash, METHOD
            )
            if existing is not None:
                repository.finish_run(
                    run_id,
                    status="skipped",
                    finished_at=datetime.now(UTC),
                    snapshot_id=snapshot_id,
                    model_id=existing["model_id"],
                    message="unchanged candidate already published",
                )
                return {
                    "run_id": run_id,
                    "status": "skipped",
                    "snapshot_id": snapshot_id,
                    "model_id": existing["model_id"],
                    "snapshot_reused": reused_snapshot,
                }

            dbt_version = (dbt_runner or _run_dbt)()
            rows = repository.snapshot_rows(snapshot_id)
            if not rows:
                raise RefreshFailure(
                    "empty_snapshot", "cannot fit an empty snapshot", run_id
                )
            fit = fit_exponential(
                [row["duration_months"] for row in rows],
                [row["event_observed"] for row in rows],
            )
            if fit.status != "fitted" or fit.rate is None:
                raise RefreshFailure(
                    "zero_events",
                    "snapshot contains no events; no model was published",
                    run_id,
                )
            dbt_totals = repository.dbt_statistics(snapshot_id)
            if dbt_totals is None:
                raise RefreshFailure(
                    "dbt_statistics_missing",
                    "dbt did not produce sufficient statistics for this snapshot",
                    run_id,
                )
            if (
                int(dbt_totals["n"]) != fit.n
                or int(dbt_totals["d"]) != fit.events
                or not math.isclose(
                    float(dbt_totals["y"]), fit.person_time, rel_tol=1e-12
                )
            ):
                raise RefreshFailure(
                    "statistics_mismatch",
                    "dbt and Python sufficient statistics disagree",
                    run_id,
                )

            snapshot = repository.get_snapshot(snapshot_id)
            if snapshot is None:
                raise RefreshFailure(
                    "snapshot_missing", "snapshot disappeared during refresh", run_id
                )
            result = _result(fit, rows)
            model_id = str(uuid.uuid4())
            created_at = datetime.now(UTC)
            provenance = {
                "snapshot_id": snapshot_id,
                "snapshot_hash": snapshot["content_hash"],
                "snapshot_created_at": snapshot["created_at"].isoformat(),
                "code_hash": code_hash,
                "config_hash": config_hash,
                "method": METHOD,
                "time_unit": "months",
                "rate_unit": "per month",
                "python_version": platform.python_version(),
                "survivallab_version": __version__,
                "sqlalchemy_version": importlib.metadata.version("sqlalchemy"),
                "psycopg_version": importlib.metadata.version("psycopg"),
                "dbt_version": dbt_version,
                "fit_started_at": started_at.isoformat(),
                "published_at": created_at.isoformat(),
            }
            repository.publish(
                model_id=model_id,
                snapshot_id=snapshot_id,
                method=METHOD,
                code_hash=code_hash,
                config_hash=config_hash,
                result=result,
                provenance=provenance,
                created_at=created_at,
            )
            repository.finish_run(
                run_id,
                status="succeeded",
                finished_at=created_at,
                snapshot_id=snapshot_id,
                model_id=model_id,
            )
            return {
                "run_id": run_id,
                "status": "succeeded",
                "snapshot_id": snapshot_id,
                "model_id": model_id,
                "snapshot_reused": reused_snapshot,
                "result": result,
            }
    except RefreshFailure as error:
        error_run_id = error.run_id or run_id
        repository.finish_run(
            error_run_id,
            status="failed",
            finished_at=datetime.now(UTC),
            snapshot_id=snapshot_id,
            error_code=error.code,
            message=str(error),
        )
        raise RefreshFailure(error.code, str(error), error_run_id) from error
    except (SQLAlchemyError, OSError, ValueError) as error:
        repository.finish_run(
            run_id,
            status="failed",
            finished_at=datetime.now(UTC),
            snapshot_id=snapshot_id,
            error_code="refresh_failed",
            message="refresh failed; inspect local service logs",
        )
        raise RefreshFailure(
            "refresh_failed",
            "refresh failed; inspect local service logs",
            run_id,
        ) from error
