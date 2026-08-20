"""Pure portfolio-risk and position-sizing calculations.

The module has no IBKR or FastAPI dependency. Callers provide current positions and
aligned daily return arrays, which makes the calculations testable and reusable.
"""

from __future__ import annotations

from math import floor
from typing import Mapping, Sequence

import numpy as np
import pandas as pd
from skfolio.measures import RiskMeasure
from skfolio.optimization import HierarchicalRiskParity

TRADING_DAYS = 252


def _clean_series(values: Sequence[float]) -> pd.Series:
    # Preserve a supplied Series index (normally trading dates from IBKR). Plain
    # arrays retain a RangeIndex for tests and other callers.
    series = pd.Series(values)
    return series.astype(float).replace([np.inf, -np.inf], np.nan).dropna()


def _returns_frame(
    returns_by_ticker: Mapping[str, Sequence[float]],
    min_observations: int,
) -> tuple[pd.DataFrame, list[str]]:
    cleaned = {ticker: _clean_series(values) for ticker, values in returns_by_ticker.items()}
    excluded = sorted(ticker for ticker, values in cleaned.items() if len(values) < min_observations)
    eligible = {ticker: values for ticker, values in cleaned.items() if len(values) >= min_observations}
    if len(eligible) < 2:
        raise ValueError("At least two positions need sufficient price history")

    if all(isinstance(values.index, pd.DatetimeIndex) for values in eligible.values()):
        frame = pd.concat(eligible, axis=1, join="inner").dropna()
    else:
        common_length = min(len(values) for values in eligible.values())
        frame = pd.DataFrame({ticker: values.iloc[-common_length:].to_numpy() for ticker, values in eligible.items()}).dropna()
    if len(frame) < min_observations:
        raise ValueError("Insufficient overlapping return history")
    return frame, excluded


def _portfolio_returns(frame: pd.DataFrame, positions: Sequence[dict]) -> pd.Series:
    raw = {p["code"]: max(float(p.get("val_nzd", 0)), 0) for p in positions if p["code"] in frame.columns}
    invested = sum(raw.values())
    if invested <= 0:
        raise ValueError("Portfolio market value must be positive")
    weights = pd.Series({ticker: value / invested for ticker, value in raw.items()})
    return frame[weights.index].mul(weights, axis=1).sum(axis=1)


def _max_drawdown(returns: pd.Series) -> float:
    wealth = (1 + returns).cumprod()
    drawdown = wealth / wealth.cummax() - 1
    return float(drawdown.min())


def build_optimization_report(
    positions: Sequence[dict],
    returns_by_ticker: Mapping[str, Sequence[float]],
    total_nav: float,
    cash_nzd: float,
    max_weight_pct: float = 15,
    min_observations: int = 60,
) -> dict:
    """Build current-book risk metrics and long-only HRP comparison weights."""
    frame, excluded = _returns_frame(returns_by_ticker, min_observations)
    eligible_codes = [p["code"] for p in positions if p["code"] in frame.columns]
    frame = frame[eligible_codes]

    # A uniform cap below 1/N is mathematically infeasible. Relax only to the
    # smallest feasible cap for small books; normal 10-20 name portfolios retain
    # the user-selected cap.
    feasible_max_weight = max(max_weight_pct / 100, 1 / len(frame.columns))
    try:
        optimizer = HierarchicalRiskParity(
            risk_measure=RiskMeasure.STANDARD_DEVIATION,
            min_weights=0.0,
            max_weights=feasible_max_weight,
        )
        optimizer.fit(frame)
        hrp = pd.Series(optimizer.weights_, index=frame.columns)
    except (ValueError, IndexError):
        # Some degenerate correlation matrices (especially two-asset books) cannot
        # form a useful hierarchy. Inverse volatility is the closest risk-only
        # fallback and keeps the endpoint usable rather than fabricating a view.
        inverse_vol = 1 / frame.std(ddof=1).replace(0, np.nan)
        hrp = inverse_vol.fillna(0)
    # Numerical fallbacks can leave tiny normalization differences.
    hrp = hrp.clip(lower=0)
    hrp = hrp / hrp.sum()

    portfolio_returns = _portfolio_returns(frame, positions)
    annual_return = float(portfolio_returns.mean() * TRADING_DAYS)
    annual_volatility = float(portfolio_returns.std(ddof=1) * np.sqrt(TRADING_DAYS))
    downside = portfolio_returns[portfolio_returns < 0]
    downside_vol = float(downside.std(ddof=1) * np.sqrt(TRADING_DAYS)) if len(downside) > 1 else 0.0
    var_95 = float(np.quantile(portfolio_returns, 0.05))
    tail = portfolio_returns[portfolio_returns <= var_95]
    cvar_95 = float(tail.mean()) if len(tail) else var_95

    current_invested = sum(max(float(p.get("val_nzd", 0)), 0) for p in positions)
    current_weights = {
        p["code"]: (max(float(p.get("val_nzd", 0)), 0) / current_invested if current_invested else 0)
        for p in positions
    }
    concentration = sum(weight * weight for weight in current_weights.values())
    correlation = frame.corr()
    upper = correlation.where(np.triu(np.ones(correlation.shape), k=1).astype(bool)).stack()

    rows = []
    for position in positions:
        code = position["code"]
        target = float(hrp[code] * 100) if code in hrp else None
        current = current_weights.get(code, 0) * 100
        rows.append({
            "code": code,
            "stock_name": position.get("stock_name", code),
            "current_weight_pct": round(current, 2),
            "hrp_weight_pct": round(target, 2) if target is not None else None,
            "gap_pct": round(target - current, 2) if target is not None else None,
            "current_value_nzd": round(float(position.get("val_nzd", 0)), 2),
            "annualized_volatility_pct": round(float(frame[code].std(ddof=1) * np.sqrt(TRADING_DAYS) * 100), 2) if code in frame else None,
        })
    rows.sort(key=lambda row: abs(row["gap_pct"]) if row["gap_pct"] is not None else -1, reverse=True)

    return {
        "method": "hierarchical_risk_parity",
        "as_of_observations": len(frame),
        "metrics": {
            "annualized_return_pct": round(annual_return * 100, 2),
            "annualized_volatility_pct": round(annual_volatility * 100, 2),
            "downside_volatility_pct": round(downside_vol * 100, 2),
            "max_drawdown_pct": round(_max_drawdown(portfolio_returns) * 100, 2),
            "daily_var_95_pct": round(var_95 * 100, 2),
            "daily_cvar_95_pct": round(cvar_95 * 100, 2),
            "effective_positions": round(1 / concentration, 2) if concentration else 0,
            "mean_pairwise_correlation": round(float(upper.mean()), 3) if len(upper) else 0,
            "cash_weight_pct": round((cash_nzd / total_nav * 100) if total_nav else 0, 2),
        },
        "coverage": {
            "total_positions": len(positions),
            "used_positions": len(frame.columns),
            "excluded_tickers": excluded,
        },
        "positions": rows,
        "warnings": [
            "HRP is a risk allocation reference, not a return forecast or trade instruction.",
            "Historical correlations and volatility can change abruptly, especially in thematic portfolios.",
        ],
    }


