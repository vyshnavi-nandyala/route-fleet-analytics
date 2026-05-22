{{ config(materialized='view') }}

with source as (
    select * from {{ source('raw', 'routes') }}
),

renamed as (
    select
        route_id::varchar          as route_id,
        route_name::varchar        as route_name,
        zone::varchar              as zone,
        district::varchar          as district,
        total_stops::integer       as total_stops,
        created_at::timestamp_ntz  as created_at,
        _loaded_at
    from source
)

select * from renamed
