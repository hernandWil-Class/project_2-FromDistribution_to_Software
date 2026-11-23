"""Reproducible simulation of exponential MLE bias and interval coverage."""

from __future__ import annotations

import argparse
import json

import numpy as np

from survivallab.stats import fit_exponential, rate_intervals


def simulate(
    repetitions: int, size: int, rate: float, seed: int
) -> dict[str, float | int]:
    if repetitions <= 0 or size <= 0 or rate <= 0:
        raise ValueError("repetitions, size, and rate must be positive")
    rng = np.random.default_rng(seed)
    estimates: list[float] = []
    covered = 0
    for _ in range(repetitions):
        event_times = rng.exponential(scale=1 / rate, size=size)
        censor_times = rng.uniform(12, 60, size=size)
        durations = np.minimum(event_times, censor_times)
        events = (event_times <= censor_times).astype(int)
        fit = fit_exponential(durations, events)
        if fit.rate is None:
            continue
        estimates.append(fit.rate)
        lower, upper = rate_intervals(fit)["likelihood_ratio"]
        covered += int(lower <= rate <= upper)
    return {
        "repetitions": repetitions,
        "fitted_repetitions": len(estimates),
        "sample_size": size,
        "true_rate_per_month": rate,
        "mean_estimated_rate": float(np.mean(estimates)) if estimates else 0.0,
        "bias": float(np.mean(estimates) - rate) if estimates else 0.0,
        "lr_coverage": covered / len(estimates) if estimates else 0.0,
        "seed": seed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=1000)
    parser.add_argument("--size", type=int, default=100)
    parser.add_argument("--rate", type=float, default=0.03)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    print(
        json.dumps(
            simulate(args.repetitions, args.size, args.rate, args.seed),
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
