{{ config(materialized='table') }}

with segments as (
    select * from {{ ref('int_route_segments') }}
),

daily as (
    select
        vehicle_id,
        event_date,
        count(distinct route_id)                               as trips_count,
        sum(segment_distance_miles)                            as total_miles,
        avg(speed_mph)                                         as avg_speed_mph,
        sum(case when idle_flag = 1 then elapsed_mins else 0 end) as total_idle_mins,
        sum(elapsed_mins)                                      as total_active_mins,
        count(*)                                               as event_count
    from segments
    group by vehicle_id, event_date
),

final as (
    select
        vehicle_id,
        event_date,
        trips_count,
        round(total_miles, 4)                                  as total_miles,
        round(avg_speed_mph, 2)                                as avg_speed_mph,
        round(total_idle_mins, 2)                              as total_idle_mins,
        round(total_active_mins, 2)                            as total_active_mins,
        round(
            case
                when total_active_mins > 0
                then total_idle_mins / total_active_mins * 100
                else 0
            end, 2
        )                                                      as idle_pct,
        event_count
    from daily
)

select * from final

