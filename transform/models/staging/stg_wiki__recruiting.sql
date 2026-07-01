-- Grain: one row per team per season (team + season). Team recruiting-class rankings scraped
-- from Wikipedia (247Sports / Rivals / On3). Rename + recast only; the one team-name mismatch
-- vs the warehouse ("Miami (FL)" -> "Miami") is conformed here so it joins to ratings/games.
with source as (

    select * from {{ source('bronze', 'recruiting') }}

),

renamed as (

    select
        case when trim(school) = 'Miami (FL)' then 'Miami' else trim(school) end as team,
        cast(cfb_season as integer)                     as season,
        cast(rank_247 as integer)                       as recruiting_rank_247,
        cast(rank_rivals as integer)                    as recruiting_rank_rivals,
        cast(rank_on3 as integer)                       as recruiting_rank_on3,

        -- lineage
        cast(cfb_pull_id as varchar)                    as _pull_id,
        cast(cfb_fetched_at as timestamp)               as _fetched_at
    from source

)

select * from renamed
