"""Command-line interface for synthetic data and model fitting."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path
from typing import Any

from survivallab import __version__
from survivallab.data import generate_cohort, validate_csv, write_cohort
from survivallab.stats import fit_exponential, rate_intervals

LOGGER = logging.getLogger("survivallab")


def _read_fit_csv(path: Path) -> tuple[list[float], list[int]]:
    durations: list[float] = []
    events: list[int] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"duration_months", "event_observed"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError("CSV must contain duration_months and event_observed")
        for row in reader:
            durations.append(float(row["duration_months"]))
            value = float(row["event_observed"])
            if value not in (0, 1):
                raise ValueError("event_observed must be exactly 0 or 1")
            events.append(int(value))
    return durations, events


def _write_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="survivallab", description="Synthetic survival analysis teaching tools"
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    generate = commands.add_parser("generate", help="generate synthetic study files")
    generate.add_argument("--size", type=int, default=100)
    generate.add_argument("--seed", type=int, required=True)
    generate.add_argument("--rate", type=float, default=0.03)
    generate.add_argument("--censor-min", type=float, default=12)
    generate.add_argument("--censor-max", type=float, default=60)
    generate.add_argument("--output", type=Path, default=Path("data/generated"))

    validate = commands.add_parser("validate", help="validate an observed-data CSV")
    validate.add_argument("csv_path", type=Path)

    fit = commands.add_parser(
        "fit-csv", help="fit exponential model from an observed CSV"
    )
    fit.add_argument("csv_path", type=Path)
    fit.add_argument("--z", type=float, default=1.96)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    args = build_parser().parse_args(argv)
    try:
        if args.command == "generate":
            cohort = generate_cohort(
                size=args.size,
                seed=args.seed,
                rate=args.rate,
                censor_min=args.censor_min,
                censor_max=args.censor_max,
            )
            write_cohort(cohort, args.output)
            _write_json({"output": str(args.output), **cohort.metadata})
            return 0
        if args.command == "validate":
            errors = validate_csv(args.csv_path)
            _write_json({"valid": not errors, "errors": errors})
            return 0 if not errors else 2
        if args.command == "fit-csv":
            durations, events = _read_fit_csv(args.csv_path)
            fit = fit_exponential(durations, events)
            output: dict[str, Any] = {
                **fit.to_dict(),
                "assumptions": [
                    "independent subjects",
                    "independent right censoring",
                    "one constant common hazard",
                ],
            }
            if fit.status == "fitted":
                assert fit.rate is not None
                output["intervals"] = {
                    method: {"lower": bounds[0], "upper": bounds[1]}
                    for method, bounds in rate_intervals(fit, args.z).items()
                }
            _write_json(output)
            return 0
    except (OSError, ValueError) as error:
        LOGGER.error("%s", error)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
