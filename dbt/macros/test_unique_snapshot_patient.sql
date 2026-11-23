{% test unique_snapshot_patient(model) %}
select snapshot_id, patient_id
from {{ model }}
group by snapshot_id, patient_id
having count(*) > 1
{% endtest %}
