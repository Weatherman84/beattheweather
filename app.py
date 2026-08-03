from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from runtime_bootstrap import discard_stale_weatherman_modules

discard_stale_weatherman_modules("10.5.2")

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import func, select

from weatherman.analytics import (
    detect_market_model_conflict,
    fixed_decision_snapshots,
    flat_bet_simulation,
    forecast_ladder_frame,
    forecast_scorecards,
    historical_d1_ladder,
    market_edges,
    model_metrics,
    preferred_station_actuals,
    score_frame,
)
from weatherman.db import (
    BasketSnapshot,
    DailyActual,
    Forecast,
    ForecastSnapshot,
    ForecastVariantSnapshot,
    HourlyForecast,
    MarketSnapshot,
    Observation,
    RegimeMemorySnapshot,
    Session,
    ShadowEvaluation,
    SignalSnapshot,
    StrategySnapshot,
    TafReport,
    init_db,
    refresh_database_connections,
)
from weatherman.decision import (
    balanced_hedge_plan,
    build_trade_decision,
    hedge_outcome_table,
    latest_prior_probabilities,
)
from weatherman.nowcast import build_live_nowcast
from weatherman.regime_memory import enrich_nowcast_with_regime_memory
from weatherman.navigation import render_app_navigation
from weatherman.live_ui import render_compact_live_forecast
from weatherman.research import filter_target_window, market_timing_metrics
from weatherman.service import collect, collect_live_aviation
from weatherman.catalog import trading_airports
from weatherman.settings import settings
from weatherman.taf import taf_verification_frame, taf_verification_metrics


def last_update(frame: pd.DataFrame, column: str, timezone_name: str) -> str:
    if frame.empty or column not in frame:
        return "not available"
    values = pd.to_datetime(frame[column], utc=True, errors="coerce").dropna()
    if values.empty:
        return "not available"
    latest = values.max().tz_convert(timezone_name)
    return latest.strftime("%d.%m.%Y %H:%M")


def latest_metar_time(airport_code: str) -> datetime | None:
    with Session() as session:
        return session.scalar(
            select(func.max(Observation.observed_at)).where(Observation.airport == airport_code)
        )


def latest_taf_time(airport_code: str) -> datetime | None:
    with Session() as session:
        return session.scalar(
            select(func.max(TafReport.issue_time)).where(TafReport.airport == airport_code)
        )


def utc_timestamp(value: datetime | None) -> pd.Timestamp | None:
    if value is None:
        return None
    parsed = pd.Timestamp(value)
    return parsed.tz_localize("UTC") if parsed.tzinfo is None else parsed.tz_convert("UTC")


def critical_window_labels(airport_details: dict, target_date) -> tuple[str, str] | None:
    configured = airport_details.get("critical_window_local")
    if not isinstance(configured, (list, tuple)) or len(configured) != 2:
        return None
    airport_zone = ZoneInfo(airport_details["timezone"])
    vienna_zone = ZoneInfo("Europe/Vienna")
    local_times = []
    vienna_times = []
    for value in configured:
        hour, minute = (int(part) for part in str(value).split(":", maxsplit=1))
        local = datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            hour,
            minute,
            tzinfo=airport_zone,
        )
        local_times.append(local.strftime("%H:%M"))
        vienna_times.append(local.astimezone(vienna_zone).strftime("%H:%M"))
    return "–".join(local_times), "–".join(vienna_times)


@st.cache_data(show_spinner=False, ttl=900)
def cached_forecast_scorecards(
    forecast_frame: pd.DataFrame, actual_frame: pd.DataFrame
) -> pd.DataFrame:
    return forecast_scorecards(forecast_frame, actual_frame)


@st.cache_data(show_spinner=False, ttl=900)
def cached_airport_timing_metrics(
    forecast_frame: pd.DataFrame,
    actual_frame: pd.DataFrame,
    observation_frame: pd.DataFrame,
    snapshot_frame: pd.DataFrame,
    airport_code: str,
    airport_details: dict,
    window_days: int,
) -> pd.DataFrame:
    timezone_map = {airport_code: airport_details["timezone"]}
    airport_catalog = {airport_code: airport_details}
    station_actuals = preferred_station_actuals(
        observation_frame,
        actual_frame,
        timezone_map,
    )
    historical_scored = filter_target_window(
        historical_d1_ladder(forecast_frame, station_actuals),
        window_days,
    )
    fixed = fixed_decision_snapshots(snapshot_frame, timezone_map)
    fixed_scored = filter_target_window(
        forecast_ladder_frame(fixed, station_actuals),
        window_days,
    )
    live_scored = filter_target_window(
        forecast_ladder_frame(snapshot_frame, station_actuals),
        window_days,
    )
    if not live_scored.empty:
        live_scored = live_scored[live_scored.lead_bucket.str.startswith("D0 live", na=False)]
    return pd.concat(
        [
            market_timing_metrics(historical_scored, airport_catalog),
            market_timing_metrics(fixed_scored, airport_catalog),
            market_timing_metrics(live_scored, airport_catalog),
        ],
        ignore_index=True,
    )


st.set_page_config(page_title="Weatherman · Trading Desk", page_icon="🌡️", layout="wide")
# A GitHub workflow can replace the SQLite file while Streamlit is still alive.
# Reopening pooled handles on every rerun makes that new snapshot visible without
# requiring the user to reboot the whole app.
refresh_database_connections()
init_db()
catalog = trading_airports()

render_app_navigation(st)
st.title("Weatherman · Trading Desk")
airport = st.sidebar.selectbox(
    "Airport", list(catalog), format_func=lambda code: f"{code} · {catalog[code]['name']}"
)
timezone_name = catalog[airport]["timezone"]
target = st.sidebar.date_input("Target date", value=datetime.now(ZoneInfo(timezone_name)).date())
critical_window = critical_window_labels(catalog[airport], target)
if critical_window is not None:
    st.sidebar.caption(
        f"Critical window · {critical_window[0]} airport local · {critical_window[1]} Austria"
    )


@st.fragment(run_every=60)
def live_aviation_poller() -> None:
    """Poll the primary aviation feed without rerunning expensive model collection."""
    now = datetime.now(timezone.utc)
    poll_key = f"live_poll_at_{airport}"
    taf_key = f"live_taf_poll_at_{airport}"
    detection_key = f"metar_detected_at_{airport}"
    last_poll = st.session_state.get(poll_key)
    should_poll = last_poll is None or now - last_poll >= timedelta(seconds=55)
    if should_poll:
        before_metar = utc_timestamp(latest_metar_time(airport))
        before_taf = utc_timestamp(latest_taf_time(airport))
        last_taf_poll = st.session_state.get(taf_key)
        include_taf = last_taf_poll is None or now - last_taf_poll >= timedelta(minutes=10)
        try:
            collect_live_aviation(airport, include_taf=include_taf)
        except Exception as exc:
            st.session_state[f"live_poll_error_{airport}"] = (
                f"Live aviation check failed ({type(exc).__name__}); retrying automatically."
            )
        else:
            refresh_database_connections()
            after_metar = utc_timestamp(latest_metar_time(airport))
            after_taf = utc_timestamp(latest_taf_time(airport))
            st.session_state.pop(f"live_poll_error_{airport}", None)
            st.session_state[poll_key] = now
            if include_taf:
                st.session_state[taf_key] = now
            metar_advanced = after_metar is not None and (
                before_metar is None or after_metar > before_metar
            )
            taf_advanced = after_taf is not None and (before_taf is None or after_taf > before_taf)
            if metar_advanced:
                st.session_state[detection_key] = now
            if metar_advanced or taf_advanced:
                st.cache_data.clear()
                st.rerun(scope="app")

    checked_at = st.session_state.get(poll_key)
    if checked_at is not None:
        checked_local = checked_at.astimezone(ZoneInfo(timezone_name))
        detected_at = st.session_state.get(detection_key)
        status = f"Live feed checked {checked_local:%H:%M:%S}"
        if detected_at is not None:
            detected_local = detected_at.astimezone(ZoneInfo(timezone_name))
            status += f" · newest METAR detected {detected_local:%H:%M:%S}"
        st.sidebar.caption(status)
    error = st.session_state.get(f"live_poll_error_{airport}")
    if error:
        st.sidebar.warning(error)


live_aviation_poller()
refresh_feedback = st.session_state.pop("refresh_feedback", None)
if refresh_feedback:
    level, message = refresh_feedback
    if level == "success":
        st.sidebar.success(message)
    else:
        st.sidebar.warning(message)

if st.sidebar.button("Refresh forecasts + METAR + TAF", type="primary"):
    before_metar = utc_timestamp(latest_metar_time(airport))
    try:
        with st.spinner("Fetching models, METAR, TAF and market data…"):
            result = collect([airport])
    except Exception as exc:
        st.sidebar.error(
            f"Refresh failed ({type(exc).__name__}). The dashboard remains usable; "
            "the full cause is available in the Streamlit log."
        )
    else:
        # Force a new file handle and a clean Streamlit run. This fixes both a
        # replaced SQLite snapshot and calculations cached from the prior METAR.
        refresh_database_connections()
        init_db()
        after_metar = utc_timestamp(latest_metar_time(airport))
        st.cache_data.clear()
        saved = (
            f"Saved {result['forecasts']} daily forecasts, "
            f"{result['taf_reports']} TAF report(s) and "
            f"{result['market_prices']} market prices."
        )
        if after_metar is not None and (before_metar is None or after_metar > before_metar):
            local_metar = after_metar.tz_convert(timezone_name).strftime("%d.%m.%Y %H:%M")
            feedback = ("success", f"{saved} METAR advanced to {local_metar}.")
        elif after_metar is not None:
            local_metar = after_metar.tz_convert(timezone_name).strftime("%d.%m.%Y %H:%M")
            feedback = (
                "warning",
                f"{saved} The aviation feed returned no newer METAR; the latest remains "
                f"{local_metar}. The displayed data was reloaded.",
            )
        else:
            feedback = (
                "warning",
                f"{saved} No usable METAR was returned. The displayed data was reloaded.",
            )
        st.session_state["refresh_feedback"] = feedback
        st.rerun()

