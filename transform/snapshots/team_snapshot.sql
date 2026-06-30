{#
  SCD2 history of team attributes (conference / division / classification) across seasons.

  dbt snapshots track change across successive RUNS, so we feed one season per run via the
  `snapshot_season` var and replay seasons in chronological order (run.py loops 2023, 2024, ...).
  Each run compares the prior snapshot state to that season's team metadata; a team whose
  conference changed (e.g. the 2024 realignment: Texas/Oklahoma -> SEC, the Pac-12 collapse)
  gets its old version closed (dbt_valid_to set) and a new version opened. `check` strategy is
  used because the source has no natural updated_at — conference realignment is the change event.
#}
{% snapshot team_snapshot %}

{{
    config(
        target_schema='snapshots',
        unique_key='team_id',
        strategy='check',
        check_cols=['conference', 'division', 'classification', 'school'],
        invalidate_hard_deletes=True,
    )
}}

select
    team_id,
    season          as source_season,
    school,
    mascot,
    abbreviation,
    conference,
    division,
    classification,
    color,
    alt_color,
    logo
from {{ ref('stg_cfbd__teams') }}
where season = {{ var('snapshot_season', 2024) }}

{% endsnapshot %}
