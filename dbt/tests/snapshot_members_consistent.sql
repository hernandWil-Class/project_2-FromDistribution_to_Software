select snapshot.snapshot_id
from {{ source('meta', 'snapshots') }} as snapshot
left join (
    select snapshot_id, count(*)::integer as actual_members
    from {{ source('meta', 'snapshot_members') }}
    group by snapshot_id
) as members using (snapshot_id)
where snapshot.member_count <> coalesce(members.actual_members, 0)
