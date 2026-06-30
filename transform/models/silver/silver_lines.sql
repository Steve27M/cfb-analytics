-- Grain: one row per game (game_id). Collapses the up-to-5 sportsbook rows per game into a
-- single consensus line via the median across providers (robust to a single book's outlier).
-- spread is from the home team's perspective (negative = home favored).
with lines as (

    select * from {{ ref('stg_cfbd__lines') }}

),

consensus as (

    select
        game_id,
        any_value(season)                               as season,
        any_value(week)                                 as week,
        median(spread)                                  as spread,
        median(spread_open)                             as spread_open,
        median(over_under)                              as over_under,
        median(over_under_open)                         as over_under_open,
        count(*)                                        as provider_count,
        max(_fetched_at)                                as _fetched_at
    from lines
    group by game_id

)

select * from consensus