with Session() as session:
    all_forecasts = pd.read_sql(select(Forecast).where(Forecast.airport == airport), session.bind)
    all_actuals = pd.read_sql(
        select(DailyActual).where(DailyActual.airport == airport), session.bind
    )
    all_observations = pd.read_sql(
        select(Observation).where(Observation.airport == airport), session.bind
    )
    hourly = pd.read_sql(
        select(HourlyForecast).where(HourlyForecast.airport == airport), session.bind
    )
    all_market_snapshots = pd.read_sql(
        select(MarketSnapshot).where(MarketSnapshot.airport == airport), session.bind
    )
    all_signal_snapshots = pd.read_sql(
        select(SignalSnapshot).where(SignalSnapshot.airport == airport), session.bind
    )
    all_strategy_snapshots = pd.read_sql(
        select(StrategySnapshot).where(StrategySnapshot.airport == airport), session.bind
    )
    all_shadow_evaluations = pd.read_sql(
        select(ShadowEvaluation).where(ShadowEvaluation.airport == airport),
        session.bind,
    )
    all_basket_snapshots = pd.read_sql(
        select(BasketSnapshot).where(BasketSnapshot.airport == airport),
        session.bind,
    )
    all_forecast_snapshots = pd.read_sql(
        select(ForecastSnapshot).where(ForecastSnapshot.airport == airport),
        session.bind,
    )
    all_forecast_variants = pd.read_sql(
        select(ForecastVariantSnapshot).where(
            ForecastVariantSnapshot.airport == airport
        ),
        session.bind,
    )
    all_regime_memory_snapshots = pd.read_sql(
        select(RegimeMemorySnapshot).where(
            RegimeMemorySnapshot.airport == airport
        ),
        session.bind,
    )
    all_tafs = pd.read_sql(select(TafReport).where(TafReport.airport == airport), session.bind)

forecasts = (
    all_forecasts[all_forecasts.airport == airport].copy()
    if not all_forecasts.empty
    else all_forecasts
)
actuals = (
    all_actuals[all_actuals.airport == airport].copy() if not all_actuals.empty else all_actuals
)
observations = (
    all_observations[all_observations.airport == airport].copy()
    if not all_observations.empty
    else all_observations
)
market_snapshots = (
    all_market_snapshots[all_market_snapshots.airport == airport].copy()
    if not all_market_snapshots.empty
    else all_market_snapshots
)
signal_snapshots = (
    all_signal_snapshots[all_signal_snapshots.airport == airport].copy()
    if not all_signal_snapshots.empty
    else all_signal_snapshots
)
strategy_snapshots = (
    all_strategy_snapshots[all_strategy_snapshots.airport == airport].copy()
    if not all_strategy_snapshots.empty
    else all_strategy_snapshots
)
shadow_evaluations = (
    all_shadow_evaluations[all_shadow_evaluations.airport == airport].copy()
    if not all_shadow_evaluations.empty
    else all_shadow_evaluations
)
basket_snapshots = (
    all_basket_snapshots[all_basket_snapshots.airport == airport].copy()
    if not all_basket_snapshots.empty
    else all_basket_snapshots
)
tafs = all_tafs[all_tafs.airport == airport].copy() if not all_tafs.empty else all_tafs

target_markets = (
    market_snapshots[pd.to_datetime(market_snapshots.target_date).dt.date == target].copy()
    if not market_snapshots.empty
    else market_snapshots
)
if not target_markets.empty:
    target_markets["captured_at"] = pd.to_datetime(target_markets.captured_at, utc=True)
    latest_markets = target_markets.sort_values("captured_at").drop_duplicates(
        "market_id", keep="last"
    )
else:
    latest_markets = target_markets
d1_forecasts = forecasts[forecasts.horizon == "D-1"].copy() if not forecasts.empty else forecasts
d1_scored = score_frame(d1_forecasts, actuals)
# Cross-airport scoring is intentionally deferred to the Airport Research page.
# Keeping placeholders makes the former tab implementation below import-safe while
# st.stop() prevents it from being rendered on the Trading Desk.
settled_performance = pd.DataFrame()
probability_comparison = pd.DataFrame()
trade_scorecards = pd.DataFrame()
station_actuals = pd.DataFrame()
airport_station_actuals = pd.DataFrame()
d1_scored = pd.DataFrame()
airport_forecast_scorecards = pd.DataFrame()
ladder_metrics = pd.DataFrame()
historical_ladder = pd.DataFrame()
historical_ladder_metrics = pd.DataFrame()
factor_diagnostics = pd.DataFrame()
strategy_performance = pd.DataFrame()
historical_price_performance = pd.DataFrame()

st.caption(
    f"Last data update · Forecast: {last_update(forecasts, 'run_at', timezone_name)} · "
    f"METAR: {last_update(observations, 'observed_at', timezone_name)} · "
    f"TAF: {last_update(tafs, 'issue_time', timezone_name)} · "
        f"Polymarket: {last_update(market_snapshots, 'captured_at', timezone_name)} · "
        f"Shadow: {last_update(shadow_evaluations, 'captured_at', timezone_name)} "
        f"({timezone_name} local time)"
    )

tab_live, tab_market, tab_shadow, tab_accuracy = st.tabs(
    ["Live forecast", "Market comparison", "Shadow watcher", "Accuracy by timing"]
)
tab_performance = tab_airports = tab_simulation = tab_data = None

