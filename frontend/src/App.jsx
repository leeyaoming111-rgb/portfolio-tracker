import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { Treemap, ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, Legend, BarChart, Bar, Cell, CartesianGrid, ReferenceLine, Area, ComposedChart } from "recharts";
import IndustryScreener from "./IndustryScreener";

// ── Config ──
const API_BASE = "http://localhost:8000/api";
const POLL_INTERVAL = 30000;

// ── Demo Data (embedded for standalone preview) ──
const DEMO_PORTFOLIO = {
  positions: [
    { code: "US.MSFT", stock_name: "Microsoft", qty: 30, cost_price: 380.2, price: 423.85, val: 12715.5, pl_val: 1309.5, pl_ratio: 11.48, weight_pct: 16.04, target_pct: 12, tier: "high", drift: 4.04, drift_alert: true, concentration_alert: true },
    { code: "US.AAPL", stock_name: "Apple", qty: 50, cost_price: 178.5, price: 227.63, val: 11381.5, pl_val: 2456.5, pl_ratio: 27.52, weight_pct: 14.36, target_pct: 12, tier: "high", drift: 2.36, drift_alert: true, concentration_alert: true },
    { code: "US.TSLA", stock_name: "Tesla", qty: 35, cost_price: 240, price: 272.16, val: 9525.6, pl_val: 1125.6, pl_ratio: 13.4, weight_pct: 12.02, target_pct: 8, tier: "high", drift: 4.02, drift_alert: true, concentration_alert: true },
    { code: "US.META", stock_name: "Meta", qty: 15, cost_price: 330, price: 612.77, val: 9191.55, pl_val: 4241.55, pl_ratio: 85.69, weight_pct: 11.6, target_pct: 8, tier: "high", drift: 3.6, drift_alert: true, concentration_alert: true },
    { code: "US.GOOGL", stock_name: "Alphabet", qty: 40, cost_price: 140, price: 167.42, val: 6696.8, pl_val: 1096.8, pl_ratio: 19.59, weight_pct: 8.45, target_pct: 8, tier: "medium", drift: 0.45, drift_alert: false, concentration_alert: false },
    { code: "US.V", stock_name: "Visa", qty: 18, cost_price: 260, price: 341.12, val: 6140.16, pl_val: 1460.16, pl_ratio: 31.2, weight_pct: 7.75, target_pct: 8, tier: "medium", drift: -0.25, drift_alert: false, concentration_alert: false },
    { code: "MY.1155", stock_name: "Maybank", qty: 500, cost_price: 9.8, price: 10.42, val: 5210, pl_val: 310, pl_ratio: 6.33, weight_pct: 6.57, target_pct: 5, tier: "medium", drift: 1.57, drift_alert: false, concentration_alert: false },
    { code: "US.AMZN", stock_name: "Amazon", qty: 25, cost_price: 155, price: 203.98, val: 5099.5, pl_val: 1224.5, pl_ratio: 31.6, weight_pct: 6.43, target_pct: 8, tier: "medium", drift: -1.57, drift_alert: false, concentration_alert: false },
    { code: "US.JPM", stock_name: "JPMorgan", qty: 20, cost_price: 185, price: 252.93, val: 5058.6, pl_val: 1358.6, pl_ratio: 36.69, weight_pct: 6.38, target_pct: 5, tier: "medium", drift: 1.38, drift_alert: false, concentration_alert: false },
    { code: "US.UNH", stock_name: "UnitedHealth", qty: 8, cost_price: 520, price: 487.65, val: 3901.2, pl_val: -258.8, pl_ratio: -6.22, weight_pct: 4.92, target_pct: 5, tier: "medium", drift: -0.08, drift_alert: false, concentration_alert: false },
    { code: "US.NVDA", stock_name: "NVIDIA", qty: 20, cost_price: 450, price: 131.88, val: 2637.6, pl_val: -6362.4, pl_ratio: -70.69, weight_pct: 3.33, target_pct: 5, tier: "watch", drift: -1.67, drift_alert: false, concentration_alert: false },
    { code: "MY.1295", stock_name: "Public Bank", qty: 400, cost_price: 4.5, price: 4.78, val: 1912, pl_val: 112, pl_ratio: 6.22, weight_pct: 2.41, target_pct: 3, tier: "watch", drift: -0.59, drift_alert: false, concentration_alert: false },
  ],
  cash_plus: 15420,
  equity_nav: 79270.01,
  total_nav: 94690.01,
  settings: { concentration_cap: "10.0", drift_threshold: "2.0", poll_interval: "30" },
  timestamp: new Date().toISOString(),
  is_live: false,
};

const DEMO_ACTIONS = {
  actions: [
    { ticker: "US.MSFT", stock_name: "Microsoft", current_pct: 16.04, target_pct: 12, drift: 4.04, action: "SELL", shares: 7, value: 2966.95, running_cash: 18386.95 },
    { ticker: "US.AAPL", stock_name: "Apple", current_pct: 14.36, target_pct: 12, drift: 2.36, action: "SELL", shares: 8, value: 1821.04, running_cash: 20207.99 },
    { ticker: "US.TSLA", stock_name: "Tesla", current_pct: 12.02, target_pct: 8, drift: 4.02, action: "SELL", shares: 11, value: 2993.76, running_cash: 23201.75 },
    { ticker: "US.META", stock_name: "Meta", current_pct: 11.6, target_pct: 8, drift: 3.6, action: "SELL", shares: 4, value: 2451.08, running_cash: 25652.83 },
    { ticker: "US.AMZN", stock_name: "Amazon", current_pct: 6.43, target_pct: 8, drift: -1.57, action: "BUY", shares: 6, value: 1223.88, running_cash: 24428.95 },
    { ticker: "US.NVDA", stock_name: "NVIDIA", current_pct: 3.33, target_pct: 5, drift: -1.67, action: "BUY", shares: 10, value: 1318.80, running_cash: 23110.15 },
  ],
  starting_cash: 15420,
  ending_cash: 23110.15,
};

// ── Utility Functions ──
const fmt = (n, decimals = 2) => {
  if (n == null || isNaN(n)) return "—";
  return n.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
};
const fmtNzd = (n) => `NZ$ ${fmt(n)}`;
const fmtUsd = (n) => `$${fmt(n)}`;
const fmtPct = (n) => `${n >= 0 ? "+" : ""}${fmt(n)}%`;
const isUS = (code) => code && code.startsWith("US.");

const tierColors = { high: "#58a6ff", medium: "#8b949e", watch: "#6e7681", unset: "#484f58" };
const tierLabels = { high: "High Conviction", medium: "Medium", watch: "Watch / Starter", unset: "No Target" };

// ── Custom Treemap Content ──
const TreemapCell = ({ x, y, width, height, name, drift, weight_pct, concentration_alert }) => {
  if (width < 2 || height < 2) return null;
  const bg = name === "Cash Plus"
    ? "#d29922"
    : drift > 2 ? "#238636" : drift < -2 ? "#da3633" : "#30363d";
  const border = concentration_alert ? "#f85149" : "rgba(0,0,0,0.3)";
  return (
    <g>
      <rect x={x} y={y} width={width} height={height} fill={bg} stroke={border}
        strokeWidth={concentration_alert ? 2 : 1} rx={4} style={{ transition: "all 0.3s" }} />
      {width > 50 && height > 30 && (
        <>
          <text x={x + 8} y={y + 18} fill="#e6edf3" fontSize={width > 90 ? 13 : 11}
            fontFamily="'JetBrains Mono', 'Fira Code', monospace" fontWeight="600">{name}</text>
          {height > 44 && (
            <text x={x + 8} y={y + 34} fill="rgba(230,237,243,0.7)" fontSize={11}
              fontFamily="'JetBrains Mono', monospace">{fmt(weight_pct, 1)}%</text>
          )}
        </>
      )}
    </g>
  );
};

// ── Tabs ──
const TABS = ["Dashboard", "Returns", "Allocation", "Rebalance", "History", "Screener"];

// ── Conviction Editor Component ──
// Handles inline editing of thesis, catalysts, invalidations, and valuation for a single position.
function ConvictionEditor({ cv, ticker, isUS: isUSStock, onSave }) {
  const [thesis, setThesis] = useState(cv.thesis || "");
  const [catalysts, setCatalysts] = useState(cv.catalysts?.length ? cv.catalysts : []);
  const [invalidations, setInvalidations] = useState(cv.invalidations?.length ? cv.invalidations : []);
  const [fairValue, setFairValue] = useState(cv.fair_value || 0);
  const [valMethod, setValMethod] = useState(cv.valuation_method || "");
  const [valNotes, setValNotes] = useState(cv.valuation_notes || "");

  const inputStyle = {
    background: "#0d1117", border: "1px solid #30363d", borderRadius: 4,
    color: "#e6edf3", padding: "6px 10px", fontSize: 12, width: "100%",
    fontFamily: "inherit",
  };

  // ── Catalyst helpers: add, remove, update ──
  const addCatalyst = () => setCatalysts(prev => [...prev, { text: "", date: "", status: "active" }]);
  const removeCatalyst = (i) => setCatalysts(prev => prev.filter((_, idx) => idx !== i));
  const updateCatalyst = (i, field, val) => setCatalysts(prev =>
    prev.map((c, idx) => idx === i ? { ...c, [field]: val } : c)
  );

  // ── Invalidation helpers ──
  const addInvalidation = () => setInvalidations(prev => [...prev, { text: "", triggered: false }]);
  const removeInvalidation = (i) => setInvalidations(prev => prev.filter((_, idx) => idx !== i));
  const updateInvalidation = (i, field, val) => setInvalidations(prev =>
    prev.map((inv, idx) => idx === i ? { ...inv, [field]: val } : inv)
  );

  const handleSave = () => {
    onSave({
      thesis,
      catalysts: catalysts.filter(c => c.text.trim()),
      invalidations: invalidations.filter(inv => inv.text.trim()),
      fair_value: fairValue,
      valuation_method: valMethod,
      valuation_notes: valNotes,
      last_reviewed: new Date().toISOString(),
    });
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>

      {/* Left column: Thesis + Catalysts */}
      <div>
        {/* Thesis */}
        <div style={{ marginBottom: 14 }}>
          <label style={{ fontSize: 10, color: "#8b949e", display: "block", marginBottom: 4, textTransform: "uppercase", letterSpacing: 1 }}>
            Investment Thesis
          </label>
          <textarea value={thesis} onChange={e => setThesis(e.target.value)}
            placeholder="Why do you own this? What's the bull case in 2-3 sentences..."
            rows={4} style={{ ...inputStyle, resize: "vertical", lineHeight: 1.5 }} />
        </div>

        {/* Catalysts */}
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <label style={{ fontSize: 10, color: "#8b949e", textTransform: "uppercase", letterSpacing: 1 }}>
              Catalysts (next 6 months)
            </label>
            <button className="btn" onClick={addCatalyst}
              style={{ fontSize: 10, padding: "1px 8px" }}>+ Add</button>
          </div>
          {catalysts.map((cat, i) => (
            <div key={i} style={{ display: "flex", gap: 6, marginBottom: 6, alignItems: "center" }}>
              <input value={cat.text} onChange={e => updateCatalyst(i, "text", e.target.value)}
                placeholder="e.g. Q2 earnings beat, FDA approval..."
                style={{ ...inputStyle, flex: 1 }} />
              <input type="date" value={cat.date || ""} onChange={e => updateCatalyst(i, "date", e.target.value)}
                style={{ ...inputStyle, width: 140 }} />
              <button onClick={() => removeCatalyst(i)}
                style={{ background: "none", border: "none", color: "#f85149", cursor: "pointer", fontSize: 14, padding: "0 4px" }}>×</button>
            </div>
          ))}
          {catalysts.length === 0 && (
            <div style={{ fontSize: 11, color: "#484f58", padding: "4px 0" }}>
              No catalysts. A position without a catalyst within 6 months lacks conviction.
            </div>
          )}
        </div>
      </div>

      {/* Right column: Invalidations + Valuation */}
      <div>
        {/* Invalidations */}
        <div style={{ marginBottom: 14 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <label style={{ fontSize: 10, color: "#8b949e", textTransform: "uppercase", letterSpacing: 1 }}>
              Invalidation Triggers
            </label>
            <button className="btn" onClick={addInvalidation}
              style={{ fontSize: 10, padding: "1px 8px" }}>+ Add</button>
          </div>
          {invalidations.map((inv, i) => (
            <div key={i} style={{ display: "flex", gap: 6, marginBottom: 6, alignItems: "center" }}>
              <input value={inv.text} onChange={e => updateInvalidation(i, "text", e.target.value)}
                placeholder="e.g. revenue growth < 10% for 2 Qs..."
                style={{ ...inputStyle, flex: 1 }} />
              <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10, color: inv.triggered ? "#f85149" : "#8b949e", cursor: "pointer", flexShrink: 0 }}>
                <input type="checkbox" checked={inv.triggered} onChange={e => updateInvalidation(i, "triggered", e.target.checked)}
                  style={{ accentColor: "#f85149" }} />
                Fired
              </label>
              <button onClick={() => removeInvalidation(i)}
                style={{ background: "none", border: "none", color: "#f85149", cursor: "pointer", fontSize: 14, padding: "0 4px" }}>×</button>
            </div>
          ))}
          {invalidations.length === 0 && (
            <div style={{ fontSize: 11, color: "#484f58", padding: "4px 0" }}>
              Define what would make you wrong. If you can't, your thesis may be too vague.
            </div>
          )}
        </div>

        {/* Valuation */}
        <div style={{ marginBottom: 14 }}>
          <label style={{ fontSize: 10, color: "#8b949e", display: "block", marginBottom: 6, textTransform: "uppercase", letterSpacing: 1 }}>
            Valuation
          </label>
          <div style={{ display: "flex", gap: 8, marginBottom: 6 }}>
            <div style={{ flex: 1 }}>
              <label style={{ fontSize: 10, color: "#484f58", display: "block", marginBottom: 2 }}>Fair Value ({isUSStock ? "USD" : "NZD"})</label>
              <input type="number" step="0.01" value={fairValue || ""} onChange={e => setFairValue(parseFloat(e.target.value) || 0)}
                placeholder="0.00" style={inputStyle} />
            </div>
            <div style={{ flex: 1 }}>
              <label style={{ fontSize: 10, color: "#484f58", display: "block", marginBottom: 2 }}>Method</label>
              <select value={valMethod} onChange={e => setValMethod(e.target.value)}
                style={{ ...inputStyle }}>
                <option value="">Select...</option>
                <option value="DCF">DCF</option>
                <option value="Comps">Comps / Multiples</option>
                <option value="DDM">Dividend Discount</option>
                <option value="Sum-of-Parts">Sum-of-Parts</option>
                <option value="Yield">Yield-based</option>
                <option value="Gut">Gut / Qualitative</option>
              </select>
            </div>
          </div>
          <input value={valNotes} onChange={e => setValNotes(e.target.value)}
            placeholder="Notes: e.g. 25x fwd PE on $8 EPS, peer avg 22x..."
            style={inputStyle} />
        </div>

        {/* Save button */}
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <button className="btn btn-primary" onClick={handleSave}
            style={{ padding: "6px 20px" }}>Save Conviction</button>
        </div>
      </div>
    </div>
  );
}

