-- Grain: one row per team per game (game_id + team_id) — the home/away game header
-- unpivoted to a team-centric "long" shape. This is the spine of fct_team_game.
with games as (

    select * from {{ ref('silver_games') }}

),

home_side as (

    select
        game_id,
        season,
        week,
        season_type,
        start_date,
        is_neutral_site,
        is_conference_game,
        home_team_id                                    as team_id,
        home_team                                       as team,
        home_conference                                 as conference,
        away_team_id                                    as opponent_team_id,
        away_team                                       as opponent,
        away_conference                                 as opponent_conference,
        'home'                                          as home_away,
        not is_neutral_site                             as is_home_field,
        home_points                                     as points_for,
        away_points                                     as points_against,
        home_pregame_elo                                as pregame_elo,
        _fetched_at
    from games

),

away_side as (

    select
        game_id,
        season,
        week,
        season_type,
        start_date,
        is_neutral_site,
        is_conference_game,
        away_team_id                                    as team_id,
        away_team                                       as team,
        away_conference                                 as conference,
        home_team_id                                    as opponent_team_id,
        home_team                                       as opponent,
        home_conference                                 as opponent_conference,
        'away'                                          as home_away,
        false                                           as is_home_field,
        away_points                                     as points_for,
        home_points                                     as points_against,
        away_pregame_elo                                as pregame_elo,
        _fetched_at
    from games

),

unioned as (

    select * from home_side
    union all
    select * from away_side

)

select
    game_id,
    team_id,
    team,
    conference,
    opponent_team_id,
    opponent,
    opponent_conference,
    season,
    week,
    season_type,
    start_date,
    home_away,
    is_home_field,
    is_neutral_site,
    is_conference_game,
    points_for,
    points_against,
    (points_for - points_against)                       as point_margin,
    pregame_elo,
    (points_for > points_against)                       as won,
    _fetched_at
from unioned