def size_candidate_position(
    positions: Sequence[dict],
    existing_returns: Mapping[str, Sequence[float]],
    candidate_code: str,
    candidate_returns: Sequence[float],
    expected_return_pct: float,
    conviction: int,
    total_nav: float,
    available_cash_nzd: float,
    current_position_nzd: float,
    candidate_price_nzd: float,
    max_position_pct: float = 15,
    risk_free_rate_pct: float = 4.5,
    min_observations: int = 60,
) -> dict:
    """Blend fractional Kelly with HRP, then enforce cash and position caps.

    Conviction is a 1-5 scalar. It scales the final risk-informed target rather
    than pretending to be a probability estimate.
    """
    if conviction < 1 or conviction > 5:
        raise ValueError("Conviction must be between 1 and 5")
    if total_nav <= 0 or candidate_price_nzd <= 0:
        raise ValueError("NAV and candidate price must be positive")

    candidate = _clean_series(candidate_returns)
    if len(candidate) < min_observations:
        raise ValueError(f"Candidate needs at least {min_observations} daily returns")

    combined = dict(existing_returns)
    combined[candidate_code] = candidate.to_numpy()
    candidate_positions = [p for p in positions if p["code"] != candidate_code]
    candidate_positions.append({
        "code": candidate_code,
        "stock_name": candidate_code,
        # 0.0 for a new position: HRP weights come from the returns frame, not
        # val_nzd, so the candidate still gets an HRP row while the current-book
        # metrics reflect the actual holdings (no phantom $1 position).
        "val_nzd": max(current_position_nzd, 0.0),
    })
    report = build_optimization_report(
        candidate_positions,
        combined,
        total_nav=total_nav,
        cash_nzd=available_cash_nzd,
        max_weight_pct=max_position_pct,
        min_observations=min_observations,
    )
    row = next(item for item in report["positions"] if item["code"] == candidate_code)
    hrp_weight = float(row["hrp_weight_pct"])

    annual_variance = float(candidate.var(ddof=1) * TRADING_DAYS)
    excess_return = (expected_return_pct - risk_free_rate_pct) / 100
    raw_kelly_pct = max(excess_return / annual_variance * 100, 0) if annual_variance > 0 else 0
    half_kelly_pct = raw_kelly_pct * 0.5
    conviction_multiplier = conviction / 5
    blended_target_pct = conviction_multiplier * (0.35 * half_kelly_pct + 0.65 * hrp_weight)
    target_pct = min(max(blended_target_pct, 0), max_position_pct)

    current_weight_pct = current_position_nzd / total_nav * 100
    target_value_nzd = target_pct / 100 * total_nav
    unconstrained_trade = target_value_nzd - current_position_nzd
    suggested_trade_nzd = max(min(unconstrained_trade, available_cash_nzd), 0)
    shares = floor(suggested_trade_nzd / candidate_price_nzd)
    executable_trade_nzd = shares * candidate_price_nzd

    return {
        "candidate_code": candidate_code,
        "expected_return_pct": round(expected_return_pct, 2),
        "conviction": conviction,
        "annualized_volatility_pct": round(float(candidate.std(ddof=1) * np.sqrt(TRADING_DAYS) * 100), 2),
        "raw_kelly_pct": round(raw_kelly_pct, 2),
        "half_kelly_pct": round(half_kelly_pct, 2),
        "hrp_weight_pct": round(hrp_weight, 2),
        "suggested_total_weight_pct": round(target_pct, 2),
        "current_weight_pct": round(current_weight_pct, 2),
        "suggested_trade_nzd": round(executable_trade_nzd, 2),
        "suggested_shares": shares,
        "post_trade_weight_pct": round((current_position_nzd + executable_trade_nzd) / total_nav * 100, 2),
        "requires_sale": unconstrained_trade < 0,
        "cash_limited": unconstrained_trade > available_cash_nzd,
        "max_position_pct": max_position_pct,
        "warnings": [
            "Expected return is your input, not a model forecast.",
            "Kelly is highly sensitive to expected return and should be treated as a ceiling, not a mandate.",
        ],
    }
