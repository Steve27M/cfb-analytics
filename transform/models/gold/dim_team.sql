-- Grain: one row per team SCD2 version (team_sk). Built from the team_snapshot, which is
-- replayed one season per run so conference/division realignment becomes versioned history.
-- The snapshot's dbt_valid_from/to are run-clock timestamps; for season-aware fact joins we
-- derive a SEASON range from each version's source_season and the next version's start.
with snap as (

    select * from {{ ref('team_snapshot') }}

),

-- One version per (team_id, source_season). Guards against snapshot re-runs, and lets us derive
-- validity from the SEASON the version describes rather than wall-clock run order (the snapshot
-- may be replayed out of chronological order, which would otherwise invert/overlap the ranges).
snap_dedup as (

    select *
    from snap
    qualify row_number() over (
        partition by team_id, source_season order by dbt_valid_from desc
    ) = 1

),

versioned as (

    select
        team_id,
        source_season,
        school,
        mascot,
        abbreviation,
        conference,
        division,
        classification,
        color,
        alt_color,
        logo,
        -- season this version starts covering, and (next version's start - 1) it stops at,
        -- ordered by the data's own season chronology so the ranges never overlap
        source_season                                   as valid_from_season,
        coalesce(
            lead(source_season) over (
                partition by team_id order by source_season
            ) - 1,
            9999
        )                                               as valid_to_season
    from snap_dedup

),

versions as (

    select
        {{ dbt_utils.generate_surrogate_key(['team_id', 'valid_from_season']) }} as team_sk,
        team_id,
        school,
        mascot,
        abbreviation,
        conference,
        division,
        classification,
        color,
        alt_color,
        logo,
        valid_from_season,
        valid_to_season,
        (valid_to_season = 9999)                        as is_current
    from versioned

),

-- Kimball "unknown member": the games/plays feed covers all divisions, but this is an FBS
-- warehouse — non-FBS participants (FCS cupcakes, etc.) have no team row. Facts COALESCE
-- their unmatched FKs to this placeholder so the star stays referentially complete.
placeholder as (

    select
        '-1'                                            as team_sk,
        cast(-1 as bigint)                              as team_id,
        'Non-FBS'                                       as school,
        cast(null as varchar)                           as mascot,
        cast(null as varchar)                           as abbreviation,
        'Non-FBS'                                       as conference,
        cast(null as varchar)                           as division,
        cast(null as varchar)                           as classification,
        cast(null as varchar)                           as color,
        cast(null as varchar)                           as alt_color,
        cast(null as varchar)                           as logo,
        cast(0 as integer)                              as valid_from_season,
        cast(9999 as integer)                           as valid_to_season,
        true                                            as is_current

)

select * from versions
union all
select * from placeholder
