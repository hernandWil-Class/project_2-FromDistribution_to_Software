"""Streamlit presentation layer for the aggregate-only SurvivalLab API."""

from __future__ import annotations

import math
import os
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import streamlit as st

from survivallab.dashboard import (
    ApiClient,
    ApiError,
    ApiUnavailableError,
    build_observation_payload,
    publication_state,
)


@st.cache_data(ttl=15, show_spinner=False)
def cached_curve(base_url: str, model_id: str) -> dict[str, Any]:
    """Cache only aggregate curves for 15 seconds, keyed by published model."""
    client = ApiClient(base_url, os.environ.get("API_KEY", ""))
    return client.exponential_curve(model_id)


def _client() -> ApiClient:
    return ApiClient(
        os.environ.get("SURVIVALLAB_API_URL", "http://127.0.0.1:8000"),
        os.environ.get("API_KEY", ""),
    )


def _show_api_error(error: ApiError) -> None:
    if error.status_code == 409:
        st.error(f"Conflict: {error}")
    elif error.status_code == 422:
        st.error(f"Validation error: {error}")
    elif error.status_code == 503:
        st.warning(f"Service or model unavailable: {error}")
    else:
        st.error(f"API request failed ({error.status_code}): {error}")


def _observation_form(client: ApiClient) -> None:
    st.subheader("Record synthetic follow-up")
    st.caption("Saving an observation does not refresh or fit the model.")
    with st.form("observation_form"):
        patient_id = st.text_input("Synthetic patient ID")
        version = st.number_input("Version", min_value=1, step=1, value=1)
        duration = st.number_input(
            "Follow-up (months)", min_value=0.000001, value=12.0, step=1.0
        )
        event = st.radio("Death observed by this follow-up?", ["No", "Yes"])
        correction = st.checkbox("This is an explicit correction")
        correction_of = ""
        reason = ""
        if correction:
            correction_of = st.text_input("Prior observation UUID")
            reason = st.text_input("Correction reason")
        submitted = st.form_submit_button("Save observation")
    if not submitted:
        return
    try:
        payload = build_observation_payload(
            patient_id=patient_id,
            version=int(version),
            duration_months=float(duration),
            event_observed=int(event == "Yes"),
            correction_of=correction_of.strip() if correction else None,
            correction_reason=reason.strip() if correction else None,
            observed_at=datetime.now(UTC),
        )
    except ValueError as error:
        st.error(str(error))
        return
    try:
        receipt = client.save_observation(payload)
        st.success(
            f"Saved observation {receipt['observation_id']} ({receipt['status']}). "
            "The published model may now be stale; refresh it separately."
        )
    except ApiError as error:
        _show_api_error(error)
    except ApiUnavailableError as error:
        st.error(str(error))


def _prediction_controls(client: ApiClient, model: dict[str, Any]) -> None:
    st.subheader("Published-model calculator")
    st.caption("Selecting a month only calculates from a published fit; it never fits.")
    with st.form("prediction_form"):
        months = st.number_input("Horizon (months)", min_value=0.0, value=24.0)
        calculate = st.form_submit_button("Calculate survival")
    if calculate:
        try:
            prediction = client.survival(float(months))
            if prediction["is_stale"]:
                st.warning(
                    "This is the last published output; it is stale, not current."
                )
            st.metric(
                f"Survival at {months:g} months",
                f"{prediction['survival_probability']:.4f}",
            )
            st.metric("Event probability", f"{prediction['event_probability']:.4f}")
            st.caption(
                f"Model `{prediction['model_id']}` · "
                f"snapshot `{prediction['snapshot_id']}`"
            )
        except ApiError as error:
            _show_api_error(error)
        except ApiUnavailableError as error:
            st.error(str(error))

    result = model["result"]
    st.write(
        {
            "n": result["n"],
            "D": result["events"],
            "Y_person_months": result["person_time"],
            "lambda_per_month": result["rate"],
            "mean_months": result["mean_months"],
            "median_months": result["median_months"],
            "interval_method": result["interval_method"],
            "model_id": model["model_id"],
            "snapshot_id": model["snapshot_id"],
            "published_at": model["published_at"],
            "data_as_of": model["provenance"]["snapshot_created_at"],
        }
    )

    rate = result["rate"]
    with st.expander("Interval and conditional calculations"):
        start = st.number_input("Interval start (months)", min_value=0.0, value=12.0)
        end = st.number_input("Interval end (months)", min_value=0.0, value=24.0)
        if end < start:
            st.error("Interval end must be at least its start.")
        else:
            interval_probability = math.exp(-rate * start) - math.exp(-rate * end)
            st.write(
                f"Unconditional P({start:g} < T ≤ {end:g}) = {interval_probability:.4f}"
            )
        elapsed = st.number_input("Survived to (months)", min_value=0.0, value=12.0)
        future = st.number_input("Additional months", min_value=0.0, value=12.0)
        conditional = math.exp(-rate * future)
        st.write(
            f"P(T > {elapsed + future:g} | T > {elapsed:g}) = "
            f"{conditional:.4f} under a constant hazard."
        )


