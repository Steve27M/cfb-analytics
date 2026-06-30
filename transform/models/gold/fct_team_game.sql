-- Grain: one row per team per game (game_id + team_id). The headline fact: outcome,
-- betting-line cover, and offensive/defensive EPA + success-rate aggregates per team-game.
-- FKs (team_sk, opponent_team_sk) resolve to the SCD2 dim_team version valid in that season.
with team_game as (

    select * from {{ ref('silver_team_game') }}

),

lines as (

    select * from {{ ref('silver_lines') }}

),

plays as (

    select * from {{ ref('silver_plays') }}

),

dim_team as (

    select * from {{ ref('dim_team') }}

),

-- the FBS membership set (excludes the Non-FBS placeholder) used to scope the star
fbs_teams as (

    select distinct team_id from dim_team where team_id <> -1

),

-- offensive box from play-by-play: EPA/play + success rate over scrimmage plays
offense_agg as (

    select
        game_id,
        offense_team                                    as team,
        count(*)                                        as offensive_plays,
        sum(epa)                                        as offensive_epa,
        avg(epa)                                        as offensive_epa_per_play,
        avg(case when is_success then 1.0 else 0.0 end) as offensive_success_rate
    from plays
    where (is_rush or is_pass) and not is_garbage_time and epa is not null
    group by game_id, offense_team

),

-- defensive box: the same plays, attributed to the defense (lower EPA allowed = better)
defense_agg as (

    select
        game_id,
        defense_team                                    as team,
        avg(epa)                                        as defensive_epa_per_play,
        avg(case when is_success then 1.0 else 0.0 end) as defensive_success_rate
    from plays
    where (is_rush or is_pass) and not is_garbage_time and epa is not null
    group by game_id, defense_team

),

final as (

    select
        {{ dbt_utils.generate_surrogate_key(['tg.game_id', 'tg.team_id']) }} as team_game_sk,
        {{ dbt_utils.generate_surrogate_key(['tg.game_id']) }}              as game_sk,
        {{ dbt_utils.generate_surrogate_key(['tg.season', 'tg.week', 'tg.season_type']) }}
            as calendar_sk,
        -- unmatched (non-FBS) participants resolve to the dim_team placeholder
        coalesce(dt.team_sk, '-1')                      as team_sk,
        coalesce(dopp.team_sk, '-1')                    as opponent_team_sk,

        tg.game_id,
        tg.team_id,
        tg.team,
        tg.opponent_team_id,
        tg.opponent,
        tg.season,
        tg.week,
        tg.season_type,
        tg.home_away,
        tg.is_home_field,
        tg.is_neutral_site,
        tg.is_conference_game,

        -- outcome measures
        tg.points_for,
        tg.points_against,
        tg.point_margin,
        tg.won,

        -- betting market (team perspective: home keeps the line, away flips its sign)
        case when tg.home_away = 'home' then ln.spread else -ln.spread end as team_spread,
        case
            when ln.spread is null then null
            when (tg.point_margin
                  + case when tg.home_away = 'home' then ln.spread else -ln.spread end) > 0
                then true
            else false
        end                                             as covered_spread,
        ln.over_under,

        -- efficiency box (null for FCS opponents with no parsed play-by-play)
        oa.offensive_plays,
        oa.offensive_epa,
        oa.offensive_epa_per_play,
        oa.offensive_success_rate,
        da.defensive_epa_per_play,
        da.defensive_success_rate,

        tg._fetched_at
    from team_game tg
    left join lines ln on tg.game_id = ln.game_id
    left join offense_agg oa on tg.game_id = oa.game_id and tg.team = oa.team
    left join defense_agg da on tg.game_id = da.game_id and tg.team = da.team
    -- season-aware SCD2 lookups
    left join dim_team dt
        on tg.team_id = dt.team_id
        and tg.season between dt.valid_from_season and dt.valid_to_season
    left join dim_team dopp
        on tg.opponent_team_id = dopp.team_id
        and tg.season between dopp.valid_from_season and dopp.valid_to_season
    -- FBS warehouse: keep only games involving at least one FBS team (drops pure FCS/D2
    -- matchups); the FCS side of an FBS game is retained with the Non-FBS placeholder.
    where tg.team_id in (select team_id from fbs_teams)
       or tg.opponent_team_id in (select team_id from fbs_teams)

)

select * from final
