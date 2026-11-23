select
    member.snapshot_id,
    member.patient_id,
    observation.observation_id,
    observation.version,
    observation.duration_months,
    observation.event_observed,
    observation.observed_at,
    observation.ingested_at
from {{ ref('stg_snapshot_members') }} as member
join {{ ref('stg_observations') }} as observation
  on observation.observation_id = member.observation_id
join {{ source('meta', 'snapshots') }} as snapshot
  on snapshot.snapshot_id = member.snapshot_id