probabilities: dict[int, float] | None = None
day_status = None
trade_decision = None
prior_probabilities: dict[str, float] = {}
with tab_live:
    live_as_of = datetime.now(ZoneInfo("UTC"))
    live_nowcast = build_live_nowcast(
        forecasts=forecasts,
        actuals=actuals,
        observations=observations,
        hourly=hourly,
        markets=latest_markets,
        tafs=tafs,
        timezone_name=timezone_name,
        target=target,
        as_of=live_as_of,
        wind_profile=catalog[airport].get("heat_wind_profile"),
        routine_metar_minutes=catalog[airport].get("metar_minutes"),
        pre_metar_guard_minutes=catalog[airport].get(
            "pre_metar_guard_minutes", 7
        ),
        critical_window_local=catalog[airport].get("critical_window_local"),
        post_convective_profile=catalog[airport].get(
            "post_convective_uncertainty"
        ),
        heat_regime_profile=catalog[airport].get("heat_regime"),
        phase_amplitude_profile=catalog[airport].get("phase_vs_amplitude"),
        maritime_advection_profile=catalog[airport].get("maritime_advection"),
        maritime_low_range_profile=catalog[airport].get("maritime_low_range"),
        live_adjustment_guardrails=catalog[airport].get(
            "live_adjustment_guardrails"
        ),
        recent_warm_bias_profile=catalog[airport].get(
            "recent_warm_bias_challenger"
        ),
        future_reheating_profile=catalog[airport].get("future_reheating"),
        maximum_model_age_minutes=settings.maximum_live_model_age_minutes,
    )
    memory_config = dict(catalog[airport].get("regime_memory") or {})
    memory_config.setdefault(
        "allow_promoted",
        settings.regime_memory_allow_promoted,
    )
    memory_config.setdefault(
        "minimum_oos_days",
        settings.regime_memory_minimum_oos_days,
    )
    live_nowcast = enrich_nowcast_with_regime_memory(
        live_nowcast,
        all_forecast_snapshots,
        actuals,
        observations,
        all_forecast_variants,
        airport_profile=catalog[airport],
        timezone_name=timezone_name,
        target=target,
        as_of=live_as_of,
        config=memory_config,
    )
    if live_nowcast is None:
        st.info("No current forecast stored for this date. Click Refresh forecasts + METAR + TAF.")
    else:
        current = live_nowcast.current
        corrected = live_nowcast.corrected
        heat = live_nowcast.heat
        day_status = live_nowcast.day_status
        probabilities = live_nowcast.probabilities
        observed_max = live_nowcast.observed_max
        remaining_rise = live_nowcast.remaining_rise_c
        temp_850 = live_nowcast.temp_850_c
        radiation = live_nowcast.radiation_wm2
        live_mean = live_nowcast.final_forecast_mean
        prior_probabilities = latest_prior_probabilities(signal_snapshots, target)
        current_market_conflict = detect_market_model_conflict(
            probabilities,
            latest_markets,
        )
        material_adjustments = {
            name: value
            for name, value in live_nowcast.adjustment_contributions.items()
            if name != "total" and abs(value) >= 0.05
        }
        strongest_live_signals = [
            f"{name.replace('_', ' ').title()} {value:+.2f} °C"
            for name, value in sorted(
                material_adjustments.items(),
                key=lambda item: abs(item[1]),
                reverse=True,
            )[:3]
        ]
        trade_decision = build_trade_decision(
            probabilities=probabilities,
            markets=latest_markets,
            forecast_confidence=live_nowcast.forecast_confidence,
            day_status=day_status,
            metar_pending=live_nowcast.metar_pending,
            market_model_conflict=current_market_conflict.is_conflict,
            forecast_stale=live_nowcast.forecast_data_stale,
            previous_probabilities=prior_probabilities,
            live_signals=strongest_live_signals,
            recommendations_enabled=settings.edge_recommendations_enabled,
        )

        if live_nowcast.forecast_data_stale:
            st.error(
                "MODEL DATA STALE – do not trade. Fewer than two model feeds were fetched "
                f"within the last {settings.maximum_live_model_age_minutes} minutes. "
                "BET and SHADOW BET are blocked until fresh models arrive."
            )
        elif live_nowcast.stale_models:
            st.warning(
                "Stale model feed(s) omitted from the live consensus: "
                + ", ".join(live_nowcast.stale_models)
                + "."
            )

        if live_nowcast.metar_pending:
            due_local = (
                pd.Timestamp(live_nowcast.metar_due_at).tz_convert(timezone_name)
                if live_nowcast.metar_due_at is not None
                else None
            )
            due_text = f" for {due_local:%H:%M}" if due_local is not None else ""
            st.error(
                f"METAR guard{due_text} – do not trade. A routine report is imminent or "
                "due and has not reached the official feed. Edge signals are blocked."
            )

        render_compact_live_forecast(
            st,
            nowcast=live_nowcast,
            trade_decision=trade_decision,
            latest_markets=latest_markets,
            prior_probabilities=prior_probabilities,
            target=target,
            timezone_name=timezone_name,
            actuals=actuals,
            regime_memory_snapshots=all_regime_memory_snapshots,
        )

        # The previous table-heavy renderer remains below for one release as an
        # import-safe rollback reference, but is intentionally not shown.
        if False:
            decision_title = (
                f"{trade_decision.status} · {trade_decision.bucket_label}"
                if trade_decision.bucket_label
                else trade_decision.status
            )
            if trade_decision.status == "BET":
                st.success(f"v10 Decision Engine · {decision_title}")
            elif trade_decision.status == "WATCH":
                st.warning(f"v10 Decision Engine · {decision_title}")
            else:
                st.info(f"v10 Decision Engine · {decision_title}")
            d1, d2, d3, d4 = st.columns(4)
            d1.metric(
                "Fair probability",
                (
                    f"{trade_decision.fair_probability:.1%}"
                    if trade_decision.fair_probability is not None
                    else "—"
                ),
            )
            d2.metric(
                "YES ask",
                (f"{trade_decision.buy_price:.1%}" if trade_decision.buy_price is not None else "—"),
            )
            d3.metric(
                "Probability edge",
                f"{trade_decision.edge:+.1%}" if trade_decision.edge is not None else "—",
            )
            d4.metric(
                "Change since snapshot",
                (
                    f"{trade_decision.probability_change:+.1%}"
                    if trade_decision.probability_change is not None
                    else "First snapshot"
                ),
            )
            with st.expander("Why this decision?", expanded=trade_decision.status != "BET"):
                for reason in trade_decision.reasons:
                    st.write(f"• {reason}")
                for blocker in trade_decision.blockers:
                    st.write(f"• Blocker: {blocker}")
                st.caption(
                    "BET requires at least eight percentage points of executable edge, "
                    "confidence of at least 65/100 and a bid-ask spread no wider than 12%. "
                    "WATCH means the weather setup may be interesting but at least one "
                    "required condition is still missing."
                )
            if trade_decision.basket is not None:
                basket = trade_decision.basket
                st.subheader("Event-level edge basket")
                b1, b2, b3, b4 = st.columns(4)
                b1.metric("Selected buckets", ", ".join(basket.bucket_labels))
                b2.metric("Combined fair probability", f"{basket.fair_probability:.1%}")
                b3.metric("Combined YES asks", f"{basket.total_cost:.1%}")
                b4.metric("Combined edge", f"{basket.edge:+.1%}")
                if basket.warnings:
                    st.warning(
                        "Basket blocked: "
                        + " · ".join(basket.warnings)
                        + ". The buckets are mutually exclusive and are evaluated as one position."
                    )
                else:
                    st.caption(
                        "The basket includes the model's most likely bucket and has no gap "
                        "between selected ranges. Fees and order-book depth are applied separately "
                        "by the Shadow watcher."
                    )
    
            c1, c2, c3 = st.columns(3)
            c1.metric("Raw model mean", f"{live_nowcast.raw_model_mean:.1f} °C")
            c2.metric("Weighted raw ensemble", f"{live_nowcast.weighted_raw_mean:.1f} °C")
            c3.metric(
                "Bias corrected · equal weight",
                f"{live_nowcast.bias_corrected_equal_mean:.1f} °C",
            )
            c4, c5, c6 = st.columns(3)
            c4.metric("Bias corrected · weighted", f"{corrected.mean:.1f} °C")
            c5.metric(
                "METAR-conditioned",
                f"{live_nowcast.metar_conditioned_mean:.1f} °C",
            )
            c6.metric(
                "Final incl. TAF",
                f"{live_mean:.1f} °C",
                f"TAF {live_nowcast.taf_adjustment_c:+.2f} °C",
            )
            s1, s2, s3 = st.columns(3)
            s1.metric("Bias-weighted spread", f"{corrected.spread:.1f} °C")
            s2.metric(
                "METAR max so far",
                f"{observed_max:.0f} °C" if observed_max is not None else "Not available",
            )
            s3.metric(
                "Model warming left",
                f"≤ {remaining_rise:.1f} °C" if remaining_rise is not None else "Not available",
            )
            s4, s5 = st.columns(2)
            s4.metric("Forecast confidence", f"{live_nowcast.forecast_confidence}/100")
            s5.metric("Day status", day_status.label)
            st.caption(day_status.explanation)
    
            memory = live_nowcast.regime_memory
            if memory is not None:
                memory_title = f"Regime Memory · {memory.status} · {memory.label}"
                if memory.status == "CONFIRMED":
                    st.success(memory_title)
                elif memory.status in {"WATCH", "PREDICTED"}:
                    st.warning(memory_title)
                else:
                    st.info(memory_title)
                r1, r2, r3, r4 = st.columns(4)
                r1.metric("Early-warning confidence", f"{memory.confidence}/100")
                r2.metric("Comparable days", str(memory.analog_count))
                r3.metric(
                    "Analog effect",
                    f"{memory.center_adjustment_c:+.2f} °C",
                    "Challenger" if memory.shadow_only else "Champion",
                )
                r4.metric(
                    "Promotion gate",
                    memory.promotion.status,
                    f"{memory.promotion.oos_days}/{memory.promotion.minimum_oos_days} OOS days",
                )
                st.caption(memory.explanation)
                today_memory = all_regime_memory_snapshots.copy()
                if not today_memory.empty:
                    today_memory["target_date"] = pd.to_datetime(
                        today_memory.target_date,
                        errors="coerce",
                    ).dt.date
                    today_memory["captured_at"] = pd.to_datetime(
                        today_memory.captured_at,
                        utc=True,
                        errors="coerce",
                    )
                    same_regime = today_memory[
                        (today_memory.target_date == target)
                        & (today_memory.label == memory.label)
                        & today_memory.status.isin(["PREDICTED", "WATCH", "CONFIRMED"])
                    ]
                    if not same_regime.empty:
                        detected = same_regime.captured_at.min().tz_convert(timezone_name)
                        st.caption(f"Detected since {detected:%H:%M} airport local time.")
                with st.expander("Why this regime, historical analogs and safety gate", expanded=True):
                    regime_rows = [
                        {
                            "Regime": state.name,
                            "Status": state.status,
                            "Confidence": f"{state.confidence}/100",
                            "Origin": state.source,
                            "Champion effect": state.champion_effect,
                            "Why": state.explanation,
                        }
                        for state in memory.regimes
                    ]
                    if regime_rows:
                        st.dataframe(pd.DataFrame(regime_rows), hide_index=True, width="stretch")
                    if memory.pro_signals:
                        st.markdown("**Signals for the current regime**")
                        for signal in memory.pro_signals:
                            st.write(f"• {signal}")
                    if memory.contra_signals:
                        st.markdown("**Signals against / unresolved**")
                        for signal in memory.contra_signals:
                            st.write(f"• {signal}")
                    analog_rows = [
                        {
                            "Date": analog.target_date,
                            "Similarity": f"{analog.similarity:.0%}",
                            "Historical Champion": f"{analog.forecast_c:.1f} °C",
                            "Actual": f"{analog.actual_c:.1f} °C",
                            "Residual": f"{analog.residual_c:+.1f} °C",
                            "Matched on": ", ".join(analog.matched_on),
                        }
                        for analog in memory.analogs
                    ]
                    if analog_rows:
                        st.dataframe(pd.DataFrame(analog_rows), hide_index=True, width="stretch")
                    else:
                        st.caption(
                            "No settled historical day yet clears the minimum similarity and "
                            "same-information-set checks."
                        )
                    st.caption(memory.promotion.explanation)
                    st.caption(
                        "Automatically learned patterns start as Challenger-only. In-sample "
                        "matches never count toward promotion; only forecasts saved before later "
                        "settled outcomes count as out-of-sample evidence."
                    )
    
            taf = live_nowcast.taf_guidance
            if taf is None:
                st.info("No stored TAF currently covers the selected date.")
            else:
                local_issue = pd.Timestamp(taf.issue_time).tz_convert(timezone_name)
                local_tx = (
                    pd.Timestamp(taf.max_temp_at).tz_convert(timezone_name)
                    if taf.max_temp_at is not None
                    else None
                )
                title = f"TAF guidance · {taf.agreement}"
                with st.expander(title, expanded=True):
                    t1, t2, t3 = st.columns(3)
                    t1.metric(
                        "TAF TX",
                        f"{taf.max_temp_c:.0f} °C" if taf.max_temp_c is not None else "Not issued",
                        (
                            f"at {local_tx:%H:%M} local"
                            if local_tx is not None
                            else "Conditions guidance only"
                        ),
                    )
                    t2.metric("Agreement", taf.agreement)
                    t3.metric("Issued", f"{local_issue:%d.%m. %H:%M}", f"{taf.age_hours:.1f} h old")
                    risk_label = (
                        "Thunderstorm risk"
                        if taf.thunderstorm_risk
                        else "Precipitation risk"
                        if taf.precipitation_risk
                        else taf.cloud_risk
                    )
                    p1, p2 = st.columns(2)
                    p1.metric("Peak conditions", risk_label)
                    p2.metric(
                        "TAF center effect",
                        f"{taf.center_adjustment_c:+.2f} °C",
                        f"spread +{taf.spread_addition_c:.2f} °C",
                    )
                    for signal in taf.signals:
                        st.write(f"• {signal}")
                    wind_bits = []
                    if taf.peak_wind_kph is not None:
                        wind_bits.append(f"wind up to {taf.peak_wind_kph:.0f} km/h")
                    if taf.peak_wind_direction_deg is not None:
                        wind_bits.append(f"from {taf.peak_wind_direction_deg:.0f}°")
                    if taf.peak_gust_kph is not None:
                        wind_bits.append(f"gusts {taf.peak_gust_kph:.0f} km/h")
                    if wind_bits:
                        st.caption("Peak-window TAF: " + " · ".join(wind_bits))
                    if taf.change_summary:
                        st.info(f"Change from previous TAF: {taf.change_summary}.")
                    if not taf.temperature_influence_active and taf.max_temp_c is not None:
                        st.success(
                            "TAF TX temperature influence is off: its peak time has passed and "
                            "the METAR series is cooling. The archived TX remains visible for scoring."
                        )
                    st.code(taf.raw_taf, language=None, wrap_lines=True)
                    st.caption(
                        f"TAF effect: {taf.center_adjustment_c:+.2f} °C on the final center and "
                        f"+{taf.spread_addition_c:.2f} °C uncertainty floor. This is the single "
                        "TAF temperature path and is capped at ±0.25 °C; the raw, bias-corrected "
                        "and METAR-conditioned stages above remain unchanged."
                    )
    
            with st.expander("How the live correction was built", expanded=True):
                contributions = pd.DataFrame(
                    [
                        {
                            "Factor": name.replace("_", " ").title(),
                            "Center contribution": value,
                        }
                        for name, value in live_nowcast.adjustment_contributions.items()
                        if name != "total"
                    ]
                )
                contributions["Center contribution"] = contributions["Center contribution"].map(
                    lambda value: f"{value:+.2f} °C"
                )
                st.dataframe(contributions, hide_index=True, width="stretch")
                st.caption(
                    f"Bias corrected {corrected.mean:.2f} °C → live factors "
                    f"{live_nowcast.adjustment_contributions['total']:+.2f} °C → "
                    f"METAR conditioned {live_nowcast.metar_conditioned_mean:.2f} °C → "
                    f"TAF {live_nowcast.taf_adjustment_c:+.2f} °C → final "
                    f"{live_nowcast.final_forecast_mean:.2f} °C. TAF remains a separate stage."
                )
                if memory is not None:
                    if memory.applied_to_champion:
                        st.success(
                            f"Promoted Regime Memory contributes "
                            f"{memory.center_adjustment_c:+.2f} °C after passing the OOS gate."
                        )
                    elif memory.challenger_ready:
                        st.info(
                            f"Regime Memory proposes {memory.suggested_forecast_c:.2f} °C "
                            f"({memory.center_adjustment_c:+.2f} °C), but this is stored only as "
                            "the Analog Memory Challenger and does not change the forecast above."
                        )
                    else:
                        st.caption(
                            "Regime Memory is collecting comparable settled days; it currently "
                            "has no numerical effect on either Champion or Challenger."
                        )
                features = pd.DataFrame(
                    [
                        {
                            "Stored feature": name.replace("_", " ").title(),
                            "Value": (
                                "—"
                                if value is None
                                else f"{value:.2f}"
                                if isinstance(value, (int, float)) and not isinstance(value, bool)
                                else str(value)
                            ),
                        }
                        for name, value in live_nowcast.live_features.items()
                    ]
                )
                st.dataframe(features, hide_index=True, width="stretch")
    
            with st.expander("Dynamic model weights and confidence"):
                weights = current[
                    [
                        "model",
                        "model_weight",
                        "performance_weight",
                        "outlier_multiplier",
                        "regime_weight_multiplier",
                        "robust_distance_c",
                        "historical_d1_bias",
                        "d1_bias",
                    ]
                ].copy()
                weights["model_weight"] = weights.model_weight.map(lambda value: f"{value:.1%}")
                weights["performance_weight"] = weights.performance_weight.map(
                    lambda value: f"{value:.2f}"
                )
                weights["outlier_multiplier"] = weights.outlier_multiplier.map(
                    lambda value: f"{value:.2f}×"
                )
                weights["regime_weight_multiplier"] = weights.regime_weight_multiplier.map(
                    lambda value: f"{value:.2f}×"
                )
                weights["robust_distance_c"] = weights.robust_distance_c.map(
                    lambda value: f"{value:.2f} °C"
                )
                weights["d1_bias"] = weights.d1_bias.map(lambda value: f"{value:+.2f} °C")
                weights["historical_d1_bias"] = weights.historical_d1_bias.map(
                    lambda value: f"{value:+.2f} °C"
                )
                weights = weights.rename(
                    columns={
                        "model": "Model",
                        "model_weight": "Current weight",
                        "performance_weight": "Historical weight",
                        "outlier_multiplier": "Outlier protection",
                        "regime_weight_multiplier": "Heat-regime weight",
                        "robust_distance_c": "Distance from median",
                        "historical_d1_bias": "Historical D-1 bias",
                        "d1_bias": "Effective D-1 bias",
                    }
                )
                st.dataframe(weights, hide_index=True, width="stretch")
                factors = pd.DataFrame(
                    [
                        {"Factor": name.replace("_", " ").title(), "Score": score}
                        for name, score in live_nowcast.confidence_factors.items()
                    ]
                )
                st.bar_chart(factors.set_index("Factor"), horizontal=True)
                st.caption(
                    "Weights use only earlier D-1 errors from the latest 90 days and are shrunk "
                    "toward equal weighting when the sample is small. Confidence combines historical "
                    "accuracy, current model agreement, sample size, live-data freshness and, when "
                    "available, a limited TAF agreement factor. Confirmed post-convective and rapid "
                    "heat-ramp regimes apply separate conservative confidence reductions."
                )
    
            st.subheader("Model maximum forecasts")
            provenance = live_nowcast.model_freshness[
                [
                    "model",
                    "model_run_at",
                    "available_at",
                    "fetched_at",
                    "provenance_status",
                    "age_minutes",
                    "used_in_forecast",
                ]
            ].copy()
            for column in ["model_run_at", "available_at", "fetched_at"]:
                provenance[column] = pd.to_datetime(
                    provenance[column], utc=True, errors="coerce"
                ).dt.tz_convert(timezone_name)
                provenance[column] = provenance[column].map(
                    lambda value: value.strftime("%d.%m. %H:%M") if pd.notna(value) else "Not supplied"
                )
            provenance = provenance.rename(
                columns={
                    "model": "Model",
                    "model_run_at": "Model initialization",
                    "available_at": "Provider availability",
                    "fetched_at": "Fetched by Weatherman",
                    "provenance_status": "Provenance",
                    "age_minutes": "Fetch age (minutes)",
                    "used_in_forecast": "Used in live consensus",
                }
            )
            provenance["Fetch age (minutes)"] = provenance["Fetch age (minutes)"].map(
                lambda value: round(float(value)) if pd.notna(value) else None
            )
            st.dataframe(provenance, hide_index=True, width="stretch")
            st.caption(
                "Fetched time is not relabelled as model initialization. Meteoblue supplies mLM "
                "run metadata when available; Open-Meteo's regular forecast response may not expose "
                "the underlying NWP run, which is shown explicitly."
            )
            st.caption(
                "Workflow 5 now checks current model data every ten minutes from 06:00 airport "
                "local time through the end of the critical window. Open-Meteo providers are "
                "refetched after 30 minutes and meteoblue after 60 minutes. A stale provider is "
                "omitted; with fewer than two fresh models all trade signals are blocked. The "
                "sidebar button still performs an immediate full fetch for this airport."
            )
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
                if live_nowcast.wind_speed_kph is not None:
                    wind = f"Wind: {live_nowcast.wind_speed_kph:.0f} km/h"
                    if live_nowcast.wind_direction_deg is not None:
                        wind += f" from {live_nowcast.wind_direction_deg:.0f}°"
                    if live_nowcast.wind_source:
                        wind += f" ({live_nowcast.wind_source})"
                    context.append(wind)
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
            if not latest_markets.empty and prior_probabilities:
    
                def previous_for_bucket(bucket: int) -> float | None:
                    matches = latest_markets[
                        (latest_markets.bucket_low_c.isna() | (latest_markets.bucket_low_c <= bucket))
                        & (
                            latest_markets.bucket_high_c.isna()
                            | (latest_markets.bucket_high_c >= bucket)
                        )
                    ]
                    if matches.empty:
                        return None
                    return prior_probabilities.get(str(matches.iloc[0].bucket_label))
    
                probs["change"] = probs.apply(
                    lambda row: (
                        row.probability - previous_for_bucket(int(row.bucket))
                        if previous_for_bucket(int(row.bucket)) is not None
                        else None
                    ),
                    axis=1,
                )
            st.subheader("Final bucket probabilities")
            shown_probabilities = probs.assign(
                probability=lambda frame: frame.probability.map(lambda value: f"{value:.1%}")
            )
            if "change" in shown_probabilities:
                shown_probabilities["change"] = shown_probabilities.change.map(
                    lambda value: f"{value:+.1%}" if pd.notna(value) else "—"
                )
            st.dataframe(shown_probabilities, hide_index=True, width="stretch")
            if day_status.is_locked:
                st.success(
                    f"{day_status.label}: {day_status.explanation} Probabilities outside the final "
                    "range have been removed."
                )
            elif day_status.minimum_bucket is not None:
                st.caption(
                    f"Buckets below {day_status.minimum_bucket} °C are impossible because today's "
                    f"stored METAR maximum is already {observed_max:.0f} °C. Remaining "
                    "probabilities sum to 100%."
                )
                st.caption(day_status.explanation)
            else:
                st.caption(day_status.explanation)
    
