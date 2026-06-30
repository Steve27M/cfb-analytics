-- Grain: one row per season + week + season_type (calendar_sk). The week dimension games
-- and team-games roll up to. Built from the CFBD calendar feed UNIONed with the distinct
-- weeks actually present in games, so the dimension is referentially complete for the facts
-- (the calendar feed omits a handful of weeks the schedule still uses).
with calendar as (

    select
        season,
        week,
        season_type,
        first_game_start,
        last_game_start
    from {{ ref('stg_cfbd__calendar') }}

),

game_weeks as (

    select distinct
        season,
        week,
        season_type
    from {{ ref('silver_games') }}

),

combined as (

    select
        gw.season,
        gw.week,
        gw.season_type,
        cal.first_game_start,
        cal.last_game_start
    from game_weeks gw
    left join calendar cal
        on  gw.season = cal.season
        and gw.week = cal.week
        and gw.season_type = cal.season_type

    union

    -- keep calendar-only weeks (e.g. bye weeks) that have no games
    select
        cal.season,
        cal.week,
        cal.season_type,
        cal.first_game_start,
        cal.last_game_start
    from calendar cal
    left join game_weeks gw
        on  cal.season = gw.season
        and cal.week = gw.week
        and cal.season_type = gw.season_type
    where gw.season is null

)

select
    {{ dbt_utils.generate_surrogate_key(['season', 'week', 'season_type']) }} as calendar_sk,
    season,
    week,
    season_type,
    first_game_start,
    last_game_start,
    (season_type = 'postseason')                        as is_postseason
from combined
