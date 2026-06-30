-- Grain: one row per rusher per season per team (rusher_player_name + season + offense_team).
-- Season rushing production + an odd/even-play split-half split for the book's M1 metric-
-- stability analysis (Ch.2: is yards-per-carry skill or noise?). This is the production base
-- the RYOE "over expected" residuals (M2/M3, written back by the R/Python models) attach to.
with fbs_teams as (

    -- FBS school names (current + historical SCD2 versions); excludes the Non-FBS placeholder
    select distinct school from {{ ref('dim_team') }} where team_id <> -1

),

rushes as (

    select
        p.rusher_player_name,
        p.season,
        p.offense_team                                  as team,
        p.game_play_number,
        p.rush_yards,
        p.epa,
        p.is_success,
        p.is_touchdown                                  as is_rush_td  -- TD on a rush play
    from {{ ref('fct_play') }} p
    inner join fbs_teams f on p.offense_team = f.school   -- FBS offenses only
    where p.is_rush
      and p.rusher_player_name is not null
      and not p.is_garbage_time
      and p.rush_yards is not null

),

aggregated as (

    select
        rusher_player_name,
        season,
        team,

        count(*)                                        as rush_attempts,
        sum(rush_yards)                                 as rush_yards,
        sum(case when is_rush_td then 1 else 0 end)     as rush_tds,
        avg(cast(rush_yards as double))                 as yards_per_carry,
        avg(epa)                                        as rush_epa_per_attempt,
        sum(epa)                                        as rush_epa_total,
        avg(case when is_success then 1.0 else 0.0 end) as rush_success_rate,

        -- split-half reliability inputs (odd vs even play number) for M1 stability
        avg(case when game_play_number % 2 = 1 then cast(rush_yards as double) end)
            as ypc_odd_plays,
        avg(case when game_play_number % 2 = 0 then cast(rush_yards as double) end)
            as ypc_even_plays,
        sum(case when game_play_number % 2 = 1 then 1 else 0 end) as attempts_odd,
        sum(case when game_play_number % 2 = 0 then 1 else 0 end) as attempts_even
    from rushes
    group by rusher_player_name, season, team

)

select * from aggregated
