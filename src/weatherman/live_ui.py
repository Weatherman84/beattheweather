from __future__ import annotations

from datetime import date

import pandas as pd

from .analytics import market_edges
from .live_display import (
    challenger_rows,
    forecast_chain_rows,
    forecast_driver_rows,
    strongest_driver_summary,
)


def _percent(value: object) -> str:
    return f"{float(value):.1%}" if value is not None and pd.notna(value) else "—"


def _temperature(value: object, digits: int = 1) -> str:
    return f"{float(value):.{digits}f} °C" if value is not None and pd.notna(value) else "—"


def _latest_actual(actuals: pd.DataFrame, target: date) -> float | None:
    if actuals.empty:
        return None
    frame = actuals.copy()
    frame["target_date"] = pd.to_datetime(frame.target_date, errors="coerce").dt.date
    frame = frame[frame.target_date == target]
    if frame.empty or frame.max_temp_c.dropna().empty:
        return None
    return float(frame.sort_values("target_date").iloc[-1].max_temp_c)


def _winning_market_label(markets: pd.DataFrame, actual_c: float) -> str:
    if markets.empty:
        return f"{round(actual_c)} °C"
    matches = markets[
        (markets.bucket_low_c.isna() | (markets.bucket_low_c <= actual_c))
        & (markets.bucket_high_c.isna() | (markets.bucket_high_c >= actual_c))
    ]
    return str(matches.iloc[0].bucket_label) if not matches.empty else f"{round(actual_c)} °C"


def _bucket_table(
    probabilities: dict[int, float],
    markets: pd.DataFrame,
    prior_probabilities: dict[str, float],
) -> pd.DataFrame:
    if markets.empty:
        result = pd.DataFrame(
            [
                {
                    "Bucket": f"{bucket} °C",
                    "Weatherman": probability,
                    "YES ask": None,
                    "Edge": None,
                    "Change": None,
                    "Status": "Forecast only",
                }
                for bucket, probability in probabilities.items()
            ]
        )
    else:
        comparison = market_edges(probabilities, markets)
        result = pd.DataFrame(
            {
                "Bucket": comparison.bucket_label.astype(str),
                "Weatherman": comparison.model_probability,
                "YES ask": comparison.buy_price,
                "Edge": comparison.edge,
                "Change": comparison.apply(
                    lambda row: (
                        float(row.model_probability)
                        - float(prior_probabilities[str(row.bucket_label)])
                        if str(row.bucket_label) in prior_probabilities
                        else None
                    ),
                    axis=1,
                ),
                "Status": comparison.signal,
            }
        )
    return result.sort_values("Weatherman", ascending=False).reset_index(drop=True)


def _format_bucket_table(frame: pd.DataFrame) -> pd.DataFrame:
    shown = frame.copy()
    for column in ("Weatherman", "YES ask", "Edge", "Change"):
        shown[column] = shown[column].map(_percent)
    return shown


def _today_memory_start(
    snapshots: pd.DataFrame,
    target: date,
    timezone_name: str,
) -> str | None:
    if snapshots.empty:
        return None
    frame = snapshots.copy()
    frame["target_date"] = pd.to_datetime(frame.target_date, errors="coerce").dt.date
    frame["captured_at"] = pd.to_datetime(frame.captured_at, utc=True, errors="coerce")
    frame = frame[
        (frame.target_date == target)
        & frame.status.isin(["PREDICTED", "WATCH", "CONFIRMED"])
    ]
    if frame.empty:
        return None
    detected = frame.captured_at.min().tz_convert(timezone_name)
    return f"{detected:%H:%M} local"


