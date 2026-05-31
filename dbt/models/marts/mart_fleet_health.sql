{{ config(materialized='table') }}

with vehicles as (
    select * from {{ ref('stg_vehicles') }}
),

maintenance as (
    select * from {{ ref('stg_maintenance') }}
),

last_service as (
    select
        vehicle_id,
        max(service_date)                as last_service_date,
        sum(case when date_part('year', service_date) = date_part('year', current_date())
                 then cost_usd else 0 end) as total_cost_ytd,
        count(*)                         as total_service_events
    from maintenance
    group by vehicle_id
),

final as (
    select
        v.vehicle_id,
        v.make,
        v.model,
        v.year,
        v.vehicle_class,
        v.status,
        ls.last_service_date,
        datediff('day', ls.last_service_date, current_date())  as days_since_service,
        round(ls.total_cost_ytd, 2)                            as total_cost_ytd,
        ls.total_service_events,
        case
            when datediff('day', ls.last_service_date, current_date()) > 90 then 'high'
            when datediff('day', ls.last_service_date, current_date()) > 60 then 'medium'
            else 'low'
        end                                                    as maintenance_urgency
    from vehicles v
    left join last_service ls on v.vehicle_id = ls.vehicle_id
)

select * from final


