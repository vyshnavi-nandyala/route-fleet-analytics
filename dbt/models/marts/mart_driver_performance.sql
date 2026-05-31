{{ config(materialized='table') }}

with daily_stats as (
    select * from {{ ref('int_vehicle_daily_stats') }}
),

vehicles as (
    select * from {{ ref('stg_vehicles') }}
),

monthly as (
    select
        ds.vehicle_id,
        date_trunc('month', ds.event_date)::date              as month,
        avg(ds.avg_speed_mph)                                  as avg_speed,
        avg(ds.idle_pct)                                       as idle_pct,
        sum(ds.total_miles)                                    as total_miles,
        sum(ds.trips_count)                                    as total_trips,
        avg(ds.total_active_mins)                              as avg_active_mins_per_day,
        count(distinct ds.event_date)                          as active_days
    from daily_stats ds
    group by ds.vehicle_id, date_trunc('month', ds.event_date)
),

with_score as (
    select
        m.vehicle_id,
        v.make,
        v.model,
        v.vehicle_class,
        m.month,
        round(m.avg_speed, 2)                                  as avg_speed,
        round(m.idle_pct, 2)                                   as idle_pct,
        round(m.total_miles, 2)                                as total_miles,
        m.total_trips,
        m.active_days,
        round(m.avg_active_mins_per_day, 2)                    as avg_active_mins_per_day,
        -- safety_score: rewards higher speed (up to 45 mph), penalises idling
        round(
            greatest(0,
                least(100,
                    70
                    + (least(m.avg_speed, 45) / 45 * 20)
                    - (m.idle_pct * 0.3)
                )
            ), 2
        )                                                      as safety_score
    from monthly m
    left join vehicles v on m.vehicle_id = v.vehicle_id
)

select * from with_score


