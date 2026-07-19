from __future__ import annotations

import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import select

from weatherman.analytics import (
    condition_probabilities,
    consensus,
    flat_bet_simulation,
    heat_spike_assessment,
    model_metrics,
    score_frame,
)
from weatherman.db import (
    DailyActual,
    Forecast,
    HourlyForecast,
    Observation,
    Session,
    init_db,
)
from weatherman.service import collect
from weatherman.settings import airports


def local_observations(frame: pd.DataFrame, timezone_name: str, target: date) -> pd.DataFrame:
    if frame.empty:
        return frame
    result = frame.copy()
    result["observed_at"] = pd.to_datetime(result.observed_at, utc=True)
    result["local_at"] = result.observed_at.dt.tz_convert(timezone_name)
    return result[result.local_at.dt.date == target].sort_values("observed_at")


def hourly_context(
    frame: pd.DataFrame, timezone_name: str, target: date
) -> tuple[float | None, float | None, float | None, float | None]:
    if frame.empty:
        return None, None, None, None
    result = frame.copy()
    result["valid_at"] = pd.to_datetime(result.valid_at, utc=True)
    result["run_at"] = pd.to_datetime(result.run_at, utc=True)
    result["local_valid"] = result.valid_at.dt.tz_convert(timezone_name)
    result = result[result.local_valid.dt.date == target]
    if result.empty:
        return None, None, None, None
    result = result.sort_values("run_at").drop_duplicates(["model", "valid_at"], keep="last")
    local_now = datetime.now(ZoneInfo(timezone_name))
    reference = (
        local_now
        if target == local_now.date()
        else datetime(target.year, target.month, target.day, 14, tzinfo=ZoneInfo(timezone_name))
    )
    reference_utc = pd.Timestamp(reference).tz_convert("UTC")
    result["distance"] = (result.valid_at - reference_utc).abs()
    nearest = result.sort_values("distance").drop_duplicates("model", keep="first")

    def median(column: str) -> float | None:
        values = nearest[column].dropna()
        return float(values.median()) if not values.empty else None

    return median("temp_c"), median("cloud_cover"), median("temp_850hpa_c"), median("radiation_wm2")


def model_run_trend(frame: pd.DataFrame, target: date) -> float | None:
    if frame.empty:
        return None
    recent = frame[
        (pd.to_datetime(frame.target_date).dt.date == target)
        & frame.source.isin(["open-meteo", "meteoblue"])
    ].copy()
    if recent.empty:
        return None
    recent["run_at"] = pd.to_datetime(recent.run_at, utc=True)
    changes = []
    for _, model_frame in recent.groupby("model"):
        values = model_frame.sort_values("run_at").max_temp_c.tail(2).tolist()
        if len(values) == 2:
            changes.append(float(values[-1] - values[-2]))
    return float(pd.Series(changes).median()) if changes else None


st.set_page_config(page_title="Weatherman", page_icon="🌡️", layout="wide")
init_db()
catalog = airports()

st.title("Weatherman · Temperature Market Lab")
airport = st.sidebar.selectbox(
    "Airport", list(catalog), format_func=lambda code: f"{code} · {catalog[code]['name']}"
)
target = st.sidebar.date_input("Target date", value=date.today())
if st.sidebar.button("Refresh forecasts + METAR", type="primary"):
    with st.spinner("Fetching models and observations…"):
        result = collect([airport])
    st.sidebar.success(
        f"Saved {result['forecasts']} daily, {result['hourly_forecasts']} hourly forecasts"
    )

with Session() as session:
    forecasts = pd.read_sql(select(Forecast).where(Forecast.airport == airport), session.bind)
    actuals = pd.read_sql(select(DailyActual).where(DailyActual.airport == airport), session.bind)
    observations = pd.read_sql(
        select(Observation).where(Observation.airport == airport), session.bind
    )
    hourly = pd.read_sql(
        select(HourlyForecast).where(HourlyForecast.airport == airport), session.bind
    )

timezone_name = catalog[airport]["timezone"]
d1_forecasts = forecasts[forecasts.horizon == "D-1"].copy() if not forecasts.empty else forecasts
d1_scored = score_frame(d1_forecasts, actuals)
d1_metrics = model_metrics(d1_scored)

