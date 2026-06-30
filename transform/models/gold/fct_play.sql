-- Grain: one row per play (play_key). The play-level fact for EPA / success-rate analysis
-- and the home of the "over expected" residuals (RYOE/CPOE) the R/Python models write back.
-- Built straight from the deduped, keyed silver_plays; FKs resolve game + week.
with plays as (

    select * from {{ ref('silver_plays') }}

)

select
    play_key,
    {{ dbt_utils.generate_surrogate_key(['game_id']) }}                     as game_sk,
    {{ dbt_utils.generate_surrogate_key(['season', 'week', 'season_type']) }} as calendar_sk,

    game_id,
    season,
    week,
    season_type,
    game_play_number,

    offense_team,
    defense_team,
    is_neutral_site,

    period,
    time_secs_remaining,
    offense_score_diff_start,
    down,
    distance,
    yards_to_goal,
    is_goal_to_go,

    play_type,
    yards_gained,
    epa,
    ep_before,
    ep_after,
    is_success,
    wp_before,
    wp_after,

    is_rush,
    is_pass,
    is_completion,
    is_pass_attempt,
    is_sack,
    is_touchdown,
    is_garbage_time,

    rusher_player_name,
    rush_yards,
    passer_player_name,
    receiver_player_name,
    receiving_yards
from plays
