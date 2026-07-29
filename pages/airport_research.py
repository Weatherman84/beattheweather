from __future__ import annotations

import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
SRC = APP_ROOT / "src"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from runtime_bootstrap import discard_stale_weatherman_modules

discard_stale_weatherman_modules("10.2.0")

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import select

from weatherman.analytics import (
    fixed_decision_snapshots,
    forecast_ladder_frame,
    historical_d1_ladder,
    historical_price_strategy_simulation,
    live_factor_diagnostics,
    preferred_station_actuals,
    settled_signal_performance,
    settled_shadow_performance,
    settled_strategy_performance,
)
from weatherman.db import (
    AirportMarketUniverse,
    DailyActual,
    Forecast,
    ForecastSnapshot,
    MarketSnapshot,
    Observation,
    Session,
    ShadowEvaluation,
    SignalSnapshot,
    StrategySnapshot,
    init_db,
    refresh_database_connections,
)
from weatherman.catalog import research_airports
from weatherman.navigation import render_app_navigation
from weatherman.research import filter_target_window, market_timing_metrics


st.set_page_config(
    page_title="Weatherman · Airport Research",
    page_icon="📊",
    layout="wide",
)
render_app_navigation(st)

refresh_database_connections()
init_db()
catalog = research_airports()
timezone_by_airport = {
    code: details["timezone"] for code, details in catalog.items()
}


def scoped_statement(
    model: type,
    airport_codes: tuple[str, ...],
    *,
    earliest_target: date | None = None,
    earliest_observation: datetime | None = None,
):
    statement = select(model)
    if airport_codes and hasattr(model, "airport"):
        statement = statement.where(model.airport.in_(airport_codes))
    if earliest_target is not None and hasattr(model, "target_date"):
        statement = statement.where(model.target_date >= earliest_target)
    if earliest_observation is not None and hasattr(model, "observed_at"):
        statement = statement.where(model.observed_at >= earliest_observation)
    return statement


@st.cache_data(show_spinner=False, ttl=900)
def load_weather_research_data(
    airport_codes: tuple[str, ...],
    earliest_target: date,
) -> dict[str, pd.DataFrame]:
    earliest_observation = datetime.combine(
        earliest_target - timedelta(days=1),
        time.min,
        tzinfo=timezone.utc,
    )
    with Session() as session:
        return {
            "forecasts": pd.read_sql(
                scoped_statement(
                    Forecast,
                    airport_codes,
                    earliest_target=earliest_target,
                ).where(Forecast.horizon == "D-1"),
                session.bind,
            ),
            "actuals": pd.read_sql(
                scoped_statement(
                    DailyActual,
                    airport_codes,
                    earliest_target=earliest_target,
                ),
                session.bind,
            ),
            "observations": pd.read_sql(
                scoped_statement(
                    Observation,
                    airport_codes,
                    earliest_observation=earliest_observation,
                ),
                session.bind,
            ),
            "snapshots": pd.read_sql(
                scoped_statement(
                    ForecastSnapshot,
                    airport_codes,
                    earliest_target=earliest_target,
                ),
                session.bind,
            ),
        }


@st.cache_data(show_spinner=False, ttl=900)
def load_strategy_research_data(
    airport_codes: tuple[str, ...],
    earliest_target: date,
) -> dict[str, pd.DataFrame]:
    data = load_weather_research_data(airport_codes, earliest_target)
    with Session() as session:
        data.update(
            {
                "markets": pd.read_sql(
                    scoped_statement(
                        MarketSnapshot,
                        airport_codes,
                        earliest_target=earliest_target,
                    ),
                    session.bind,
                ),
                "signals": pd.read_sql(
                    scoped_statement(
                        SignalSnapshot,
                        airport_codes,
                        earliest_target=earliest_target,
                    ),
                    session.bind,
                ),
                "strategies": pd.read_sql(
                    scoped_statement(
                        StrategySnapshot,
                        airport_codes,
                        earliest_target=earliest_target,
                    ),
                    session.bind,
                ),
                "shadows": pd.read_sql(
                    scoped_statement(
                        ShadowEvaluation,
                        airport_codes,
                        earliest_target=earliest_target,
                    ),
                    session.bind,
                ),
            }
        )
    return data


