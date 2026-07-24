from __future__ import annotations

import math
import sys
from datetime import datetime, timezone
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import select

from weatherman.analytics import (
    fixed_decision_snapshots,
    forecast_ladder_frame,
    forecast_ladder_metrics,
    forecast_scorecards,
    historical_d1_ladder,
    historical_price_strategy_simulation,
    live_factor_diagnostics,
    preferred_station_actuals,
    settled_probability_comparison,
    settled_signal_performance,
    settled_strategy_performance,
    trading_airport_scorecards,
)
from weatherman.db import (
    AirportMarketUniverse,
    DailyActual,
    Forecast,
    ForecastSnapshot,
    MarketSnapshot,
    Observation,
    Session,
    SignalSnapshot,
    StrategySnapshot,
    TafReport,
    init_db,
    refresh_database_connections,
)
from weatherman.settings import research_airports


st.set_page_config(
    page_title="Weatherman · Airport Research",
    page_icon="📊",
    layout="wide",
)
st.sidebar.markdown(
    "### Navigation\n"
    "- [🌡️ Trading Desk](/)\n"
    "- [📊 Airport Research](/airport_research)"
)
st.sidebar.divider()

refresh_database_connections()
init_db()
catalog = research_airports()
timezone_by_airport = {
    code: details["timezone"] for code, details in catalog.items()
}


@st.cache_data(show_spinner=False, ttl=900)
def load_research_data() -> dict[str, pd.DataFrame]:
    with Session() as session:
        return {
            "forecasts": pd.read_sql(select(Forecast), session.bind),
            "actuals": pd.read_sql(select(DailyActual), session.bind),
            "observations": pd.read_sql(select(Observation), session.bind),
            "snapshots": pd.read_sql(select(ForecastSnapshot), session.bind),
            "markets": pd.read_sql(select(MarketSnapshot), session.bind),
            "signals": pd.read_sql(select(SignalSnapshot), session.bind),
            "strategies": pd.read_sql(select(StrategySnapshot), session.bind),
            "tafs": pd.read_sql(select(TafReport), session.bind),
            "universe": pd.read_sql(select(AirportMarketUniverse), session.bind),
        }


def format_percent(value: object) -> str:
    return f"{float(value):.1%}" if pd.notna(value) else "—"


def format_temp(value: object, *, signed: bool = False) -> str:
    if pd.isna(value):
        return "—"
    return f"{float(value):+.2f} °C" if signed else f"{float(value):.2f} °C"


def market_bucket_hits(scored: pd.DataFrame) -> pd.DataFrame:
    """Add a unit-aware Polymarket bucket hit without mixing C and F markets."""
    if scored.empty:
        return scored
    result = scored.copy()

    def bucket(value_c: float, airport: str) -> int:
        details = catalog.get(str(airport), {})
        unit = details.get("market_unit", "C")
        width = max(1, int(details.get("market_bucket_width", 1)))
        value = value_c * 9 / 5 + 32 if unit == "F" else value_c
        reported_integer = math.floor(value + 0.5)
        return math.floor(reported_integer / width)

    result["market_bucket_hit"] = result.apply(
        lambda row: bucket(float(row.forecast_c), str(row.airport))
        == bucket(float(row.max_temp_c), str(row.airport)),
        axis=1,
    )
    return result


def market_timing_metrics(scored: pd.DataFrame) -> pd.DataFrame:
    if scored.empty:
        return pd.DataFrame()
    frame = market_bucket_hits(scored)
    base = forecast_ladder_metrics(frame)
    market_hits = (
        frame.groupby(["airport", "timing", "lead_bucket", "stage"], as_index=False)
        .market_bucket_hit.mean()
        .rename(columns={"market_bucket_hit": "market_exact_hit"})
    )
    return base.merge(
        market_hits,
        on=["airport", "timing", "lead_bucket", "stage"],
        how="left",
    )


