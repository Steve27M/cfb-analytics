-- Grain: one row per team per season. Official season box-score totals from CFBD /stats/season,
-- pivoted from the long (stat_name, stat_value) bronze rows into the columns this project uses.
-- These are AUTHORITATIVE counting stats: total offense and yards allowed are taken from here,
-- never re-derived from play-by-play (see ingest/ingest_cfbd.R for why).
with source as (

    select * from {{ source('bronze', 'season_stats') }}

),

renamed as (

    select
        cast(season as integer)   as season,
        cast(team as varchar)     as team,
        cast(stat_name as varchar) as stat_name,
        cast(stat_value as double) as stat_value,
        cast(cfb_pull_id as varchar)      as _pull_id,
        cast(cfb_fetched_at as timestamp) as _fetched_at
    from source

),

pivoted as (

    select
        season,
        team,
        max(case when stat_name = 'games'              then stat_value end) as games,
        max(case when stat_name = 'totalYards'         then stat_value end) as total_yards,
        max(case when stat_name = 'totalYardsOpponent' then stat_value end) as total_yards_allowed,
        max(case when stat_name = 'rushingYards'       then stat_value end) as rushing_yards,
        max(case when stat_name = 'netPassingYards'    then stat_value end) as passing_yards,
        max(case when stat_name = 'firstDowns'         then stat_value end) as first_downs,
        max(case when stat_name = 'turnovers'          then stat_value end) as turnovers_lost,
        max(case when stat_name = 'turnoversOpponent'  then stat_value end) as turnovers_forced,
        max(case when stat_name = 'thirdDowns'         then stat_value end) as third_downs,
        max(case when stat_name = 'thirdDownConversions' then stat_value end) as third_down_convs,
        max(case when stat_name = 'penaltyYards'       then stat_value end) as penalty_yards,
        max(_pull_id)    as _pull_id,
        max(_fetched_at) as _fetched_at
    from renamed
    group by season, team

)

select
    *,
    case when games > 0 then total_yards / games end         as yards_per_game,
    case when games > 0 then total_yards_allowed / games end as yards_allowed_per_game,
    turnovers_forced - turnovers_lost                        as turnover_margin,
    case when third_downs > 0 then third_down_convs / third_downs end as third_down_rate
from pivoted
