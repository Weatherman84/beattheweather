from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import select

from weatherman.analytics import consensus, flat_bet_simulation, model_metrics, score_frame
from weatherman.db import DailyActual, Forecast, Observation, Session, init_db
from weatherman.service import collect
from weatherman.settings import airports

st.set_page_config(page_title="Weatherman", page_icon="🌡️", layout="wide")
init_db()
catalog = airports()

st.title("Weatherman · Temperature Market Lab")
airport = st.sidebar.selectbox(
    "Airport", list(catalog), format_func=lambda x: f"{x} · {catalog[x]['name']}"
)
target = st.sidebar.date_input("Target date", value=date.today())
if st.sidebar.button("Refresh forecasts + METAR", type="primary"):
    with st.spinner("Fetching models and observation…"):
        result = collect([airport])
    st.sidebar.success(f"Saved {result['forecasts']} forecasts")

with Session() as session:
    forecasts = pd.read_sql(select(Forecast).where(Forecast.airport == airport), session.bind)
    actuals = pd.read_sql(select(DailyActual).where(DailyActual.airport == airport), session.bind)
    observations = pd.read_sql(
        select(Observation).where(Observation.airport == airport), session.bind
    )

tab_live, tab_accuracy, tab_simulation, tab_data = st.tabs(
    ["Live forecast", "Accuracy", "$1 simulation", "Data"]
)

with tab_live:
    current = (
        forecasts[pd.to_datetime(forecasts.target_date).dt.date == target].copy()
        if not forecasts.empty
        else forecasts
    )
    if current.empty:
        st.info("No forecast stored for this date. Click Refresh forecasts + METAR.")
    else:
        current["run_at"] = pd.to_datetime(current.run_at, utc=True)
        current = current.sort_values("run_at").drop_duplicates("model", keep="last")
        scored = score_frame(forecasts, actuals)
        metrics = model_metrics(scored)
        bias_map = dict(zip(metrics.model, metrics.bias)) if not metrics.empty else {}
        biases = [float(bias_map.get(model, 0)) for model in current.model]
        con = consensus(current.max_temp_c.tolist(), biases)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Bias-corrected consensus", f"{con.mean:.1f} °C")
        c2.metric("Median", f"{con.median:.1f} °C")
        c3.metric("Model spread", f"{con.spread:.1f} °C")
        if not observations.empty:
            latest = observations.sort_values("observed_at").iloc[-1]
            c4.metric("Latest METAR", f"{latest.temp_c:.0f} °C")
        chart = current[["model", "max_temp_c"]].sort_values("max_temp_c")
        st.plotly_chart(
            px.bar(
                chart, x="model", y="max_temp_c", labels={"max_temp_c": "Max °C", "model": "Model"}
            ),
            use_container_width=True,
        )
        probs = pd.DataFrame(
            [{"bucket": k, "probability": v} for k, v in con.probability_by_bucket.items()]
        )
        probs = probs[probs.probability >= 0.005]
        st.subheader("Fair bucket probabilities")
        st.dataframe(
            probs.assign(probability=lambda x: x.probability.map(lambda v: f"{v:.1%}")),
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            "Probabilities are a calibrated normal approximation from bias-corrected model spread—not financial advice."
        )

with tab_accuracy:
    scored = score_frame(forecasts, actuals)
    metrics = model_metrics(scored)
    if metrics.empty:
        st.info("Run the historical backfill first: `weatherman backfill --days 365`.")
    else:
        shown = metrics.copy()
        shown["hit_rate"] = shown.hit_rate.map(lambda x: f"{x:.1%}")
        st.dataframe(shown, hide_index=True, use_container_width=True)
        st.plotly_chart(
            px.bar(metrics, x="model", y="mae", title="Mean absolute error (lower is better)"),
            use_container_width=True,
        )

with tab_simulation:
    scored = score_frame(forecasts, actuals)
    sim = flat_bet_simulation(scored)
    if sim.empty:
        st.info("Backfill data is needed for the simulation.")
    else:
        st.metric(
            "Synthetic cumulative P/L",
            f"${sim.pnl.sum():.2f}",
            help="Fixed $1 stakes at synthetic decimal odds 2.0",
        )
        st.plotly_chart(
            px.line(sim, x="target_date", y="cumulative_pnl", title="Cumulative P/L"),
            use_container_width=True,
        )
        st.caption(
            "This is a model test with fixed synthetic odds. Real profitability requires stored market prices."
        )

with tab_data:
    st.write(
        f"Forecast rows: {len(forecasts):,} · Actual rows: {len(actuals):,} · METAR rows: {len(observations):,}"
    )
    if not forecasts.empty:
        st.download_button(
            "Download forecasts CSV",
            forecasts.to_csv(index=False),
            f"{airport}_forecasts.csv",
            "text/csv",
        )
