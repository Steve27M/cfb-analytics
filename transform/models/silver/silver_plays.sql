-- Grain: one row per play (play_key). Conformance for bronze play-by-play, which arrives
-- WITHOUT a usable natural key: cfbfastR rounds id_play to a double upstream so it collides,
-- and game_play_number is shared by a play and its accompanying penalty. We therefore:
--   1. drop exact-duplicate rows (cfbfastR emits ~54 verbatim dups),
--   2. mint a deterministic surrogate play_key = hash(game_id, game_play_number, intra-seq),
--      where intra-seq orders the (at most 3) rows that share a game_play_number.
-- The key SET is stable across rebuilds (idempotent), which is what the warehouse needs.
with plays as (

    select * from {{ ref('stg_cfbd__plays') }}
    where game_id is not null

),

-- 1. exact-duplicate removal. Within a single season pull every row carries identical
--    lineage, so two rows equal on all business columns are equal on _pull_id/_fetched_at
--    too: plain DISTINCT collapses verbatim duplicates without dropping real plays.
deduped as (

    select distinct * from plays

),

-- 2. deterministic intra-(game, play_number) sequence to disambiguate shared numbers.
keyed as (

    select
        *,
        row_number() over (
            partition by game_id, game_play_number
            order by
                play_type, offense_team, defense_team, down, distance, yards_to_goal,
                yards_gained, period, clock_minutes, clock_seconds,
                ep_before, ep_after, epa, wp_before, wp_after,
                rusher_player_name, passer_player_name, receiver_player_name, play_id_raw
        ) as _intra_seq
    from deduped

),

final as (

    select
        {{ dbt_utils.generate_surrogate_key(['game_id', 'game_play_number', '_intra_seq']) }}
            as play_key,
        game_id,
        season,
        week,
        season_type,
        game_play_number,

        offense_team,
        defense_team,
        home_team,
        away_team,
        is_neutral_site,
        is_conference_game,

        offense_score,
        defense_score,
        offense_score_diff_start,
        half,
        period,
        clock_minutes,
        clock_seconds,
        time_secs_remaining,

        down,
        distance,
        yards_to_goal,
        yards_gained,
        play_type,
        is_goal_to_go,

        epa,
        ep_before,
        ep_after,
        -- cfbfastR leaves `success` null on non-scrimmage plays (kickoffs, timeouts); coerce
        -- to a clean boolean only where the play is gradeable.
        case when is_success = 1 then true when is_success = 0 then false end as is_success,
        wp_before,
        wp_after,

        (is_rush = 1)                                   as is_rush,
        (is_pass = 1)                                   as is_pass,
        (is_completion = 1)                             as is_completion,
        (is_pass_attempt = 1)                           as is_pass_attempt,
        (is_sack = 1)                                   as is_sack,
        (is_touchdown = 1)                              as is_touchdown,
        (is_rush_td = 1)                                as is_rush_td,
        (is_pass_td = 1)                                as is_pass_td,

        rusher_player_name,
        rush_yards,
        passer_player_name,
        receiver_player_name,
        receiving_yards,

        -- garbage-time flag (cfbscrapR convention): blowout context where EPA/WP are noise.
        case
            when period = 2 and abs(offense_score_diff_start) > 38 then true
            when period = 3 and abs(offense_score_diff_start) > 28 then true
            when period = 4 and abs(offense_score_diff_start) > 22 then true
            else false
        end                                             as is_garbage_time,

        _fetched_at
    from keyed

)

select * from final