def render_compact_live_forecast(
    st,
    *,
    nowcast: object,
    trade_decision: object,
    latest_markets: pd.DataFrame,
    prior_probabilities: dict[str, float],
    target: date,
    timezone_name: str,
    actuals: pd.DataFrame,
    regime_memory_snapshots: pd.DataFrame,
) -> None:
    """Render the three-level live page: action, explanation, diagnostics."""
    probabilities = dict(getattr(nowcast, "probabilities"))
    day_status = getattr(nowcast, "day_status")
    decision_title = (
        f"{trade_decision.status} · {trade_decision.bucket_label}"
        if trade_decision.bucket_label
        else trade_decision.status
    )
    if trade_decision.status == "BET":
        st.success(f"Trading Cockpit · {decision_title}")
    elif trade_decision.status == "WATCH":
        st.warning(f"Trading Cockpit · {decision_title}")
    else:
        st.info(f"Trading Cockpit · {decision_title}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Weatherman probability", _percent(trade_decision.fair_probability))
    c2.metric("YES ask", _percent(trade_decision.buy_price))
    c3.metric("Executable edge", _percent(trade_decision.edge))
    c4.metric("Forecast confidence", f"{trade_decision.confidence}/100")

    driver_rows = forecast_driver_rows(nowcast)
    blocker = trade_decision.blockers[0] if trade_decision.blockers else None
    decision_line = strongest_driver_summary(driver_rows)
    if blocker:
        st.warning(f"Main blocker: {blocker}. {decision_line}")
    else:
        st.caption(decision_line)

    with st.expander("Why this recommendation?", expanded=False):
        for reason in trade_decision.reasons:
            st.write(f"• {reason}")
        for reason in trade_decision.blockers:
            st.write(f"• Blocker: {reason}")
        if trade_decision.probability_change is not None:
            st.caption(
                f"Selected-bucket probability changed {trade_decision.probability_change:+.1%} "
                "since the previous stored snapshot."
            )
        st.caption(
            "BET requires at least eight percentage points of executable edge, confidence "
            "of at least 65/100 and a bid-ask spread no wider than 12%."
        )

    if trade_decision.basket is not None:
        basket = trade_decision.basket
        with st.expander("Event-level edge basket", expanded=trade_decision.status == "BET"):
            b1, b2, b3, b4 = st.columns(4)
            b1.metric("Buckets", ", ".join(basket.bucket_labels))
            b2.metric("Fair probability", _percent(basket.fair_probability))
            b3.metric("Combined asks", _percent(basket.total_cost))
            b4.metric("Combined edge", _percent(basket.edge))
            if basket.warnings:
                st.warning("Basket blocked: " + " · ".join(basket.warnings))

    st.subheader("Forecast and day status")
    top_bucket = max(probabilities, key=probabilities.get)
    peak_at = getattr(nowcast, "expected_peak_at", None)
    peak_label = (
        pd.Timestamp(peak_at).tz_convert(timezone_name).strftime("%H:%M local")
        if peak_at is not None
        else "—"
    )
    f1, f2, f3, f4 = st.columns(4)
    f1.metric("Champion forecast", _temperature(nowcast.final_forecast_mean))
    f2.metric("Most likely bucket", f"{top_bucket} °C", _percent(probabilities[top_bucket]))
    f3.metric("Latest METAR", _temperature(nowcast.current_observed_temp))
    f4.metric("METAR max so far", _temperature(nowcast.observed_max, digits=0))
    f5, f6, f7, f8 = st.columns(4)
    f5.metric("Temperature trend", (
        f"{nowcast.heating_rate:+.1f} °C/h" if nowcast.heating_rate is not None else "—"
    ))
    f6.metric("Model warming left", (
        f"≤ {nowcast.remaining_rise_c:.1f} °C" if nowcast.remaining_rise_c is not None else "—"
    ))
    f7.metric("Expected model peak", peak_label)
    f8.metric("Day status", day_status.label)
    st.caption(day_status.explanation)

    st.markdown("**Forecast chain**")
    st.dataframe(pd.DataFrame(forecast_chain_rows(nowcast)), hide_index=True, width="stretch")
    st.caption(
        "Champion forecast is the current tradable final forecast. It includes model weighting, "
        "historical bias, active live regimes, live weather, TAF and day-status constraints."
    )

    completed_day = bool(day_status.is_locked or target < pd.Timestamp.now(tz=timezone_name).date())
    actual_c = (
        float(nowcast.observed_max)
        if completed_day and nowcast.observed_max is not None
        else _latest_actual(actuals, target) if completed_day else None
    )
    if actual_c is not None:
        outcome_bucket = _winning_market_label(latest_markets, actual_c)
        st.success(
            f"Outcome · actual maximum {actual_c:.1f} °C · winning bucket {outcome_bucket} · "
            f"Champion error {nowcast.final_forecast_mean - actual_c:+.1f} °C"
        )

    st.subheader("Relevant buckets")
    all_buckets = _bucket_table(probabilities, latest_markets, prior_probabilities)
    market_closed = bool(
        not latest_markets.empty
        and "closed" in latest_markets
        and latest_markets.closed.fillna(False).astype(bool).all()
    )
    if market_closed:
        all_buckets["Status"] = "Market closed"
    elif day_status.is_locked:
        all_buckets["Status"] = "Day complete"
    elif nowcast.metar_pending:
        all_buckets["Status"] = "METAR guard"
    elif nowcast.forecast_data_stale:
        all_buckets["Status"] = "Models stale"
    relevant = all_buckets.head(5)
    st.dataframe(_format_bucket_table(relevant), hide_index=True, width="stretch")
    if latest_markets.empty:
        st.caption("No matching Polymarket market is stored; market price and edge stay blank.")
    with st.expander("Complete bucket distribution", expanded=False):
        st.dataframe(_format_bucket_table(all_buckets), hide_index=True, width="stretch")
        if day_status.minimum_bucket is not None:
            st.caption(
                f"Buckets below {day_status.minimum_bucket} °C are removed because the stored "
                f"METAR maximum is already {nowcast.observed_max:.0f} °C."
            )

    st.subheader("Forecast Drivers")
    st.dataframe(pd.DataFrame(driver_rows), hide_index=True, width="stretch")
    future = getattr(nowcast, "future_outlook")
    if getattr(
        future,
        "reheating_watch",
        getattr(future, "post_rain_reheating_watch", False),
    ):
        st.warning(f"{future.status}: {future.summary}")
    else:
        st.caption(f"Future outlook · {future.status}: {future.summary}")

    variants = challenger_rows(nowcast)
    fixed_variants = [row for row in variants if row["Variant"].startswith("Without ")]
    research_variants = [
        row
        for row in variants
        if not row["Variant"].startswith("Without ")
        and row["Variant"] != "Analog Memory Challenger"
    ]
    memory = getattr(nowcast, "regime_memory", None)

    with st.expander("Live regimes and their counterfactual effect", expanded=False):
        states = []
        if memory is not None:
            states = [
                state
                for state in memory.regimes
                if state.source != "learned" and state.status != "REJECTED"
            ]
        if states:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Regime": state.name,
                            "Status": state.status,
                            "Confidence": f"{state.confidence}/100",
                            "Champion role": state.champion_effect,
                            "Explanation": state.explanation,
                        }
                        for state in states
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("No explained fixed regime is currently active or on watch.")
        if fixed_variants:
            st.markdown("**Same-time alternatives without each active factor**")
            st.dataframe(pd.DataFrame(fixed_variants), hide_index=True, width="stretch")
        detected = _today_memory_start(regime_memory_snapshots, target, timezone_name)
        if detected:
            st.caption(f"First regime-memory detection today: {detected}.")

    taf = getattr(nowcast, "taf_guidance", None)
    with st.expander("TAF details", expanded=False):
        if taf is None:
            st.caption("No stored TAF currently covers the selected date.")
        else:
            local_issue = pd.Timestamp(taf.issue_time).tz_convert(timezone_name)
            local_tx = (
                pd.Timestamp(taf.max_temp_at).tz_convert(timezone_name)
                if taf.max_temp_at is not None
                else None
            )
            t1, t2, t3 = st.columns(3)
            t1.metric("TAF TX", _temperature(taf.max_temp_c, digits=0), (
                f"at {local_tx:%H:%M} local" if local_tx is not None else "Conditions only"
            ))
            t2.metric("Agreement", taf.agreement)
            t3.metric("Issued", f"{local_issue:%d.%m. %H:%M}", f"{taf.age_hours:.1f} h old")
            st.caption(
                f"Champion effect: center {taf.center_adjustment_c:+.2f} °C · "
                f"spread +{taf.spread_addition_c:.2f} °C."
            )
            for signal in taf.signals:
                st.write(f"• {signal}")
            if taf.change_summary:
                st.info(f"Change from previous TAF: {taf.change_summary}.")
            st.code(taf.raw_taf, language=None, wrap_lines=True)

    with st.expander("Historical Analog Challenger · research only", expanded=False):
        if memory is None:
            st.caption("No regime-memory assessment is available.")
        else:
            a1, a2, a3, a4 = st.columns(4)
            a1.metric("Comparable days", str(memory.analog_count))
            a2.metric("Best similarity", _percent(memory.best_similarity))
            a3.metric("Shadow suggestion", f"{memory.center_adjustment_c:+.2f} °C")
            a4.metric(
                "OOS gate",
                memory.promotion.status,
                f"{memory.promotion.oos_days}/{memory.promotion.minimum_oos_days} days",
            )
            st.caption(memory.explanation)
            if memory.analogs:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Date": analog.target_date,
                                "Similarity": f"{analog.similarity:.0%}",
                                "Forecast": f"{analog.forecast_c:.1f} °C",
                                "Actual": f"{analog.actual_c:.1f} °C",
                                "Residual": f"{analog.residual_c:+.1f} °C",
                                "Matched on": ", ".join(analog.matched_on),
                            }
                            for analog in memory.analogs
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                )
            else:
                st.caption("No settled prior day clears the similarity threshold yet.")
            st.caption(memory.promotion.explanation)

    with st.expander("Other research-only challengers", expanded=False):
        if research_variants:
            st.dataframe(pd.DataFrame(research_variants), hide_index=True, width="stretch")
        else:
            st.caption("No research-only alternative is active at this timestamp.")
        st.caption(
            "Research-only alternatives never change the Champion or BET/WATCH/NO BET status."
        )

    with st.expander("Advanced diagnostics", expanded=False):
        contributions = pd.DataFrame(
            [
                {
                    "Live factor": name.replace("_", " ").title(),
                    "Center contribution": f"{float(value):+.2f} °C",
                }
                for name, value in nowcast.adjustment_contributions.items()
                if name != "total"
            ]
        )
        st.markdown("**Center contributions**")
        st.dataframe(contributions, hide_index=True, width="stretch")
        st.caption(
            f"Bias/regime base {nowcast.corrected.mean:.2f} °C → live weather "
            f"{nowcast.adjustment_contributions['total']:+.2f} °C → live adjusted "
            f"{nowcast.metar_conditioned_mean:.2f} °C → TAF {nowcast.taf_adjustment_c:+.2f} °C "
            f"→ Champion {nowcast.final_forecast_mean:.2f} °C."
        )

        st.markdown("**Model maxima, weights and freshness**")
        model_table = nowcast.current[
            [
                "model",
                "max_temp_c",
                "corrected_max",
                "model_weight",
                "d1_bias",
                "age_minutes",
            ]
        ].copy()
        model_table["model_weight"] = model_table.model_weight.map(lambda value: f"{value:.1%}")
        model_table["d1_bias"] = model_table.d1_bias.map(lambda value: f"{value:+.2f} °C")
        model_table["age_minutes"] = model_table.age_minutes.map(lambda value: f"{value:.0f}")
        model_table = model_table.rename(
            columns={
                "model": "Model",
                "max_temp_c": "Raw max °C",
                "corrected_max": "Corrected max °C",
                "model_weight": "Weight",
                "d1_bias": "Applied D-1 bias",
                "age_minutes": "Fetch age min",
            }
        )
        st.dataframe(model_table, hide_index=True, width="stretch")

        st.markdown("**Confidence and Heat Spike diagnostics**")
        st.caption(
            f"Heat Spike {nowcast.heat.status} ({nowcast.heat.score}/100). The former Heat "
            "Spike table is retained here only as a diagnostic; its displayed adjustment is "
            "the combined live-weather adjustment, not a separate additive Heat Spike factor."
        )
        for signal in nowcast.heat.signals:
            st.write(f"• {signal}")
        confidence = pd.DataFrame(
            [
                {"Confidence factor": name.replace("_", " ").title(), "Score": score}
                for name, score in nowcast.confidence_factors.items()
            ]
        )
        st.dataframe(confidence, hide_index=True, width="stretch")

        st.markdown("**Stored raw features · developer diagnostics**")
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
                for name, value in nowcast.live_features.items()
            ]
        )
        st.dataframe(features, hide_index=True, width="stretch")