def canonical_strategy_checkpoints(strategies: pd.DataFrame) -> pd.DataFrame:
    if strategies.empty:
        return strategies
    frame = strategies.copy()
    frame["captured_at"] = pd.to_datetime(frame.captured_at, utc=True)
    frame["target_date"] = pd.to_datetime(frame.target_date).dt.date
    rows = []
    for (airport, target, strategy), group in frame.groupby(
        ["airport", "target_date", "strategy"]
    ):
        timezone_name = timezone_by_airport.get(str(airport))
        if not timezone_name:
            continue
        target_timestamp = pd.Timestamp(target)
        cutoffs = (
            (
                "D-1 Evening · 20:00",
                (
                    target_timestamp.tz_localize(timezone_name)
                    - pd.Timedelta(days=1)
                    + pd.Timedelta(hours=20)
                ).tz_convert("UTC"),
            ),
            (
                "D0 Morning · 10:00",
                (
                    target_timestamp.tz_localize(timezone_name)
                    + pd.Timedelta(hours=10)
                ).tz_convert("UTC"),
            ),
        )
        for label, cutoff in cutoffs:
            candidates = group[
                (group.captured_at <= cutoff)
                & (group.captured_at >= cutoff - pd.Timedelta(hours=6))
            ]
            if candidates.empty:
                continue
            selected = candidates.sort_values("captured_at").iloc[-1].copy()
            selected["timing"] = label
            rows.append(selected)
    return pd.DataFrame(rows).reset_index(drop=True) if rows else pd.DataFrame()


if st.sidebar.button("Reload research data"):
    refresh_database_connections()
    st.cache_data.clear()
    st.rerun()

st.title("Airport Research")
st.caption(
    "Cross-airport model research is separated from the live Trading Desk. "
    "The goal is to identify where Weatherman is consistently accurate and at "
    "which information checkpoint that accuracy becomes tradeable."
)

module = st.radio(
    "Research module",
    [
        "Airport leaderboard",
        "Accuracy by timing",
        "Forecast stages",
        "Strategy performance",
        "Universe & coverage",
    ],
    horizontal=True,
)
airport_options = ["All mapped airports", *sorted(catalog)]
airport_scope = st.selectbox(
    "Airport filter",
    airport_options,
    format_func=lambda code: (
        code
        if code == "All mapped airports"
        else f"{code} · {catalog[code]['name']}"
    ),
)
selected_airport = None if airport_scope == "All mapped airports" else airport_scope
window_days = st.selectbox(
    "Evaluation window",
    [90, 30, 365],
    format_func=lambda value: f"Last {value} days",
)

data = load_research_data()
forecasts = data["forecasts"]
actuals = data["actuals"]
observations = data["observations"]
snapshots = data["snapshots"]
markets = data["markets"]
signals = data["signals"]
strategies = data["strategies"]
universe = data["universe"]

station_actuals = preferred_station_actuals(
    observations,
    actuals,
    timezone_by_airport,
)
fixed_snapshots = fixed_decision_snapshots(
    snapshots,
    timezone_by_airport,
)
fixed_scored = forecast_ladder_frame(fixed_snapshots, station_actuals)
fixed_metrics = market_timing_metrics(fixed_scored)
historical_scored = historical_d1_ladder(forecasts, station_actuals)
historical_metrics = market_timing_metrics(historical_scored)