def _model_history(client: ApiClient, current_model: dict[str, Any]) -> None:
    st.subheader("Model history and aggregate curves")
    try:
        history = client.model_history()
        if not history:
            st.info("No model history is available.")
            return
        labels = {
            f"{entry['created_at']} · {entry['model_id']}": entry["model_id"]
            for entry in history
        }
        selected_label = st.selectbox("Historical fit", list(labels))
        selected_id = labels[selected_label]
        selected = (
            current_model
            if selected_id == current_model["model_id"]
            else client.model(selected_id)
        )
        left, right = st.columns(2)
        left.metric("Selected model events", selected["result"]["events"])
        right.metric("Current model events", current_model["result"]["events"])
        curve = cached_curve(
            os.environ.get("SURVIVALLAB_API_URL", "http://127.0.0.1:8000"),
            selected_id,
        )
        frame = pd.DataFrame(curve["curve"]).set_index("months")
        st.line_chart(frame[["survival", "lower", "upper"]])
        km = pd.DataFrame(curve["kaplan_meier"]).set_index("time_months")
        st.line_chart(km[["survival"]])
        st.caption(
            "Months since diagnosis; exponential pointwise band transforms the "
            "asymptotic likelihood-ratio rate interval. Kaplan–Meier is aggregate."
        )
    except ApiError as error:
        _show_api_error(error)
    except ApiUnavailableError as error:
        st.error(str(error))


def render_dashboard() -> None:
    st.set_page_config(page_title="SurvivalLab", layout="wide")
    st.title("SurvivalLab")
    st.warning(
        "Synthetic-data teaching application only. Do not enter real patient "
        "information; this is not clinical advice."
    )
    client = _client()
    _observation_form(client)
    st.divider()
    st.subheader("Refresh pipeline")
    st.caption("Observation entry and model refresh are separate operations.")
    if st.button("Refresh model"):
        try:
            outcome = client.refresh()
            st.success(f"Refresh {outcome['status']} (run {outcome['run_id']}).")
            cached_curve.clear()
        except ApiError as error:
            _show_api_error(error)
        except ApiUnavailableError as error:
            st.error(str(error))

    try:
        pipeline = client.pipeline_status()
    except ApiUnavailableError as error:
        st.error(f"API unavailable; no prediction is shown. {error}")
        return
    except ApiError as error:
        _show_api_error(error)
        return
    run = pipeline["pipeline"]
    state = publication_state(
        bool(pipeline.get("is_stale")),
        str(run.get("status", "idle")),
    )
    if state == "failed":
        st.error(
            f"Last refresh candidate failed ({run.get('error_code')}); "
            "the last valid publication remains active."
        )
    try:
        model = client.latest_model()
    except ApiError as error:
        _show_api_error(error)
        return
    except ApiUnavailableError as error:
        st.error(f"API unavailable; no prediction is shown. {error}")
        return
    state = publication_state(
        model["is_stale"],
        str(run.get("status", "idle")),
    )
    if state == "stale":
        st.warning("Published output is stale because newer observations are pending.")
    elif state == "failed":
        st.error(
            f"Last refresh candidate failed ({run.get('error_code')}); "
            "the last valid publication remains active."
        )
    else:
        st.success("Published model is current.")
    _prediction_controls(client, model)
    _model_history(client, model)


if __name__ == "__main__":
    render_dashboard()