with tab_market:
    st.subheader("Our probability versus the live Polymarket price")
    st.caption(
        "A positive difference means our weather model assigns a higher chance than the current "
        "price to buy YES. It is a model signal, not a guarantee or trading instruction."
    )
    if probabilities is None:
        st.info("A current weather forecast is required before a market comparison can be made.")
    elif target_markets.empty:
        if market_snapshots.empty:
            st.info(
                "No Polymarket prices have been stored for this airport yet. Run workflow "
                "2 - Collect current forecasts once. Its final result should show a "
                "market_prices value greater than zero for a published market."
            )
        else:
            st.info(
                f"Polymarket data exists, but no matching market is stored for {target:%d.%m.%Y}. "
                "Daily markets are often published only shortly before the target day."
            )
    else:
        comparison = market_edges(probabilities, latest_markets)
        if comparison.empty:
            st.info("The stored market does not contain recognizable Celsius ranges.")
        else:
            market_closed = latest_markets.closed.fillna(False).astype(bool).all()
            market_conflict = detect_market_model_conflict(probabilities, latest_markets)
            metar_pending = bool(live_nowcast and live_nowcast.metar_pending)
            trading_suppressed = (
                market_closed
                or bool(day_status and day_status.is_locked)
                or metar_pending
                or market_conflict.is_conflict
            )
            actionable = comparison[comparison.best_ask.notna()]
            best = actionable.iloc[0] if not actionable.empty else comparison.iloc[0]
            market_sum = float(comparison.yes_price.sum())
            m1, m2, m3 = st.columns(3)
            if trading_suppressed:
                top_market = comparison.sort_values("yes_price", ascending=False).iloc[0]
                if market_closed:
                    status_label = "Officially resolved"
                    comparison["signal"] = "Day complete"
                    message = (
                        "The market is resolved. Weatherman no longer displays new edge signals."
                    )
                elif day_status and day_status.is_locked:
                    status_label = "Daily peak locked"
                    comparison["signal"] = "Day complete"
                    message = (
                        "The temperature peak is locked. Weatherman no longer displays new edge "
                        "signals for this date."
                    )
                elif metar_pending:
                    status_label = "METAR guard"
                    comparison["signal"] = "METAR guard"
                    message = (
                        "A routine METAR is due but not yet available. Signals are blocked until "
                        "the official feed publishes it."
                    )
                else:
                    status_label = "Market–model conflict"
                    comparison["signal"] = "Market-model conflict"
                    message = (
                        f"The market assigns {market_conflict.market_probability:.1%} to "
                        f"{market_conflict.bucket_label}, while Weatherman assigns "
                        f"{market_conflict.model_probability:.1%}. The market is not copied into "
                        "the forecast, but new edge signals are blocked as a safety warning."
                    )
                m1.metric("Status", status_label)
                m2.metric(
                    "Official winning range" if market_closed else "Market-leading range",
                    top_market.bucket_label,
                )
                m3.metric("Market probability", f"{top_market.yes_price:.1%}")
                if market_closed or bool(day_status and day_status.is_locked):
                    st.success(message)
                else:
                    st.warning(message)
            else:
                m1.metric("Largest uncalibrated gap", f"{best.edge:+.1%}")
                m2.metric("Temperature range", best.bucket_label)
                m3.metric("Market price sum", f"{market_sum:.1%}")
                if pd.notna(best.best_ask) and best.edge >= 0.08:
                    st.info(
                        f"Research signal: {best.bucket_label} is {best.edge:+.1%} above the "
                        "current YES buy price. This is raw model-market disagreement, not a "
                        "calibrated edge or trade recommendation."
                    )
                else:
                    st.write(
                        "There is currently no raw positive difference of at least 8 points."
                    )

            if prior_probabilities:
                comparison["probability_change"] = comparison.apply(
                    lambda row: (
                        float(row.model_probability) - prior_probabilities[str(row.bucket_label)]
                        if str(row.bucket_label) in prior_probabilities
                        else None
                    ),
                    axis=1,
                )
            else:
                comparison["probability_change"] = None

            shown = comparison[
                [
                    "bucket_label",
                    "model_probability",
                    "probability_change",
                    "yes_price",
                    "best_bid",
                    "best_ask",
                    "edge",
                    "spread",
                    "volume",
                    "signal",
                ]
            ].copy()
            shown["signal"] = shown.signal.map(
                {
                    "Possible edge": "Possible edge",
                    "Uncalibrated disagreement": "Uncalibrated disagreement",
                    "Market-model conflict": "Market-model conflict",
                    "Watch": "Watch only",
                    "Watch only": "Watch only",
                    "No clear edge": "No material disagreement",
                    "No material disagreement": "No material disagreement",
                    "Day complete": "Day complete",
                    "METAR guard": "METAR guard",
                    "METAR pending": "METAR guard",
                }
            )
            shown = shown.rename(
                columns={
                    "bucket_label": "Range",
                    "model_probability": "Raw model",
                    "probability_change": "Change",
                    "yes_price": "Market",
                    "best_bid": "Best bid",
                    "best_ask": "Buy YES",
                    "edge": "Uncalibrated gap",
                    "spread": "Spread",
                    "volume": "Volume $",
                    "signal": "Signal",
                }
            )
            percent_columns = [
                "Raw model",
                "Change",
                "Market",
                "Best bid",
                "Buy YES",
                "Uncalibrated gap",
                "Spread",
            ]
            for column in percent_columns:
                shown[column] = shown[column].map(
                    lambda value: f"{value:.1%}" if pd.notna(value) else "—"
                )
            shown["Volume $"] = shown["Volume $"].map(
                lambda value: f"${value:,.0f}" if pd.notna(value) else "—"
            )
            st.dataframe(shown, hide_index=True, width="stretch")

            with st.expander("Position & hedge calculator"):
                st.caption(
                    "This balances the gross payout between two selected YES buckets. "
                    "All other outcomes remain uncovered, so it is a scenario hedge, "
                    "not complete downside protection."
                )
                hedge_options = (
                    actionable[actionable.best_ask.notna()].bucket_label.astype(str).tolist()
                )
                if len(hedge_options) < 2:
                    st.info("At least two executable YES asks are needed for a hedge calculation.")
                else:
                    h1, h2, h3 = st.columns(3)
                    primary_bucket = h1.selectbox(
                        "Existing position",
                        hedge_options,
                        key=f"hedge_primary_{airport}_{target}",
                    )
                    primary_row = actionable[
                        actionable.bucket_label.astype(str) == primary_bucket
                    ].iloc[0]
                    primary_stake = h2.number_input(
                        "Amount already invested ($)",
                        min_value=0.01,
                        value=1.00,
                        step=0.25,
                        key=f"hedge_stake_{airport}_{target}",
                    )
                    primary_price = h3.number_input(
                        "Average entry price",
                        min_value=0.001,
                        max_value=1.0,
                        value=float(primary_row.buy_price),
                        step=0.01,
                        format="%.3f",
                        key=f"hedge_entry_{airport}_{target}",
                    )
                    alternatives = [label for label in hedge_options if label != primary_bucket]
                    hedge_bucket = st.selectbox(
                        "Hedge bucket",
                        alternatives,
                        key=f"hedge_bucket_{airport}_{target}",
                    )
                    hedge_row = actionable[
                        actionable.bucket_label.astype(str) == hedge_bucket
                    ].iloc[0]
                    plan = balanced_hedge_plan(
                        primary_bucket=primary_bucket,
                        primary_stake=primary_stake,
                        primary_price=primary_price,
                        hedge_bucket=hedge_bucket,
                        hedge_price=float(hedge_row.buy_price),
                    )
                    p1, p2, p3 = st.columns(3)
                    p1.metric("Balanced hedge cost", f"${plan.balanced_hedge_stake:.2f}")
                    p2.metric("Total cost", f"${plan.total_cost:.2f}")
                    p3.metric(
                        "P/L if either selected bucket wins",
                        f"${plan.covered_result:+.2f}",
                    )
                    hedge_stake = st.number_input(
                        "Hedge amount to test ($)",
                        min_value=0.0,
                        value=float(round(plan.balanced_hedge_stake, 2)),
                        step=0.25,
                        key=f"hedge_test_stake_{airport}_{target}",
                    )
                    outcomes = hedge_outcome_table(
                        outcome_buckets=hedge_options,
                        primary_bucket=primary_bucket,
                        primary_stake=primary_stake,
                        primary_price=primary_price,
                        hedge_bucket=hedge_bucket,
                        hedge_stake=hedge_stake,
                        hedge_price=float(hedge_row.buy_price),
                    )
                    outcome_frame = pd.DataFrame(outcomes)
                    for column in ("Payout", "Net P/L"):
                        outcome_frame[column] = outcome_frame[column].map(
                            lambda value: f"${value:+.2f}"
                        )
                    st.dataframe(outcome_frame, hide_index=True, width="stretch")
            selected_range = st.selectbox(
                "Price history range",
                comparison.bucket_label.tolist(),
                key="market_history_range",
            )
            selected_market_id = str(
                comparison.loc[comparison.bucket_label == selected_range, "market_id"].iloc[0]
            )
            price_history = target_markets[
                target_markets.market_id.astype(str) == selected_market_id
            ].sort_values("captured_at")
            if price_history.captured_at.nunique() > 1:
                price_chart = price_history[
                    ["captured_at", "yes_price", "best_bid", "best_ask"]
                ].melt(
                    id_vars="captured_at",
                    var_name="price_type",
                    value_name="price",
                )
                price_chart = price_chart.dropna(subset=["price"])
                st.plotly_chart(
                    px.line(
                        price_chart,
                        x="captured_at",
                        y="price",
                        color="price_type",
                        markers=True,
                        title=f"Collected price history · {selected_range}",
                        labels={"captured_at": "Captured", "price": "Price / probability"},
                    ),
                    width="stretch",
                )
            else:
                st.caption("Price history starts with this collection and grows every three hours.")
            event_slug = str(comparison.event_slug.iloc[0])
            st.link_button(
                "Open this market on Polymarket",
                f"https://polymarket.com/event/{event_slug}",
            )
            resolution = comparison.resolution_source.dropna()
            if not resolution.empty:
                st.caption(
                    "Resolution source: "
                    f"{resolution.iloc[0]}. Weatherman uses airport METAR as the live reference; "
                    "the official market source remains decisive."
                )
            st.caption(
                "Market-leading range means the open bucket with the highest displayed YES "
                "price; it becomes the winning range only after official resolution. Market "
                "probability is that displayed YES price. Buying YES normally requires the ask, "
                "which can be higher. Missing asks use the displayed value only as an approximation."
            )
            

