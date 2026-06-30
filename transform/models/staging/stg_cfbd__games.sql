-- Grain: one row per game (game_id). Staging = rename + recast only, 1:1 with bronze.games.
with source as (

    select * from {{ source('bronze', 'games') }}

),

renamed as (

    select
        cast(game_id as bigint)                         as game_id,
        cast(season as integer)                         as season,
        cast(week as integer)                           as week,
        cast(season_type as varchar)                    as season_type,
        cast(start_date as timestamp)                   as start_date,
        cast(start_time_tbd as boolean)                 as start_time_tbd,
        cast(completed as boolean)                      as is_completed,
        cast(neutral_site as boolean)                   as is_neutral_site,
        cast(conference_game as boolean)                as is_conference_game,
        cast(attendance as integer)                     as attendance,
        cast(venue_id as integer)                       as venue_id,
        cast(venue as varchar)                          as venue,

        cast(home_id as bigint)                         as home_team_id,
        cast(home_team as varchar)                      as home_team,
        cast(home_division as varchar)                  as home_division,
        cast(home_conference as varchar)                as home_conference,
        cast(home_points as integer)                    as home_points,
        cast(home_post_win_prob as double)              as home_post_win_prob,
        cast(home_pregame_elo as integer)               as home_pregame_elo,
        cast(home_postgame_elo as integer)              as home_postgame_elo,

        cast(away_id as bigint)                         as away_team_id,
        cast(away_team as varchar)                      as away_team,
        cast(away_division as varchar)                  as away_division,
        cast(away_conference as varchar)                as away_conference,
        cast(away_points as integer)                    as away_points,
        cast(away_post_win_prob as double)              as away_post_win_prob,
        cast(away_pregame_elo as integer)               as away_pregame_elo,
        cast(away_postgame_elo as integer)              as away_postgame_elo,

        cast(excitement_index as double)                as excitement_index,

        -- lineage (carried from bronze, never used as business logic)
        cast(cfb_pull_id as varchar)                    as _pull_id,
        cast(cfb_fetched_at as timestamp)               as _fetched_at
    from source

)

select * from renamed
