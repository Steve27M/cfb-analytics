-- Grain: one row per season + week + season_type. Rename + recast only.
with source as (

    select * from {{ source('bronze', 'calendar') }}

),

renamed as (

    select
        cast(season as integer)                         as season,
        cast(week as integer)                           as week,
        cast(season_type as varchar)                    as season_type,
        cast(first_game_start as timestamp)             as first_game_start,
        cast(last_game_start as timestamp)              as last_game_start,

        -- lineage
        cast(cfb_pull_id as varchar)                    as _pull_id,
        cast(cfb_fetched_at as timestamp)               as _fetched_at
    from source

)

select * from renamed