with tab_shadow:
    st.subheader(f"{airport} · research-only market watcher")
    st.caption(
        "Workflow 5 evaluates the public CLOB order book during the critical "
        "window. It walks the available ask depth for a $10 all-in paper stake "
        "and subtracts estimated weather-market taker fees, slippage and a "
        "two-percentage-point safety margin. Raw model probabilities are not calibrated; "
        "the watcher is RESEARCH ONLY and cannot place an order."
    )
    target_shadow = (
        shadow_evaluations[
            pd.to_datetime(shadow_evaluations.target_date).dt.date == target
        ].copy()
        if not shadow_evaluations.empty
        else shadow_evaluations
    )
    target_baskets = (
        basket_snapshots[
            pd.to_datetime(basket_snapshots.target_date).dt.date == target
        ].copy()
        if not basket_snapshots.empty
        else basket_snapshots
    )
    if target_shadow.empty:
        st.info(
            "No shadow evaluation is stored for this airport and date yet. "
            "Collection starts automatically when the airport enters its critical "
            "trading window."
        )
    else:
        target_shadow["captured_at"] = pd.to_datetime(
            target_shadow.captured_at,
            utc=True,
        )
        latest_capture = target_shadow.captured_at.max()
        latest_shadow = target_shadow[
            target_shadow.captured_at == latest_capture
        ].copy()
        executable = latest_shadow[
            latest_shadow.status == "SHADOW BET"
        ]
        actionable_edges = pd.to_numeric(executable.net_edge, errors="coerce")
        best_actionable_edge = actionable_edges.max() if not actionable_edges.empty else None
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Stored checks", target_shadow.captured_at.nunique())
        s2.metric("Buckets checked now", len(latest_shadow))
        s3.metric("Actionable paper bets", len(executable))
        s4.metric(
            "Best actionable edge",
            (
                f"{best_actionable_edge:+.1%}"
                if best_actionable_edge is not None and pd.notna(best_actionable_edge)
                else "No actionable edge"
            ),
        )
        st.caption(
            f"Latest CLOB evaluation: "
            f"{latest_capture.tz_convert(timezone_name):%d.%m.%Y %H:%M:%S} "
            f"{timezone_name}"
        )
        shown = latest_shadow[
            [
                "bucket_label",
                "fair_probability",
                "best_ask",
                "average_fill_price",
                "fee_per_share",
                "slippage",
                "all_in_price",
                "net_edge",
                "depth_at_best_usdc",
                "available_depth_usdc",
                "forecast_confidence",
                "status",
            ]
        ].copy()
        for column in [
            "fair_probability",
            "best_ask",
            "average_fill_price",
            "fee_per_share",
            "slippage",
            "all_in_price",
            "net_edge",
        ]:
            shown[column] = shown[column].map(
                lambda value: f"{float(value):+.1%}"
                if column in {"slippage", "net_edge"} and pd.notna(value)
                else f"{float(value):.1%}"
                if pd.notna(value)
                else "—"
            )
        for column in ["depth_at_best_usdc", "available_depth_usdc"]:
            shown[column] = shown[column].map(
                lambda value: f"${float(value):,.2f}" if pd.notna(value) else "—"
            )
        shown = shown.rename(
            columns={
                "bucket_label": "Range",
                "fair_probability": "Raw model probability",
                "best_ask": "Best ask",
                "average_fill_price": "Average fill",
                "fee_per_share": "Fee/share",
                "slippage": "Slippage",
                "all_in_price": "All-in/share",
                "net_edge": "Uncalibrated net gap",
                "depth_at_best_usdc": "Depth at best",
                "available_depth_usdc": "Total ask depth",
                "forecast_confidence": "Confidence",
                "status": "Paper decision",
            }
        )
        st.dataframe(shown, hide_index=True, width="stretch")
        if not target_baskets.empty:
            target_baskets["captured_at"] = pd.to_datetime(
                target_baskets.captured_at,
                utc=True,
            )
            latest_basket = target_baskets.sort_values("captured_at").iloc[-1]
            labels = json.loads(str(latest_basket.bucket_labels_json))
            warnings = json.loads(str(latest_basket.warnings_json))
            st.subheader("Latest simultaneous event basket")
            b1, b2, b3, b4 = st.columns(4)
            b1.metric("Buckets", ", ".join(str(value) for value in labels))
            b2.metric("Raw combined probability", f"{float(latest_basket.fair_probability):.1%}")
            b3.metric("All-in basket cost", f"{float(latest_basket.total_cost):.1%}")
            b4.metric("Uncalibrated basket gap", f"{float(latest_basket.net_edge):+.1%}")
            if warnings:
                st.warning(
                    f"{latest_basket.status}: " + " · ".join(str(value) for value in warnings)
                )
            else:
                st.success(
                    f"{latest_basket.status}: evaluated jointly as one mutually exclusive event."
                )
        paper_entries = target_shadow[
            target_shadow.status == "SHADOW BET"
        ].sort_values("captured_at")
        if not paper_entries.empty:
            st.caption(
                "A market bucket is counted as a future paper entry only at its "
                "first SHADOW BET. Repeated checks are retained to measure how "
                "long the executable edge remained available."
            )


