select cohort.snapshot_id, cohort.patient_id, cohort.observation_id
from {{ ref('analysis_cohort') }} as cohort
left join {{ source('meta', 'snapshots') }} as snapshot
  on snapshot.snapshot_id = cohort.snapshot_id
left join {{ source('raw', 'observations') }} as observation
  on observation.observation_id = cohort.observation_id
where snapshot.snapshot_id is null
   or observation.observation_id is null
   or cohort.duration_months is null
   or cohort.duration_months <= 0
   or cohort.duration_months = 'NaN'::double precision
   or cohort.duration_months = 'Infinity'::double precision
   or cohort.event_observed not in (0, 1)
