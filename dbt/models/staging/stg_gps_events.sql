{{ config(materialized='view') }}

with source as (
    select * from {{ source('raw', 'gps_events') }}
),

renamed as (
    select
        event_id::varchar           as event_id,
        vehicle_id::varchar         as vehicle_id,
        route_id::varchar           as route_id,
        lat::float                  as lat,
        lon::float                  as lon,
        speed_mph::float            as speed_mph,
        heading_deg::integer        as heading_deg,
        event_ts::timestamp_ntz     as event_ts,
        event_date::date            as event_date,
        _loaded_at
    from source
    where lat between 29.5 and 30.1
      and lon between -95.8 and -95.1
)

select * from renamed


