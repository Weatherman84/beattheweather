from __future__ import annotations

import sys
from datetime import datetime
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
    flat_bet_simulation,
    market_edges,
    model_metrics,
    score_frame,
    settled_signal_performance,
)
from weatherman.db import (
    DailyActual,
    Forecast,
    HourlyForecast,
    MarketSnapshot,
    Observation,
    Session,
    SignalSnapshot,
    init_db,
)
from weatherman.nowcast import build_live_nowcast
from weatherman.service import collect
from weatherman.settings import airports


def last_update(frame: pd.DataFrame, column: str, timezone_name: str) -> str:
    if frame.empty or column not in frame:
        return "not available"
    values = pd.to_datetime(frame[column], utc=True, errors="coerce").dropna()
    if values.empty:
        return "not available"
    latest = values.max().tz_convert(timezone_name)
    return latest.strftime("%d.%m.%Y %H:%M")


st.set_page_config(page_title="Weatherman", page_icon="🌡️", layout="wide")
init_db()
catalog = airports()

st.title("Weatherman · Temperature Market Lab")
airport = st.sidebar.selectbox(
    "Airport", list(catalog), format_func=lambda code: f"{code} · {catalog[code]['name']}"
)
timezone_name = catalog[airport]["timezone"]
target = st.sidebar.date_input(
    "Target date", value=datetime.now(ZoneInfo(timezone_name)).date()
)
if st.sidebar.button("Refresh forecasts + METAR", type="primary"):
    try:
        with st.spinner("Fetching models and observations…"):
            result = collect([airport])
    except Exception as exc:
        st.sidebar.error(
            f"Refresh failed ({type(exc).__name__}). The dashboard remains usable; "
            "the full cause is available in the Streamlit log."
        )
    else:
        st.sidebar.success(
            f"Saved {result['forecasts']} daily, {result['hourly_forecasts']} hourly and "
            f"{result['market_prices']} market prices; journaled {result['signals']} model "
            f"comparisons and refreshed {result['actuals']} actuals"
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
    all_market_snapshots = pd.read_sql(select(MarketSnapshot), session.bind)
    all_signal_snapshots = pd.read_sql(select(SignalSnapshot), session.bind)

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

st.caption(
    f"Last data update · Forecast: {last_update(forecasts, 'run_at', timezone_name)} · "
    f"METAR: {last_update(observations, 'observed_at', timezone_name)} · "
    f"Polymarket: {last_update(market_snapshots, 'captured_at', timezone_name)} · "
    f"Signals: {last_update(signal_snapshots, 'captured_at', timezone_name)} "
    f"({timezone_name} local time)"
)

tab_live, tab_market, tab_performance, tab_accuracy, tab_simulation, tab_data = st.tabs(
    [
        "Live forecast",
        "Market comparison",
        "Tracked performance",
        "Accuracy by timing",
        "D-1 $1 simulation",
        "Data coverage",
    ]
)

probabilities: dict[int, float] | None = None
day_status = None
with tab_live:
    live_nowcast = build_live_nowcast(
        forecasts=forecasts,
        actuals=actuals,
        observations=observations,
        hourly=hourly,
        markets=latest_markets,
        timezone_name=timezone_name,
        target=target,
        as_of=datetime.now(ZoneInfo("UTC")),
    )
    if live_nowcast is None:
        st.info("No current forecast stored for this date. Click Refresh forecasts + METAR.")
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
        live_mean = sum(bucket * probability for bucket, probability in probabilities.items())

        c1, c2, c3 = st.columns(3)
        c1.metric("Raw model mean", f"{current.max_temp_c.mean():.1f} °C")
        c2.metric("D-1 bias-corrected", f"{corrected.mean:.1f} °C")
        c3.metric("METAR-conditioned nowcast", f"{live_mean:.1f} °C")
        c4, c5, c6, c7 = st.columns(4)
        c4.metric("Model spread", f"{corrected.spread:.1f} °C")
        c5.metric(
            "METAR max so far",
            f"{observed_max:.0f} °C" if observed_max is not None else "Not available",
        )
        c6.metric(
            "Model warming left",
            f"≤ {remaining_rise:.1f} °C" if remaining_rise is not None else "Not available",
        )
        c7.metric("Day status", day_status.label)

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
            trading_suppressed = market_closed or bool(day_status and day_status.is_locked)
            actionable = comparison[comparison.best_ask.notna()]
            best = actionable.iloc[0] if not actionable.empty else comparison.iloc[0]
            market_sum = float(comparison.yes_price.sum())
            m1, m2, m3 = st.columns(3)
            if trading_suppressed:
                top_market = comparison.sort_values("yes_price", ascending=False).iloc[0]
                status_label = "Officially resolved" if market_closed else "Daily peak locked"
                m1.metric("Status", status_label)
                m2.metric("Leading / winning range", top_market.bucket_label)
                m3.metric("Market probability", f"{top_market.yes_price:.1%}")
                comparison["signal"] = "Day complete"
                st.success(
                    "The temperature day is complete. Weatherman no longer displays new edge "
                    "signals for this date."
                )
            else:
                m1.metric("Best model difference", f"{best.edge:+.1%}")
                m2.metric("Temperature range", best.bucket_label)
                m3.metric("Market price sum", f"{market_sum:.1%}")
                if pd.notna(best.best_ask) and best.edge >= 0.08:
                    st.info(
                        f"Model signal: {best.bucket_label} is {best.edge:+.1%} above the current "
                        "YES buy price. Check spread, liquidity and the resolution source before "
                        "drawing any conclusion."
                    )
                else:
                    st.write(
                        "There is currently no large positive difference of at least 8 points."
                    )

            shown = comparison[
                [
                    "bucket_label",
                    "model_probability",
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
                    "Watch": "Watch",
                    "No clear edge": "No clear edge",
                    "Day complete": "Day complete",
                }
            )
            shown = shown.rename(
                columns={
                    "bucket_label": "Range",
                    "model_probability": "Our model",
                    "yes_price": "Market",
                    "best_bid": "Best bid",
                    "best_ask": "Buy YES",
                    "edge": "Model − buy price",
                    "spread": "Spread",
                    "volume": "Volume $",
                    "signal": "Signal",
                }
            )
            percent_columns = [
                "Our model",
                "Market",
                "Best bid",
                "Buy YES",
                "Model − buy price",
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
                "The displayed market value is an implied probability. Buying YES normally "
                "requires the ask price, which can be higher. Missing asks use the displayed "
                "market value only as an approximation."
            )


with tab_performance:
    st.subheader("Tracked performance from real market prices")
    st.caption(
        "Starting with v9, every workflow run journals the probability shown by Weatherman and "
        "the contemporaneous YES ask. After official resolution, the first Possible-edge signal "
        "for each range is settled as a hypothetical $1 stake. No real order is placed."
    )
    settled = settled_signal_performance(all_signal_snapshots, all_market_snapshots)
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


with tab_accuracy:
    horizon = st.selectbox("Forecast timing", ["D-1", "D0-morning", "Live"])
    selected = forecasts[forecasts.horizon == horizon] if not forecasts.empty else forecasts
    scored = score_frame(selected, actuals)
    metrics = model_metrics(scored)
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
            "Fixed 2.0 odds are synthetic. Results based on collected Polymarket asks are shown "
            "separately under Tracked performance."
        )

with tab_data:
    st.write(
        f"Forecast rows: {len(forecasts):,} · Hourly rows: {len(hourly):,} · "
        f"Actual rows: {len(actuals):,} · METAR rows: {len(observations):,} · "
        f"Market rows: {len(market_snapshots):,} · Signal rows: {len(signal_snapshots):,}"
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
