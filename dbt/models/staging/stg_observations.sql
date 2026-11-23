select
    observation_id,
    patient_id,
    version,
    duration_months,
    event_observed,
    observed_at,
    ingested_at,
    payload_hash
from {{ source('raw', 'observations') }}
