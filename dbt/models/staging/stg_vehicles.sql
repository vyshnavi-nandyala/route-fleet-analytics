{{ config(materialized='view') }}

with source as (
    select * from {{ source('raw', 'vehicles') }}
),

renamed as (
    select
        vehicle_id::varchar    as vehicle_id,
        make::varchar          as make,
        model::varchar         as model,
        year::integer          as year,
        vehicle_class::varchar as vehicle_class,
        status::varchar        as status,
        vin::varchar           as vin,
        license_plate::varchar as license_plate,
        _loaded_at
    from source
)

select * from renamed


