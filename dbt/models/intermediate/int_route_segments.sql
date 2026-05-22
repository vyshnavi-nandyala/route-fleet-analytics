{{ config(materialized='table') }}

-- Joins GPS events with route metadata and computes per-event derived fields.
-- Haversine distance is approximated between consecutive events per vehicle/route/day.

with gps as (
    select * from {{ ref('stg_gps_events') }}
),

routes as (
    select * from {{ ref('stg_routes') }}
),

gps_with_prev as (
    select
        g.event_id,
        g.vehicle_id,
        g.route_id,
        g.lat,
        g.lon,
        g.speed_mph,
        g.heading_deg,
        g.event_ts,
        g.event_date,
        lag(g.lat)  over (partition by g.vehicle_id, g.route_id, g.event_date order by g.event_ts) as prev_lat,
        lag(g.lon)  over (partition by g.vehicle_id, g.route_id, g.event_date order by g.event_ts) as prev_lon,
        lag(g.event_ts) over (partition by g.vehicle_id, g.route_id, g.event_date order by g.event_ts) as prev_ts
    from gps g
),

with_distance as (
    select
        event_id,
        vehicle_id,
        route_id,
        lat,
        lon,
        speed_mph,
        heading_deg,
        event_ts,
        event_date,
        case
            when prev_lat is null then 0
            else (
                2 * 3958.8 * asin(
                    sqrt(
                        pow(sin(radians((lat - prev_lat) / 2)), 2)
                        + cos(radians(prev_lat)) * cos(radians(lat))
                          * pow(sin(radians((lon - prev_lon) / 2)), 2)
                    )
                )
            )
        end                             as segment_distance_miles,
        case when speed_mph < 5 then 1 else 0 end as idle_flag,
        datediff('second', prev_ts, event_ts) / 60.0 as elapsed_mins
    from gps_with_prev
),

final as (
    select
        d.event_id,
        d.vehicle_id,
        d.route_id,
        r.route_name,
        r.zone,
        r.district,
        d.lat,
        d.lon,
        d.speed_mph,
        d.heading_deg,
        d.event_ts,
        d.event_date,
        d.segment_distance_miles,
        d.idle_flag,
        d.elapsed_mins
    from with_distance d
    left join routes r on d.route_id = r.route_id
)

select * from final
