"""Streamlit dashboard for Route Fleet Analytics."""

from __future__ import annotations

import os
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    layout="wide",
    page_title="Fleet Analytics",
    page_icon="🚛",
    initial_sidebar_state="expanded",
)

# ── Snowflake connection helper ───────────────────────────────────────────────

def _get_snowflake_connection():
    import snowflake.connector
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        database=os.getenv("SNOWFLAKE_DATABASE", "FLEET_ANALYTICS"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "FLEET_WH"),
        schema="GOLD",
    )


@st.cache_data(ttl=600)
def query_snowflake(sql: str) -> pd.DataFrame:
    with _get_snowflake_connection() as conn:
        return pd.read_sql(sql, conn)


# ── Sidebar filters ───────────────────────────────────────────────────────────
st.sidebar.title("Fleet Analytics")
st.sidebar.markdown("---")

today = date.today()
default_start = today - timedelta(days=30)

date_range = st.sidebar.date_input(
    "Date range",
    value=(default_start, today),
    min_value=today - timedelta(days=365),
    max_value=today,
)
start_date = date_range[0] if len(date_range) == 2 else default_start
end_date = date_range[1] if len(date_range) == 2 else today

@st.cache_data(ttl=3600)
def load_route_options() -> list[str]:
    df = query_snowflake("SELECT DISTINCT route_id FROM FLEET_ANALYTICS.GOLD.MART_ROUTE_EFFICIENCY ORDER BY 1")
    return df["ROUTE_ID"].tolist() if not df.empty else []

@st.cache_data(ttl=3600)
def load_vehicle_class_options() -> list[str]:
    return ["light", "medium", "heavy"]

all_routes = load_route_options()
selected_routes = st.sidebar.multiselect(
    "Routes", options=all_routes, default=all_routes[:5] if all_routes else []
)
selected_classes = st.sidebar.multiselect(
    "Vehicle class", options=load_vehicle_class_options(), default=load_vehicle_class_options()
)

route_filter = (
    f"AND route_id IN ({','.join(repr(r) for r in selected_routes)})"
    if selected_routes else ""
)
class_filter = (
    f"AND vehicle_class IN ({','.join(repr(c) for c in selected_classes)})"
    if selected_classes else ""
)

# ── Data loaders ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=600)
def load_efficiency(start: date, end: date, rf: str) -> pd.DataFrame:
    sql = f"""
        SELECT segment_date, route_id, zone, avg_speed, avg_idle_pct,
               total_miles, vehicles_on_route, efficiency_score
        FROM FLEET_ANALYTICS.GOLD.MART_ROUTE_EFFICIENCY
        WHERE segment_date BETWEEN '{start}' AND '{end}'
        {rf}
        ORDER BY segment_date
    """
    return query_snowflake(sql)


@st.cache_data(ttl=600)
def load_fleet_health(cf: str) -> pd.DataFrame:
    sql = f"""
        SELECT vehicle_id, make, model, vehicle_class, status,
               last_service_date, days_since_service,
               total_cost_ytd, maintenance_urgency
        FROM FLEET_ANALYTICS.GOLD.MART_FLEET_HEALTH
        WHERE 1=1 {cf}
        ORDER BY days_since_service DESC
    """
    return query_snowflake(sql)


# ── Main content ──────────────────────────────────────────────────────────────
st.title("🚛 Route Fleet Analytics Dashboard")

eff_df = load_efficiency(start_date, end_date, route_filter)
health_df = load_fleet_health(class_filter)

# ── Row 1: KPI metrics ────────────────────────────────────────────────────────
st.markdown("### Key Performance Indicators")
kpi1, kpi2, kpi3, kpi4 = st.columns(4)

active_routes = eff_df["ROUTE_ID"].nunique() if not eff_df.empty else 0
avg_speed = round(eff_df["AVG_SPEED"].mean(), 1) if not eff_df.empty else 0.0

total_vehicles = len(health_df) if not health_df.empty else 0
active_vehicles = len(health_df[health_df["STATUS"] == "active"]) if not health_df.empty else 0
fleet_utilisation = round(active_vehicles / total_vehicles * 100, 1) if total_vehicles > 0 else 0.0

maintenance_alerts = (
    len(health_df[health_df["MAINTENANCE_URGENCY"].isin(["medium", "high"])])
    if not health_df.empty else 0
)

kpi1.metric("Active Routes", active_routes)
kpi2.metric("Avg Speed (mph)", f"{avg_speed}")
kpi3.metric("Fleet Utilisation", f"{fleet_utilisation}%")
kpi4.metric("Maintenance Alerts", maintenance_alerts, delta=None)