// ── Main App ──
export default function App() {
  const [portfolio, setPortfolio] = useState(DEMO_PORTFOLIO);
  const [actions, setActions] = useState(DEMO_ACTIONS);
  const [activeTab, setActiveTab] = useState("Dashboard");
  const [weights, setWeights] = useState({});
  const [trades, setTrades] = useState([]);
  const [snapshots, setSnapshots] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [showAlertPanel, setShowAlertPanel] = useState(false);
  const [editingWeight, setEditingWeight] = useState(null);
  const [tradeForm, setTradeForm] = useState({ ticker: "", action: "trim", shares: "", price: "", notes: "" });
  const [isLive, setIsLive] = useState(false);
  const [returnsPeriod, setReturnsPeriod] = useState("total");
  const [showAllNZD, setShowAllNZD] = useState(true);
  const [sortBy, setSortBy] = useState("weight_pct");
  const [sortDir, setSortDir] = useState("desc");
  const pollRef = useRef(null);

  // ── Returns / Performance state ──
  const [returnData, setReturnData] = useState(null);
  const [returnsLoading, setReturnsLoading] = useState(false);
  const [returnsError, setReturnsError] = useState(null);
  const [chartPeriod, setChartPeriod] = useState("3M");
  const [showBenchmark, setShowBenchmark] = useState(true);
  const [chartMode, setChartMode] = useState("indexed"); // "indexed" or "log"
  const [activeBenchmarks, setActiveBenchmarks] = useState(["SPY"]); // others need paid FMP
  const [depositsData, setDepositsData] = useState(null);
  const [benchmarkDaily, setBenchmarkDaily] = useState(null);

  // ── Deal History state ──
  const [dealHistory, setDealHistory] = useState(null);
  const [dealDays, setDealDays] = useState(90);

  // ── Conviction state ──
  const [convictionData, setConvictionData] = useState({});
  const [editingConviction, setEditingConviction] = useState(null);  // ticker being edited
  const [expandedConviction, setExpandedConviction] = useState(null); // ticker expanded

  const PERIOD_OPTIONS = [
    { key: "1D", days: 1 }, { key: "1W", days: 7 }, { key: "1M", days: 30 },
    { key: "3M", days: 90 }, { key: "1Y", days: 365 }, { key: "ALL", days: 3650 },
  ];

  // Fetch portfolio from backend API
  const fetchPortfolio = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/portfolio`);
      if (res.ok) {
        const data = await res.json();
        setPortfolio(data);
        setIsLive(data.is_live);
      }
    } catch (e) {
      // Backend not running — stay on demo data
      console.log("Backend not reachable, using demo data");
    }
  }, []);

  const fetchActions = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/rebalance`);
      if (res.ok) {
        const data = await res.json();
        setActions(data);
      }
    } catch (e) {}
  }, []);

  const fetchReturns = useCallback(async (days) => {
    setReturnsLoading(true);
    setReturnsError(null);
    try {
      const res = await fetch(`${API_BASE}/returns?days=${days}`);
      if (res.ok) {
        const data = await res.json();
        setReturnData(data);
      }
    } catch (e) {
      setReturnsError("Backend not reachable");
    } finally {
      setReturnsLoading(false);
    }
  }, []);

  const fetchDeposits = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/deposits`);
      if (res.ok) {
        const data = await res.json();
        setDepositsData(data);
      }
    } catch (e) {}
  }, []);

  const fetchConviction = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/conviction`);
      if (res.ok) {
        const data = await res.json();
        setConvictionData(data);
      }
    } catch (e) {}
  }, []);

  const fetchBenchmarkDaily = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/benchmarks/daily`);
      if (res.ok) {
        const data = await res.json();
        setBenchmarkDaily(data);
      }
    } catch (e) {}
  }, []);

  const fetchDealHistory = useCallback(async (days) => {
    try {
      const res = await fetch(`${API_BASE}/deals?days=${days || dealDays}`);
      if (res.ok) {
        const data = await res.json();
        setDealHistory(data);
      }
    } catch (e) {}
  }, [dealDays]);

  // Fetch on mount and poll every 30s
  useEffect(() => {
    fetchPortfolio();
    fetchActions();
    fetchReturns(90);  // default 3M
    fetchDeposits();
    fetchConviction();
    fetchBenchmarkDaily();
    fetchDealHistory(90);
    const interval = setInterval(() => {
      fetchPortfolio();
      fetchActions();
      fetchBenchmarkDaily();
    }, POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [fetchPortfolio, fetchActions, fetchReturns, fetchDeposits, fetchConviction, fetchBenchmarkDaily, fetchDealHistory]);

  // Re-fetch returns when chart period changes
  useEffect(() => {
    const period = PERIOD_OPTIONS.find(p => p.key === chartPeriod);
    if (period) fetchReturns(period.days);
  }, [chartPeriod, fetchReturns]);

  // Initialize weights from portfolio
  useEffect(() => {
    const w = {};
    portfolio.positions.forEach(p => {
      if (p.target_pct > 0) w[p.code] = { target_pct: p.target_pct, tier: p.tier };
    });
    setWeights(w);
  }, []);

  // Check for drift alerts
  useEffect(() => {
    const newAlerts = portfolio.positions
      .filter(p => p.drift_alert)
      .map(p => ({
        ticker: p.code,
        name: p.stock_name,
        current_pct: p.weight_pct,
        target_pct: p.target_pct,
        drift: p.drift,
        action: p.drift > 0 ? "Trim" : "Add",
      }));
    setAlerts(newAlerts);
  }, [portfolio]);

  // ── Treemap data ──
  const treemapData = [
    ...portfolio.positions.map(p => ({
      name: p.stock_name || p.code.split(".")[1],
      size: p.val_nzd || p.val,
      drift: p.drift,
      weight_pct: p.weight_pct,
      concentration_alert: p.concentration_alert,
    })),
    { name: "Cash Plus", size: portfolio.cash_plus, drift: 0, weight_pct: portfolio.cash_plus_pct || (portfolio.total_nav > 0 ? (portfolio.cash_plus / portfolio.total_nav * 100) : 0), concentration_alert: false },
  ];

  // ── Top 5 concentration bar ──
  const top5 = portfolio.positions.slice(0, 5);
  const top5Total = top5.reduce((s, p) => s + p.weight_pct, 0);

  // ── Drift history chart data (mock for preview) ──
  const driftChartData = (() => {
    if (snapshots.length > 0) return snapshots;
    const tickers = portfolio.positions.slice(0, 5).map(p => p.stock_name || p.code.split(".")[1]);
    const data = [];
    for (let i = 30; i >= 0; i--) {
      const d = new Date(); d.setDate(d.getDate() - i);
      const entry = { date: d.toISOString().slice(5, 10) };
      tickers.forEach((t, idx) => {
        entry[t] = portfolio.positions[idx].weight_pct + (Math.random() - 0.5) * 3;
      });
      data.push(entry);
    }
    return data;
  })();
  const chartTickers = portfolio.positions.slice(0, 5).map(p => p.stock_name || p.code.split(".")[1]);
  const chartColors = ["#58a6ff", "#3fb950", "#d29922", "#f78166", "#bc8cff"];

  // ── Render ──
  return (
    <div style={{
      minHeight: "100vh", background: "#0d1117", color: "#e6edf3",
      fontFamily: "'JetBrains Mono', 'Fira Code', 'SF Mono', 'Cascadia Code', monospace",
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #161b22; }
        ::-webkit-scrollbar-thumb { background: #30363d; border-radius: 3px; }
        input, select { font-family: inherit; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        .fade-in { animation: fadeIn 0.4s ease-out; }
        .card { background: #161b22; border: 1px solid #21262d; border-radius: 8px; padding: 20px; }
        .card-header { font-size: 11px; text-transform: uppercase; letter-spacing: 1.5px; color: #8b949e; margin-bottom: 12px; }
        .btn { padding: 6px 14px; border-radius: 6px; border: 1px solid #30363d; background: #21262d; color: #e6edf3; cursor: pointer; font-size: 12px; font-family: inherit; transition: all 0.15s; }
        .btn:hover { background: #30363d; border-color: #8b949e; }
        .btn-primary { background: #1f6feb; border-color: #1f6feb; }
        .btn-primary:hover { background: #388bfd; }
        .btn-danger { background: rgba(248,81,73,0.15); border-color: #da3633; color: #f85149; }
        .btn-success { background: rgba(35,134,54,0.15); border-color: #238636; color: #3fb950; }
        .mono { font-family: 'JetBrains Mono', monospace; font-variant-numeric: tabular-nums; }
        table { width: 100%; border-collapse: collapse; }
        th { text-align: left; font-size: 10px; text-transform: uppercase; letter-spacing: 1px; color: #8b949e; padding: 8px 12px; border-bottom: 1px solid #21262d; font-weight: 500; }
        td { padding: 10px 12px; border-bottom: 1px solid rgba(33,38,45,0.5); font-size: 13px; white-space: nowrap; }
        tr:hover td { background: rgba(56,139,253,0.04); }
        .alert-dot { width: 8px; height: 8px; border-radius: 50%; background: #f85149; display: inline-block; animation: pulse 2s infinite; }
      `}</style>

      {/* ── Header ── */}
      <header style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "16px 24px", borderBottom: "1px solid #21262d",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ fontSize: 18, fontWeight: 700, letterSpacing: "-0.5px" }}>
            <span style={{ color: "#8b949e" }}>port</span>
            <span style={{ color: "#58a6ff" }}>folio</span>
          </div>
          <div style={{
            fontSize: 10, padding: "2px 8px", borderRadius: 10,
            background: isLive ? "rgba(35,134,54,0.2)" : "rgba(210,153,34,0.2)",
            color: isLive ? "#3fb950" : "#d29922", border: `1px solid ${isLive ? "#238636" : "#d29922"}`,
          }}>
            {isLive ? "LIVE" : "DEMO"}
          </div>
        </div>

        <nav style={{ display: "flex", gap: 4 }}>
          {TABS.map(tab => (
            <button key={tab} onClick={() => setActiveTab(tab)} style={{
              padding: "8px 16px", borderRadius: 6, border: "none",
              background: activeTab === tab ? "#21262d" : "transparent",
              color: activeTab === tab ? "#e6edf3" : "#8b949e",
              cursor: "pointer", fontSize: 13, fontFamily: "inherit", fontWeight: 500,
              transition: "all 0.15s",
            }}>{tab}</button>
          ))}
        </nav>

        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {alerts.length > 0 && (
            <button onClick={() => setShowAlertPanel(!showAlertPanel)} style={{
              position: "relative", background: "none", border: "none", cursor: "pointer",
              color: "#f85149", fontSize: 13, fontFamily: "inherit", display: "flex", alignItems: "center", gap: 6,
            }}>
              <span className="alert-dot" />
              <span>{alerts.length} alert{alerts.length > 1 ? "s" : ""}</span>
            </button>
          )}
          <span style={{ fontSize: 11, color: "#484f58" }}>
            {new Date(portfolio.timestamp).toLocaleTimeString()}
          </span>
        </div>
      </header>

      {/* ── Alert Panel (slide-down) ── */}
      {showAlertPanel && alerts.length > 0 && (
        <div className="fade-in" style={{
          background: "#161b22", borderBottom: "1px solid #21262d", padding: "12px 24px",
        }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {alerts.map((a, i) => (
              <div key={i} style={{
                padding: "8px 14px", borderRadius: 6,
                background: a.drift > 0 ? "rgba(35,134,54,0.1)" : "rgba(218,54,51,0.1)",
                border: `1px solid ${a.drift > 0 ? "#238636" : "#da3633"}`,
                fontSize: 12,
              }}>
                <span style={{ fontWeight: 600 }}>{a.name}</span>
                <span style={{ color: "#8b949e", margin: "0 6px" }}>
                  {fmt(a.current_pct, 1)}% → {fmt(a.target_pct, 1)}%
                </span>
                <span style={{ color: a.drift > 0 ? "#3fb950" : "#f85149" }}>
                  {a.action} ({fmtPct(a.drift)})
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Main Content ── */}
      <main style={{ padding: "20px 24px" }}>

        {/* ════ DASHBOARD TAB ════ */}
        {activeTab === "Dashboard" && (
          <div className="fade-in">
            {/* NAV Summary Row */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 16, marginBottom: 20 }}>
              {[
                { label: "Total NAV", value: fmtNzd(portfolio.total_nav), sub: null, color: "#e6edf3" },
                { label: "Equity NAV", value: fmtNzd(portfolio.equity_nav), sub: portfolio.total_nav > 0 ? `${fmt(portfolio.equity_nav / portfolio.total_nav * 100, 1)}% of NAV` : null, color: "#58a6ff" },
                { label: "Deployable Cash", value: fmtNzd(portfolio.cash_plus), sub: portfolio.total_nav > 0 ? `${fmt(portfolio.cash_plus / portfolio.total_nav * 100, 1)}% of NAV` : null, color: "#d29922" },
                { label: "Today's P&L", value: `${(portfolio.today_pl_total || 0) >= 0 ? "+" : ""}${fmtNzd(portfolio.today_pl_total || 0)}`, sub: null, color: (portfolio.today_pl_total || 0) >= 0 ? "#3fb950" : "#f85149" },
                { label: "Positions", value: portfolio.positions.length, sub: null, color: "#8b949e" },
              ].map((s, i) => (
                <div key={i} className="card" style={{ textAlign: "center" }}>
                  <div className="card-header">{s.label}</div>
                  <div className="mono" style={{ fontSize: 22, fontWeight: 700, color: s.color }}>{s.value}</div>
                  {s.sub && <div style={{ fontSize: 11, color: "#484f58", marginTop: 4 }}>{s.sub}</div>}
                </div>
              ))}
            </div>

            {/* Treemap + Concentration */}
            {/* ── Market Overview Strip ── */}
            {benchmarkDaily && Object.keys(benchmarkDaily).length > 0 && (
              <div className="card" style={{ marginBottom: 20, padding: "12px 16px" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
                  <div style={{ fontSize: 12, color: "#8b949e", fontWeight: 600, letterSpacing: 0.5, textTransform: "uppercase" }}>Markets</div>
                  <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
                    {Object.entries(benchmarkDaily).map(([bk, d]) => {
                      const isUp = d.change_pct != null && d.change_pct >= 0;
                      return (
                        <div key={bk} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span style={{ fontSize: 12, color: d.color, fontWeight: 600 }}>{d.label}</span>
                          <span className="mono" style={{ fontSize: 13, color: "#e6edf3", fontWeight: 500 }}>
                            ${d.close.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                          </span>
                          {d.change_pct != null && (
                            <span className="mono" style={{
                              fontSize: 11, fontWeight: 600, padding: "1px 6px", borderRadius: 4,
                              background: isUp ? "rgba(63,185,80,0.12)" : "rgba(248,81,73,0.12)",
                              color: isUp ? "#3fb950" : "#f85149",
                            }}>
                              {isUp ? "+" : ""}{d.change_pct.toFixed(2)}%
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                  {benchmarkDaily.SPY?.date && (
                    <div style={{ fontSize: 10, color: "#484f58" }}>
                      as of {benchmarkDaily.SPY.date}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Treemap + Concentration */}
            <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 16, marginBottom: 20 }}>
              <div className="card">
                <div className="card-header">NAV Composition</div>
                <div style={{ fontSize: 10, color: "#484f58", marginBottom: 8 }}>
                  Green = overweight · Red = underweight · Grey = within band · Amber = cash
                </div>
                <ResponsiveContainer width="100%" height={300}>
                  <Treemap data={treemapData} dataKey="size" content={<TreemapCell />}
                    animationDuration={500} />
                </ResponsiveContainer>
              </div>

              <div className="card">
                <div className="card-header">Concentration Risk</div>
                <div style={{ marginBottom: 16 }}>
                  <div style={{ fontSize: 11, color: "#8b949e", marginBottom: 4 }}>
                    Top 5 = {fmt(top5Total, 1)}% of Equity NAV
                  </div>
                  <div style={{
                    height: 24, borderRadius: 4, overflow: "hidden",
                    display: "flex", background: "#0d1117",
                  }}>
                    {top5.map((p, i) => (
                      <div key={i} title={`${p.stock_name}: ${fmt(p.weight_pct, 1)}%`} style={{
                        width: `${p.weight_pct / top5Total * 100}%`, height: "100%",
                        background: p.concentration_alert
                          ? `hsl(${0 + i * 8}, 70%, 45%)`
                          : `hsl(${210 + i * 15}, 50%, ${35 + i * 5}%)`,
                        display: "flex", alignItems: "center", justifyContent: "center",
                        fontSize: 9, fontWeight: 600, color: "#e6edf3",
                        borderRight: "1px solid #0d1117",
                      }}>
                        {p.stock_name || p.code.split(".")[1]}
                      </div>
                    ))}
                  </div>
                </div>

                {top5.map((p, i) => (
                  <div key={i} style={{
                    display: "flex", justifyContent: "space-between", alignItems: "center",
                    padding: "6px 0", borderBottom: i < 4 ? "1px solid rgba(33,38,45,0.5)" : "none",
                  }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      {p.concentration_alert && <span className="alert-dot" style={{ width: 6, height: 6 }} />}
                      <span style={{ fontSize: 13, fontWeight: 500 }}>{p.stock_name}</span>
                    </div>
                    <span className="mono" style={{
                      fontSize: 13, color: p.concentration_alert ? "#f85149" : "#8b949e",
                    }}>{fmt(p.weight_pct, 1)}%</span>
                  </div>
                ))}

                <div style={{
                  marginTop: 12, padding: "8px 12px", borderRadius: 6,
                  background: "rgba(248,81,73,0.08)", border: "1px solid rgba(248,81,73,0.2)",
                  fontSize: 11, color: "#f85149",
                }}>
                  Cap: {portfolio.settings.concentration_cap}% per position
                </div>
              </div>
            </div>

            {/* Positions Table */}
            <div className="card">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <div className="card-header" style={{ marginBottom: 0 }}>Positions</div>
                <div style={{
                  display: "flex", borderRadius: 8, overflow: "hidden",
                  border: "1px solid #30363d",
                }}>
                  <button onClick={() => setShowAllNZD(true)} style={{
                    padding: "6px 16px", fontSize: 12, fontFamily: "inherit", fontWeight: 600,
                    border: "none", cursor: "pointer",
                    background: showAllNZD ? "#d29922" : "#161b22",
                    color: showAllNZD ? "#0d1117" : "#8b949e",
                  }}>All NZD</button>
                  <button onClick={() => setShowAllNZD(false)} style={{
                    padding: "6px 16px", fontSize: 12, fontFamily: "inherit", fontWeight: 600,
                    border: "none", cursor: "pointer", borderLeft: "1px solid #30363d",
                    background: !showAllNZD ? "#bc8cff" : "#161b22",
                    color: !showAllNZD ? "#0d1117" : "#8b949e",
                  }}>Original Currency</button>
                </div>
              </div>
              <div style={{ overflowX: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Ticker</th><th>Shares</th><th style={{ textAlign: "right" }}>Avg Cost</th>
                      <th style={{ textAlign: "right" }}>Price</th>
                      {[
                        { key: "val_nzd", label: "Mkt Value" },
                        { key: "weight_pct", label: "% NAV" },
                        { key: "target_pct", label: "Target" },
                        { key: "drift", label: "Drift" },
                        { key: "unrealized_pl_nzd", label: "Unrealized" },
                        { key: "realized_pl_nzd", label: "Realized" },
                        { key: "pl_ratio", label: "P&L %" },
                      ].map(col => (
                        <th key={col.key} onClick={() => {
                          if (sortBy === col.key) setSortDir(d => d === "desc" ? "asc" : "desc");
                          else { setSortBy(col.key); setSortDir("desc"); }
                        }} style={{
                          textAlign: "right", cursor: "pointer", userSelect: "none",
                          color: sortBy === col.key ? "#58a6ff" : "#8b949e",
                        }}>
                          {col.label} {sortBy === col.key ? (sortDir === "desc" ? "↓" : "↑") : ""}
                        </th>
                      ))}
                      <th>Tier</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...portfolio.positions].sort((a, b) => {
                      const av = a[sortBy] || 0, bv = b[sortBy] || 0;
                      return sortDir === "desc" ? bv - av : av - bv;
                    }).map((p, i) => {
                      const us = isUS(p.code);
                      const sym = us ? "US$" : "NZ$";
                      const valDisplay = showAllNZD ? (p.val_nzd || p.val) : p.val;
                      const unrealDisplay = showAllNZD ? (p.unrealized_pl_nzd || 0) : (p.unrealized_pl || 0);
                      const realDisplay = showAllNZD ? (p.realized_pl_nzd || 0) : (p.realized_pl || 0);
                      const valPrefix = showAllNZD ? "NZ$" : sym;
                      return (
                      <tr key={i}>
                        <td style={{ fontWeight: 600 }}>
                          <div>{p.stock_name}</div>
                          <div style={{ fontSize: 10, color: "#8b949e", fontWeight: 400 }}>{p.code}</div>
                        </td>
                        <td className="mono">{p.qty < 1 ? fmt(p.qty, 2) : fmt(p.qty, 0)}</td>
                        <td className="mono" style={{ textAlign: "right" }}>
                          <span style={{ color: us ? "#bc8cff" : "#e6edf3" }}>{sym} {fmt(p.cost_price)}</span>
                        </td>
                        <td className="mono" style={{ textAlign: "right" }}>
                          <span style={{ color: us ? "#bc8cff" : "#e6edf3" }}>{sym} {fmt(p.price)}</span>
                        </td>
                        <td className="mono" style={{ textAlign: "right" }}>
                          <div>{valPrefix} {fmt(valDisplay, valDisplay >= 1000 ? 0 : 2)}</div>
                          {showAllNZD && us && <div style={{ fontSize: 10, color: "#bc8cff" }}>US$ {fmt(p.val, 0)}</div>}
                        </td>
                        <td className="mono" style={{
                          textAlign: "right", fontWeight: 600,
                          color: p.concentration_alert ? "#f85149" : "#e6edf3",
                        }}>
                          {fmt(p.weight_pct, 1)}%
                        </td>
                        <td className="mono" style={{ textAlign: "right", color: "#8b949e" }}>
                          {p.target_pct > 0 ? `${fmt(p.target_pct, 1)}%` : "—"}
                        </td>
                        <td className="mono" style={{
                          textAlign: "right",
                          color: p.target_pct > 0
                            ? (p.drift > 2 ? "#3fb950" : p.drift < -2 ? "#f85149" : "#8b949e")
                            : "#484f58",
                        }}>
                          {p.target_pct > 0 ? fmtPct(p.drift) : "—"}
                        </td>
                        <td className="mono" style={{
                          textAlign: "right", color: unrealDisplay >= 0 ? "#3fb950" : "#f85149",
                        }}>
                          <div>{unrealDisplay >= 0 ? "+" : ""}{valPrefix} {fmt(Math.abs(unrealDisplay), Math.abs(unrealDisplay) >= 1000 ? 0 : 2)}</div>
                          {showAllNZD && us && <div style={{ fontSize: 10, color: unrealDisplay >= 0 ? "rgba(63,185,80,0.5)" : "rgba(248,81,73,0.5)" }}>US$ {fmt(Math.abs(p.unrealized_pl || 0), 0)}</div>}
                        </td>
                        <td className="mono" style={{
                          textAlign: "right", color: realDisplay !== 0 ? (realDisplay >= 0 ? "#3fb950" : "#f85149") : "#484f58",
                        }}>
                          {realDisplay !== 0 ? (
                            <div>{realDisplay >= 0 ? "+" : ""}{valPrefix} {fmt(Math.abs(realDisplay), Math.abs(realDisplay) >= 1000 ? 0 : 2)}</div>
                          ) : "—"}
                        </td>
                        <td className="mono" style={{
                          textAlign: "right", color: p.pl_ratio >= 0 ? "#3fb950" : "#f85149",
                        }}>{fmtPct(p.pl_ratio)}</td>
                        <td>
                          <span style={{
                            fontSize: 10, padding: "2px 8px", borderRadius: 10,
                            background: `${tierColors[p.tier]}20`, color: tierColors[p.tier],
                            border: `1px solid ${tierColors[p.tier]}40`,
                          }}>{p.tier}</span>
                        </td>
                      </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            {/* ── Realized P&L (All-Time, persisted) ── */}
            {((portfolio.stored_realized || []).length > 0 || (portfolio.closed_positions || []).length > 0) && (
              <div className="card" style={{ marginTop: 16 }}>
                <div className="card-header">Realized P&L — All Positions</div>
                <div style={{ overflowX: "auto" }}>
                  <table>
                    <thead>
                      <tr>
                        <th>Ticker</th>
                        <th style={{ textAlign: "right" }}>Realized P&L</th>
                        <th style={{ textAlign: "right" }}>Realized (NZD)</th>
                        <th style={{ textAlign: "right" }}>Gain %</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(portfolio.stored_realized || portfolio.closed_positions || []).map((p, i) => {
                        const currSyms = { USD: "US$", NZD: "NZ$", JPY: "\u00a5", GBP: "\u00a3", EUR: "\u20ac", AUD: "A$", HKD: "HK$" };
                        const sym = currSyms[p.currency] || "NZ$";
                        const realNzd = p.total_realized_nzd || p.realized_pl_nzd || 0;
                        const realNative = p.total_realized || p.realized_pl || 0;
                        const gainPct = p.gain_pct || 0;
                        return (
                          <tr key={i}>
                            <td style={{ fontWeight: 600 }}>
                              <div>{p.stock_name || p.ticker || p.code}</div>
                              <div style={{ fontSize: 10, color: "#8b949e", fontWeight: 400 }}>{p.ticker || p.code}</div>
                            </td>
                            <td className="mono" style={{
                              textAlign: "right",
                              color: realNative >= 0 ? "#3fb950" : "#f85149",
                            }}>
                              {realNative >= 0 ? "+" : ""}{sym} {fmt(Math.abs(realNative), Math.abs(realNative) >= 1000 ? 0 : 2)}
                            </td>
                            <td className="mono" style={{
                              textAlign: "right",
                              color: realNzd >= 0 ? "#3fb950" : "#f85149",
                            }}>
                              {realNzd >= 0 ? "+NZ$ " : "-NZ$ "}{fmt(Math.abs(realNzd), Math.abs(realNzd) >= 1000 ? 0 : 2)}
                            </td>
                            <td className="mono" style={{
                              textAlign: "right",
                              color: gainPct >= 0 ? "#3fb950" : "#f85149",
                            }}>
                              {gainPct !== 0 ? `${gainPct >= 0 ? "+" : ""}${fmt(gainPct, 1)}%` : "\u2014"}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                {portfolio.total_realized_nzd != null && (
                  <div style={{
                    marginTop: 8, padding: "8px 12px", borderRadius: 6,
                    background: portfolio.total_realized_nzd >= 0 ? "rgba(63,185,80,0.08)" : "rgba(248,81,73,0.08)",
                    border: `1px solid ${portfolio.total_realized_nzd >= 0 ? "rgba(63,185,80,0.2)" : "rgba(248,81,73,0.2)"}`,
                    fontSize: 12, display: "flex", justifyContent: "space-between",
                  }}>
                    <span style={{ color: "#8b949e" }}>Total Realized (all positions)</span>
                    <span className="mono" style={{
                      fontWeight: 600,
                      color: portfolio.total_realized_nzd >= 0 ? "#3fb950" : "#f85149",
                    }}>
                      {portfolio.total_realized_nzd >= 0 ? "+NZ$ " : "-NZ$ "}{fmt(Math.abs(portfolio.total_realized_nzd), 0)}
                    </span>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* ════ RETURNS TAB ════ */}
        {activeTab === "Returns" && (() => {
          // ── Compute returns data — all in NZD ──
          // FX now handled per-position via p.fx_rate
          const toNzd = (p, val) => val * (p.fx_rate || 1);
          const totalPL = portfolio.positions.reduce((s, p) => s + (p.pl_val_nzd || toNzd(p, p.pl_val || 0)), 0);
          const totalUnrealized = portfolio.positions.reduce((s, p) => s + (p.unrealized_pl_nzd || toNzd(p, p.unrealized_pl || 0)), 0);
          const totalRealized = (portfolio.total_realized_nzd || 0);
          const totalCost = portfolio.positions.reduce((s, p) => s + (p.cost_total_nzd || p.cost_price * p.qty * (p.fx_rate || 1)), 0);
          const totalReturnPct = totalCost > 0 ? (totalPL / totalCost * 100) : 0;
          const todayPL = portfolio.today_pl_total || 0;

          // Attribution: each stock's contribution to total P&L (in NZD)
          const attribution = portfolio.positions
            .map(p => {
              const plNzd = toNzd(p, p.pl_val || 0);
              return {
                name: p.stock_name,
                code: p.code,
                pl_val: plNzd,
                unrealized: toNzd(p, p.unrealized_pl || 0),
                realized: toNzd(p, p.realized_pl || 0),
                today_pl: toNzd(p, p.today_pl || 0),
                pl_ratio: p.pl_ratio,
                weight_pct: p.weight_pct,
                contribution: totalCost > 0 ? (plNzd / totalCost * 100) : 0,
                market: p.code.split(".")[0] || "US",
              };
            })
            .sort((a, b) => b.pl_val - a.pl_val);

          // Multi-market breakdown (in NZD)
          const marketGroups = {};
          portfolio.positions.forEach(p => {
            const mkt = p.code.split(".")[0] || "Other";
            if (!marketGroups[mkt]) marketGroups[mkt] = { value: 0, pl: 0 };
            marketGroups[mkt].value += (p.val_nzd || p.val || 0);
            marketGroups[mkt].pl += (p.pl_val_nzd || p.pl_val || 0);
          });
          const marketTotal = Object.values(marketGroups).reduce((s, m) => s + m.value, 0);
          const marketColors = { US: "#bc8cff", NZ: "#58a6ff", JP: "#f778ba", AU: "#3fb950", UK: "#d29922", EU: "#79c0ff", MY: "#f0883e" };

          // Max absolute P&L for bar scaling
          const maxAbsPL = Math.max(...attribution.map(a => Math.abs(a.pl_val)), 1);

          // ── Performance chart data ──
          const chartSeries = returnData?.series || [];
          const periodReturns = returnData?.period_returns || {};
          const benchmarkMeta = returnData?.benchmarks || {};
          // Only show benchmarks that have actual cached data (non-zero values in series)
          const availableBenchmarks = Object.fromEntries(
            Object.entries(benchmarkMeta).filter(([bk]) => {
              const key = `${bk.toLowerCase()}_indexed`;
              return chartSeries.some(d => d[key] && d[key] !== 100);
            })
          );

          // Build data keys based on chart mode
          const bmKeys = showBenchmark ? activeBenchmarks : [];
          const getDataKey = (bk) => `${bk.toLowerCase()}_indexed`;

          // Y-axis domain
          const allChartVals = chartSeries.flatMap(d => {
            const vals = [d.portfolio];
            bmKeys.forEach(bk => {
              const v = d[getDataKey(bk)];
              if (v) vals.push(v);
            });
            return vals;
          }).filter(v => v != null && v > 0);
          const yMin = allChartVals.length ? Math.floor(Math.min(...allChartVals) * 0.97) : 95;
          const yMax = allChartVals.length ? Math.ceil(Math.max(...allChartVals) * 1.03) : 105;

          const formatDateLabel = (dateStr) => {
            if (!dateStr) return "";
            const d = new Date(dateStr + "T00:00:00");
            if (chartPeriod === "1D" || chartPeriod === "1W" || chartPeriod === "1M" || chartPeriod === "3M") {
              return d.toLocaleDateString("en-MY", { month: "short", day: "numeric" });
            }
            return d.toLocaleDateString("en-MY", { year: "2-digit", month: "short" });
          };

          const toggleBenchmark = (bk) => {
            setActiveBenchmarks(prev =>
              prev.includes(bk) ? prev.filter(x => x !== bk) : [...prev, bk]
            );
          };

          return (
            <div className="fade-in">

              {/* ════ PERFORMANCE CHART SECTION ════ */}
              <div className="card" style={{ marginBottom: 20 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16, flexWrap: "wrap", gap: 8 }}>
                  <div className="card-header" style={{ marginBottom: 0 }}>
                    Performance — {chartMode === "indexed" ? "Time-Weighted Return" : "Log Scale"}
                  </div>
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    {/* Mode toggle */}
                    <div style={{ display: "flex", background: "#0d1117", borderRadius: 6, border: "1px solid #21262d", overflow: "hidden" }}>
                      {[
                        { key: "indexed", label: "Linear" },
                        { key: "log", label: "Log" },
                      ].map(m => (
                        <button key={m.key} onClick={() => setChartMode(m.key)} style={{
                          padding: "4px 10px", border: "none", fontSize: 11, fontWeight: 500,
                          cursor: "pointer", fontFamily: "inherit",
                          background: chartMode === m.key ? "#1f6feb" : "transparent",
                          color: chartMode === m.key ? "#fff" : "#8b949e",
                          transition: "all 0.15s",
                        }}>{m.label}</button>
                      ))}
                    </div>
                    <label style={{ fontSize: 11, color: "#8b949e", display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
                      <input type="checkbox" checked={showBenchmark} onChange={e => setShowBenchmark(e.target.checked)}
                        style={{ accentColor: "#d29922" }} />
                      Benchmarks
                    </label>
                  </div>
                </div>

                {/* Benchmark Selector Pills */}
                {showBenchmark && (
                  <div style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap" }}>
                    {Object.entries(availableBenchmarks).map(([bk, meta]) => {
                      const active = activeBenchmarks.includes(bk);
                      return (
                        <button key={bk} onClick={() => toggleBenchmark(bk)} style={{
                          padding: "3px 10px", borderRadius: 12, fontSize: 11, fontWeight: 500,
                          cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s",
                          border: `1px solid ${active ? meta.color : "#21262d"}`,
                          background: active ? `${meta.color}18` : "transparent",
                          color: active ? meta.color : "#484f58",
                        }}>
                          <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%",
                            background: active ? meta.color : "#30363d", marginRight: 5, verticalAlign: "middle" }} />
                          {meta.label}
                        </button>
                      );
                    })}
                  </div>
                )}

                {/* Period Return Badges */}
                <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
                  {["1D", "1W", "1M", "3M", "YTD", "1Y"].map(key => {
                    const val = periodReturns[key];
                    const isUp = val != null && val > 0;
                    const isDown = val != null && val < 0;
                    return (
                      <div key={key} style={{
                        background: "#0d1117", border: `1px solid ${chartPeriod === key ? "#58a6ff" : "#21262d"}`,
                        borderRadius: 6, padding: "8px 14px", textAlign: "center", minWidth: 72,
                      }}>
                        <div style={{ fontSize: 10, color: "#8b949e", letterSpacing: 0.5, marginBottom: 2, textTransform: "uppercase" }}>{key}</div>
                        <div className="mono" style={{
                          fontSize: 15, fontWeight: 600,
                          color: val == null ? "#484f58" : isUp ? "#3fb950" : isDown ? "#f85149" : "#8b949e",
                        }}>
                          {val != null ? fmtPct(val) : "—"}
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Period Selector Tabs */}
                <div style={{ display: "flex", gap: 4, marginBottom: 16 }}>
                  {PERIOD_OPTIONS.map(p => (
                    <button key={p.key} onClick={() => setChartPeriod(p.key)} style={{
                      padding: "5px 12px", borderRadius: 6, border: "none", fontSize: 12, fontWeight: 500,
                      cursor: "pointer", fontFamily: "inherit",
                      background: chartPeriod === p.key ? "#1f6feb" : "transparent",
                      color: chartPeriod === p.key ? "#fff" : "#8b949e",
                      transition: "all 0.15s",
                    }}>{p.key}</button>
                  ))}
                </div>

                {/* Chart */}
                <div style={{ minHeight: 300 }}>
                  {returnsLoading ? (
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 280, color: "#8b949e" }}>
                      Loading returns data...
                    </div>
                  ) : returnsError ? (
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 280, color: "#f85149" }}>
                      {returnsError}
                    </div>
                  ) : chartSeries.length < 2 ? (
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: 280, color: "#484f58", gap: 8 }}>
                      <span style={{ fontSize: 28 }}>📊</span>
                      <span>Not enough snapshots for this period.</span>
                      <span style={{ fontSize: 11, color: "#484f58" }}>
                        Snapshots are taken daily while the backend runs. Check back after a few days of data.
                      </span>
                    </div>
                  ) : (
                    <ResponsiveContainer width="100%" height={280}>
                      <ComposedChart data={chartSeries.map(d => ({ ...d, dateLabel: formatDateLabel(d.date) }))}>
                        <defs>
                          <linearGradient id="gradPortfolio" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#58a6ff" stopOpacity={0.15} />
                            <stop offset="95%" stopColor="#58a6ff" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="#21262d" opacity={0.5} />
                        <XAxis dataKey="dateLabel" tick={{ fill: "#8b949e", fontSize: 11 }} axisLine={{ stroke: "#21262d" }}
                          tickLine={false} interval="preserveStartEnd" minTickGap={40} />
                        <YAxis domain={[yMin, yMax]}
                          scale={chartMode === "log" ? "log" : "linear"}
                          tick={{ fill: "#8b949e", fontSize: 11 }} axisLine={false}
                          tickLine={false} tickFormatter={v => v.toFixed(0)} width={48}
                          allowDataOverflow={chartMode === "log"} />
                        <Tooltip
                          contentStyle={{ background: "#161b22", border: "1px solid #30363d", borderRadius: 8, fontSize: 12 }}
                          labelStyle={{ color: "#8b949e" }}
                          formatter={(value, name) => {
                            if (name === "portfolio") return [`${fmt(value)} (${value >= 100 ? "+" : ""}${fmt(value - 100)}%)`, "Portfolio"];
                            const bk = Object.keys(benchmarkMeta).find(k => getDataKey(k) === name);
                            if (bk) return [`${fmt(value)} (${value >= 100 ? "+" : ""}${fmt(value - 100)}%)`, benchmarkMeta[bk]?.label || bk];
                            return [value, name];
                          }}
                        />
                        <ReferenceLine y={100} stroke="#484f58" strokeDasharray="4 4" strokeOpacity={0.5} />
                        <Area type="monotone" dataKey="portfolio"
                          stroke="#58a6ff" fill="url(#gradPortfolio)"
                          strokeWidth={2} dot={false} activeDot={{ r: 4, stroke: "#58a6ff" }}
                          name="portfolio" />
                        {showBenchmark && bmKeys.map(bk => (
                          <Line key={bk} type="monotone" dataKey={getDataKey(bk)}
                            stroke={benchmarkMeta[bk]?.color || "#8b949e"} strokeWidth={1.5}
                            dot={false} strokeDasharray="5 3"
                            activeDot={{ r: 3, stroke: benchmarkMeta[bk]?.color || "#8b949e" }}
                            name={getDataKey(bk)} />
                        ))}
                      </ComposedChart>
                    </ResponsiveContainer>
                  )}
                </div>

                {/* Stats Row */}
                {returnData && (
                  <div style={{ display: "flex", gap: 12, marginTop: 12, flexWrap: "wrap" }}>
                    {[
                      { label: "Total Deposited", value: fmtNzd(returnData.total_deposits) },
                      { label: "Deposits", value: returnData.deposit_count },
                      { label: "Snapshots", value: returnData.snapshot_count },
                    ].map((s, i) => (
                      <div key={i} style={{
                        background: "#0d1117", border: "1px solid #21262d", borderRadius: 6,
                        padding: "4px 10px", fontSize: 11,
                      }}>
                        <span style={{ color: "#8b949e" }}>{s.label}: </span>
                        <span className="mono" style={{ color: "#e6edf3", fontWeight: 500 }}>{s.value}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Legend */}
                <div style={{ display: "flex", gap: 16, marginTop: 12, fontSize: 11, color: "#484f58", flexWrap: "wrap" }}>
                  <span><span style={{ color: "#58a6ff" }}>━━</span> Portfolio (TWR, deposit-adjusted){chartMode === "log" ? " · log scale" : ""}</span>
                  {showBenchmark && bmKeys.map(bk => (
                    <span key={bk}><span style={{ color: benchmarkMeta[bk]?.color || "#8b949e" }}>╌╌</span> {benchmarkMeta[bk]?.label}</span>
                  ))}
                  <span><span style={{ color: "#484f58" }}>╌╌</span> Base (100)</span>
                </div>
              </div>

              {/* ── Hero P&L ── */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 16, marginBottom: 24 }}>
                <div className="card" style={{ textAlign: "center", padding: 24 }}>
                  <div className="card-header">Total P&L</div>
                  <div className="mono" style={{
                    fontSize: 28, fontWeight: 700,
                    color: totalPL >= 0 ? "#3fb950" : "#f85149",
                  }}>{totalPL >= 0 ? "+" : ""}{fmtNzd(totalPL)}</div>
                  <div className="mono" style={{
                    fontSize: 13, marginTop: 6,
                    color: totalPL >= 0 ? "rgba(63,185,80,0.6)" : "rgba(248,81,73,0.6)",
                  }}>{fmtPct(totalReturnPct)} on invested</div>
                </div>
                <div className="card" style={{ textAlign: "center", padding: 24 }}>
                  <div className="card-header">Unrealized</div>
                  <div className="mono" style={{
                    fontSize: 28, fontWeight: 700,
                    color: totalUnrealized >= 0 ? "#3fb950" : "#f85149",
                  }}>{totalUnrealized >= 0 ? "+" : ""}{fmtNzd(totalUnrealized)}</div>
                  <div style={{ fontSize: 12, marginTop: 6, color: "#484f58" }}>still holding</div>
                </div>
                <div className="card" style={{ textAlign: "center", padding: 24 }}>
                  <div className="card-header">Realized</div>
                  <div className="mono" style={{
                    fontSize: 28, fontWeight: 700,
                    color: totalRealized >= 0 ? "#3fb950" : "#f85149",
                  }}>{totalRealized >= 0 ? "+" : ""}{fmtNzd(totalRealized)}</div>
                  <div style={{ fontSize: 12, marginTop: 6, color: "#484f58" }}>from trims / sales</div>
                </div>
                <div className="card" style={{ textAlign: "center", padding: 24 }}>
                  <div className="card-header">Today</div>
                  <div className="mono" style={{
                    fontSize: 28, fontWeight: 700,
                    color: todayPL >= 0 ? "#3fb950" : "#f85149",
                  }}>{todayPL >= 0 ? "+" : ""}{fmtNzd(todayPL)}</div>
                  <div style={{ fontSize: 12, marginTop: 6, color: "#484f58" }}>daily P&L</div>
                </div>
              </div>

              {/* ── Per-Stock Returns ── */}
              <div className="card" style={{ marginBottom: 20 }}>
                <div className="card-header">Return by Position</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 8 }}>
                  {attribution.map((a, i) => {
                    const barWidth = Math.abs(a.pl_val) / maxAbsPL * 100;
                    const isPositive = a.pl_val >= 0;
                    return (
                      <div key={i} style={{ display: "grid", gridTemplateColumns: "140px 1fr 100px 80px", alignItems: "center", gap: 12 }}>
                        <div>
                          <div style={{ fontSize: 13, fontWeight: 600 }}>{a.name}</div>
                          <div style={{ fontSize: 10, color: "#484f58" }}>{a.code}</div>
                        </div>
                        <div style={{ position: "relative", height: 28, display: "flex", alignItems: "center" }}>
                          <div style={{
                            position: "absolute", left: isPositive ? "50%" : `${50 - barWidth / 2}%`,
                            width: `${barWidth / 2}%`, height: 20, borderRadius: 3,
                            background: isPositive
                              ? "linear-gradient(90deg, rgba(63,185,80,0.3), rgba(63,185,80,0.6))"
                              : "linear-gradient(270deg, rgba(248,81,73,0.3), rgba(248,81,73,0.6))",
                            transition: "all 0.5s ease",
                          }} />
                          {/* Center line */}
                          <div style={{
                            position: "absolute", left: "50%", top: 0, bottom: 0,
                            width: 1, background: "#30363d",
                          }} />
                        </div>
                        <div className="mono" style={{
                          textAlign: "right", fontSize: 13, fontWeight: 600,
                          color: isPositive ? "#3fb950" : "#f85149",
                        }}>{isPositive ? "+" : ""}{fmtNzd(a.pl_val)}</div>
                        <div className="mono" style={{
                          textAlign: "right", fontSize: 12,
                          color: isPositive ? "rgba(63,185,80,0.7)" : "rgba(248,81,73,0.7)",
                        }}>{fmtPct(a.pl_ratio)}</div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* ── Attribution + Market Split ── */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 20 }}>
                {/* Contribution to portfolio return */}
                <div className="card">
                  <div className="card-header">Contribution to Total Return</div>
                  <div style={{ fontSize: 11, color: "#484f58", marginBottom: 12 }}>
                    How much each stock added or subtracted from your total return
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {attribution.map((a, i) => (
                      <div key={i} style={{
                        display: "flex", justifyContent: "space-between", alignItems: "center",
                        padding: "8px 12px", borderRadius: 6,
                        background: a.pl_val >= 0 ? "rgba(63,185,80,0.05)" : "rgba(248,81,73,0.05)",
                        border: `1px solid ${a.pl_val >= 0 ? "rgba(63,185,80,0.15)" : "rgba(248,81,73,0.15)"}`,
                      }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <div style={{
                            width: 8, height: 8, borderRadius: "50%",
                            background: a.pl_val >= 0 ? "#3fb950" : "#f85149",
                          }} />
                          <span style={{ fontSize: 13, fontWeight: 500 }}>{a.name}</span>
                        </div>
                        <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
                          <span className="mono" style={{
                            fontSize: 12, color: a.contribution >= 0 ? "#3fb950" : "#f85149",
                          }}>{a.contribution >= 0 ? "+" : ""}{fmt(a.contribution, 2)}%</span>
                          <span className="mono" style={{
                            fontSize: 13, fontWeight: 600,
                            color: a.pl_val >= 0 ? "#3fb950" : "#f85149",
                          }}>{a.pl_val >= 0 ? "+" : ""}{fmtNzd(a.pl_val)}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Market Breakdown */}
                <div className="card">
                  <div className="card-header">Market Breakdown</div>
                  <div style={{ fontSize: 11, color: "#484f58", marginBottom: 16 }}>
                    Performance split by market
                  </div>

                  {/* Multi-market allocation bar */}
                  <div style={{ marginBottom: 20 }}>
                    <div style={{ fontSize: 11, color: "#8b949e", marginBottom: 6 }}>Allocation by Value</div>
                    <div style={{
                      height: 32, borderRadius: 6, overflow: "hidden", display: "flex",
                      background: "#0d1117",
                    }}>
                      {Object.entries(marketGroups).sort((a,b) => b[1].value - a[1].value).map(([mkt, data]) => {
                        const pct = marketTotal > 0 ? data.value / marketTotal * 100 : 0;
                        if (pct < 1) return null;
                        return (
                          <div key={mkt} style={{
                            width: `${pct}%`, height: "100%",
                            background: marketColors[mkt] || "#8b949e",
                            display: "flex", alignItems: "center", justifyContent: "center",
                            fontSize: 11, fontWeight: 600, color: "#fff",
                          }}>{mkt} {fmt(pct, 0)}%</div>
                        );
                      })}
                    </div>
                  </div>

                  {/* Per-market cards */}
                  {Object.entries(marketGroups).sort((a,b) => b[1].value - a[1].value).map(([mkt, data]) => {
                    const mktFlags = { US: "🇺🇸", NZ: "🇳🇿", JP: "🇯🇵", AU: "🇦🇺", UK: "🇬🇧", EU: "🇪🇺", MY: "🇲🇾", HK: "🇭🇰", SG: "🇸🇬", CA: "🇨🇦" };
                    const mktNames = { US: "US Market", NZ: "NZ Market", JP: "Japan", AU: "Australia", UK: "UK Market", EU: "Europe", MY: "Malaysia", HK: "Hong Kong" };
                    const color = marketColors[mkt] || "#8b949e";
                    const stocks = attribution.filter(a => a.market === mkt);
                    return (
                      <div key={mkt} style={{
                        padding: 14, borderRadius: 6, marginBottom: 10,
                        background: `${color}0F`, border: `1px solid ${color}26`,
                      }}>
                        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                          <span style={{ fontSize: 13, fontWeight: 600 }}>{mktFlags[mkt] || "🌍"} {mktNames[mkt] || mkt}</span>
                          <span className="mono" style={{ fontSize: 13, color }}>{fmtNzd(data.value)}</span>
                        </div>
                        <div style={{ display: "flex", justifyContent: "space-between" }}>
                          <span style={{ fontSize: 12, color: "#8b949e" }}>P&L</span>
                          <span className="mono" style={{
                            fontSize: 13, fontWeight: 600,
                            color: data.pl >= 0 ? "#3fb950" : "#f85149",
                          }}>{data.pl >= 0 ? "+" : ""}{fmtNzd(data.pl)}</span>
                        </div>
                        <div style={{ marginTop: 6 }}>
                          {stocks.map((s, i) => (
                            <span key={i} style={{
                              fontSize: 10, padding: "2px 8px", borderRadius: 10, marginRight: 4,
                              background: `${color}1A`, color,
                            }}>{s.name}</span>
                          ))}
                        </div>
                      </div>
                    );
                  })}

                  {/* Benchmark reference */}
                  <div style={{
                    marginTop: 16, padding: "10px 12px", borderRadius: 6,
                    background: "#0d1117", border: "1px solid #21262d",
                    fontSize: 11, color: "#484f58",
                  }}>
                    📊 See the Performance chart above for multi-benchmark comparison (SPY, ACWI, QQQ, EEM) with deposit-adjusted TWR.
                  </div>
                </div>
              </div>
            </div>
          );
        })()}

        {/* ════ ALLOCATION TAB ════ */}
        {activeTab === "Allocation" && (
          <div className="fade-in">
            <div className="card" style={{ marginBottom: 20 }}>
              <div className="card-header">Allocation System — Conviction Tiers</div>
              <div style={{ fontSize: 13, color: "#8b949e", lineHeight: 1.6, maxWidth: 700 }}>
                <p style={{ marginBottom: 8 }}>
                  <strong style={{ color: "#e6edf3" }}>Recommended system: Conviction-Weighted with Drift Bands.</strong>
                </p>
                <p style={{ marginBottom: 12 }}>
                  With fewer than 20 positions, equal-weight lacks the flexibility to express
                  conviction. Instead, allocate by tier and flag when drift exceeds ±2%:
                </p>
                <div style={{ display: "flex", gap: 16 }}>
                  {[
                    { tier: "High Conviction", range: "8–12%", color: "#58a6ff", desc: "Core holdings, high confidence" },
                    { tier: "Medium", range: "3–8%", color: "#8b949e", desc: "Solid positions, standard sizing" },
                    { tier: "Watch / Starter", range: "1–3%", color: "#6e7681", desc: "New or speculative positions" },
                  ].map((t, i) => (
                    <div key={i} style={{
                      flex: 1, padding: 14, borderRadius: 6,
                      background: "#0d1117", border: `1px solid ${t.color}40`,
                    }}>
                      <div style={{ color: t.color, fontWeight: 600, fontSize: 12, marginBottom: 4 }}>{t.tier}</div>
                      <div className="mono" style={{ fontSize: 18, fontWeight: 700, marginBottom: 4 }}>{t.range}</div>
                      <div style={{ fontSize: 11, color: "#484f58" }}>{t.desc}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="card">
              <div className="card-header">Set Target Weights</div>
              <div style={{ fontSize: 11, color: "#484f58", marginBottom: 12 }}>
                Click any target cell to edit. Total should ideally sum to ~100%.
              </div>

              {(() => {
                const totalTarget = portfolio.positions.reduce((s, p) => s + (weights[p.code]?.target_pct || p.target_pct || 0), 0);
                return (
                  <div style={{ marginBottom: 12, padding: "8px 12px", borderRadius: 6, background: "#0d1117", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontSize: 12, color: "#8b949e" }}>Total allocated:</span>
                    <span className="mono" style={{
                      fontSize: 14, fontWeight: 700,
                      color: Math.abs(totalTarget - 100) < 2 ? "#3fb950" : "#d29922",
                    }}>{fmt(totalTarget, 1)}%</span>
                  </div>
                );
              })()}

              <table>
                <thead>
                  <tr>
                    <th>Ticker</th><th>Name</th><th style={{ textAlign: "right" }}>Current %</th>
                    <th style={{ textAlign: "right" }}>Target %</th><th>Tier</th><th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {portfolio.positions.map((p, i) => {
                    const isEditing = editingWeight === p.code;
                    const w = weights[p.code] || { target_pct: p.target_pct || 0, tier: p.tier || "medium" };
                    return (
                      <tr key={i}>
                        <td style={{ fontWeight: 600 }}>{p.code}</td>
                        <td style={{ color: "#8b949e" }}>{p.stock_name}</td>
                        <td className="mono" style={{ textAlign: "right" }}>{fmt(p.weight_pct, 1)}%</td>
                        <td style={{ textAlign: "right" }}>
                          {isEditing ? (
                            <input type="number" step="0.5" min="0" max="25"
                              defaultValue={w.target_pct} autoFocus
                              style={{
                                width: 60, background: "#0d1117", border: "1px solid #58a6ff",
                                borderRadius: 4, color: "#e6edf3", padding: "2px 6px",
                                fontSize: 13, textAlign: "right",
                              }}
                              onBlur={(e) => {
                                const val = parseFloat(e.target.value) || 0;
                                const newW = { ...w, target_pct: val };
                                setWeights(prev => ({ ...prev, [p.code]: newW }));
                                setEditingWeight(null);
                                // Save to backend
                                fetch(`${API_BASE}/weights`, {
                                  method: "POST",
                                  headers: { "Content-Type": "application/json" },
                                  body: JSON.stringify({ ticker: p.code, target_pct: val, tier: newW.tier }),
                                }).then(() => fetchPortfolio());
                              }}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") e.target.blur();
                                if (e.key === "Escape") setEditingWeight(null);
                              }}
                            />
                          ) : (
                            <span className="mono" onClick={() => setEditingWeight(p.code)}
                              style={{ cursor: "pointer", padding: "2px 6px", borderRadius: 4, border: "1px solid transparent" }}
                              onMouseEnter={(e) => e.target.style.borderColor = "#30363d"}
                              onMouseLeave={(e) => e.target.style.borderColor = "transparent"}
                            >
                              {w.target_pct > 0 ? `${fmt(w.target_pct, 1)}%` : "—"}
                            </span>
                          )}
                        </td>
                        <td>
                          <select value={w.tier} onChange={(e) => {
                            const newTier = e.target.value;
                            const newW = { ...w, tier: newTier };
                            setWeights(prev => ({ ...prev, [p.code]: newW }));
                            // Save to backend
                            fetch(`${API_BASE}/weights`, {
                              method: "POST",
                              headers: { "Content-Type": "application/json" },
                              body: JSON.stringify({ ticker: p.code, target_pct: newW.target_pct, tier: newTier }),
                            }).then(() => fetchPortfolio());
                          }} style={{
                            background: "#0d1117", border: "1px solid #30363d", borderRadius: 4,
                            color: tierColors[w.tier], padding: "2px 6px", fontSize: 11,
                          }}>
                            <option value="high">High</option>
                            <option value="medium">Medium</option>
                            <option value="watch">Watch</option>
                          </select>
                        </td>
                        <td>
                          {!isEditing && (
                            <button className="btn" onClick={() => setEditingWeight(p.code)}
                              style={{ fontSize: 11, padding: "2px 10px" }}>Edit</button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* ── Conviction Framework ── */}
            <div className="card" style={{ marginTop: 20 }}>
              <div className="card-header">Investment Thesis &amp; Conviction Framework</div>
              <div style={{ fontSize: 11, color: "#484f58", marginBottom: 16 }}>
                Each position needs a thesis, forward catalysts, invalidation triggers, and a valuation anchor.
                Positions with active catalysts and no triggered invalidations = high conviction.
                Expired catalysts or triggered invalidations = review immediately.
              </div>

              {portfolio.positions.map((p) => {
                const cv = convictionData[p.code] || {
                  thesis: "", catalysts: [], invalidations: [],
                  fair_value: 0, valuation_method: "", valuation_notes: "",
                  last_reviewed: "",
                };
                const isExpanded = expandedConviction === p.code;
                const isEditing = editingConviction === p.code;

                // ── Derive conviction status ──
                const now = new Date();
                const activeCatalysts = (cv.catalysts || []).filter(c => {
                  if (!c.date) return false;
                  return new Date(c.date) >= now && c.status !== "expired";
                });
                const expiredCatalysts = (cv.catalysts || []).filter(c => {
                  if (!c.date) return true;
                  return new Date(c.date) < now || c.status === "expired";
                });
                const triggeredInvalidations = (cv.invalidations || []).filter(inv => inv.triggered);
                const hasThesis = cv.thesis && cv.thesis.trim().length > 0;
                const hasCatalysts = (cv.catalysts || []).length > 0;

                let statusColor = "#484f58";
                let statusLabel = "No thesis";
                let statusBg = "rgba(72,79,88,0.1)";
                if (!hasThesis) {
                  statusColor = "#484f58"; statusLabel = "No thesis set"; statusBg = "rgba(72,79,88,0.1)";
                } else if (triggeredInvalidations.length > 0) {
                  statusColor = "#f85149"; statusLabel = "Invalidation triggered"; statusBg = "rgba(248,81,73,0.08)";
                } else if (activeCatalysts.length > 0) {
                  statusColor = "#3fb950"; statusLabel = "Active — catalyst live"; statusBg = "rgba(63,185,80,0.08)";
                } else if (hasCatalysts && activeCatalysts.length === 0) {
                  statusColor = "#d29922"; statusLabel = "Catalysts expired — review"; statusBg = "rgba(210,153,34,0.08)";
                } else {
                  statusColor = "#8b949e"; statusLabel = "Thesis only"; statusBg = "rgba(139,148,158,0.08)";
                }

                // ── Valuation: margin of safety ──
                const currentPrice = p.price || 0;
                const fairValue = cv.fair_value || 0;
                const marginOfSafety = fairValue > 0 ? ((fairValue - currentPrice) / fairValue * 100) : null;

                // ── Save handler ──
                const saveConviction = async (updated) => {
                  try {
                    await fetch(`${API_BASE}/conviction`, {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ ticker: p.code, ...updated }),
                    });
                    await fetchConviction();
                    setEditingConviction(null);
                  } catch (e) { console.error("Save conviction failed:", e); }
                };

                return (
                  <div key={p.code} style={{
                    marginBottom: 8, borderRadius: 6, overflow: "hidden",
                    border: `1px solid ${isExpanded ? statusColor + "60" : "#21262d"}`,
                    background: isExpanded ? statusBg : "transparent",
                    transition: "all 0.2s",
                  }}>
                    {/* ── Collapsed row ── */}
                    <div onClick={() => setExpandedConviction(isExpanded ? null : p.code)}
                      style={{
                        display: "flex", alignItems: "center", gap: 12, padding: "10px 14px",
                        cursor: "pointer",
                      }}>
                      <span style={{ fontSize: 10, color: "#484f58", transition: "transform 0.2s",
                        transform: isExpanded ? "rotate(90deg)" : "rotate(0deg)" }}>▶</span>
                      <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 10 }}>
                        <span style={{ fontWeight: 600, fontSize: 13 }}>{p.stock_name}</span>
                        <span style={{ fontSize: 11, color: "#484f58" }}>{p.code}</span>
                      </div>
                      <span style={{
                        fontSize: 10, padding: "2px 8px", borderRadius: 10,
                        background: statusBg, color: statusColor,
                        border: `1px solid ${statusColor}30`,
                      }}>{statusLabel}</span>
                      {fairValue > 0 && (
                        <span className="mono" style={{
                          fontSize: 11, color: marginOfSafety > 0 ? "#3fb950" : "#f85149",
                        }}>FV: {isUS(p.code) ? "$" : "NZ$"}{fmt(fairValue)} ({marginOfSafety > 0 ? "+" : ""}{fmt(marginOfSafety, 0)}%)</span>
                      )}
                      <span className="mono" style={{ fontSize: 12, color: "#8b949e", width: 50, textAlign: "right" }}>
                        {fmt(p.weight_pct, 1)}%
                      </span>
                    </div>

                    {/* ── Expanded card ── */}
                    {isExpanded && (
                      <div style={{ padding: "4px 14px 16px", borderTop: `1px solid #21262d` }}>

                        {/* Edit / View toggle */}
                        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 8 }}>
                          <button className="btn" onClick={(e) => { e.stopPropagation(); setEditingConviction(isEditing ? null : p.code); }}
                            style={{ fontSize: 11, padding: "2px 10px" }}>
                            {isEditing ? "Cancel" : "Edit"}
                          </button>
                        </div>

                        {isEditing ? (
                          /* ═══ EDIT MODE ═══ */
                          <ConvictionEditor cv={cv} ticker={p.code} isUS={isUS(p.code)} onSave={saveConviction} />
                        ) : (
                          /* ═══ VIEW MODE ═══ */
                          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>

                            {/* Left: Thesis + Catalysts */}
                            <div>
                              {/* Thesis */}
                              <div style={{ marginBottom: 14 }}>
                                <div style={{ fontSize: 10, color: "#8b949e", textTransform: "uppercase", letterSpacing: 1, marginBottom: 4 }}>Thesis</div>
                                <div style={{ fontSize: 12, color: hasThesis ? "#e6edf3" : "#484f58", lineHeight: 1.6 }}>
                                  {hasThesis ? cv.thesis : "No thesis written yet. Click Edit to add one."}
                                </div>
                              </div>

                              {/* Catalysts */}
                              <div>
                                <div style={{ fontSize: 10, color: "#8b949e", textTransform: "uppercase", letterSpacing: 1, marginBottom: 6 }}>
                                  Catalysts {hasCatalysts && <span style={{ color: "#3fb950" }}>({activeCatalysts.length} active)</span>}
                                </div>
                                {(cv.catalysts || []).length === 0 ? (
                                  <div style={{ fontSize: 11, color: "#484f58" }}>No catalysts defined.</div>
                                ) : (
                                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                                    {(cv.catalysts || []).map((cat, ci) => {
                                      const catDate = cat.date ? new Date(cat.date) : null;
                                      const isExpiredCat = catDate && catDate < now;
                                      const daysLeft = catDate ? Math.ceil((catDate - now) / 86400000) : null;
                                      return (
                                        <div key={ci} style={{
                                          display: "flex", alignItems: "center", gap: 8, padding: "6px 10px",
                                          borderRadius: 4, background: "#0d1117", border: `1px solid ${isExpiredCat ? "#d29922" : "#21262d"}`,
                                        }}>
                                          <span style={{
                                            width: 6, height: 6, borderRadius: "50%",
                                            background: isExpiredCat ? "#d29922" : "#3fb950",
                                            flexShrink: 0,
                                          }} />
                                          <span style={{ fontSize: 12, flex: 1, color: isExpiredCat ? "#8b949e" : "#e6edf3" }}>
                                            {cat.text}
                                          </span>
                                          {catDate && (
                                            <span className="mono" style={{
                                              fontSize: 10, flexShrink: 0,
                                              color: isExpiredCat ? "#d29922" : daysLeft <= 30 ? "#f0883e" : "#3fb950",
                                            }}>
                                              {isExpiredCat ? "EXPIRED" : `${daysLeft}d left`}
                                            </span>
                                          )}
                                        </div>
                                      );
                                    })}
                                  </div>
                                )}
                              </div>
                            </div>

                            {/* Right: Invalidations + Valuation */}
                            <div>
                              {/* Invalidations */}
                              <div style={{ marginBottom: 14 }}>
                                <div style={{ fontSize: 10, color: "#8b949e", textTransform: "uppercase", letterSpacing: 1, marginBottom: 6 }}>
                                  Invalidation Triggers {triggeredInvalidations.length > 0 && <span style={{ color: "#f85149" }}>({triggeredInvalidations.length} triggered!)</span>}
                                </div>
                                {(cv.invalidations || []).length === 0 ? (
                                  <div style={{ fontSize: 11, color: "#484f58" }}>No invalidation triggers defined.</div>
                                ) : (
                                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                                    {(cv.invalidations || []).map((inv, ii) => (
                                      <div key={ii} style={{
                                        display: "flex", alignItems: "center", gap: 8, padding: "6px 10px",
                                        borderRadius: 4, background: "#0d1117",
                                        border: `1px solid ${inv.triggered ? "#da3633" : "#21262d"}`,
                                      }}>
                                        <span style={{
                                          width: 6, height: 6, borderRadius: "50%",
                                          background: inv.triggered ? "#f85149" : "#30363d",
                                          flexShrink: 0,
                                        }} />
                                        <span style={{
                                          fontSize: 12, flex: 1,
                                          color: inv.triggered ? "#f85149" : "#e6edf3",
                                          textDecoration: inv.triggered ? "line-through" : "none",
                                        }}>
                                          {inv.text}
                                        </span>
                                        <span style={{ fontSize: 10, color: inv.triggered ? "#f85149" : "#3fb950" }}>
                                          {inv.triggered ? "FIRED" : "OK"}
                                        </span>
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>

                              {/* Valuation */}
                              <div>
                                <div style={{ fontSize: 10, color: "#8b949e", textTransform: "uppercase", letterSpacing: 1, marginBottom: 6 }}>Valuation</div>
                                {fairValue > 0 ? (
                                  <div style={{ padding: "10px 12px", borderRadius: 6, background: "#0d1117", border: "1px solid #21262d" }}>
                                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                                      <div>
                                        <div style={{ fontSize: 10, color: "#8b949e" }}>Fair Value</div>
                                        <div className="mono" style={{ fontSize: 16, fontWeight: 700, color: "#e6edf3" }}>
                                          {isUS(p.code) ? "$" : "NZ$"}{fmt(fairValue)}
                                        </div>
                                      </div>
                                      <div style={{ textAlign: "right" }}>
                                        <div style={{ fontSize: 10, color: "#8b949e" }}>Current</div>
                                        <div className="mono" style={{ fontSize: 16, fontWeight: 700, color: "#8b949e" }}>
                                          {isUS(p.code) ? "$" : "NZ$"}{fmt(currentPrice)}
                                        </div>
                                      </div>
                                      <div style={{ textAlign: "right" }}>
                                        <div style={{ fontSize: 10, color: "#8b949e" }}>Margin of Safety</div>
                                        <div className="mono" style={{
                                          fontSize: 16, fontWeight: 700,
                                          color: marginOfSafety > 0 ? "#3fb950" : "#f85149",
                                        }}>
                                          {marginOfSafety > 0 ? "+" : ""}{fmt(marginOfSafety, 1)}%
                                        </div>
                                      </div>
                                    </div>
                                    {/* Valuation bar */}
                                    <div style={{ height: 8, background: "#161b22", borderRadius: 4, overflow: "hidden", position: "relative", marginBottom: 6 }}>
                                      <div style={{
                                        position: "absolute", left: 0, top: 0, height: "100%", borderRadius: 4,
                                        width: `${Math.min(Math.max((currentPrice / fairValue) * 100, 5), 150)}%`,
                                        background: marginOfSafety > 20 ? "#238636" : marginOfSafety > 0 ? "#3fb950" : marginOfSafety > -10 ? "#d29922" : "#da3633",
                                        transition: "width 0.3s",
                                      }} />
                                    </div>
                                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "#484f58" }}>
                                      <span>Method: {cv.valuation_method || "—"}</span>
                                      {cv.valuation_notes && <span>{cv.valuation_notes}</span>}
                                    </div>
                                  </div>
                                ) : (
                                  <div style={{ fontSize: 11, color: "#484f58" }}>No fair value set.</div>
                                )}
                              </div>

                              {/* Last reviewed */}
                              {cv.last_reviewed && (
                                <div style={{ marginTop: 10, fontSize: 10, color: "#484f58" }}>
                                  Last reviewed: {new Date(cv.last_reviewed).toLocaleDateString()}
                                </div>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ════ REBALANCE TAB ════ */}
        {activeTab === "Rebalance" && (
          <div className="fade-in">
            {/* Cash Impact Summary */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 20 }}>
              <div className="card" style={{ textAlign: "center" }}>
                <div className="card-header">Starting Cash Plus</div>
                <div className="mono" style={{ fontSize: 20, fontWeight: 700, color: "#d29922" }}>
                  {fmtNzd(actions.starting_cash)}
                </div>
              </div>
              <div className="card" style={{ textAlign: "center" }}>
                <div className="card-header">After Rebalance</div>
                <div className="mono" style={{ fontSize: 20, fontWeight: 700, color: "#3fb950" }}>
                  {fmtNzd(actions.ending_cash)}
                </div>
              </div>
              <div className="card" style={{ textAlign: "center" }}>
                <div className="card-header">Net Cash Change</div>
                <div className="mono" style={{ fontSize: 20, fontWeight: 700, color: "#58a6ff" }}>
                  {fmtNzd(actions.ending_cash - actions.starting_cash)}
                </div>
              </div>
            </div>

            {/* Action Table */}
            <div className="card" style={{ marginBottom: 20 }}>
              <div className="card-header">Trim / Deploy Recommendations</div>
              <table>
                <thead>
                  <tr>
                    <th>Ticker</th><th>Name</th><th style={{ textAlign: "right" }}>Current %</th>
                    <th style={{ textAlign: "right" }}>Target %</th><th style={{ textAlign: "right" }}>Drift</th>
                    <th style={{ textAlign: "center" }}>Action</th><th style={{ textAlign: "right" }}>Shares</th>
                    <th style={{ textAlign: "right" }}>Value</th>
                    <th style={{ textAlign: "right" }}>Running Cash</th>
                  </tr>
                </thead>
                <tbody>
                  {actions.actions.map((a, i) => (
                    <tr key={i}>
                      <td style={{ fontWeight: 600 }}>{a.stock_name}</td>
                      <td style={{ color: "#8b949e" }}>{a.stock_name}</td>
                      <td className="mono" style={{ textAlign: "right" }}>{fmt(a.current_pct, 1)}%</td>
                      <td className="mono" style={{ textAlign: "right" }}>{fmt(a.target_pct, 1)}%</td>
                      <td className="mono" style={{
                        textAlign: "right", color: a.drift > 0 ? "#3fb950" : "#f85149",
                      }}>{fmtPct(a.drift)}</td>
                      <td style={{ textAlign: "center" }}>
                        <span style={{
                          padding: "3px 10px", borderRadius: 4, fontSize: 11, fontWeight: 600,
                          background: a.action === "SELL" ? "rgba(248,81,73,0.12)" : "rgba(35,134,54,0.12)",
                          color: a.action === "SELL" ? "#f85149" : "#3fb950",
                          border: `1px solid ${a.action === "SELL" ? "#da3633" : "#238636"}`,
                        }}>{a.action}</span>
                      </td>
                      <td className="mono" style={{ textAlign: "right" }}>{a.shares}</td>
                      <td className="mono" style={{ textAlign: "right" }}>{fmtNzd(a.value)}</td>
                      <td className="mono" style={{ textAlign: "right", color: "#d29922" }}>
                        {fmtNzd(a.running_cash)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {actions.actions.length === 0 && (
                <div style={{ padding: 40, textAlign: "center", color: "#484f58" }}>
                  All positions within drift tolerance. No rebalance needed.
                </div>
              )}
            </div>

            {/* Trade Log Entry */}
            <div className="card">
              <div className="card-header">Log a Trade</div>
              <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
                <div>
                  <label style={{ fontSize: 10, color: "#8b949e", display: "block", marginBottom: 4 }}>Ticker</label>
                  <input value={tradeForm.ticker} onChange={e => setTradeForm(f => ({ ...f, ticker: e.target.value }))}
                    placeholder="US.AAPL" style={{
                      background: "#0d1117", border: "1px solid #30363d", borderRadius: 4,
                      color: "#e6edf3", padding: "6px 10px", width: 100, fontSize: 13,
                    }} />
                </div>
                <div>
                  <label style={{ fontSize: 10, color: "#8b949e", display: "block", marginBottom: 4 }}>Action</label>
                  <select value={tradeForm.action} onChange={e => setTradeForm(f => ({ ...f, action: e.target.value }))}
                    style={{
                      background: "#0d1117", border: "1px solid #30363d", borderRadius: 4,
                      color: "#e6edf3", padding: "6px 10px", fontSize: 13,
                    }}>
                    <option value="trim">Trim (Sell)</option>
                    <option value="add">Add (Buy)</option>
                  </select>
                </div>
                <div>
                  <label style={{ fontSize: 10, color: "#8b949e", display: "block", marginBottom: 4 }}>Shares</label>
                  <input type="number" value={tradeForm.shares}
                    onChange={e => setTradeForm(f => ({ ...f, shares: e.target.value }))}
                    style={{
                      background: "#0d1117", border: "1px solid #30363d", borderRadius: 4,
                      color: "#e6edf3", padding: "6px 10px", width: 80, fontSize: 13,
                    }} />
                </div>
                <div>
                  <label style={{ fontSize: 10, color: "#8b949e", display: "block", marginBottom: 4 }}>Price</label>
                  <input type="number" step="0.01" value={tradeForm.price}
                    onChange={e => setTradeForm(f => ({ ...f, price: e.target.value }))}
                    style={{
                      background: "#0d1117", border: "1px solid #30363d", borderRadius: 4,
                      color: "#e6edf3", padding: "6px 10px", width: 100, fontSize: 13,
                    }} />
                </div>
                <div style={{ flex: 1 }}>
                  <label style={{ fontSize: 10, color: "#8b949e", display: "block", marginBottom: 4 }}>Notes</label>
                  <input value={tradeForm.notes} onChange={e => setTradeForm(f => ({ ...f, notes: e.target.value }))}
                    placeholder="Took profit at resistance" style={{
                      background: "#0d1117", border: "1px solid #30363d", borderRadius: 4,
                      color: "#e6edf3", padding: "6px 10px", width: "100%", fontSize: 13,
                    }} />
                </div>
                <button className="btn btn-primary" onClick={() => {
                  if (tradeForm.ticker && tradeForm.shares) {
                    setTrades(prev => [{
                      timestamp: new Date().toISOString(),
                      ...tradeForm,
                      shares: parseFloat(tradeForm.shares),
                      price: parseFloat(tradeForm.price),
                    }, ...prev]);
                    setTradeForm({ ticker: "", action: "trim", shares: "", price: "", notes: "" });
                  }
                }}>Log Trade</button>
              </div>

              {trades.length > 0 && (
                <table style={{ marginTop: 16 }}>
                  <thead>
                    <tr>
                      <th>Date</th><th>Ticker</th><th>Action</th><th style={{ textAlign: "right" }}>Shares</th>
                      <th style={{ textAlign: "right" }}>Price</th><th>Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((t, i) => (
                      <tr key={i}>
                        <td style={{ color: "#8b949e", fontSize: 12 }}>
                          {new Date(t.timestamp).toLocaleDateString()}
                        </td>
                        <td style={{ fontWeight: 600 }}>{t.ticker}</td>
                        <td>
                          <span style={{
                            padding: "2px 8px", borderRadius: 4, fontSize: 11,
                            background: t.action === "trim" ? "rgba(248,81,73,0.1)" : "rgba(35,134,54,0.1)",
                            color: t.action === "trim" ? "#f85149" : "#3fb950",
                          }}>{t.action}</span>
                        </td>
                        <td className="mono" style={{ textAlign: "right" }}>{t.shares}</td>
                        <td className="mono" style={{ textAlign: "right" }}>{fmtNzd(t.price)}</td>
                        <td style={{ color: "#8b949e", fontSize: 12 }}>{t.notes}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        )}

        {/* ════ HISTORY TAB ════ */}
        {activeTab === "History" && (
          <div className="fade-in">
            {/* ── Deal History ── */}
            <div className="card" style={{ marginBottom: 20 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
                <div className="card-header" style={{ marginBottom: 0 }}>Order History</div>
                <div style={{ display: "flex", gap: 4 }}>
                  {[
                    { key: 30, label: "1M" }, { key: 90, label: "3M" },
                    { key: 180, label: "6M" }, { key: 365, label: "1Y" },
                  ].map(p => (
                    <button key={p.key} onClick={() => { setDealDays(p.key); fetchDealHistory(p.key); }}
                      style={{
                        padding: "4px 10px", borderRadius: 6, border: "none", fontSize: 11, fontWeight: 500,
                        cursor: "pointer", fontFamily: "inherit",
                        background: dealDays === p.key ? "#1f6feb" : "transparent",
                        color: dealDays === p.key ? "#fff" : "#8b949e",
                      }}>{p.label}</button>
                  ))}
                </div>
              </div>

              {dealHistory && dealHistory.deals && dealHistory.deals.length > 0 ? (
                <div style={{ overflowY: "auto", maxHeight: 500 }}>
                  <table>
                    <thead>
                      <tr>
                        <th style={{ textAlign: "left" }}>Date</th>
                        <th style={{ textAlign: "left" }}>Ticker</th>
                        <th style={{ textAlign: "center" }}>Side</th>
                        <th style={{ textAlign: "right" }}>Qty</th>
                        <th style={{ textAlign: "right" }}>Price</th>
                        <th style={{ textAlign: "right" }}>Value</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dealHistory.deals.map((d, i) => {
                        const isBuy = d.trd_side === "BUY" || d.trd_side?.includes("BUY");
                        const isSell = d.trd_side === "SELL" || d.trd_side?.includes("SELL");
                        const isUS = d.code?.startsWith("US.");
                        const sym = isUS ? "US$" : "NZ$";
                        const dateStr = d.create_time ? d.create_time.slice(0, 16).replace("T", " ") : "—";
                        const ticker = d.code?.split(".").pop() || d.code;
                        return (
                          <tr key={i} style={{ background: i % 2 ? "#0d1117" : "transparent" }}>
                            <td style={{ fontSize: 12, color: "#8b949e", whiteSpace: "nowrap" }}>{dateStr}</td>
                            <td style={{ fontWeight: 600 }}>
                              <div style={{ color: "#e6edf3", fontSize: 13 }}>{ticker}</div>
                              <div style={{ fontSize: 10, color: "#6e7681", fontWeight: 400 }}>{d.stock_name}</div>
                            </td>
                            <td style={{ textAlign: "center" }}>
                              <span style={{
                                fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 4,
                                background: isBuy ? "rgba(63,185,80,0.12)" : isSell ? "rgba(248,81,73,0.12)" : "#21262d",
                                color: isBuy ? "#3fb950" : isSell ? "#f85149" : "#8b949e",
                                letterSpacing: "0.05em",
                              }}>
                                {isBuy ? "BUY" : isSell ? "SELL" : d.trd_side}
                              </span>
                            </td>
                            <td className="mono" style={{ textAlign: "right", fontSize: 12 }}>
                              {fmt(d.qty, 0)}
                            </td>
                            <td className="mono" style={{ textAlign: "right", fontSize: 12, color: isUS ? "#bc8cff" : "#e6edf3" }}>
                              {sym} {fmt(d.price)}
                            </td>
                            <td className="mono" style={{ textAlign: "right", fontSize: 12 }}>
                              <div>{showAllNZD ? `RM ${fmt(d.total_value_nzd, 0)}` : `${sym} ${fmt(d.total_value, 0)}`}</div>
                              {showAllNZD && isUS && (
                                <div style={{ fontSize: 10, color: "#bc8cff" }}>US$ {fmt(d.total_value, 0)}</div>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : dealHistory ? (
                <div style={{ padding: "20px 0", textAlign: "center", color: "#484f58", fontSize: 13 }}>
                  No deals found for this period.
                </div>
              ) : (
                <div style={{ padding: "20px 0", textAlign: "center", color: "#484f58", fontSize: 13 }}>
                  Loading deal history…
                </div>
              )}

              {dealHistory?.deals?.length > 0 && (() => {
                // FX now handled per-deal via d.currency
                const buys = dealHistory.deals.filter(d => d.trd_side?.includes("BUY"));
                const sells = dealHistory.deals.filter(d => d.trd_side?.includes("SELL"));
                const totalBought = buys.reduce((s, d) => s + d.total_value_nzd, 0);
                const totalSold = sells.reduce((s, d) => s + d.total_value_nzd, 0);
                return (
                  <div style={{ display: "flex", gap: 16, marginTop: 12, flexWrap: "wrap" }}>
                    <div style={{ fontSize: 12 }}>
                      <span style={{ color: "#8b949e" }}>Deals: </span>
                      <span className="mono" style={{ color: "#e6edf3", fontWeight: 500 }}>{dealHistory.deals.length}</span>
                    </div>
                    <div style={{ fontSize: 12 }}>
                      <span style={{ color: "#3fb950" }}>Bought: </span>
                      <span className="mono" style={{ color: "#3fb950", fontWeight: 500 }}>RM {fmt(totalBought, 0)}</span>
                      <span style={{ color: "#484f58" }}> ({buys.length})</span>
                    </div>
                    <div style={{ fontSize: 12 }}>
                      <span style={{ color: "#f85149" }}>Sold: </span>
                      <span className="mono" style={{ color: "#f85149", fontWeight: 500 }}>RM {fmt(totalSold, 0)}</span>
                      <span style={{ color: "#484f58" }}> ({sells.length})</span>
                    </div>
                    <div style={{ fontSize: 12 }}>
                      <span style={{ color: "#8b949e" }}>Net: </span>
                      <span className="mono" style={{ color: totalSold - totalBought >= 0 ? "#3fb950" : "#d29922", fontWeight: 500 }}>
                        RM {fmt(totalSold - totalBought, 0)}
                      </span>
                    </div>
                  </div>
                );
              })()}
            </div>

            {/* ── Weight Drift Chart ── */}
            <div className="card" style={{ marginBottom: 20 }}>
              <div className="card-header">Weight Drift Over Time — Top 5 Positions</div>
              <ResponsiveContainer width="100%" height={350}>
                <LineChart data={driftChartData}>
                  <XAxis dataKey="date" tick={{ fill: "#8b949e", fontSize: 11 }} axisLine={{ stroke: "#21262d" }} tickLine={false} />
                  <YAxis tick={{ fill: "#8b949e", fontSize: 11 }} axisLine={{ stroke: "#21262d" }} tickLine={false}
                    domain={["dataMin - 2", "dataMax + 2"]} tickFormatter={v => `${v.toFixed(0)}%`} />
                  <Tooltip
                    contentStyle={{ background: "#161b22", border: "1px solid #30363d", borderRadius: 8, fontSize: 12 }}
                    labelStyle={{ color: "#8b949e" }}
                    formatter={(value) => [`${value.toFixed(1)}%`]}
                  />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  {chartTickers.map((t, i) => (
                    <Line key={t} type="monotone" dataKey={t} stroke={chartColors[i]}
                      strokeWidth={2} dot={false} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              <div className="card">
                <div className="card-header">Snapshot Controls</div>
                <p style={{ fontSize: 12, color: "#8b949e", marginBottom: 12 }}>
                  Take a manual snapshot of your current portfolio state. In production,
                  snapshots are taken automatically every 24 hours.
                </p>
                <button className="btn btn-primary" onClick={() => {
                  setSnapshots(prev => [...prev, {
                    date: new Date().toISOString().slice(0, 10),
                    total_nav: portfolio.total_nav,
                    equity_nav: portfolio.equity_nav,
                    cash_plus: portfolio.cash_plus,
                  }]);
                }}>Take Snapshot Now</button>
                {snapshots.length > 0 && (
                  <div style={{ marginTop: 12, fontSize: 12, color: "#3fb950" }}>
                    {snapshots.length} snapshot{snapshots.length > 1 ? "s" : ""} saved this session
                  </div>
                )}
              </div>

              <div className="card">
                <div className="card-header">NAV History</div>
                {snapshots.length > 0 ? (
                  <table>
                    <thead>
                      <tr>
                        <th>Date</th><th style={{ textAlign: "right" }}>Total NAV</th>
                        <th style={{ textAlign: "right" }}>Equity</th><th style={{ textAlign: "right" }}>Cash</th>
                      </tr>
                    </thead>
                    <tbody>
                      {snapshots.map((s, i) => (
                        <tr key={i}>
                          <td style={{ color: "#8b949e" }}>{s.date}</td>
                          <td className="mono" style={{ textAlign: "right" }}>{fmtNzd(s.total_nav)}</td>
                          <td className="mono" style={{ textAlign: "right" }}>{fmtNzd(s.equity_nav)}</td>
                          <td className="mono" style={{ textAlign: "right", color: "#d29922" }}>{fmtNzd(s.cash_plus)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p style={{ fontSize: 12, color: "#484f58" }}>No snapshots yet. Click "Take Snapshot" to start.</p>
                )}
              </div>
            </div>
          </div>
        )}

        {activeTab === "Screener" && (
          <div className="fade-in">
            <IndustryScreener />
          </div>
        )}
      </main>

      {/* ── Footer ── */}
      <footer style={{
        padding: "16px 24px", borderTop: "1px solid #21262d",
        display: "flex", justifyContent: "space-between", fontSize: 11, color: "#484f58",
      }}>
        <span>Backed by IBKR Gateway · {isLive ? "Live" : "Demo"} mode · {portfolio.fx_rates ? Object.entries(portfolio.fx_rates).map(([c, r]) => `${c}/NZD ${(1/r).toFixed(2)}`).join(" · ") : "FX loading..."}</span>
        <span>Drift threshold: ±{portfolio.settings.drift_threshold}% · Concentration cap: {portfolio.settings.concentration_cap}%</span>
      </footer>
    </div>
  );
}
