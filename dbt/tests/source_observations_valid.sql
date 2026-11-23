select observation_id
from {{ source('raw', 'observations') }}
where duration_months is null
   or duration_months <= 0
   or duration_months = 'NaN'::double precision
   or duration_months = 'Infinity'::double precision
   or duration_months = '-Infinity'::double precision
   or event_observed not in (0, 1)
   or version < 1