with tab_accuracy:
    st.subheader(f"{airport} · accuracy by information timing")
    st.caption(
        "This is the same timing analysis as Airport Research, restricted to the "
        "airport selected in the Trading Desk sidebar."
    )
    accuracy_window = st.selectbox(
        "Evaluation window",
        [90, 30, 365],
        format_func=lambda value: f"Last {value} days",
        key=f"trading_accuracy_window_{airport}",
    )
    with st.spinner(f"Calculating timing accuracy for {airport}…"):
        timing_metrics = cached_airport_timing_metrics(
            forecasts,
            actuals,
            observations,
            all_forecast_snapshots,
            airport,
            catalog[airport],
            accuracy_window,
        )
    if timing_metrics.empty:
        st.info(
            "No completed forecast days are available for this airport yet. "
            "Historical D-1 results appear after the backfill; fixed 20:00, "
            "10:00 and Live results grow from collected checkpoints."
        )
    else:
        timing_options = sorted(timing_metrics.lead_bucket.dropna().unique())
        timing = st.selectbox(
            "Comparable information set",
            timing_options,
            key=f"trading_accuracy_timing_{airport}",
        )
        selected_metrics = timing_metrics[timing_metrics.lead_bucket == timing].copy()
        table = selected_metrics[
            [
                "stage",
                "n_days",
                "bias",
                "mae",
                "rmse",
                "market_exact_hit",
                "within_1c",
                "mae_gain_vs_raw",
            ]
        ].copy()
        for column in ["bias", "mae_gain_vs_raw"]:
            table[column] = table[column].map(
                lambda value: f"{float(value):+.2f} °C" if pd.notna(value) else "—"
            )
        for column in ["mae", "rmse"]:
            table[column] = table[column].map(
                lambda value: f"{float(value):.2f} °C" if pd.notna(value) else "—"
            )
        for column in ["market_exact_hit", "within_1c"]:
            table[column] = table[column].map(
                lambda value: f"{float(value):.1%}" if pd.notna(value) else "—"
            )
        st.dataframe(
            table.rename(
                columns={
                    "stage": "Forecast stage",
                    "n_days": "Independent days",
                    "bias": "Bias",
                    "mae": "MAE",
                    "rmse": "RMSE",
                    "market_exact_hit": "Exact market bucket",
                    "within_1c": "Within ±1 °C",
                    "mae_gain_vs_raw": "MAE gain vs raw",
                }
            ),
            hide_index=True,
            width="stretch",
        )
        st.plotly_chart(
            px.bar(
                selected_metrics.sort_values("mae"),
                x="stage",
                y="mae",
                title=f"{airport} · {timing} · MAE by forecast stage",
                labels={"stage": "Forecast stage", "mae": "MAE °C"},
            ),
            width="stretch",
        )
    with st.expander("Exact timing definitions"):
        st.write(
            "**D-1 · 24h lead:** each valid model hour uses the value produced "
            "exactly 24 hours earlier; this is not a single evening run."
        )
        st.write(
            "**D-1 Evening · 20:00:** latest stored forecast known at or before "
            "20:00 local airport time on the previous day, maximum age six hours."
        )
        st.write(
            "**D0 Morning · 10:00:** latest stored forecast known at or before "
            "10:00 local airport time on the target day, maximum age six hours."
        )
        st.write("**Live:** snapshots grouped by hours remaining until the median modelled peak.")


# Airport-wide analytics live on their own page and are not evaluated on Trading Desk reruns.
st.stop()


with tab_performance:
    st.subheader("Tracked performance from real market prices")
    st.caption(
        "Starting with v9, every workflow run journals the probability shown by Weatherman and "
        "the contemporaneous YES ask. After official resolution, the first Possible-edge signal "
        "for each range is settled as a hypothetical $1 stake. No real order is placed."
    )
    settled = settled_performance
    recorded_ranges = (
        all_signal_snapshots.market_id.nunique() if not all_signal_snapshots.empty else 0
    )
    possible_entries = (
        all_signal_snapshots[all_signal_snapshots.signal == "Possible edge"].market_id.nunique()
        if not all_signal_snapshots.empty
        else 0
    )
    if all_signal_snapshots.empty:
        st.info(
            "The v9 signal journal is still empty. Run workflow 2 - Collect current forecasts "
            "once. It will then update automatically every three hours."
        )
    elif settled.empty:
        st.info(
            f"The journal already contains {recorded_ranges} market ranges and "
            f"{possible_entries} Possible-edge entries. Performance appears as soon as one of "
            "those markets is officially resolved."
        )
    else:
        total_pnl = float(settled.pnl.sum())
        win_rate = float(settled.won.mean())
        roi = total_pnl / len(settled)
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("Settled $1 entries", f"{len(settled)}")
        p2.metric("Hit rate", f"{win_rate:.1%}")
        p3.metric("Tracked P/L", f"${total_pnl:+.2f}")
        p4.metric("Return on test stakes", f"{roi:+.1%}")

        airport_summary = settled.groupby("airport", as_index=False).agg(
            settled_entries=("market_id", "count"),
            wins=("won", "sum"),
            pnl=("pnl", "sum"),
            average_edge=("edge", "mean"),
        )
        airport_summary["hit_rate"] = airport_summary.wins / airport_summary.settled_entries
        airport_summary["return"] = airport_summary.pnl / airport_summary.settled_entries
        airport_summary["airport_name"] = airport_summary.airport.map(
            lambda code: catalog.get(code, {}).get("name", code)
        )
        airport_summary = airport_summary.sort_values("pnl", ascending=False)
        ranking = airport_summary[
            [
                "airport",
                "airport_name",
                "settled_entries",
                "hit_rate",
                "pnl",
                "return",
                "average_edge",
            ]
        ].copy()
        ranking = ranking.rename(
            columns={
                "airport": "Airport",
                "airport_name": "Name",
                "settled_entries": "Settled entries",
                "hit_rate": "Hit rate",
                "pnl": "P/L",
                "return": "Return",
                "average_edge": "Average model edge",
            }
        )
        for column in ["Hit rate", "Return", "Average model edge"]:
            ranking[column] = ranking[column].map(lambda value: f"{value:.1%}")
        ranking["P/L"] = ranking["P/L"].map(lambda value: f"${value:+.2f}")
        st.subheader("Airport comparison")
        st.dataframe(ranking, hide_index=True, width="stretch")

        selected_performance = settled[settled.airport == airport].copy()
        if selected_performance.empty:
            st.info(f"No Possible-edge entry has settled for {airport} yet.")
        else:
            selected_performance = selected_performance.sort_values("captured_at")
            selected_performance["airport_cumulative_pnl"] = selected_performance.pnl.cumsum()
            st.plotly_chart(
                px.line(
                    selected_performance,
                    x="captured_at",
                    y="airport_cumulative_pnl",
                    markers=True,
                    title=f"{airport} · tracked cumulative P/L",
                    labels={
                        "captured_at": "Signal time",
                        "airport_cumulative_pnl": "P/L from $1 test stakes",
                    },
                ),
                width="stretch",
            )

        details = settled[
            [
                "airport",
                "target_date",
                "bucket_label",
                "timing",
                "model_probability",
                "buy_price",
                "edge",
                "won",
                "pnl",
            ]
        ].copy()
        details = details.sort_values("target_date", ascending=False)
        details["won"] = details.won.map({True: "Won", False: "Lost"})
        for column in ["model_probability", "buy_price", "edge"]:
            details[column] = details[column].map(lambda value: f"{value:.1%}")
        details["pnl"] = details.pnl.map(lambda value: f"${value:+.2f}")
        details = details.rename(
            columns={
                "airport": "Airport",
                "target_date": "Target date",
                "bucket_label": "Range",
                "timing": "Entry timing",
                "model_probability": "Our model",
                "buy_price": "YES ask",
                "edge": "Edge at entry",
                "won": "Result",
                "pnl": "P/L",
            }
        )
        st.subheader("Settled signal details")
        st.dataframe(details, hide_index=True, width="stretch")
        st.caption(
            "This is a historical model check, not a brokerage statement. It assumes one $1 "
            "test stake at the recorded ask and does not include fees, slippage or liquidity "
            "limits. Multiple qualifying temperature ranges are evaluated separately."
        )

    st.divider()
    st.subheader("Always-consensus strategy benchmarks")
    st.caption(
        "Each strategy buys exactly one bucket: the bucket with that forecast stage's highest "
        "probability. No minimum edge is required. Results are separated by information timing, "
        "and every entry uses a hypothetical $1 stake."
    )
    if strategy_performance.empty:
        tracked = len(all_strategy_snapshots)
        st.info(
            f"{tracked} consensus-strategy entries are journaled. Results appear after their "
            "markets resolve; tracking begins with v9.4."
        )
    else:
        strategy_summary = strategy_performance.groupby(["strategy", "timing"], as_index=False).agg(
            entries=("market_id", "count"),
            hit_rate=("won", "mean"),
            pnl=("pnl", "sum"),
            average_buy_price=("buy_price", "mean"),
        )
        strategy_summary["roi"] = strategy_summary.pnl / strategy_summary.entries
        for column in ["hit_rate", "roi", "average_buy_price"]:
            strategy_summary[column] = strategy_summary[column].map(lambda value: f"{value:.1%}")
        strategy_summary["pnl"] = strategy_summary.pnl.map(lambda value: f"${value:+.2f}")
        strategy_summary = strategy_summary.rename(
            columns={
                "strategy": "Strategy",
                "timing": "Information timing",
                "entries": "Settled days",
                "hit_rate": "Hit rate",
                "pnl": "P/L",
                "average_buy_price": "Average buy price",
                "roi": "Return",
            }
        )
        st.dataframe(strategy_summary, hide_index=True, width="stretch")

    st.subheader("Historical price simulation")
    if historical_price_performance.empty:
        st.info(
            "Run workflow 3 - Backfill historical market prices. The simulation then combines "
            "leakage-safe reconstructed D-1 forecasts with the nearest sampled historical YES "
            "trade price."
        )
    else:
        historical_summary = historical_price_performance.groupby("strategy", as_index=False).agg(
            days=("target_date", "nunique"),
            hit_rate=("won", "mean"),
            pnl=("pnl", "sum"),
            average_price=("buy_price", "mean"),
        )
        historical_summary["return"] = historical_summary.pnl / historical_summary.days
        for column in ["hit_rate", "average_price", "return"]:
            historical_summary[column] = historical_summary[column].map(
                lambda value: f"{value:.1%}"
            )
        historical_summary["pnl"] = historical_summary.pnl.map(lambda value: f"${value:+.2f}")
        historical_summary = historical_summary.rename(
            columns={
                "strategy": "D-1 strategy",
                "days": "Simulated days",
                "hit_rate": "Hit rate",
                "pnl": "P/L",
                "average_price": "Average sampled price",
                "return": "Return",
            }
        )
        st.dataframe(historical_summary, hide_index=True, width="stretch")
        st.warning(
            "Historical CLOB prices are observed trade-price samples, not reconstructed old "
            "best asks or order books. Forward v9.4 tracking is the higher-quality executable-price "
            "benchmark."
        )