if module == "Airport leaderboard":
    st.subheader("Airport predictability leaderboard")
    st.caption(
        "D-1 · 24h lead is a standardized meteorological comparison. "
        "D-1 Evening and D0 Morning use the latest snapshot known at or before "
        "20:00 on the previous local day and 10:00 on the target day. A snapshot "
        "after a cut-off is never used."
    )
    scorecards = forecast_scorecards(forecasts, station_actuals)
    base = pd.DataFrame(
        [
            {
                "airport": code,
                "name": details["name"],
                "station_status": details.get("station_match", "candidate station"),
                "unit": details.get("market_unit", "C"),
            }
            for code, details in catalog.items()
        ]
    )
    window = (
        scorecards[
            (scorecards.window_days == window_days)
            & (scorecards.model == "Weighted ensemble")
        ].copy()
        if not scorecards.empty
        else pd.DataFrame()
    )
    if not window.empty:
        window = window[
            [
                "airport",
                "n",
                "mae",
                "rmse",
                "exact_hit",
                "within_1c",
                "forecast_score",
                "data_quality",
            ]
        ]
        base = base.merge(window, on="airport", how="left")

    def timing_slice(
        metrics: pd.DataFrame,
        timing: str,
        prefix: str,
    ) -> pd.DataFrame:
        if metrics.empty:
            return pd.DataFrame(columns=["airport"])
        selected = metrics[
            (metrics.timing == timing)
            & (metrics.stage == "Bias corrected · performance weighted")
        ][
            [
                "airport",
                "n_days",
                "mae",
                "rmse",
                "market_exact_hit",
                "within_1c",
                "mae_gain_vs_raw",
            ]
        ].copy()
        return selected.rename(
            columns={
                column: f"{prefix}_{column}"
                for column in selected.columns
                if column != "airport"
            }
        )

    leaderboard = base.merge(
        timing_slice(historical_metrics, "D-1 · 24h lead", "d1_24h"),
        on="airport",
        how="left",
    )
    for timing, prefix in (
        ("D-1 Evening · 20:00", "d1_20"),
        ("D0 Morning · 10:00", "d0_10"),
    ):
        leaderboard = leaderboard.merge(
            timing_slice(fixed_metrics, timing, prefix),
            on="airport",
            how="left",
        )
    expected_metric_columns = [
        "d1_24h_n_days",
        "d1_24h_mae",
        "d1_24h_rmse",
        "d1_24h_market_exact_hit",
        "d1_24h_within_1c",
        "d1_24h_mae_gain_vs_raw",
        "d1_20_n_days",
        "d1_20_mae",
        "d1_20_market_exact_hit",
        "d0_10_n_days",
        "d0_10_mae",
        "d0_10_market_exact_hit",
    ]
    for column in expected_metric_columns:
        if column not in leaderboard:
            leaderboard[column] = pd.NA
    if "d1_24h_n_days" not in leaderboard:
        leaderboard["d1_24h_n_days"] = 0
    leaderboard["sample_status"] = pd.to_numeric(
        leaderboard.d1_24h_n_days, errors="coerce"
    ).fillna(0).map(
        lambda count: (
            "Strong"
            if count >= 90
            else "Usable"
            if count >= 30
            else "Limited"
            if count >= 10
            else "Too early"
        )
    )
    leaderboard = leaderboard.sort_values(
        ["d1_24h_market_exact_hit", "d1_24h_mae"],
        ascending=[False, True],
        na_position="last",
    )
    if selected_airport:
        leaderboard = leaderboard[leaderboard.airport == selected_airport]
    display = leaderboard[
        [
            "airport",
            "name",
            "station_status",
            "unit",
            "sample_status",
            "d1_24h_n_days",
            "d1_24h_market_exact_hit",
            "d1_24h_within_1c",
            "d1_24h_mae",
            "d1_24h_rmse",
            "d1_24h_mae_gain_vs_raw",
            "d1_20_n_days",
            "d1_20_market_exact_hit",
            "d1_20_mae",
            "d0_10_n_days",
            "d0_10_market_exact_hit",
            "d0_10_mae",
        ]
    ].copy()
    for column in [
        "d1_24h_market_exact_hit",
        "d1_24h_within_1c",
        "d1_20_market_exact_hit",
        "d0_10_market_exact_hit",
    ]:
        display[column] = display[column].map(format_percent)
    for column in ["d1_24h_mae", "d1_24h_rmse", "d1_20_mae", "d0_10_mae"]:
        display[column] = display[column].map(format_temp)
    display["d1_24h_mae_gain_vs_raw"] = display[
        "d1_24h_mae_gain_vs_raw"
    ].map(lambda value: format_temp(value, signed=True))
    for column in ["d1_24h_n_days", "d1_20_n_days", "d0_10_n_days"]:
        display[column] = pd.to_numeric(
            display[column], errors="coerce"
        ).fillna(0).astype(int)
    display = display.rename(
        columns={
            "airport": "Airport",
            "name": "Station",
            "station_status": "Mapping",
            "unit": "Market unit",
            "sample_status": "Sample",
            "d1_24h_n_days": "24h days",
            "d1_24h_market_exact_hit": "24h exact market bucket",
            "d1_24h_within_1c": "24h within ±1 °C",
            "d1_24h_mae": "24h MAE",
            "d1_24h_rmse": "24h RMSE",
            "d1_24h_mae_gain_vs_raw": "24h MAE gain",
            "d1_20_n_days": "20:00 days",
            "d1_20_market_exact_hit": "20:00 exact market bucket",
            "d1_20_mae": "20:00 MAE",
            "d0_10_n_days": "10:00 days",
            "d0_10_market_exact_hit": "10:00 exact market bucket",
            "d0_10_mae": "10:00 MAE",
        }
    )
    st.dataframe(display, hide_index=True, width="stretch")
    st.caption(
        "Exact market bucket respects each catalogued market unit and bucket width "
        "(for example 1 °C or paired 2 °F ranges). Candidate station mappings must "
        "be verified against the market's resolution source before an airport is promoted to trading."
    )

