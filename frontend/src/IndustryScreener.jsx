/*
  IndustryScreener.jsx — Thematic stock discovery + research chat
  Card-based layout. No horizontal scroll. Clean LLM formatting.
*/

import { useState, useCallback, useMemo, useEffect, useRef } from "react";

const API = "http://localhost:8000/screener";

const fmtMktCap = v => v == null ? null : v >= 1e12 ? `$${(v/1e12).toFixed(1)}T` : v >= 1e9 ? `$${(v/1e9).toFixed(1)}B` : v >= 1e6 ? `$${(v/1e6).toFixed(0)}M` : `$${v}`;
const fmtPct = v => v == null ? null : `${(v * 100).toFixed(1)}%`;
const fmtNum = (v, d = 1) => v == null ? null : v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

// Render LLM markdown as formatted React elements
function RenderMD({ text, style = {} }) {
  if (!text) return null;

  // Split into blocks (tables, paragraphs)
  const blocks = [];
  const lines = text.split("\n");
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Detect markdown table (line with | characters)
    if (line.includes("|") && line.trim().startsWith("|")) {
      const tableLines = [];
      while (i < lines.length && lines[i].includes("|")) {
        tableLines.push(lines[i]);
        i++;
      }
      blocks.push({ type: "table", lines: tableLines });
      continue;
    }

    // Regular line
    if (line.trim()) {
      blocks.push({ type: "text", content: line });
    } else {
      blocks.push({ type: "break" });
    }
    i++;
  }

  return (
    <div style={{ fontSize: 13, color: "#b1bac4", lineHeight: 1.6, ...style }}>
      {blocks.map((block, bi) => {
        if (block.type === "break") return <div key={bi} style={{ height: 8 }} />;

        if (block.type === "table") {
          const rows = block.lines
            .filter(l => !l.match(/^\s*\|[\s-:|]+\|\s*$/)) // skip separator rows
            .map(l => l.split("|").map(cell => cell.trim()).filter(Boolean));

          if (rows.length === 0) return null;
          const header = rows[0];
          const body = rows.slice(1);

          return (
            <div key={bi} style={{ overflowX: "auto", margin: "8px 0" }}>
              <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 12 }}>
                <thead>
                  <tr>
                    {header.map((cell, ci) => (
                      <th key={ci} style={{
                        padding: "6px 10px", textAlign: "left", fontWeight: 600, color: "#e6edf3",
                        borderBottom: "2px solid #30363d", whiteSpace: "nowrap", fontSize: 11,
                        background: "#161b22",
                      }}><InlineFormat text={cell} /></th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {body.map((row, ri) => (
                    <tr key={ri} style={{ background: ri % 2 ? "#0d111722" : "transparent" }}>
                      {row.map((cell, ci) => (
                        <td key={ci} style={{
                          padding: "5px 10px", borderBottom: "1px solid #21262d",
                          color: ci === 0 ? "#c9d1d9" : "#8b949e", fontSize: 12,
                          whiteSpace: ci === 0 ? "nowrap" : "normal",
                        }}><InlineFormat text={cell} /></td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }

        // Text block — handle headers, bullets, bold/italic
        let content = block.content;
        const isHeader = content.match(/^#{1,3}\s+/);
        if (isHeader) content = content.replace(/^#{1,3}\s+/, "");
        const isBullet = content.match(/^[-*•]\s+/);
        if (isBullet) content = content.replace(/^[-*•]\s+/, "");
        const isNumbered = content.match(/^\d+[.)]\s+/);

        return (
          <div key={bi} style={{
            ...(isHeader ? { fontWeight: 600, color: "#e6edf3", fontSize: 13, marginTop: 10, marginBottom: 2 } : {}),
            ...(isBullet || isNumbered ? { paddingLeft: 14, position: "relative" } : {}),
          }}>
            {isBullet && <span style={{ position: "absolute", left: 0, color: "#484f58" }}>·</span>}
            <InlineFormat text={content} />
          </div>
        );
      })}
    </div>
  );
}

// Inline formatting: **bold**, *italic*, `code`, [links]
function InlineFormat({ text }) {
  if (!text) return null;
  const parts = [];
  let remaining = text;
  let key = 0;

  while (remaining.length > 0) {
    // **bold**
    const boldMatch = remaining.match(/\*\*([^*]+)\*\*/);
    // *italic*
    const italicMatch = remaining.match(/\*([^*]+)\*/);
    // `code`
    const codeMatch = remaining.match(/`([^`]+)`/);

    // Find earliest match
    const matches = [
      boldMatch && { idx: remaining.indexOf(boldMatch[0]), len: boldMatch[0].length, content: boldMatch[1], type: "bold" },
      italicMatch && !boldMatch?.index === italicMatch?.index && { idx: remaining.indexOf(italicMatch[0]), len: italicMatch[0].length, content: italicMatch[1], type: "italic" },
      codeMatch && { idx: remaining.indexOf(codeMatch[0]), len: codeMatch[0].length, content: codeMatch[1], type: "code" },
    ].filter(Boolean).sort((a, b) => a.idx - b.idx);

    if (matches.length === 0) {
      parts.push(<span key={key++}>{remaining}</span>);
      break;
    }

    const first = matches[0];
    if (first.idx > 0) {
      parts.push(<span key={key++}>{remaining.slice(0, first.idx)}</span>);
    }

    if (first.type === "bold") {
      parts.push(<strong key={key++} style={{ color: "#e6edf3", fontWeight: 600 }}>{first.content}</strong>);
    } else if (first.type === "italic") {
      parts.push(<em key={key++} style={{ color: "#c9d1d9" }}>{first.content}</em>);
    } else if (first.type === "code") {
      parts.push(<code key={key++} style={{ background: "#21262d", padding: "1px 5px", borderRadius: 3, fontSize: 11, color: "#bc8cff", fontFamily: "'JetBrains Mono', monospace" }}>{first.content}</code>);
    }

    remaining = remaining.slice(first.idx + first.len);
  }

  return <>{parts}</>;
}

// Simple text cleaner for card descriptions (no components, just string)
function cleanDesc(text) {
  if (!text) return "";
  return text.replace(/\*\*([^*]+)\*\*/g, "$1").replace(/\*([^*]+)\*/g, "$1").trim();
}

const THEMES = [
  "Glass substrate companies",
  "Optics for data centres",
  "AI inference chips",
  "GLP-1 drug manufacturers",
  "Uranium miners",
  "Solid-state batteries",
  "Space economy",
  "Malaysian semiconductor",
];

export default function IndustryScreener() {
  const [query, setQuery] = useState("");
  const [phase, setPhase] = useState("idle");
  const [discovered, setDiscovered] = useState([]);
  const [error, setError] = useState(null);
  const [searchSummary, setSearchSummary] = useState("");
  const [financials, setFinancials] = useState({});
  const [finLoading, setFinLoading] = useState(false);
  const [finLoaded, setFinLoaded] = useState(false);
  const [expandedTicker, setExpandedTicker] = useState(null);
  const [detailCache, setDetailCache] = useState({});
  const [detailLoading, setDetailLoading] = useState(null);
  const [showConfig, setShowConfig] = useState(false);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [configStatus, setConfigStatus] = useState(null);
  const [pplxStatus, setPplxStatus] = useState(null);

  const [chatMessages, setChatMessages] = useState([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [showChat, setShowChat] = useState(false);
  const chatEndRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    Promise.all([
      fetch(`${API}/config`).then(r => r.json()).catch(() => ({ configured: false })),
      fetch(`${API}/pplx-config`).then(r => r.json()).catch(() => ({ configured: false })),
    ]).then(([fmp, pplx]) => { setConfigStatus(fmp); setPplxStatus(pplx); });
  }, []);

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [chatMessages]);

  const saveApiKey = async () => {
    setError(null);
    try {
      const r = await fetch(`${API}/config`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ api_key: apiKeyInput }) });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "Failed");
      setApiKeyInput(""); setConfigStatus({ configured: true });
    } catch (e) { setError(e.message); }
  };

  // ── Search ──
  const runSearch = useCallback(async () => {
    if (!query.trim()) return;
    setPhase("discovering"); setError(null); setDiscovered([]); setFinancials({});
    setFinLoaded(false); setExpandedTicker(null); setSearchSummary("");
    setChatMessages([]); setShowChat(true);
    try {
      const r = await fetch(`${API}/discover`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query: query.trim() }) });
      if (!r.ok) { const err = await r.json().catch(() => ({})); throw new Error(err.detail || `Failed (${r.status})`); }
      const data = await r.json();
      const found = data.companies || [];
      if (!found.length) throw new Error("No companies found. Try different keywords.");
      setDiscovered(found);
      const src = { ollama: "Ollama", gemini: "Gemini", perplexity: "Perplexity", yahoo: "Yahoo", web: "Web" }[data.source] || "";
      setSearchSummary(`${found.length} companies${src ? ` · ${src}` : ""}`);
      setPhase("done");
    } catch (e) { setError(e.message); setPhase("idle"); }
  }, [query]);

  // ── Financials ──
  const loadFinancials = async () => {
    if (!configStatus?.configured) { setShowConfig(true); setError("FMP API key needed for financials."); return; }
    setFinLoading(true);
    try {
      const r = await fetch(`${API}/batch`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(discovered.map(c => c.t)) });
      const result = await r.json();
      const map = {}; for (const c of (result.data || [])) map[c.ticker] = c;
      setFinancials(map); setFinLoaded(true);
    } catch { setError("Failed to load financials"); }
    finally { setFinLoading(false); }
  };

  // ── Detail ──
  const toggleDetail = async (ticker) => {
    if (expandedTicker === ticker) { setExpandedTicker(null); return; }
    setExpandedTicker(ticker);
    if (detailCache[ticker]) return;
    setDetailLoading(ticker);
    try {
      const r = await fetch(`${API}/detail`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ticker }) });
      if (r.ok) { const data = await r.json(); setDetailCache(prev => ({ ...prev, [ticker]: data.summary })); }
      else setDetailCache(prev => ({ ...prev, [ticker]: "Could not load." }));
    } catch { setDetailCache(prev => ({ ...prev, [ticker]: "Failed." })); }
    finally { setDetailLoading(null); }
  };

  // ── Chat ──
  const sendChat = async () => {
    if (!chatInput.trim() || chatLoading) return;
    const msg = chatInput.trim(); setChatInput("");
    const newMsgs = [...chatMessages, { role: "user", content: msg }];
    setChatMessages(newMsgs); setChatLoading(true);
    try {
      const ctx = `${query}. Companies: ${discovered.map(c => `${c.t}: ${c.d}`).join(", ")}`;
      const r = await fetch(`${API}/chat`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg, context: ctx, history: newMsgs.slice(-8) }) });
      if (r.ok) {
        const data = await r.json();
        setChatMessages(prev => [...prev, { role: "assistant", content: data.response }]);
        if (data.new_tickers?.length) {
          const existing = new Set(discovered.map(c => c.t));
          const brandNew = data.new_tickers.filter(t => !existing.has(t));
          if (brandNew.length) {
            const withNames = [];
            for (const t of brandNew) {
              try {
                const pr = await fetch(`${API}/profile/${t}`);
                if (pr.ok) {
                  const p = await pr.json();
                  const name = p.companyName || "";
                  withNames.push({ t, d: p.industry || "" });
                  // Add to financials map so name shows
                  setFinancials(prev => ({ ...prev, [t]: { ...p, ticker: t, name, marketCap: p.marketCap || p.mktCap } }));
                } else {
                  withNames.push({ t, d: "" });
                }
              } catch { withNames.push({ t, d: "" }); }
            }
            setDiscovered(prev => [...prev, ...withNames]);
          }
        }
      } else {
        const err = await r.json().catch(() => ({}));
        setChatMessages(prev => [...prev, { role: "assistant", content: `Error: ${err.detail || "Failed"}` }]);
      }
    } catch (e) { setChatMessages(prev => [...prev, { role: "assistant", content: `Error: ${e.message}` }]); }
    finally { setChatLoading(false); }
  };

  const handleSearch = (e) => { if (e.key === "Enter") runSearch(); };
  const handleChatKey = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); } };

  const exportCSV = () => {
    const rows = discovered.map(c => {
      const f = financials[c.t] || {};
      return [c.t, `"${f.name || ""}"`, `"${(c.d || "").replace(/"/g, "'")}"`, f.marketCap || "", f.peRatio || "", f.price || ""].join(",");
    });
    const blob = new Blob([["Ticker,Name,Description,MktCap,PE,Price", ...rows].join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = `screener-${Date.now()}.csv`; a.click();
  };

  const isSearching = phase === "discovering";

  // ── Render ──
  return (
    <div>
      {/* ── Header ── */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
          <span style={{ fontSize: 18, fontWeight: 700, color: "#e6edf3", letterSpacing: "-0.02em" }}>Screener</span>
          {pplxStatus?.configured ? (
            <span style={{ fontSize: 11, color: "#3fb950", opacity: 0.8 }}>{pplxStatus.key_preview}</span>
          ) : (
            <span style={{ fontSize: 11, color: "#d29922", opacity: 0.7 }}>ollama not detected</span>
          )}
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {discovered.length > 0 && <button className="btn" onClick={exportCSV} style={{ fontSize: 11, padding: "4px 10px" }}>CSV</button>}
          {discovered.length > 0 && (
            <button className="btn" onClick={() => setShowChat(p => !p)}
              style={{ fontSize: 11, padding: "4px 10px", background: showChat ? "#1f6feb20" : undefined, color: showChat ? "#58a6ff" : undefined }}>
              {showChat ? "Close chat" : "Chat"}
            </button>
          )}
          <button className="btn" onClick={() => setShowConfig(p => !p)} style={{ fontSize: 11, padding: "4px 10px" }}>
            {showConfig ? "Close" : "Setup"}
          </button>
        </div>
      </div>

      {/* ── Config ── */}
      {showConfig && (
        <div className="card fade-in" style={{ marginBottom: 16, padding: "14px 16px" }}>
          <div style={{ marginBottom: 10, fontSize: 12, color: "#8b949e" }}>
            <strong style={{ color: "#e6edf3" }}>LLM</strong> — Ollama (local, free). Run: <code style={{ color: "#bc8cff", fontSize: 11 }}>brew install ollama && ollama pull gemma3:4b</code>
            {pplxStatus?.configured && <span style={{ color: "#3fb950", marginLeft: 8 }}>✓ {pplxStatus.key_preview}</span>}
          </div>
          <div style={{ fontSize: 12, color: "#8b949e", marginBottom: 6 }}>
            <strong style={{ color: "#e6edf3" }}>FMP</strong> — financial data (optional). <a href="https://site.financialmodelingprep.com/developer/docs" target="_blank" rel="noopener" style={{ color: "#58a6ff" }}>Free key ↗</a>
            {configStatus?.configured && <span style={{ color: "#3fb950", marginLeft: 8 }}>✓</span>}
          </div>
          {!configStatus?.configured && (
            <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
              <input type="password" value={apiKeyInput} onChange={e => setApiKeyInput(e.target.value)} placeholder="FMP key…"
                style={{ flex: 1, background: "#0d1117", border: "1px solid #30363d", borderRadius: 6, color: "#e6edf3", padding: "6px 10px", fontSize: 12, fontFamily: "'JetBrains Mono', monospace", outline: "none" }} />
              <button className="btn btn-primary" onClick={saveApiKey} disabled={!apiKeyInput.trim()} style={{ fontSize: 11, opacity: apiKeyInput.trim() ? 1 : 0.4 }}>Save</button>
            </div>
          )}
        </div>
      )}

      {/* ── Search ── */}
      <div style={{ display: "flex", background: "#0d1117", border: "1px solid #30363d", borderRadius: 10, overflow: "hidden", marginBottom: 14 }}>
        <input value={query} onChange={e => setQuery(e.target.value)} onKeyDown={handleSearch} disabled={isSearching}
          ref={inputRef} autoFocus
          placeholder="Search any theme… glass substrates, uranium miners, GLP-1 drugs"
          style={{ flex: 1, background: "transparent", border: "none", color: "#e6edf3", padding: "13px 16px", fontSize: 14, fontFamily: "inherit", outline: "none" }} />
        <button onClick={runSearch} disabled={!query.trim() || isSearching}
          style={{ padding: "12px 28px", border: "none", cursor: "pointer", fontFamily: "inherit",
            background: !query.trim() || isSearching ? "#21262d" : "#238636", color: "#fff", fontSize: 13, fontWeight: 600, transition: "background 0.15s" }}>
          {isSearching ? "Searching…" : "Screen"}
        </button>
      </div>

      {/* ── Theme chips ── */}
      {phase === "idle" && discovered.length === 0 && !error && (
        <div style={{ marginBottom: 20 }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
            {THEMES.map(t => (
              <button key={t} onClick={() => { setQuery(t); inputRef.current?.focus(); }}
                style={{ padding: "5px 14px", borderRadius: 20, fontSize: 12, cursor: "pointer", fontFamily: "inherit",
                  background: "transparent", border: "1px solid #30363d", color: "#8b949e", transition: "all 0.15s" }}
                onMouseEnter={e => { e.target.style.borderColor = "#58a6ff"; e.target.style.color = "#58a6ff"; }}
                onMouseLeave={e => { e.target.style.borderColor = "#30363d"; e.target.style.color = "#8b949e"; }}>
                {t}
              </button>
            ))}
          </div>
          <div style={{ fontSize: 12, color: "#484f58" }}>Or enter tickers directly: <span style={{ color: "#8b949e" }}>NVDA, ASML, TSM</span></div>
        </div>
      )}

      {/* ── Status ── */}
      {isSearching && (
        <div style={{ padding: "16px 0", fontSize: 14, color: "#8b949e", display: "flex", alignItems: "center", gap: 10 }}>
          <span className="alert-dot" />
          <span>Discovering companies for <strong style={{ color: "#e6edf3" }}>{query}</strong>…</span>
        </div>
      )}
      {error && (
        <div style={{ padding: "10px 14px", borderRadius: 8, marginBottom: 14, fontSize: 13,
          background: "rgba(248,81,73,0.06)", border: "1px solid rgba(248,81,73,0.15)", color: "#f85149" }}>
          {error}
        </div>
      )}

      {/* ── Results + Chat layout ── */}
      {discovered.length > 0 && (
        <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>

          {/* ── Left: Results ── */}
          <div style={{ flex: 1, minWidth: 0 }}>
            {/* Summary bar */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <span style={{ fontSize: 12, color: "#8b949e" }}>{searchSummary}</span>
              <div style={{ display: "flex", gap: 8 }}>
                {!finLoaded && (
                  <button className="btn" onClick={loadFinancials} disabled={finLoading}
                    style={{ fontSize: 11, padding: "3px 10px", opacity: finLoading ? 0.5 : 1 }}>
                    {finLoading ? "Loading…" : "Load financials"}
                  </button>
                )}
                {finLoaded && <span style={{ fontSize: 11, color: "#3fb950" }}>Financials loaded</span>}
              </div>
            </div>

            {/* ── Company cards ── */}
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              {discovered.map((c, i) => {
                const f = financials[c.t] || {};
                const isExpanded = expandedTicker === c.t;
                const cap = fmtMktCap(f.marketCap);
                const pe = f.peRatio ? fmtNum(f.peRatio) : null;
                const price = f.price ? `$${fmtNum(f.price, 2)}` : null;
                const gm = fmtPct(f.grossMargin);
                const rg = fmtPct(f.revenueGrowth);

                return (
                  <div key={c.t} style={{
                    background: isExpanded ? "#161b22" : i % 2 === 0 ? "#0d1117" : "transparent",
                    borderRadius: 8, overflow: "hidden",
                    border: isExpanded ? "1px solid #30363d" : "1px solid transparent",
                    transition: "all 0.15s",
                  }}>
                    {/* Card header — always visible */}
                    <div onClick={() => toggleDetail(c.t)}
                      style={{ padding: "10px 14px", cursor: "pointer", display: "flex", alignItems: "flex-start", gap: 12 }}
                      onMouseEnter={e => { if (!isExpanded) e.currentTarget.parentElement.style.background = "#161b22"; }}
                      onMouseLeave={e => { if (!isExpanded) e.currentTarget.parentElement.style.background = i % 2 === 0 ? "#0d1117" : "transparent"; }}>

                      {/* Ticker + name */}
                      <div style={{ flex: "0 0 auto", minWidth: 0, maxWidth: 260 }}>
                        <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                          <span style={{ fontSize: 14, fontWeight: 700, color: "#58a6ff", fontFamily: "'JetBrains Mono', monospace", letterSpacing: "0.02em", flexShrink: 0 }}>
                            {c.t}
                          </span>
                          <span style={{ fontSize: 12, color: "#8b949e", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {f.name || ""}
                          </span>
                        </div>
                      </div>

                      {/* Description */}
                      <div style={{ flex: 1, minWidth: 0, fontSize: 13, color: "#c9d1d9", lineHeight: 1.45 }}>
                        {c.d && c.d !== "From chat" && c.d !== "Added from chat" ? cleanDesc(c.d) : f.industry || ""}
                      </div>

                      {/* Metrics (if loaded) */}
                      {finLoaded && (cap || pe) && (
                        <div style={{ flex: "0 0 auto", display: "flex", gap: 6, alignItems: "center", flexShrink: 0 }}>
                          {cap && <span style={{ fontSize: 11, color: "#8b949e", background: "#21262d", padding: "2px 7px", borderRadius: 4, fontFamily: "'JetBrains Mono', monospace" }}>{cap}</span>}
                          {pe && <span style={{ fontSize: 11, color: "#8b949e", background: "#21262d", padding: "2px 7px", borderRadius: 4, fontFamily: "'JetBrains Mono', monospace" }}>{pe}x</span>}
                        </div>
                      )}

                      {/* Links */}
                      <div style={{ flex: "0 0 auto", display: "flex", gap: 4, alignItems: "center" }} onClick={e => e.stopPropagation()}>
                        {[
                          { href: `https://www.perplexity.ai/finance/${c.t}`, label: "P" },
                          { href: `https://finance.yahoo.com/quote/${c.t}`, label: "Y" },
                          { href: `https://finviz.com/quote.ashx?t=${c.t}`, label: "F" },
                          { href: `https://www.capitaliq.com/CIQDotNet/Search/QuickSearch.aspx?query=${c.t}`, label: "C" },
                        ].map(link => (
                          <a key={link.label} href={link.href} target="_blank" rel="noopener"
                            style={{ width: 22, height: 22, display: "flex", alignItems: "center", justifyContent: "center",
                              borderRadius: 4, fontSize: 10, fontWeight: 700, color: "#484f58", textDecoration: "none",
                              border: "1px solid #21262d", transition: "all 0.15s", fontFamily: "'JetBrains Mono', monospace" }}
                            onMouseEnter={e => { e.target.style.color = "#58a6ff"; e.target.style.borderColor = "#58a6ff40"; }}
                            onMouseLeave={e => { e.target.style.color = "#484f58"; e.target.style.borderColor = "#21262d"; }}>
                            {link.label}
                          </a>
                        ))}
                      </div>
                    </div>

                    {/* Expanded detail */}
                    {isExpanded && (
                      <div style={{ padding: "0 14px 14px 14px" }}>
                        <div style={{ borderTop: "1px solid #21262d", paddingTop: 12 }}>
                          {/* Extra financials row if loaded */}
                          {finLoaded && (price || gm || rg) && (
                            <div style={{ display: "flex", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
                              {[
                                price && { label: "Price", value: price },
                                cap && { label: "Mkt Cap", value: cap },
                                pe && { label: "P/E", value: pe },
                                gm && { label: "Gross Margin", value: gm, color: pctColor(f.grossMargin) },
                                rg && { label: "Rev Growth", value: rg, color: pctColor(f.revenueGrowth) },
                                f.roe != null && { label: "ROE", value: fmtPct(f.roe), color: pctColor(f.roe) },
                              ].filter(Boolean).map((m, j) => (
                                <div key={j} style={{ fontSize: 11 }}>
                                  <span style={{ color: "#6e7681" }}>{m.label} </span>
                                  <span style={{ color: m.color || "#c9d1d9", fontFamily: "'JetBrains Mono', monospace", fontWeight: 500 }}>{m.value}</span>
                                </div>
                              ))}
                            </div>
                          )}

                          {/* Investor briefing */}
                          {detailLoading === c.t ? (
                            <div style={{ color: "#8b949e", fontSize: 13, display: "flex", alignItems: "center", gap: 8 }}>
                              <span className="alert-dot" /> Loading recent news…
                            </div>
                          ) : detailCache[c.t] ? (
                            <RenderMD text={detailCache[c.t]} />
                          ) : (
                            <div style={{ fontSize: 12, color: "#484f58" }}>Loading…</div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* ── Right: Chat ── */}
          {showChat && (
            <div style={{ flex: "0 0 320px", position: "sticky", top: 16, maxHeight: "calc(100vh - 100px)", display: "flex", flexDirection: "column" }}>
              <div style={{
                flex: 1, display: "flex", flexDirection: "column",
                background: "#0d1117", border: "1px solid #21262d", borderRadius: 10, overflow: "hidden",
              }}>
                {/* Chat header */}
                <div style={{ padding: "10px 14px", borderBottom: "1px solid #21262d", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: "#e6edf3" }}>Research</span>
                  <span style={{ fontSize: 10, color: "#484f58" }}>{discovered.length} co.</span>
                </div>

                {/* Messages */}
                <div style={{ flex: 1, overflowY: "auto", padding: "10px 12px", display: "flex", flexDirection: "column", gap: 8, minHeight: 200 }}>
                  {chatMessages.length === 0 && (
                    <div style={{ padding: "12px 0" }}>
                      <div style={{ fontSize: 11, color: "#484f58", marginBottom: 8 }}>Follow-up ideas:</div>
                      {["Which are pure-play?", "Give me more companies", "Compare the top 3", "Which have the best moat?"].map(q => (
                        <button key={q} onClick={() => setChatInput(q)}
                          style={{ display: "block", width: "100%", padding: "6px 10px", marginBottom: 4, textAlign: "left",
                            background: "transparent", border: "1px solid #21262d", borderRadius: 6,
                            color: "#6e7681", fontSize: 11, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s" }}
                          onMouseEnter={e => { e.target.style.borderColor = "#30363d"; e.target.style.color = "#8b949e"; }}
                          onMouseLeave={e => { e.target.style.borderColor = "#21262d"; e.target.style.color = "#6e7681"; }}>
                          {q}
                        </button>
                      ))}
                    </div>
                  )}
                  {chatMessages.map((m, i) => (
                    <div key={i} style={{
                      padding: "8px 11px", borderRadius: 8,
                      background: m.role === "user" ? "#1f6feb12" : "#161b22",
                      border: `1px solid ${m.role === "user" ? "#1f6feb25" : "#21262d"}`,
                      maxWidth: "100%",
                    }}>
                      <div style={{ fontSize: 12, color: m.role === "user" ? "#58a6ff" : "#b1bac4", lineHeight: 1.55 }}>
                        {m.role === "user" ? m.content : <RenderMD text={m.content} style={{ fontSize: 12 }} />}
                      </div>
                    </div>
                  ))}
                  {chatLoading && (
                    <div style={{ padding: "6px 10px", color: "#6e7681", fontSize: 12 }}>
                      <span className="alert-dot" /> Thinking…
                    </div>
                  )}
                  <div ref={chatEndRef} />
                </div>

                {/* Input */}
                <div style={{ padding: "8px 10px", borderTop: "1px solid #21262d", display: "flex", gap: 6 }}>
                  <input value={chatInput} onChange={e => setChatInput(e.target.value)}
                    onKeyDown={handleChatKey} disabled={chatLoading}
                    placeholder="Ask anything…"
                    style={{ flex: 1, background: "#161b22", border: "1px solid #30363d", borderRadius: 6,
                      color: "#e6edf3", padding: "8px 10px", fontSize: 12, fontFamily: "inherit", outline: "none" }} />
                  <button onClick={sendChat} disabled={!chatInput.trim() || chatLoading}
                    style={{ padding: "8px 12px", border: "none", borderRadius: 6, cursor: "pointer",
                      background: chatInput.trim() && !chatLoading ? "#238636" : "#21262d",
                      color: "#fff", fontSize: 13, fontWeight: 700, fontFamily: "inherit", transition: "background 0.15s" }}>↑</button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Empty state ── */}
      {phase === "idle" && discovered.length === 0 && !error && (
        <div style={{ textAlign: "center", padding: "50px 20px", color: "#484f58" }}>
          <div style={{ fontSize: 15, color: "#8b949e", marginBottom: 6 }}>
            Type any investment theme and hit <strong style={{ color: "#e6edf3" }}>Screen</strong>
          </div>
          <div style={{ fontSize: 12 }}>
            Local AI discovery via Ollama. Click any result for an investor briefing.
          </div>
        </div>
      )}
    </div>
  );
}
