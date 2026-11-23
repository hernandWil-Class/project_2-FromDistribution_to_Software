select
    snapshot_id,
    count(*)::bigint as n,
    sum(event_observed)::bigint as d,
    sum(duration_months)::double precision as y
from {{ ref('analysis_cohort') }}
group by snapshot_id