elif module == "Accuracy by timing":
    st.subheader("Accuracy by information timing")
    live_scored = forecast_ladder_frame(snapshots, station_actuals)
    live_scored = (
        live_scored[live_scored.lead_bucket.str.startswith("D0 live", na=False)]
        if not live_scored.empty
        else live_scored
    )
    live_metrics = market_timing_metrics(live_scored)
    all_metrics = pd.concat(
        [historical_metrics, fixed_metrics, live_metrics],
        ignore_index=True,
    )
    if selected_airport:
        all_metrics = all_metrics[all_metrics.airport == selected_airport]
    if all_metrics.empty:
        st.info("No completed airport days are available for the selected scope yet.")
    else:
        timing_options = sorted(all_metrics.lead_bucket.dropna().unique())
        timing = st.selectbox("Comparable information set", timing_options)
        table = all_metrics[all_metrics.lead_bucket == timing][
            [
                "airport",
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
                lambda value: format_temp(value, signed=True)
            )
        for column in ["mae", "rmse"]:
            table[column] = table[column].map(format_temp)
        for column in ["market_exact_hit", "within_1c"]:
            table[column] = table[column].map(format_percent)
        table = table.rename(
            columns={
                "airport": "Airport",
                "stage": "Forecast stage",
                "n_days": "Independent days",
                "bias": "Bias",
                "mae": "MAE",
                "rmse": "RMSE",
                "market_exact_hit": "Exact market bucket",
                "within_1c": "Within ±1 °C",
                "mae_gain_vs_raw": "MAE gain vs raw",
            }
        )
        st.dataframe(table, hide_index=True, width="stretch")
        chart_source = all_metrics[
            (all_metrics.lead_bucket == timing)
            & (
                all_metrics.stage
                == "Bias corrected · performance weighted"
            )
        ]
        if not chart_source.empty:
            st.plotly_chart(
                px.bar(
                    chart_source.sort_values("mae"),
                    x="airport",
                    y="mae",
                    color="n_days",
                    title=f"{timing} · airport MAE",
                    labels={"mae": "MAE °C", "n_days": "Days"},
                ),
                width="stretch",
            )
    with st.expander("Exact definitions"):
        st.write(
            "**D-1 · 24h lead:** every valid model hour uses the value produced "
            "exactly 24 hours earlier; this is not a single evening model run."
        )
        st.write(
            "**D-1 Evening · 20:00:** latest stored forecast known at or before "
            "20:00 local airport time on the previous day, maximum age six hours."
        )
        st.write(
            "**D0 Morning · 10:00:** latest stored forecast known at or before "
            "10:00 local airport time on the target day, maximum age six hours."
        )
        st.write(
            "**Live:** snapshots grouped by hours remaining until the median "
            "modelled peak. “After median modelled peak” is not the observed METAR peak."
        )

elif module == "Forecast stages":
    st.subheader("Forecast-stage contribution")
    combined = pd.concat([historical_metrics, fixed_metrics], ignore_index=True)
    if selected_airport:
        combined = combined[combined.airport == selected_airport]
    if combined.empty:
        st.info("Forecast-stage results appear after snapshots have matching actuals.")
    else:
        timing = st.selectbox(
            "Information checkpoint",
            sorted(combined.lead_bucket.dropna().unique()),
        )
        stage_table = combined[combined.lead_bucket == timing][
            [
                "airport",
                "stage",
                "n_days",
                "mae",
                "rmse",
                "market_exact_hit",
                "mae_gain_vs_raw",
            ]
        ].copy()
        for column in ["mae", "rmse"]:
            stage_table[column] = stage_table[column].map(format_temp)
        stage_table["mae_gain_vs_raw"] = stage_table.mae_gain_vs_raw.map(
            lambda value: format_temp(value, signed=True)
        )
        stage_table["market_exact_hit"] = stage_table.market_exact_hit.map(
            format_percent
        )
        st.dataframe(
            stage_table.rename(
                columns={
                    "airport": "Airport",
                    "stage": "Forecast stage",
                    "n_days": "Days",
                    "mae": "MAE",
                    "rmse": "RMSE",
                    "market_exact_hit": "Exact market bucket",
                    "mae_gain_vs_raw": "MAE gain vs raw",
                }
            ),
            hide_index=True,
            width="stretch",
        )

    diagnostics = live_factor_diagnostics(snapshots, station_actuals)
    if selected_airport and not diagnostics.empty:
        diagnostics = diagnostics[diagnostics.airport == selected_airport]
    st.subheader("Live-factor diagnostics")
    if diagnostics.empty:
        st.caption(
            "Live-factor diagnostics need completed METAR-conditioned snapshots."
        )
    else:
        factor_table = diagnostics.copy()
        for column in [
            "average_contribution_c",
            "cumulative_mae",
            "marginal_mae_gain",
        ]:
            factor_table[column] = factor_table[column].map(
                lambda value, metric=column: (
                    f"{float(value):+.3f} °C"
                    if metric != "cumulative_mae"
                    else f"{float(value):.3f} °C"
                )
            )
        st.dataframe(factor_table, hide_index=True, width="stretch")
        st.caption(
            "Positive marginal gain means the factor improved out-of-sample MAE "
            "at its current conservative coefficient; negative means it hurt."
        )

elif module == "Strategy performance":
    st.subheader("Strategy Performance · standardized $1 stakes")
    st.caption(
        "The former standalone synthetic D-1 $1 simulation has been removed. "
        "Real tracked asks and explicitly labelled historical price samples are "
        "kept together here, with one entry per strategy and airport-day."
    )
    edge_results = settled_signal_performance(signals, markets)
    probability_results = settled_probability_comparison(signals, markets)
    trade_scores = trading_airport_scorecards(edge_results, probability_results)
    canonical_strategies = canonical_strategy_checkpoints(strategies)
    consensus_results = settled_strategy_performance(canonical_strategies, markets)
    price_history_results = historical_price_strategy_simulation(
        historical_scored,
        markets,
    )

    if selected_airport:
        edge_results = edge_results[edge_results.airport == selected_airport]
        consensus_results = consensus_results[
            consensus_results.airport == selected_airport
        ]
        price_history_results = price_history_results[
            price_history_results.airport == selected_airport
        ]
        trade_scores = trade_scores[trade_scores.airport == selected_airport]

    if consensus_results.empty:
        st.info(
            "Fixed-checkpoint consensus results appear after a tracked market resolves."
        )
    else:
        summary = (
            consensus_results.groupby(
                ["airport", "strategy", "timing"],
                as_index=False,
            )
            .agg(
                entries=("market_id", "count"),
                hit_rate=("won", "mean"),
                pnl=("pnl", "sum"),
                average_buy_price=("buy_price", "mean"),
            )
        )
        summary["roi"] = summary.pnl / summary.entries
        drawdown_rows = []
        for keys, group in consensus_results.groupby(
            ["airport", "strategy", "timing"]
        ):
            airport_code, strategy_name, timing_name = keys
            cumulative = group.sort_values(
                ["target_date", "captured_at"]
            ).pnl.cumsum()
            drawdown_rows.append(
                {
                    "airport": airport_code,
                    "strategy": strategy_name,
                    "timing": timing_name,
                    "max_drawdown": float(
                        (cumulative.cummax() - cumulative).max()
                    ),
                }
            )
        summary = summary.merge(
            pd.DataFrame(drawdown_rows),
            on=["airport", "strategy", "timing"],
            how="left",
        )
        for column in ["hit_rate", "roi", "average_buy_price"]:
            summary[column] = summary[column].map(format_percent)
        for column in ["pnl", "max_drawdown"]:
            summary[column] = summary[column].map(
                lambda value: f"${float(value):+.2f}"
                if column == "pnl"
                else f"${float(value):.2f}"
            )
        st.dataframe(summary, hide_index=True, width="stretch")

    st.subheader("Possible-edge tracker")
    if edge_results.empty:
        st.caption("No Possible-edge entries have settled in this scope.")
    else:
        edge_summary = edge_results.groupby("airport", as_index=False).agg(
            entries=("market_id", "count"),
            hit_rate=("won", "mean"),
            pnl=("pnl", "sum"),
            average_edge=("edge", "mean"),
        )
        edge_summary["roi"] = edge_summary.pnl / edge_summary.entries
        for column in ["hit_rate", "average_edge", "roi"]:
            edge_summary[column] = edge_summary[column].map(format_percent)
        edge_summary["pnl"] = edge_summary.pnl.map(
            lambda value: f"${float(value):+.2f}"
        )
        st.dataframe(edge_summary, hide_index=True, width="stretch")

    st.subheader("Historical price simulation · lower evidence quality")
    if price_history_results.empty:
        st.caption(
            "No historical price samples are available. Forward tracked asks remain "
            "the preferred strategy evidence."
        )
    else:
        history_summary = price_history_results.groupby(
            ["airport", "strategy"], as_index=False
        ).agg(
            days=("target_date", "nunique"),
            hit_rate=("won", "mean"),
            pnl=("pnl", "sum"),
            average_price=("buy_price", "mean"),
        )
        history_summary["roi"] = history_summary.pnl / history_summary.days
        for column in ["hit_rate", "average_price", "roi"]:
            history_summary[column] = history_summary[column].map(format_percent)
        history_summary["pnl"] = history_summary.pnl.map(
            lambda value: f"${float(value):+.2f}"
        )
        st.dataframe(history_summary, hide_index=True, width="stretch")
        st.warning(
            "Historical CLOB points are observed trade-price samples, not old "
            "executable asks or reconstructed order books."
        )

elif module == "Universe & coverage":
    st.subheader("Polymarket temperature-market universe")
    if universe.empty:
        st.info(
            "Run workflow 4 once. It discovers active Polymarket temperature cities "
            "and records unmapped cities instead of silently dropping them."
        )
    else:
        active = universe[universe.active.fillna(False).astype(bool)].copy()
        u1, u2, u3 = st.columns(3)
        u1.metric("Active temperature cities", active.market_city.nunique())
        u2.metric("Mapped to a station", active.airport.notna().sum())
        u3.metric("Station mapping required", active.airport.isna().sum())
        active["last_seen_at"] = pd.to_datetime(
            active.last_seen_at, utc=True, errors="coerce"
        ).dt.strftime("%d.%m.%Y %H:%M UTC")
        st.dataframe(
            active[
                [
                    "display_name",
                    "market_city",
                    "airport",
                    "mapping_status",
                    "market_unit",
                    "latest_target_date",
                    "last_seen_at",
                    "resolution_source",
                ]
            ].rename(
                columns={
                    "display_name": "Market city",
                    "market_city": "Slug",
                    "airport": "Mapped station",
                    "mapping_status": "Mapping status",
                    "market_unit": "Unit",
                    "latest_target_date": "Latest target",
                    "last_seen_at": "Last discovered",
                    "resolution_source": "Resolution source",
                }
            ),
            hide_index=True,
            width="stretch",
        )

    coverage = pd.DataFrame(
        [
            {
                "airport": code,
                "name": details["name"],
                "tier": details.get("tier", "research"),
                "mapping": details.get("station_match", "candidate station"),
            }
            for code, details in catalog.items()
        ]
    )
    for frame, column, output in (
        (forecasts, "target_date", "forecast_days"),
        (snapshots, "target_date", "snapshot_days"),
        (station_actuals, "target_date", "actual_days"),
        (markets, "target_date", "market_days"),
    ):
        if not frame.empty:
            grouped = frame.groupby("airport", as_index=False).agg(
                **{output: (column, "nunique")}
            )
            coverage = coverage.merge(grouped, on="airport", how="left")
    fixed_counts = (
        fixed_snapshots.groupby(["airport", "timing"], as_index=False)
        .target_date.nunique()
        .pivot(index="airport", columns="timing", values="target_date")
        .reset_index()
        if not fixed_snapshots.empty
        else pd.DataFrame(columns=["airport"])
    )
    coverage = coverage.merge(fixed_counts, on="airport", how="left")
    for column in coverage.columns:
        if column.endswith("_days") or column in {
            "D-1 Evening · 20:00",
            "D0 Morning · 10:00",
        }:
            coverage[column] = pd.to_numeric(
                coverage[column], errors="coerce"
            ).fillna(0).astype(int)
    if selected_airport:
        coverage = coverage[coverage.airport == selected_airport]
    st.subheader("Research data coverage")
    st.dataframe(coverage, hide_index=True, width="stretch")
    st.caption(
        "Candidate mappings are research proxies until their station and reporting "
        "unit are checked against the market's official resolution rules. Unknown "
        "cities remain visible in the universe table for manual mapping."
    )

st.caption(
    f"Research view generated {datetime.now(timezone.utc):%d.%m.%Y %H:%M UTC}. "
    "Results are cached for 15 minutes; use Reload research data after a workflow update."
)
