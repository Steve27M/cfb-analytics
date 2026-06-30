-- Grain: one row per team per season (team_id + season). Team + venue metadata.
-- Rename + recast only. SCD2 over conference/coach changes is handled by a gold snapshot.
with source as (

    select * from {{ source('bronze', 'teams') }}

),

renamed as (

    select
        cast(team_id as bigint)                         as team_id,
        cast(cfb_season as integer)                     as season,
        cast(school as varchar)                         as school,
        cast(mascot as varchar)                         as mascot,
        cast(abbreviation as varchar)                   as abbreviation,
        cast(conference as varchar)                     as conference,
        cast(division as varchar)                       as division,
        cast(classification as varchar)                 as classification,
        cast(color as varchar)                          as color,
        cast(alt_color as varchar)                      as alt_color,
        cast(logo as varchar)                           as logo,

        cast(venue_id as integer)                       as venue_id,
        cast(venue_name as varchar)                     as venue_name,
        cast(city as varchar)                           as city,
        cast(state as varchar)                          as state,
        cast(latitude as double)                        as latitude,
        cast(longitude as double)                       as longitude,
        cast(elevation as double)                       as elevation,
        cast(capacity as integer)                       as capacity,
        cast(dome as boolean)                           as is_dome,
        cast(grass as boolean)                          as is_grass,

        -- lineage
        cast(cfb_pull_id as varchar)                    as _pull_id,
        cast(cfb_fetched_at as timestamp)               as _fetched_at
    from source

)

select * from renamed
