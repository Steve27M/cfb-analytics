-- Grain: one row per team per season (season + team). SP+ ratings. Rename + recast only.
with source as (

    select * from {{ source('bronze', 'ratings_sp') }}

),

renamed as (

    select
        cast(year as integer)                           as season,
        cast(team as varchar)                           as team,
        cast(conference as varchar)                     as conference,

        cast(rating as double)                          as sp_rating,
        cast(ranking as integer)                        as sp_ranking,
        cast(second_order_wins as double)               as second_order_wins,
        cast(sos as double)                             as strength_of_schedule,

        cast(offense_rating as double)                  as offense_rating,
        cast(offense_ranking as integer)                as offense_ranking,
        cast(offense_success as double)                 as offense_success,
        cast(offense_explosiveness as double)           as offense_explosiveness,
        cast(offense_rushing as double)                 as offense_rushing,
        cast(offense_passing as double)                 as offense_passing,
        cast(offense_pace as double)                    as offense_pace,

        cast(defense_rating as double)                  as defense_rating,
        cast(defense_ranking as integer)                as defense_ranking,
        cast(defense_success as double)                 as defense_success,
        cast(defense_explosiveness as double)           as defense_explosiveness,
        cast(defense_rushing as double)                 as defense_rushing,
        cast(defense_passing as double)                 as defense_passing,
        cast(defense_havoc_total as double)             as defense_havoc_total,

        cast(special_teams_rating as double)            as special_teams_rating,

        -- lineage
        cast(cfb_pull_id as varchar)                    as _pull_id,
        cast(cfb_fetched_at as timestamp)               as _fetched_at
    from source

)

select * from renamed