@st.cache_data(show_spinner=False, ttl=900)
def load_universe_research_data(
    airport_codes: tuple[str, ...],
    earliest_target: date,
) -> dict[str, pd.DataFrame]:
    data = load_weather_research_data(airport_codes, earliest_target)
    with Session() as session:
        data.update(
            {
                "markets": pd.read_sql(
                    scoped_statement(
                        MarketSnapshot,
                        airport_codes,
                        earliest_target=earliest_target,
                    ),
                    session.bind,
                ),
                "universe": pd.read_sql(
                    select(AirportMarketUniverse),
                    session.bind,
                ),
            }
        )
    return data


def format_percent(value: object) -> str:
    return f"{float(value):.1%}" if pd.notna(value) else "—"


def format_temp(value: object, *, signed: bool = False) -> str:
    if pd.isna(value):
        return "—"
    return f"{float(value):+.2f} °C" if signed else f"{float(value):.2f} °C"


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


@st.cache_data(show_spinner=False, ttl=900)
def calculate_timing_bundle(
    airport_codes: tuple[str, ...],
    window_days: int,
    *,
    include_live: bool = False,
    include_diagnostics: bool = False,
) -> dict[str, pd.DataFrame]:
    # The extra history is used only to calibrate walk-forward bias and weights.
    earliest_target = (
        datetime.now(timezone.utc).date()
        - timedelta(days=window_days + 120)
    )
    data = load_weather_research_data(airport_codes, earliest_target)
    local_timezones = {
        code: timezone_by_airport[code]
        for code in airport_codes
        if code in timezone_by_airport
    }
    station_actuals = preferred_station_actuals(
        data["observations"],
        data["actuals"],
        local_timezones,
    )
    historical_scored = filter_target_window(
        historical_d1_ladder(data["forecasts"], station_actuals),
        window_days,
    )
    fixed_snapshots = fixed_decision_snapshots(
        data["snapshots"],
        local_timezones,
    )
    fixed_scored = filter_target_window(
        forecast_ladder_frame(fixed_snapshots, station_actuals),
        window_days,
    )
    result = {
        "historical_scored": historical_scored,
        "historical_metrics": market_timing_metrics(
            historical_scored,
            catalog,
        ),
        "fixed_snapshots": fixed_snapshots,
        "fixed_metrics": market_timing_metrics(fixed_scored, catalog),
    }
    if include_live:
        live_scored = filter_target_window(
            forecast_ladder_frame(data["snapshots"], station_actuals),
            window_days,
        )
        if not live_scored.empty:
            live_scored = live_scored[
                live_scored.lead_bucket.str.startswith("D0 live", na=False)
            ]
        result["live_metrics"] = market_timing_metrics(live_scored, catalog)
    if include_diagnostics:
        result["diagnostics"] = live_factor_diagnostics(
            filter_target_window(data["snapshots"], window_days),
            station_actuals,
        )
    return result


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
        "Airport Analysis",
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
airport_codes = (
    (selected_airport,)
    if selected_airport
    else tuple(sorted(catalog))
)
timing_bundle: dict[str, pd.DataFrame] = {}
if module in {"Airport Analysis", "Accuracy by timing", "Forecast stages"}:
    with st.spinner(
        f"Calculating {module} for "
        f"{selected_airport or f'{len(airport_codes)} airports'}…"
    ):
        timing_bundle = calculate_timing_bundle(
            airport_codes,
            window_days,
            include_live=module == "Accuracy by timing",
            include_diagnostics=module == "Forecast stages",
        )
historical_metrics = timing_bundle.get("historical_metrics", pd.DataFrame())
fixed_metrics = timing_bundle.get("fixed_metrics", pd.DataFrame())