st.markdown("---")

# ── Row 2: Time-series chart ───────────────────────────────────────────────────
st.markdown("### Speed & Idle Trend by Route")

if not eff_df.empty:
    chart_df = (
        eff_df.groupby("SEGMENT_DATE")[["AVG_SPEED", "AVG_IDLE_PCT"]]
        .mean()
        .reset_index()
    )
    fig_ts = go.Figure()
    fig_ts.add_trace(go.Scatter(
        x=chart_df["SEGMENT_DATE"], y=chart_df["AVG_SPEED"],
        name="Avg Speed (mph)", mode="lines+markers", line=dict(color="#1f77b4"),
    ))
    fig_ts.add_trace(go.Scatter(
        x=chart_df["SEGMENT_DATE"], y=chart_df["AVG_IDLE_PCT"],
        name="Idle %", mode="lines+markers", line=dict(color="#ff7f0e"), yaxis="y2",
    ))
    fig_ts.update_layout(
        yaxis=dict(title="Avg Speed (mph)"),
        yaxis2=dict(title="Idle %", overlaying="y", side="right"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        hovermode="x unified",
        height=350,
    )
    st.plotly_chart(fig_ts, use_container_width=True)
else:
    st.info("No efficiency data for the selected filters.")

st.markdown("---")

# ── Row 3: Fleet health heatmap ───────────────────────────────────────────────
st.markdown("### Fleet Health Overview")

if not health_df.empty:
    col_left, col_right = st.columns([2, 1])

    with col_left:
        urgency_order = ["low", "medium", "high"]
        urgency_colors = {"low": "#2ecc71", "medium": "#f39c12", "high": "#e74c3c"}
        urgency_counts = (
            health_df["MAINTENANCE_URGENCY"]
            .value_counts()
            .reindex(urgency_order, fill_value=0)
            .reset_index()
        )
        urgency_counts.columns = ["urgency", "count"]
        fig_bar = px.bar(
            urgency_counts,
            x="urgency", y="count",
            color="urgency",
            color_discrete_map=urgency_colors,
            title="Vehicles by Maintenance Urgency",
        )
        fig_bar.update_layout(showlegend=False, height=300)
        st.plotly_chart(fig_bar, use_container_width=True)

    with col_right:
        st.markdown("**Top vehicles needing service**")
        urgent = health_df[health_df["MAINTENANCE_URGENCY"] == "high"][
            ["VEHICLE_ID", "MAKE", "MODEL", "DAYS_SINCE_SERVICE", "MAINTENANCE_URGENCY"]
        ].head(10)
        st.dataframe(urgent, hide_index=True, use_container_width=True)

    st.markdown("**Full Fleet Health Table**")
    display_cols = [
        "VEHICLE_ID", "MAKE", "MODEL", "VEHICLE_CLASS", "STATUS",
        "LAST_SERVICE_DATE", "DAYS_SINCE_SERVICE", "TOTAL_COST_YTD", "MAINTENANCE_URGENCY"
    ]
    st.dataframe(
        health_df[[c for c in display_cols if c in health_df.columns]],
        hide_index=True,
        use_container_width=True,
    )
else:
    st.info("No fleet health data available.")

st.markdown("---")

# ── Row 4: Cortex NLP query box ───────────────────────────────────────────────
st.markdown("### Ask a Question (Cortex Analyst)")
st.caption("Powered by Snowflake Cortex Analyst — ask in plain English")

question = st.text_input(
    "Your question",
    placeholder="e.g. Which routes had the highest idle time last week?",
)

if question:
    with st.spinner("Querying Cortex Analyst..."):
        try:
            import sys
            sys.path.insert(0, str(os.path.join(os.path.dirname(__file__), "..", "cortex")))
            from query_client import CortexAnalystClient

            client = CortexAnalystClient()
            result = client.ask(question)

            if result.fallback or result.error:
                st.warning(result.error or "Cortex returned no result.")
            else:
                st.success(f"Confidence: {result.confidence:.0%}")
                if not result.df.empty:
                    st.dataframe(result.df, use_container_width=True)
                else:
                    st.info("Query returned no rows.")

            with st.expander("Generated SQL"):
                st.code(result.sql or "— no SQL generated —", language="sql")

        except Exception as exc:
            st.error(f"Error: {exc}")
            with st.expander("Details"):
                st.exception(exc)