tab_live, tab_accuracy, tab_simulation, tab_data = st.tabs(
    ["Live forecast", "Accuracy by timing", "D-1 $1 simulation", "Data coverage"]
)

with tab_live:
    current = (
        forecasts[pd.to_datetime(forecasts.target_date).dt.date == target].copy()
        if not forecasts.empty
        else forecasts
    )
    current = current[current.source.isin(["open-meteo", "meteoblue"])]
    if current.empty:
        st.info("No current forecast stored for this date. Click Refresh forecasts + METAR.")
    else:
        current["run_at"] = pd.to_datetime(current.run_at, utc=True)
        current = current.sort_values("run_at").drop_duplicates("model", keep="last")
        bias_map = dict(zip(d1_metrics.model, d1_metrics.bias)) if not d1_metrics.empty else {}
        current["d1_bias"] = current.model.map(bias_map).fillna(0).astype(float)
        current["corrected_max"] = current.max_temp_c - current.d1_bias
        corrected = consensus(current.max_temp_c.tolist(), current.d1_bias.tolist())

        obs_today = local_observations(observations, timezone_name, target)
        latest_obs = obs_today.iloc[-1] if not obs_today.empty else None
        observed_max = float(obs_today.temp_c.max()) if not obs_today.empty else None
        heating_rate = None
        if len(obs_today) >= 2:
            latest_time = pd.Timestamp(obs_today.observed_at.iloc[-1])
            recent_obs = obs_today[obs_today.observed_at >= latest_time - timedelta(hours=3)]
            elapsed = (
                recent_obs.observed_at.iloc[-1] - recent_obs.observed_at.iloc[0]
            ).total_seconds() / 3600
            if elapsed > 0:
                heating_rate = float(
                    (recent_obs.temp_c.iloc[-1] - recent_obs.temp_c.iloc[0]) / elapsed
                )

        expected_now, cloud_cover, temp_850, radiation = hourly_context(
            hourly, timezone_name, target
        )
        trend = model_run_trend(forecasts, target)
        recent_baseline = None
        if not actuals.empty:
            past = actuals[pd.to_datetime(actuals.target_date).dt.date < target].sort_values(
                "target_date"
            )
            if not past.empty:
                recent_baseline = float(past.max_temp_c.tail(14).median())

        heat = heat_spike_assessment(
            forecast_mean=corrected.mean,
            recent_baseline=recent_baseline,
            run_trend=trend,
            model_spread=corrected.spread,
            observed_temp=float(latest_obs.temp_c) if latest_obs is not None else None,
            observed_dewpoint=(
                float(latest_obs.dewpoint_c)
                if latest_obs is not None and pd.notna(latest_obs.dewpoint_c)
                else None
            ),
            expected_temp_now=expected_now
            if target == datetime.now(ZoneInfo(timezone_name)).date()
            else None,
            heating_rate=heating_rate,
            cloud_cover=cloud_cover,
        )
        nowcast = consensus((current.corrected_max + heat.adjustment_c).tolist())
        minimum_bucket = math.floor(observed_max + 0.5) if observed_max is not None else None
        probabilities = condition_probabilities(nowcast.probability_by_bucket, minimum_bucket)
        live_mean = sum(bucket * probability for bucket, probability in probabilities.items())

        c1, c2, c3 = st.columns(3)
        c1.metric("Raw model mean", f"{current.max_temp_c.mean():.1f} °C")
        c2.metric("D-1 bias-corrected", f"{corrected.mean:.1f} °C")
        c3.metric("METAR-conditioned nowcast", f"{live_mean:.1f} °C")
        c4, c5, c6 = st.columns(3)
        c4.metric("Model spread", f"{corrected.spread:.1f} °C")
        c5.metric(
            "METAR max so far",
            f"{observed_max:.0f} °C" if observed_max is not None else "Not available",
        )
        c6.metric("Heat Spike Score", f"{heat.score}/100", heat.status)

        st.subheader("Model maximum forecasts")
        chart = current[["model", "max_temp_c", "corrected_max"]].melt(
            id_vars="model", var_name="forecast", value_name="temperature_c"
        )
        st.plotly_chart(
            px.bar(
                chart,
                x="model",
                y="temperature_c",
                color="forecast",
                barmode="group",
                labels={"temperature_c": "Max °C", "model": "Model"},
            ),
            width="stretch",
        )

        with st.expander(f"Heat Spike · {heat.status} ({heat.score}/100)", expanded=True):
            for signal in heat.signals:
                st.write(f"• {signal}")
            context = []
            if temp_850 is not None:
                context.append(f"850 hPa: {temp_850:.1f} °C")
            if radiation is not None:
                context.append(f"Radiation: {radiation:.0f} W/m²")
            if context:
                st.caption(" · ".join(context))
            st.caption(
                f"Cautious nowcast adjustment: {heat.adjustment_c:+.1f} °C. "
                "The score will be calibrated per airport as observations accumulate."
            )

        probs = pd.DataFrame(
            [{"bucket": bucket, "probability": value} for bucket, value in probabilities.items()]
        )
        probs = probs[probs.probability >= 0.005]
        st.subheader("METAR-conditioned bucket probabilities")
        st.dataframe(
            probs.assign(
                probability=lambda frame: frame.probability.map(lambda value: f"{value:.1%}")
            ),
            hide_index=True,
            width="stretch",
        )
        if minimum_bucket is not None:
            st.caption(
                f"Buckets below {minimum_bucket} °C are impossible because today's stored METAR "
                f"maximum is already {observed_max:.0f} °C. Remaining probabilities sum to 100%."
            )

