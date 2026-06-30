-- Grain: one row per play row as delivered by cfbfastR::load_cfb_pbp. NO dedup or key
-- minting here (that is silver's job) — staging only renames + recasts 1:1 with bronze.plays.
-- NOTE: id_play is unreliable (cfbfastR rounds it to a double upstream → collisions); kept for
-- reference only. The deterministic play key is minted downstream in silver_plays.
with source as (

    select * from {{ source('bronze', 'plays') }}

),

renamed as (

    select
        cast(id_play as bigint)                         as play_id_raw,
        cast(year as integer)                           as season,
        cast(week as integer)                           as week,
        cast(game_id as bigint)                         as game_id,
        cast(game_play_number as integer)               as game_play_number,
        cast(season_type as varchar)                    as season_type,

        cast(pos_team as varchar)                       as offense_team,
        cast(def_pos_team as varchar)                   as defense_team,
        cast(home as varchar)                           as home_team,
        cast(away as varchar)                           as away_team,
        cast(neutral_site as boolean)                   as is_neutral_site,
        cast(conference_game as boolean)                as is_conference_game,

        cast(pos_team_score as integer)                 as offense_score,
        cast(def_pos_team_score as integer)             as defense_score,
        cast(pos_score_diff_start as integer)           as offense_score_diff_start,

        cast(half as integer)                           as half,
        cast(period as integer)                         as period,
        cast(clock_minutes as integer)                  as clock_minutes,
        cast(clock_seconds as integer)                  as clock_seconds,
        cast("TimeSecsRem" as integer)                  as time_secs_remaining,

        cast(down as integer)                           as down,
        cast(distance as integer)                       as distance,
        cast(yards_to_goal as integer)                  as yards_to_goal,
        cast(yards_gained as integer)                   as yards_gained,
        cast(play_type as varchar)                      as play_type,
        cast("Goal_To_Go" as boolean)                   as is_goal_to_go,

        cast("EPA" as double)                           as epa,
        cast(ep_before as double)                       as ep_before,
        cast(ep_after as double)                        as ep_after,
        cast(success as integer)                        as is_success,
        cast(wp_before as double)                       as wp_before,
        cast(wp_after as double)                        as wp_after,

        cast(rush as integer)                           as is_rush,
        cast(rush_td as integer)                        as is_rush_td,
        cast(pass as integer)                           as is_pass,
        cast(pass_td as integer)                        as is_pass_td,
        cast(completion as integer)                     as is_completion,
        cast(pass_attempt as integer)                   as is_pass_attempt,
        cast(target as integer)                         as is_target,
        cast(sack as integer)                           as is_sack,
        cast(td_play as integer)                        as is_td_play,
        cast(touchdown as integer)                      as is_touchdown,
        cast(fg_made as integer)                        as is_fg_made,

        cast(rusher_player_name as varchar)             as rusher_player_name,
        cast(yds_rushed as integer)                     as rush_yards,
        cast(passer_player_name as varchar)             as passer_player_name,
        cast(receiver_player_name as varchar)           as receiver_player_name,
        cast(yds_receiving as integer)                  as receiving_yards,

        -- lineage
        cast(cfb_pull_id as varchar)                    as _pull_id,
        cast(cfb_fetched_at as timestamp)               as _fetched_at
    from source

)

select * from renamed
