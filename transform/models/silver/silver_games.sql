-- Grain: one row per completed game (game_id). Conformed game header with derived
-- outcome fields. Built from staging via ref() — no source() outside staging.
with games as (

    select * from {{ ref('stg_cfbd__games') }}

),

conformed as (

    select
        game_id,
        season,
        week,
        season_type,
        start_date,
        is_neutral_site,
        is_conference_game,
        venue_id,
        venue,
        attendance,

        home_team_id,
        home_team,
        home_conference,
        home_points,
        home_pregame_elo,
        home_postgame_elo,

        away_team_id,
        away_team,
        away_conference,
        away_points,
        away_pregame_elo,
        away_postgame_elo,

        excitement_index,

        -- derived outcome fields (skill: business logic lives in silver/marts, not staging)
        (home_points - away_points)                     as home_margin,
        (home_points + away_points)                     as total_points,
        case
            when home_points > away_points then true
            when home_points < away_points then false
        end                                             as home_won,

        _fetched_at
    from games
    -- a star is built from settled facts; drop the handful of not-yet-final games
    where is_completed
      and home_points is not null
      and away_points is not null

)

select * from conformed
