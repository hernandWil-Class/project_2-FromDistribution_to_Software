select
    snapshot_id,
    patient_id,
    observation_id
from {{ source('meta', 'snapshot_members') }}
