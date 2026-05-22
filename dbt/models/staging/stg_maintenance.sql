{{ config(materialized='view') }}

with source as (
    select * from {{ source('raw', 'maintenance_logs') }}
),

renamed as (
    select
        log_id::varchar          as log_id,
        vehicle_id::varchar      as vehicle_id,
        service_type::varchar    as service_type,
        service_date::date       as service_date,
        cost_usd::float          as cost_usd,
        mileage_at_service::integer as mileage_at_service,
        technician::varchar      as technician,
        notes::varchar           as notes,
        _loaded_at
    from source
)

select * from renamed
