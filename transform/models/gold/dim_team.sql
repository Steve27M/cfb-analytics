-- Grain: one row per team SCD2 version (team_sk). Built from the team_snapshot, which is
-- replayed one season per run so conference/division realignment becomes versioned history.
-- The snapshot's dbt_valid_from/to are run-clock timestamps; for season-aware fact joins we
-- derive a SEASON range from each version's source_season and the next version's start.
with snap as (

    select * from {{ ref('team_snapshot') }}

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
        dbt_valid_from,
        dbt_valid_to,
        -- season this version starts covering, and (next version's start - 1) it stops at
        source_season                                   as valid_from_season,
        coalesce(
            lead(source_season) over (
                partition by team_id order by dbt_valid_from
            ) - 1,
            9999
        )                                               as valid_to_season,
        (dbt_valid_to is null)                          as is_current
    from snap

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
        is_current
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