with tab_airports:
    st.subheader("Airport and model scorecards")
    st.caption(
        "Forecast Score measures weather accuracy. Trade Score measures settled market results. "
        "They remain separate because an accurate airport is not automatically a profitable one."
    )
    analysis_window = st.selectbox(
        "Historical accuracy window",
        [90, 30, 365],
        format_func=lambda days: f"Last {days} days",
        key="airport_analysis_window",
    )
    window_scores = (
        airport_forecast_scorecards[
            airport_forecast_scorecards.window_days == analysis_window
        ].copy()
        if not airport_forecast_scorecards.empty
        else airport_forecast_scorecards
    )
    if window_scores.empty:
        st.info("Run the historical D-1 backfill once to create airport scorecards.")
    else:
        ensemble_ranking = window_scores[window_scores.model == "Weighted ensemble"].copy()
        if ensemble_ranking.empty:
            ensemble_ranking = window_scores.sort_values(
                "forecast_score", ascending=False
            ).drop_duplicates("airport", keep="first")
        ensemble_ranking["airport_name"] = ensemble_ranking.airport.map(
            lambda code: catalog.get(code, {}).get("name", code)
        )
        combined = ensemble_ranking[
            ["airport", "airport_name", "forecast_score", "n", "mae", "data_quality"]
        ].merge(
            trade_scorecards[["airport", "trade_score", "resolved_days", "confidence"]]
            if not trade_scorecards.empty
            else pd.DataFrame(columns=["airport", "trade_score", "resolved_days", "confidence"]),
            on="airport",
            how="left",
        )
        combined = combined.sort_values("forecast_score", ascending=False)
        combined["trade_score"] = combined.trade_score.map(
            lambda value: f"{value:.0f}/100" if pd.notna(value) else "Waiting for data"
        )
        combined["resolved_days"] = (
            pd.to_numeric(combined.resolved_days, errors="coerce").fillna(0).astype(int)
        )
        combined["confidence"] = combined.confidence.fillna("Not enough data")
        combined["forecast_score"] = combined.forecast_score.map(lambda value: f"{value:.0f}/100")
        combined["mae"] = combined.mae.map(lambda value: f"{value:.2f} °C")
        combined = combined.rename(
            columns={
                "airport": "Airport",
                "airport_name": "Name",
                "forecast_score": "Forecast Score",
                "trade_score": "Trade Score",
                "resolved_days": "Settled airport days",
                "confidence": "Trade-score status",
                "n": "Forecast days",
                "mae": "Ensemble MAE",
                "data_quality": "Forecast data",
            }
        )
        st.subheader("Airport ranking")
        st.dataframe(combined, hide_index=True, width="stretch")

        selected_models = window_scores[window_scores.airport == airport].copy()
        expected_models = pd.DataFrame({"model": catalog[airport]["models"] + ["meteoblue"]})
        selected_models = expected_models.merge(selected_models, on="model", how="left")
        selected_models["airport"] = selected_models.airport.fillna(airport)
        selected_models["n"] = (
            pd.to_numeric(selected_models.n, errors="coerce").fillna(0).astype(int)
        )
        selected_models["data_quality"] = selected_models.data_quality.fillna("No scored D-1 data")
        current_weights = live_nowcast.model_weights if live_nowcast is not None else {}
        selected_models["current_weight"] = selected_models.model.map(current_weights)
        selected_models = selected_models.sort_values(
            "forecast_score", ascending=False, na_position="last"
        )
        model_table = selected_models[
            [
                "model",
                "n",
                "bias",
                "mae",
                "rmse",
                "exact_hit",
                "within_1c",
                "forecast_score",
                "current_weight",
                "data_quality",
            ]
        ].copy()
        for column in ["bias", "mae", "rmse"]:
            model_table[column] = model_table[column].map(
                lambda value: f"{value:.2f} °C" if pd.notna(value) else "—"
            )
        for column in ["exact_hit", "within_1c", "current_weight"]:
            model_table[column] = model_table[column].map(
                lambda value: f"{value:.1%}" if pd.notna(value) else "—"
            )
        model_table["forecast_score"] = model_table.forecast_score.map(
            lambda value: f"{value:.0f}/100" if pd.notna(value) else "—"
        )
        model_table["model"] = model_table.model.replace({"meteoblue": "meteoblue mLM"})
        model_table = model_table.rename(
            columns={
                "model": "Model",
                "n": "Days",
                "bias": "Bias",
                "mae": "MAE",
                "rmse": "RMSE",
                "exact_hit": "Exact bucket",
                "within_1c": "Within ±1 °C",
                "forecast_score": "Forecast Score",
                "current_weight": "Current live weight",
                "data_quality": "Data quality",
            }
        )
        st.subheader(f"{airport} · model detail")
        st.dataframe(model_table, hide_index=True, width="stretch")
        st.caption(
            "The Weighted ensemble is tested walk-forward: every historical day uses only errors "
            "known before that day. Current model weights use the latest 90 days and are limited "
            "so that a short lucky period cannot dominate the forecast."
        )

    trade_base = pd.DataFrame(
        [{"airport": code, "airport_name": details["name"]} for code, details in catalog.items()]
    )
    trade_table = trade_base.merge(trade_scorecards, on="airport", how="left")
    trade_table["resolved_days"] = (
        pd.to_numeric(trade_table.resolved_days, errors="coerce").fillna(0).astype(int)
    )
    trade_table["entries"] = (
        pd.to_numeric(trade_table.entries, errors="coerce").fillna(0).astype(int)
    )
    trade_table["confidence"] = trade_table.confidence.fillna("Not enough data")
    trade_table["trade_score"] = trade_table.trade_score.map(
        lambda value: f"{value:.0f}/100" if pd.notna(value) else "Locked"
    )
    for column in ["hit_rate", "roi", "average_edge", "average_market_gap"]:
        trade_table[column] = trade_table[column].map(
            lambda value: f"{value:.1%}" if pd.notna(value) else "—"
        )
    trade_table["pnl"] = trade_table.pnl.map(
        lambda value: f"${value:+.2f}" if pd.notna(value) else "$0.00"
    )
    trade_table["max_drawdown"] = trade_table.max_drawdown.map(
        lambda value: f"${value:.2f}" if pd.notna(value) else "—"
    )
    trade_table["sharpe"] = trade_table.sharpe.map(
        lambda value: f"{value:.2f}" if pd.notna(value) else "Waiting for 30 days"
    )
    trade_table["calibration_error"] = trade_table.calibration_error.map(
        lambda value: f"{value:.3f}" if pd.notna(value) else "Collecting"
    )
    trade_table = trade_table[
        [
            "airport",
            "airport_name",
            "trade_score",
            "confidence",
            "resolved_days",
            "entries",
            "hit_rate",
            "roi",
            "pnl",
            "max_drawdown",
            "sharpe",
            "average_edge",
            "average_market_gap",
            "calibration_error",
        ]
    ].rename(
        columns={
            "airport": "Airport",
            "airport_name": "Name",
            "trade_score": "Trade Score",
            "confidence": "Status",
            "resolved_days": "Settled days",
            "entries": "Entries",
            "hit_rate": "Hit rate",
            "roi": "ROI",
            "pnl": "P/L",
            "max_drawdown": "Max drawdown",
            "sharpe": "Daily Sharpe",
            "average_edge": "Average entry edge",
            "average_market_gap": "Average model-market gap",
            "calibration_error": "Calibration error",
        }
    )
    st.subheader("Trading scorecard · data gates active")
    st.dataframe(trade_table, hide_index=True, width="stretch")
    st.caption(
        "Trade Score stays locked below 10 independent settled airport days. It is Provisional "
        "from 10–29 days, Developing from 30–99 and More robust from 100 days. Daily Sharpe "
        "starts at 30 days; calibration error requires at least 100 probability samples and "
        "30 settled days. Model-market gap measures disagreement, not guaranteed inefficiency."
    )


