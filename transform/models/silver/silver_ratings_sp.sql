-- Grain: one row per team per season (season + team). Conformed SP+ ratings — passthrough
-- of the staged columns the marts/models consume, with team kept as the conformance key.
with ratings as (

    select * from {{ ref('stg_cfbd__ratings_sp') }}

)

select
    season,
    team,
    conference,
    sp_rating,
    sp_ranking,
    second_order_wins,
    strength_of_schedule,
    offense_rating,
    offense_ranking,
    offense_success,
    offense_explosiveness,
    defense_rating,
    defense_ranking,
    defense_success,
    defense_explosiveness,
    defense_havoc_total,
    special_teams_rating,
    _fetched_at
from ratings
