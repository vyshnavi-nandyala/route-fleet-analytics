{{ config(materialized='table') }}

with segments as (
    select * from {{ ref('int_route_segments') }}
),

daily_route as (
    select
        route_id,
        route_name,
        zone,
        district,
        event_date                                             as segment_date,
        count(distinct vehicle_id)                             as vehicles_on_route,
        avg(speed_mph)                                         as avg_speed,
        sum(segment_distance_miles)                            as total_miles,
        avg(case when idle_flag = 1 then 100.0 else 0.0 end)   as avg_idle_pct,
        count(*)                                               as total_events
    from segments
    group by route_id, route_name, zone, district, event_date
),

with_score as (
    select
        route_id,
        route_name,
        zone,
        district,
        segment_date,
        vehicles_on_route,
        round(avg_speed, 2)                                    as avg_speed,
        round(total_miles, 4)                                  as total_miles,
        round(avg_idle_pct, 2)                                 as avg_idle_pct,
        total_events,
        -- efficiency_score: penalises idling and low average speed
        round(
            greatest(0,
                least(100,
                    100
                    - (avg_idle_pct * 0.5)
                    - (greatest(0, 35 - avg_speed) * 0.3)
                )
            ), 2
        )                                                      as efficiency_score
    from daily_route
)

select * from with_score