if module == "Airport Analysis":
    st.subheader("Airport predictability leaderboard")
    st.caption(
        "D-1 · 24h lead is a standardized meteorological comparison. "
        "D-1 Evening and D0 Morning use the latest snapshot known at or before "
        "20:00 on the previous local day and 10:00 on the target day. A snapshot "
        "after a cut-off is never used."
    )
    base = pd.DataFrame(
        [
            {
                "airport": code,
                "name": details["name"],
                "station_status": details.get("station_match", "candidate station"),
                "unit": details.get("market_unit", "C"),
            }
            for code, details in catalog.items()
            if code in airport_codes
        ]
    )
    window = (
        historical_metrics[
            (
                historical_metrics.stage
                == "Bias corrected · performance weighted"
            )
            & (historical_metrics.timing == "D-1 · 24h lead")
        ].copy()
        if not historical_metrics.empty
        else pd.DataFrame()
    )
    if not window.empty:
        window["mae_score"] = 100 / (1 + (window.mae / 1.0) ** 2)
        window["rmse_score"] = 100 / (1 + (window.rmse / 1.25) ** 2)
        window["raw_score"] = (
            0.35 * window.mae_score
            + 0.20 * window.rmse_score
            + 0.25 * window.exact_hit * 100
            + 0.20 * window.within_1c * 100
        )
        window["reliability"] = (window.n_days / 30).clip(upper=1.0)
        window["forecast_score"] = (
            50 + window.reliability * (window.raw_score - 50)
        ).clip(lower=0, upper=100)
        window["data_quality"] = window.n_days.map(
            lambda count: (
                "Strong"
                if count >= 90
                else "Moderate"
                if count >= 30
                else "Limited"
            )
        )
        window = window[
            [
                "airport",
                "n_days",
                "mae",
                "rmse",
                "exact_hit",
                "within_1c",
                "forecast_score",
                "data_quality",
            ]
        ].rename(columns={"n_days": "n"})
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
    live_metrics = timing_bundle.get("live_metrics", pd.DataFrame())
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

    diagnostics = timing_bundle.get("diagnostics", pd.DataFrame())
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
    st.subheader("Strategy Performance · forward and historical paper tests")
    st.caption(
        "The former standalone synthetic D-1 $1 simulation has been removed. "
        "Real tracked asks and explicitly labelled historical price samples are "
        "kept together here, with one entry per strategy and airport-day."
    )
    with st.expander("What the four tables mean"):
        st.markdown(
            """
| Table | What is hypothetically bought? | Entry timing and price |
|---|---|---|
| **Fixed-checkpoint top-bucket benchmark** | The highest-probability bucket from each forecast stage, whether or not it has positive edge | D-1 Evening at 20:00 and D0 Morning at 10:00 local airport time; first journaled entry at the checkpoint's recorded YES ask |
| **Net-edge shadow watcher** | Every first SHADOW BET after checking the full YES ask book for a $10 paper stake | During the live critical window; includes actual depth, slippage, the weather-market taker fee and a 2-point safety margin |
| **Possible-edge tracker** | Every market bucket whose Weatherman probability first exceeds its current YES ask by at least 8 percentage points | The first recorded Possible-edge signal for that bucket; D-1, D0 and Live signals may all occur |
| **Historical price simulation** | The rounded bucket from the reconstructed D-1 forecast | D-1 at 20:00 local airport time; nearest stored historical trade-price sample, not an executable old ask |
"""
        )
        st.caption(
            "The tables can therefore disagree without a calculation error. The "
            "top-bucket benchmark, shadow watcher and Possible-edge tracker may "
            "buy different buckets, and one low-priced winner can produce positive P/L despite "
            "a low hit rate. Historical price results have lower evidence quality "
            "because an old trade-price sample is not a reconstructed order book."
        )
    earliest_target = (
        datetime.now(timezone.utc).date()
        - timedelta(days=window_days + 120)
    )
    with st.spinner(
        f"Loading strategy data for "
        f"{selected_airport or f'{len(airport_codes)} airports'}…"
    ):
        strategy_data = load_strategy_research_data(
            airport_codes,
            earliest_target,
        )
    markets = strategy_data["markets"]
    signals = strategy_data["signals"]
    strategies = strategy_data["strategies"]
    shadows = strategy_data["shadows"]
    local_timezones = {
        code: timezone_by_airport[code]
        for code in airport_codes
        if code in timezone_by_airport
    }
    station_actuals = preferred_station_actuals(
        strategy_data["observations"],
        strategy_data["actuals"],
        local_timezones,
    )
    historical_scored = filter_target_window(
        historical_d1_ladder(
            strategy_data["forecasts"],
            station_actuals,
        ),
        window_days,
    )
    edge_results = settled_signal_performance(signals, markets)
    shadow_results = settled_shadow_performance(shadows, markets)
    canonical_strategies = canonical_strategy_checkpoints(strategies)
    consensus_results = settled_strategy_performance(canonical_strategies, markets)
    price_history_results = historical_price_strategy_simulation(
        historical_scored,
        markets,
    )

    if selected_airport:
        edge_results = (
            edge_results[edge_results.airport == selected_airport]
            if "airport" in edge_results.columns
            else edge_results.iloc[0:0]
        )
        shadow_results = (
            shadow_results[shadow_results.airport == selected_airport]
            if "airport" in shadow_results.columns
            else shadow_results.iloc[0:0]
        )
        consensus_results = (
            consensus_results[consensus_results.airport == selected_airport]
            if "airport" in consensus_results.columns
            else consensus_results.iloc[0:0]
        )
        price_history_results = (
            price_history_results[
                price_history_results.airport == selected_airport
            ]
            if "airport" in price_history_results.columns
            else price_history_results.iloc[0:0]
        )

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

    st.subheader("Net-edge shadow watcher · $10 all-in paper stakes")
    if shadow_results.empty:
        recorded_shadow_bets = (
            int((shadows.status == "SHADOW BET").sum())
            if not shadows.empty and "status" in shadows
            else 0
        )
        st.caption(
            f"No shadow entry has settled in this scope yet. "
            f"{recorded_shadow_bets} SHADOW BET checkpoint(s) are currently journaled."
        )
    else:
        shadow_summary = shadow_results.groupby("airport", as_index=False).agg(
            entries=("market_id", "count"),
            hit_rate=("won", "mean"),
            pnl=("pnl", "sum"),
            average_net_edge=("net_edge", "mean"),
            average_all_in_price=("all_in_price", "mean"),
            average_slippage=("slippage", "mean"),
        )
        shadow_summary["roi"] = (
            shadow_results.groupby("airport").pnl.sum().to_numpy()
            / shadow_results.groupby("airport").total_cost_usdc.sum().to_numpy()
        )
        for column in [
            "hit_rate",
            "average_net_edge",
            "average_all_in_price",
            "average_slippage",
            "roi",
        ]:
            shadow_summary[column] = shadow_summary[column].map(format_percent)
        shadow_summary["pnl"] = shadow_summary.pnl.map(
            lambda value: f"${float(value):+.2f}"
        )
        st.dataframe(shadow_summary, hide_index=True, width="stretch")
        st.caption(
            "Only the first SHADOW BET per market bucket is settled. The stored "
            "share count already reflects the full order-book walk and estimated "
            "taker fee; no real order was placed."
        )

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
    earliest_target = (
        datetime.now(timezone.utc).date()
        - timedelta(days=window_days - 1)
    )
    with st.spinner(
        f"Loading coverage for "
        f"{selected_airport or f'{len(airport_codes)} airports'}…"
    ):
        coverage_data = load_universe_research_data(
            airport_codes,
            earliest_target,
        )
    forecasts = coverage_data["forecasts"]
    actuals = coverage_data["actuals"]
    observations = coverage_data["observations"]
    snapshots = coverage_data["snapshots"]
    markets = coverage_data["markets"]
    universe = coverage_data["universe"]
    local_timezones = {
        code: timezone_by_airport[code]
        for code in airport_codes
        if code in timezone_by_airport
    }
    station_actuals = preferred_station_actuals(
        observations,
        actuals,
        local_timezones,
    )
    fixed_snapshots = fixed_decision_snapshots(
        snapshots,
        local_timezones,
    )
    st.subheader("Polymarket temperature-market universe")
    if universe.empty:
        st.info(
            "Run workflow 4 once. It discovers active Polymarket temperature cities "
            "and records unmapped cities instead of silently dropping them."
        )
    else:
        active = universe[universe.active.fillna(False).astype(bool)].copy()
        if selected_airport:
            active = active[active.airport == selected_airport]
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
            if code in airport_codes
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
