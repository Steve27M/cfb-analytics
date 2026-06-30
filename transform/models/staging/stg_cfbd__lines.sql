-- Grain: one row per game per sportsbook provider (game_id + provider). Rename + recast only.
with source as (

    select * from {{ source('bronze', 'lines') }}

),

renamed as (

    select
        cast(game_id as bigint)                         as game_id,
        cast(season as integer)                         as season,
        cast(week as integer)                           as week,
        cast(season_type as varchar)                    as season_type,
        cast(provider as varchar)                       as provider,

        cast(home_team_id as bigint)                    as home_team_id,
        cast(home_team as varchar)                      as home_team,
        cast(home_conference as varchar)                as home_conference,
        cast(home_score as integer)                     as home_score,
        cast(away_team_id as bigint)                    as away_team_id,
        cast(away_team as varchar)                       as away_team,
        cast(away_conference as varchar)                as away_conference,
        cast(away_score as integer)                     as away_score,

        -- spread is from the home team's perspective (negative = home favored)
        cast(spread as double)                          as spread,
        cast(spread_open as double)                     as spread_open,
        cast(formatted_spread as varchar)               as formatted_spread,
        cast(over_under as double)                      as over_under,
        cast(over_under_open as double)                 as over_under_open,
        cast(home_moneyline as integer)                 as home_moneyline,
        cast(away_moneyline as integer)                 as away_moneyline,

        -- lineage
        cast(cfb_pull_id as varchar)                    as _pull_id,
        cast(cfb_fetched_at as timestamp)               as _fetched_at
    from source

)

select * from renamed
