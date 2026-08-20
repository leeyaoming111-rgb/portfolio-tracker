import { useCallback, useEffect, useState } from "react";

const API_BASE = "http://localhost:8000/api";
const fmt = (n, d = 2) => n == null || Number.isNaN(Number(n)) ? "—" : Number(n).toLocaleString("en-NZ", { minimumFractionDigits: d, maximumFractionDigits: d });

export default function PortfolioOptimization() {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ ticker: "", expected_return_pct: 20, conviction: 3, max_position_pct: 15, risk_free_rate_pct: 4.5 });
  const [sizing, setSizing] = useState(null);
  const [sizingBusy, setSizingBusy] = useState(false);

  // Fetch with a hard timeout so a stalled backend (e.g. IBKR rate limits)
  // surfaces as an error instead of "Calculating…" forever.
  const fetchWithTimeout = async (url, options = {}, timeoutMs = 45000) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(url, { ...options, signal: controller.signal });
    } finally {
      clearTimeout(timer);
    }
  };

  const describeError = (err) =>
    err.name === "AbortError"
      ? "Request timed out. Price history may be unavailable — check the backend logs, network, and IB Gateway."
      : err.message;

  const loadReport = useCallback(async () => {
    setLoading(true); setError("");
    const cap = Math.max(1, Math.min(100, Number(form.max_position_pct) || 15));
    try {
      const response = await fetchWithTimeout(`${API_BASE}/optimization?max_position_pct=${cap}`, {}, 60000);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not calculate portfolio risk");
      setReport(data);
    } catch (err) { setError(describeError(err)); } finally { setLoading(false); }
  }, [form.max_position_pct]);

  useEffect(() => { loadReport(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const calculateSize = async (event) => {
    event.preventDefault(); setSizingBusy(true); setSizing(null); setError("");
    try {
      const response = await fetchWithTimeout(`${API_BASE}/optimization/size`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form),
      }, 120000);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not size candidate");
      setSizing(data);
    } catch (err) { setError(describeError(err)); } finally { setSizingBusy(false); }
  };

  const inputStyle = { background: "#0d1117", border: "1px solid #30363d", borderRadius: 6, color: "#e6edf3", padding: "9px 10px", width: "100%", fontFamily: "inherit" };
  const metrics = report ? [
    ["Annualised volatility", `${fmt(report.metrics.annualized_volatility_pct)}%`],
    ["Max drawdown", `${fmt(report.metrics.max_drawdown_pct)}%`],
    ["Daily CVaR (95%)", `${fmt(report.metrics.daily_cvar_95_pct)}%`],
    ["Effective positions", fmt(report.metrics.effective_positions, 1)],
    ["Mean correlation", fmt(report.metrics.mean_pairwise_correlation, 3)],
    ["Cash weight", `${fmt(report.metrics.cash_weight_pct)}%`],
  ] : [];

  return <div className="fade-in">
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 18 }}>
      <div><h2 style={{ margin: 0, fontSize: 20 }}>Portfolio Optimisation</h2><div style={{ color: "#8b949e", fontSize: 12, marginTop: 5 }}>Live IBKR holdings · risk reference only · no orders are placed</div></div>
      <button className="btn" onClick={loadReport} disabled={loading}>{loading ? "Calculating…" : "Refresh risk"}</button>
    </div>
    {error && <div style={{ background: "rgba(248,81,73,.1)", border: "1px solid #da3633", color: "#f85149", padding: 12, borderRadius: 6, marginBottom: 16 }}>{error}</div>}

    {report && <>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(6, minmax(120px, 1fr))", gap: 12, marginBottom: 18 }}>
        {metrics.map(([label, value]) => <div className="card" key={label}><div className="card-header">{label}</div><div className="mono" style={{ fontSize: 20, fontWeight: 700 }}>{value}</div></div>)}
      </div>
      <div className="card" style={{ marginBottom: 18 }}>
        <div className="card-header">Current book vs Hierarchical Risk Parity</div>
        <div style={{ color: "#8b949e", fontSize: 11, marginBottom: 12 }}>{report.methodology}. HRP shows a diversification benchmark, not what you should automatically own.</div>
        <div style={{ overflowX: "auto" }}><table><thead><tr><th>Position</th><th>Current</th><th>HRP reference</th><th>Gap</th><th>Annual vol</th><th>Value (NZD)</th></tr></thead>
          <tbody>{report.positions.map(p => <tr key={p.code}><td><div style={{ fontWeight: 600 }}>{p.code}</div><div style={{ color: "#6e7681", fontSize: 11 }}>{p.stock_name}</div></td><td className="mono">{fmt(p.current_weight_pct)}%</td><td className="mono">{p.hrp_weight_pct == null ? "No history" : `${fmt(p.hrp_weight_pct)}%`}</td><td className="mono" style={{ color: p.gap_pct > 0 ? "#3fb950" : "#f85149" }}>{p.gap_pct == null ? "—" : `${p.gap_pct > 0 ? "+" : ""}${fmt(p.gap_pct)}%`}</td><td className="mono">{p.annualized_volatility_pct == null ? "—" : `${fmt(p.annualized_volatility_pct)}%`}</td><td className="mono">${fmt(p.current_value_nzd, 0)}</td></tr>)}</tbody></table></div>
        {report.coverage.excluded_tickers.length > 0 && <div style={{ color: "#d29922", fontSize: 11, marginTop: 10 }}>Excluded for insufficient history: {report.coverage.excluded_tickers.join(", ")}</div>}
      </div>
    </>}

    <div style={{ display: "grid", gridTemplateColumns: "1fr 1.25fr", gap: 18 }}>
      <form className="card" onSubmit={calculateSize}><div className="card-header">Size a position</div>
        <div style={{ color: "#8b949e", fontSize: 11, marginBottom: 14 }}>You supply the expected return. Conviction scales the result but is not treated as a probability.</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <label style={{ fontSize: 11, color: "#8b949e" }}>Ticker<input required placeholder="PLTR or US.PLTR" style={inputStyle} value={form.ticker} onChange={e => setForm({ ...form, ticker: e.target.value })} /></label>
          <label style={{ fontSize: 11, color: "#8b949e" }}>Expected return (%)<input required type="number" step="0.5" style={inputStyle} value={form.expected_return_pct} onChange={e => setForm({ ...form, expected_return_pct: Number(e.target.value) })} /></label>
          <label style={{ fontSize: 11, color: "#8b949e" }}>Conviction (1-5)<input type="number" min="1" max="5" style={inputStyle} value={form.conviction} onChange={e => setForm({ ...form, conviction: Number(e.target.value) })} /></label>
          <label style={{ fontSize: 11, color: "#8b949e" }}>Max position (%)<input type="number" min="1" max="100" step="0.5" style={inputStyle} value={form.max_position_pct} onChange={e => setForm({ ...form, max_position_pct: Number(e.target.value) })} /></label>
        </div><button className="btn btn-primary" style={{ width: "100%", marginTop: 14 }} disabled={sizingBusy}>{sizingBusy ? "Sizing…" : "Calculate position size"}</button>
      </form>

      <div className="card"><div className="card-header">Sizing output</div>
        {!sizing ? <div style={{ color: "#484f58", padding: "42px 0", textAlign: "center" }}>Enter your expected return and conviction to calculate an advisory size.</div> : <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 16 }}>
            {[ ["Suggested total weight", `${fmt(sizing.suggested_total_weight_pct)}%`], ["Add from cash", `$${fmt(sizing.suggested_trade_nzd, 0)} NZD`], ["Approx. shares", fmt(sizing.suggested_shares, 0)] ].map(([l,v]) => <div key={l} style={{ background: "#0d1117", padding: 12, borderRadius: 6 }}><div style={{ color: "#8b949e", fontSize: 10, textTransform: "uppercase" }}>{l}</div><div className="mono" style={{ fontSize: 19, fontWeight: 700, marginTop: 5 }}>{v}</div></div>)}
          </div>
          <table><tbody>{[["Current weight", sizing.current_weight_pct], ["HRP reference", sizing.hrp_weight_pct], ["Half-Kelly ceiling", sizing.half_kelly_pct], ["Estimated volatility", sizing.annualized_volatility_pct], ["Post-trade weight", sizing.post_trade_weight_pct]].map(([l,v]) => <tr key={l}><td style={{ color: "#8b949e" }}>{l}</td><td className="mono" style={{ textAlign: "right" }}>{fmt(v)}%</td></tr>)}</tbody></table>
          <div style={{ color: "#d29922", fontSize: 11, marginTop: 12 }}>{sizing.cash_limited ? "Cash constraint is binding. " : ""}{sizing.requires_sale ? "The model target is below the current holding; no automatic sell is proposed. " : ""}Expected return remains your judgment.</div>
        </>}
      </div>
    </div>
  </div>;
}