with tab_accuracy:
    st.subheader("Forecast ladder · same timestamp, separate transformations")
    st.caption(
        "This measures the raw model mean, bias-corrected ensemble, METAR-conditioned nowcast "
        "and final forecast including TAF separately. Live snapshots are split by hours to the "
        "modelled peak so a late nowcast is never compared as if it had D-1 information. Airport "
        "METAR maxima are the preferred actual; archive data is only a fallback."
    )
    selected_ladder = (
        ladder_metrics[ladder_metrics.airport == airport].copy()
        if not ladder_metrics.empty
        else ladder_metrics
    )
    if selected_ladder.empty:
        st.info(
            "Live forecast-ladder tracking starts with the first v9.3.1 collection. Results appear "
            "after matching target days have completed. Existing forecasts are not reconstructed "
            "with later information."
        )
    else:
        timing_options = (
            selected_ladder[["timing", "lead_bucket"]]
            .drop_duplicates()
            .sort_values(["timing", "lead_bucket"])
        )
        timing_options["selection"] = (
            timing_options.timing.astype(str) + " · " + timing_options.lead_bucket.astype(str)
        )
        ladder_selection = st.selectbox(
            "Comparable forecast information set",
            timing_options.selection.tolist(),
            key="forecast_ladder_timing",
        )
        chosen = timing_options[timing_options.selection == ladder_selection].iloc[0]
        ladder_table = selected_ladder[
            (selected_ladder.timing == chosen.timing)
            & (selected_ladder.lead_bucket == chosen.lead_bucket)
        ][
            [
                "stage",
                "n_days",
                "bias",
                "mae",
                "rmse",
                "exact_hit",
                "within_1c",
                "mae_gain_vs_raw",
            ]
        ].copy()
        for column in ["bias", "mae", "rmse", "mae_gain_vs_raw"]:
            ladder_table[column] = ladder_table[column].map(
                lambda value, metric=column: (
                    f"{value:+.2f} °C"
                    if metric in {"bias", "mae_gain_vs_raw"}
                    else f"{value:.2f} °C"
                )
            )
        for column in ["exact_hit", "within_1c"]:
            ladder_table[column] = ladder_table[column].map(lambda value: f"{value:.1%}")
        ladder_table = ladder_table.rename(
            columns={
                "stage": "Forecast stage",
                "n_days": "Independent days",
                "bias": "Bias",
                "mae": "MAE",
                "rmse": "RMSE",
                "exact_hit": "Exact bucket",
                "within_1c": "Within ±1 °C",
                "mae_gain_vs_raw": "MAE gain vs raw",
            }
        )
        st.dataframe(ladder_table, hide_index=True, width="stretch")

    historical_selected = (
        historical_ladder_metrics[historical_ladder_metrics.airport == airport].copy()
        if not historical_ladder_metrics.empty
        else historical_ladder_metrics
    )
    st.subheader("Historical D-1 reconstruction")
    if historical_selected.empty:
        st.info("Run workflow 1 once to reconstruct historical raw and bias-corrected D-1 stages.")
    else:
        history_table = historical_selected[
            [
                "stage",
                "n_days",
                "bias",
                "mae",
                "rmse",
                "exact_hit",
                "within_1c",
                "mae_gain_vs_raw",
            ]
        ].copy()
        for column in ["bias", "mae", "rmse", "mae_gain_vs_raw"]:
            history_table[column] = history_table[column].map(
                lambda value, metric=column: (
                    f"{value:+.2f} °C"
                    if metric in {"bias", "mae_gain_vs_raw"}
                    else f"{value:.2f} °C"
                )
            )
        for column in ["exact_hit", "within_1c"]:
            history_table[column] = history_table[column].map(lambda value: f"{value:.1%}")
        history_table = history_table.rename(
            columns={
                "stage": "Forecast stage",
                "n_days": "Independent days",
                "bias": "Bias",
                "mae": "MAE",
                "rmse": "RMSE",
                "exact_hit": "Exact bucket",
                "within_1c": "Within ±1 °C",
                "mae_gain_vs_raw": "MAE gain vs raw",
            }
        )
        st.dataframe(history_table, hide_index=True, width="stretch")
        st.caption(
            "Every historical target day uses only errors from earlier days for its bias and "
            "performance weights. This avoids hindsight leakage."
        )

    with st.expander("How to read MAE gain, RMSE and modelled peak"):
        st.write(
            "**MAE gain vs raw** = raw-model MAE minus the selected stage's MAE. Positive is "
            "an improvement; negative means that transformation made accuracy worse."
        )
        st.write(
            "**RMSE** penalizes occasional large errors more heavily than MAE. That matters for "
            "temperature markets because a 3–4 °C miss crosses several buckets."
        )
        st.write(
            "**After median modelled peak** means the snapshot was taken after the median peak "
            "time of the latest hourly model paths. It is not the observed METAR peak; the exact "
            "expected peak time is stored with every snapshot."
        )

    st.subheader("Live-factor diagnostics")
    selected_factors = (
        factor_diagnostics[factor_diagnostics.airport == airport].copy()
        if not factor_diagnostics.empty
        else factor_diagnostics
    )
    if selected_factors.empty:
        st.info(
            "Factor diagnostics start with v9.4 and appear after live snapshots have matching "
            "completed-day METAR maxima."
        )
    else:
        factor_table = selected_factors[
            [
                "factor",
                "information_set",
                "n_days",
                "n_snapshots",
                "average_contribution_c",
                "cumulative_mae",
                "marginal_mae_gain",
            ]
        ].copy()
        for column in [
            "average_contribution_c",
            "cumulative_mae",
            "marginal_mae_gain",
        ]:
            factor_table[column] = factor_table[column].map(
                lambda value, metric=column: (
                    f"{value:+.3f} °C" if metric != "cumulative_mae" else f"{value:.3f} °C"
                )
            )
        factor_table = factor_table.rename(
            columns={
                "factor": "Cumulative factor step",
                "information_set": "Information set",
                "n_days": "Independent days",
                "n_snapshots": "Snapshots",
                "average_contribution_c": "Average contribution",
                "cumulative_mae": "MAE after step",
                "marginal_mae_gain": "Marginal MAE gain",
            }
        )
        st.dataframe(factor_table, hide_index=True, width="stretch")
        st.caption(
            "Positive marginal gain means the factor improved MAE at its current conservative "
            "coefficient; negative means it hurt. Coefficients should only be promoted from "
            "challenger to champion after stable out-of-sample gains across enough independent "
            "days, not from the same day's in-sample result."
        )

    st.divider()
    st.subheader("Individual weather-model accuracy")
    horizon = st.selectbox("Forecast timing", ["D-1", "D0-morning", "Live"])
    selected = forecasts[forecasts.horizon == horizon] if not forecasts.empty else forecasts
    scored = score_frame(selected, airport_station_actuals)
    metrics = model_metrics(scored)
    expected_accuracy_models = pd.DataFrame({"model": catalog[airport]["models"] + ["meteoblue"]})
    complete_metrics = expected_accuracy_models.merge(metrics, on="model", how="left")
    complete_metrics["n"] = pd.to_numeric(complete_metrics.n, errors="coerce").fillna(0).astype(int)
    complete_metrics["status"] = complete_metrics.n.map(
        lambda value: "Scored" if value > 0 else f"No scored {horizon} data"
    )
    display_metrics = complete_metrics.copy()
    display_metrics["model"] = display_metrics.model.replace({"meteoblue": "meteoblue mLM"})
    for column in ["bias", "mae", "rmse"]:
        display_metrics[column] = display_metrics[column].map(
            lambda value: f"{value:.2f} °C" if pd.notna(value) else "—"
        )
    display_metrics["hit_rate"] = display_metrics.hit_rate.map(
        lambda value: f"{value:.1%}" if pd.notna(value) else "—"
    )
    st.dataframe(
        display_metrics.rename(
            columns={
                "model": "Model",
                "n": "Days",
                "bias": "Bias",
                "mae": "MAE",
                "rmse": "RMSE",
                "hit_rate": "Exact bucket",
                "status": "Data status",
            }
        ),
        hide_index=True,
        width="stretch",
    )
    if metrics.empty:
        snapshot_days = selected.target_date.nunique() if not selected.empty else 0
        if horizon == "D-1":
            st.info("Run the v6 historical backfill once to create fixed 24-hour D-1 data.")
        elif snapshot_days:
            st.info(
                f"{snapshot_days} {horizon} day(s) have already been stored. Accuracy appears "
                "only after matching actual temperatures are available; recent actuals arrive "
                "with an approximately six-day safety delay."
            )
        else:
            st.info(
                f"No {horizon} snapshots are stored yet. D0-morning is collected automatically "
                "by workflow 2 during the airport's morning; the first accuracy values normally "
                "appear about one week later."
            )
    else:
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
            "Fixed 2.0 odds are synthetic. Results based on collected Polymarket asks are shown "
            "separately under Tracked performance."
        )

with tab_data:
    st.write(
        f"Forecast rows: {len(forecasts):,} · Hourly rows: {len(hourly):,} · "
        f"Actual rows: {len(actuals):,} · METAR rows: {len(observations):,} · "
        f"TAF rows: {len(tafs):,} · "
        f"Market rows: {len(market_snapshots):,} · Signal rows: {len(signal_snapshots):,} · "
        f"Strategy rows: {len(strategy_snapshots):,} · "
        f"Forecast-ladder rows: {len(all_forecast_snapshots):,}"
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
    taf_scored = taf_verification_frame(
        all_tafs,
        station_actuals,
        {code: item["timezone"] for code, item in catalog.items()},
    )
    taf_metrics = taf_verification_metrics(taf_scored)
    st.subheader("TAF TX verification")
    if taf_metrics.empty:
        st.caption(
            "TAF reports are archived from v9.2 onward. Accuracy appears after a report with an "
            "explicit TX maximum has a matching actual temperature."
        )
    else:
        selected_taf_metrics = taf_metrics[taf_metrics.airport == airport].copy()
        if selected_taf_metrics.empty:
            st.caption("No settled TX guidance is available for this airport yet.")
        else:
            for column in ["bias", "mae"]:
                selected_taf_metrics[column] = selected_taf_metrics[column].map(
                    lambda value: f"{value:.2f} °C"
                )
            for column in ["exact_hit", "within_1c"]:
                selected_taf_metrics[column] = selected_taf_metrics[column].map(
                    lambda value: f"{value:.1%}"
                )
            st.dataframe(selected_taf_metrics, hide_index=True, width="stretch")
    if not market_snapshots.empty:
        market_coverage = market_snapshots.groupby("target_date", as_index=False).agg(
            price_points=("captured_at", "nunique"),
            ranges=("market_id", "nunique"),
        )
        st.subheader("Polymarket price history collected by Weatherman")
        st.dataframe(market_coverage.sort_values("target_date", ascending=False), hide_index=True)
    if not forecasts.empty:
        st.download_button(
            "Download forecasts CSV",
            forecasts.to_csv(index=False),
            f"{airport}_forecasts.csv",
            "text/csv",
        )
