with expected as (
    select
        snapshot_id,
        count(*)::bigint as n,
        sum(event_observed)::bigint as d,
        sum(duration_months)::double precision as y
    from {{ ref('analysis_cohort') }}
    group by snapshot_id
)
select statistics.snapshot_id
from {{ ref('snapshot_statistics') }} as statistics
join expected using (snapshot_id)
where statistics.n <> expected.n
   or statistics.d <> expected.d
   or statistics.y <> expected.y
   or statistics.d > statistics.n
