-- Grain: one row per game (game_sk / game_id). Game-context dimension: when, where, and
-- the matchup framing, plus the consensus betting market. Measures live in the facts.
with games as (

    select * from {{ ref('silver_games') }}

),

lines as (

    select * from {{ ref('silver_lines') }}

)

select
    {{ dbt_utils.generate_surrogate_key(['games.game_id']) }} as game_sk,
    games.game_id,
    games.season,
    games.week,
    games.season_type,
    games.start_date,
    games.is_neutral_site,
    games.is_conference_game,
    games.venue,
    games.attendance,
    games.home_team_id,
    games.home_team,
    games.away_team_id,
    games.away_team,
    games.home_points,
    games.away_points,
    games.home_margin,
    games.total_points,
    games.home_won,
    games.excitement_index,
    -- consensus market (home-perspective spread; null where no book priced the game)
    lines.spread                                        as home_spread_consensus,
    lines.over_under                                    as over_under_consensus,
    (lines.game_id is not null)                         as has_betting_line
from games
left join lines on games.game_id = lines.game_id
