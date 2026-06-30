-- Grain: one row per team per game (game_id + team_id). Team efficiency over time: per-game
-- offensive/defensive EPA, plus season-to-date and rolling-form context built with window
-- functions. The "entering" metrics use a `rows ... 1 preceding` frame so they are strictly
-- leakage-safe (they describe form BEFORE the game) — the same discipline the game model needs.
with team_game as (

    select * from {{ ref('fct_team_game') }}
    where team_sk <> '-1'          -- FBS teams only; non-FBS placeholder has no efficiency line

),

ratings as (

    select season, team, sp_rating, offense_rating, defense_rating
    from {{ ref('silver_ratings_sp') }}

),

base as (

    select
        tg.team_game_sk,
        tg.team_sk,
        tg.opponent_team_sk,
        tg.game_id,
        tg.team_id,
        tg.team,
        tg.opponent,
        tg.opponent_team_id,
        tg.season,
        tg.week,
        tg.season_type,
        tg.home_away,
        tg.points_for,
        tg.points_against,
        tg.point_margin,
        tg.won,
        tg.offensive_epa_per_play,
        tg.defensive_epa_per_play,
        (tg.offensive_epa_per_play - tg.defensive_epa_per_play) as net_epa_per_play,
        tg.offensive_success_rate,
        tg.defensive_success_rate,
        -- opponent season SP+ strength, joined for opponent context / SoS
        opp.sp_rating                                   as opponent_sp_rating,
        opp.defense_rating                              as opponent_defense_rating
    from team_game tg
    left join ratings opp
        on tg.opponent = opp.team and tg.season = opp.season

),

windowed as (

    select
        *,

        -- games already played this season entering this game
        count(*) over w_prior                           as games_played_entering,

        -- season-to-date form ENTERING the game (excludes current row → no leakage)
        avg(net_epa_per_play) over w_prior              as std_net_epa_entering,
        avg(offensive_epa_per_play) over w_prior        as std_off_epa_entering,
        avg(defensive_epa_per_play) over w_prior        as std_def_epa_entering,
        avg(case when won then 1.0 else 0.0 end) over w_prior as std_win_pct_entering,

        -- rolling last-3-game form ENTERING the game
        avg(net_epa_per_play) over w_roll3              as roll3_net_epa_entering,

        -- strength of schedule entering: mean opponent SP+ faced so far
        avg(opponent_sp_rating) over w_prior            as sos_sp_entering,

        -- season-to-date INCLUDING the current game (for end-of-season leaderboards)
        avg(net_epa_per_play) over w_incl               as std_net_epa_to_date
    from base
    window
        w_prior as (
            partition by team_id, season
            order by week
            rows between unbounded preceding and 1 preceding
        ),
        w_roll3 as (
            partition by team_id, season
            order by week
            rows between 3 preceding and 1 preceding
        ),
        w_incl as (
            partition by team_id, season
            order by week
            rows between unbounded preceding and current row
        )

)

select * from windowed