with tab_accuracy:
    horizon = st.selectbox("Forecast timing", ["D-1", "D0-morning", "Live"])
    selected = forecasts[forecasts.horizon == horizon] if not forecasts.empty else forecasts
    scored = score_frame(selected, actuals)
    metrics = model_metrics(scored)
    if metrics.empty:
        if horizon == "D-1":
            st.info("Run the v6 historical backfill once to create fixed 24-hour D-1 data.")
        else:
            st.info(f"{horizon} accuracy will populate from newly collected snapshots.")
    else:
        shown = metrics.copy()
        shown["hit_rate"] = shown.hit_rate.map(lambda value: f"{value:.1%}")
        st.dataframe(shown, hide_index=True, width="stretch")
        st.plotly_chart(
            px.bar(metrics, x="model", y="mae", title=f"{horizon} MAE (lower is better)"),
            width="stretch",
        )
        st.caption(
            "D-1 uses forecasts made exactly 24 hours before each valid hour. "
            "D0-morning and Live use only snapshots collected by this project."
        )

with tab_simulation:
    sim = flat_bet_simulation(d1_scored)
    if sim.empty:
        st.info("Run the v6 historical backfill to create the D-1 simulation.")
    else:
        st.metric(
            "Synthetic cumulative P/L",
            f"${sim.pnl.sum():.2f}",
            help="Fixed $1 stakes at synthetic decimal odds 2.0",
        )
        st.plotly_chart(
            px.line(sim, x="target_date", y="cumulative_pnl", title="D-1 cumulative P/L"),
            width="stretch",
        )
        st.caption(
            "Bucket-hit test: D-1 forecasts are corrected only with bias known before each day. "
            "Fixed 2.0 odds are synthetic; this is not yet a real Polymarket ROI calculation."
        )

with tab_data:
    st.write(
        f"Forecast rows: {len(forecasts):,} · Hourly rows: {len(hourly):,} · "
        f"Actual rows: {len(actuals):,} · METAR rows: {len(observations):,}"
    )
    models = catalog[airport]["models"] + ["meteoblue"]
    coverage = pd.DataFrame({"model": models})
    if not d1_forecasts.empty:
        d1_coverage = d1_forecasts.groupby("model", as_index=False).agg(
            d1_days=("target_date", "nunique"),
            d1_first=("target_date", "min"),
            d1_last=("target_date", "max"),
        )
        coverage = coverage.merge(d1_coverage, on="model", how="left")
    if "d1_days" not in coverage:
        coverage["d1_days"] = 0
    else:
        coverage["d1_days"] = coverage.d1_days.fillna(0).astype(int)
    st.subheader("D-1 historical coverage")
    st.dataframe(coverage, hide_index=True, width="stretch")
    if not forecasts.empty:
        st.download_button(
            "Download forecasts CSV",
            forecasts.to_csv(index=False),
            f"{airport}_forecasts.csv",
            "text/csv",
        )
