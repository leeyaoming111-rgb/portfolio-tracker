"""
screener.py — Industry Screener backend

Discovery priority:
  1. Gemini 2.0 Flash (free, 1500 req/day — ~/.gemini_api_key)
  2. Perplexity Sonar (if ~/.perplexity_api_key exists)
  3. Yahoo Finance search (free, no key)
  4. DuckDuckGo scraping (free, no key)

Financials: FMP /stable/ API (optional)

Requires: pip install httpx
Optional: pip install duckduckgo-search
"""

import json, os, re, asyncio
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx

screener_router = APIRouter(prefix="/screener", tags=["screener"])

FMP_KEY_FILE = os.path.expanduser("~/.fmp_api_key")
GEMINI_KEY_FILE = os.path.expanduser("~/.gemini_api_key")
PPLX_KEY_FILE = os.path.expanduser("~/.perplexity_api_key")
FMP_BASE = "https://financialmodelingprep.com/stable"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
PPLX_BASE = "https://api.perplexity.ai"
YAHOO_SEARCH = "https://query2.finance.yahoo.com/v1/finance/search"


def _read_key(filepath, env_var=None):
    if env_var:
        k = os.environ.get(env_var, "").strip()
        if k: return k
    if os.path.exists(filepath):
        with open(filepath) as f:
            k = f.read().strip()
        if k: return k
    return ""

def _get_fmp_key():
    k = _read_key(FMP_KEY_FILE, "FMP_API_KEY")
    if k: return k
    raise HTTPException(400, "No FMP API key. Set it in Screener → ⚙ Keys.")


# ── Config ──────────────────────────────────────────────

class ConfigPayload(BaseModel):
    api_key: str

@screener_router.post("/config")
async def set_fmp_key(payload: ConfigPayload):
    key = payload.api_key.strip()
    if not key: raise HTTPException(400, "Empty key")
    with open(FMP_KEY_FILE, "w") as f: f.write(key)
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{FMP_BASE}/profile", params={"symbol": "AAPL", "apikey": key})
        data = r.json()
        if isinstance(data, dict) and data.get("Error Message"):
            os.remove(FMP_KEY_FILE); raise HTTPException(400, data["Error Message"])
        if isinstance(data, list) and not data:
            os.remove(FMP_KEY_FILE); raise HTTPException(400, "Key returned no data")
    return {"status": "ok"}

@screener_router.get("/config")
async def get_config():
    try:
        k = _get_fmp_key()
        return {"configured": True, "key_preview": k[:4] + "…" + k[-4:]}
    except: return {"configured": False, "key_preview": None}

@screener_router.get("/pplx-config")
async def get_pplx_config():
    # Check all LLM sources
    # 1. Ollama (local)
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            r = await client.get("http://localhost:11434/api/tags")
            if r.status_code == 200:
                models = r.json().get("models", [])
                if models:
                    return {"configured": True, "key_preview": f"Ollama ({models[0]['name']})"}
    except: pass
    # 2. Gemini
    gemini = bool(_read_key(GEMINI_KEY_FILE, "GEMINI_API_KEY"))
    if gemini: return {"configured": True, "key_preview": "Gemini ✓"}
    # 3. Perplexity
    pplx = bool(_read_key(PPLX_KEY_FILE, "PERPLEXITY_API_KEY"))
    if pplx: return {"configured": True, "key_preview": "Perplexity ✓"}
    return {"configured": False, "key_preview": None}

@screener_router.post("/pplx-config")
async def set_pplx_key(payload: ConfigPayload):
    # Save as gemini key (since that's our primary now)
    key = payload.api_key.strip()
    if not key: raise HTTPException(400, "Empty key")
    with open(GEMINI_KEY_FILE, "w") as f: f.write(key)
    return {"status": "ok", "message": "Gemini key saved"}


# ── FMP helper ──────────────────────────────────────────

async def _fmp_get(client, endpoint, key, extra_params=None):
    params = {"apikey": key}
    if extra_params: params.update(extra_params)
    try:
        r = await client.get(f"{FMP_BASE}/{endpoint}", params=params)
        if r.status_code in (429, 402): return {"__error": f"FMP {r.status_code}"}
        data = r.json()
        if isinstance(data, dict) and (data.get("Error Message") or data.get("error")):
            return {"__error": data.get("Error Message") or data.get("error")}
        return data
    except Exception as e:
        return {"__error": str(e)}


# ── LLM Discovery prompt ──────────────────────────────

DISCOVER_PROMPT = '''List every publicly traded company with significant exposure to: "{query}"

Return ONLY a JSON array. Each object must have:
- "t": stock ticker symbol (US-listed preferred, e.g. "NVDA", "ASML")
- "d": one sentence explaining relevance to the theme

Return 20-30 companies. Include both large-cap leaders and smaller pure-play companies.
NO markdown, NO code fences, ONLY the JSON array.
Example: [{{"t":"NVDA","d":"Leading GPU maker for AI training"}}]'''


def _parse_llm_json(text):
    """Parse JSON array from LLM response, handling code fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        text = match.group(0)
    companies = json.loads(text)
    if not isinstance(companies, list):
        return []
    return [{"t": c["t"].upper().strip(), "d": c.get("d", "")}
            for c in companies if isinstance(c, dict) and c.get("t")]


# ── Discovery: Ollama (local, free, no API key) ───────

OLLAMA_URL = "http://localhost:11434/api/generate"

async def _discover_ollama(query, client):
    """Use local Ollama LLM for thematic discovery. No API key needed."""
    try:
        # Check if Ollama is running
        health = await client.get("http://localhost:11434/api/tags", timeout=3)
        if health.status_code != 200:
            return []
        models = health.json().get("models", [])
        if not models:
            print("⚠️  Ollama running but no models installed. Run: ollama pull gemma3:4b")
            return []
        # Use first available model
        model = models[0]["name"]
        print(f"🤖 Using Ollama model: {model}")
    except Exception:
        return []  # Ollama not running, skip silently

    try:
        r = await client.post(OLLAMA_URL, json={
            "model": model,
            "prompt": DISCOVER_PROMPT.format(query=query),
            "stream": False,
            "options": {"temperature": 0.3},
        }, timeout=60)
        if r.status_code != 200:
            print(f"⚠️  Ollama {r.status_code}")
            return []
        text = r.json().get("response", "")
        result = _parse_llm_json(text)
        if result:
            print(f"✅ Ollama found {len(result)} companies for '{query}'")
        return result
    except Exception as e:
        print(f"⚠️  Ollama error: {e}")
        return []


# ── Discovery: Gemini (free, 1500 req/day) ─────────────

async def _discover_gemini(query, client):
    key = _read_key(GEMINI_KEY_FILE, "GEMINI_API_KEY")
    if not key: return []
    try:
        r = await client.post(
            f"{GEMINI_URL}?key={key}",
            json={
                "contents": [{"parts": [{"text": DISCOVER_PROMPT.format(query=query)}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 2000},
            },
            timeout=25,
        )
        if r.status_code == 429:
            print("⚠️  Gemini rate limited, trying next source")
            return []
        if r.status_code != 200:
            print(f"⚠️  Gemini {r.status_code}: {r.text[:200]}")
            return []
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return _parse_llm_json(text)
    except Exception as e:
        print(f"⚠️  Gemini error: {e}")
        return []


# ── Discovery: Perplexity (if key exists) ─────────────

async def _discover_pplx(query, client):
    key = _read_key(PPLX_KEY_FILE, "PERPLEXITY_API_KEY")
    if not key: return []
    try:
        r = await client.post(f"{PPLX_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "sonar", "messages": [{"role": "user", "content": DISCOVER_PROMPT.format(query=query)}], "max_tokens": 1500},
            timeout=30)
        if r.status_code != 200:
            print(f"⚠️  Perplexity {r.status_code}")
            return []
        text = r.json()["choices"][0]["message"]["content"]
        return _parse_llm_json(text)
    except Exception as e:
        print(f"⚠️  Perplexity error: {e}")
        return []


# ── Discovery: Yahoo Finance (free, no key) ───────────

async def _discover_yahoo(query, client):
    all_tickers = {}
    headers = {"User-Agent": "Mozilla/5.0"}
    words = [w for w in query.split() if len(w) > 2 and w.lower() not in
             {"the","and","for","are","inc","ltd","with","from","that","this",
              "companies","company","stock","stocks","publicly","traded"}]
    searches = [query] + words[:3]

    for sq in searches:
        try:
            r = await client.get(YAHOO_SEARCH, params={
                "q": sq, "quotesCount": "20", "newsCount": "0",
            }, headers=headers, timeout=10)
            if r.status_code != 200: continue
            for quote in r.json().get("quotes", []):
                sym = quote.get("symbol", "")
                qtype = quote.get("typeDisp", "")
                if qtype and qtype not in ("Equity", "ETF", "Fund"): continue
                if "." in sym: continue  # skip international
                if sym and sym not in all_tickers:
                    name = quote.get("shortname") or quote.get("longname") or sym
                    exch = quote.get("exchDisp", "")
                    all_tickers[sym] = {"t": sym, "d": f"{name} ({exch})" if exch else name}
        except Exception as e:
            print(f"⚠️  Yahoo '{sq}': {e}")
    return list(all_tickers.values())


# ── Discovery: Web scraping (httpx only, no packages) ──

NOISE = {"THE","AND","FOR","ARE","INC","LTD","ETF","USA","CEO","IPO","SEC",
         "LLC","PLC","NYSE","ALL","TOP","NEW","HAS","ITS","NOT","BUT","CAN",
         "MAY","WAS","ONE","TWO","NOW","HOW","GET","BUY","USD","EUR","GBP",
         "FAQ","PDF","URL","CFO","COO","CTO","ESG","EPS","ROE","COM","NET",}

def _extract_tickers(text):
    tickers = set()
    for m in re.finditer(r'\b(?:NASDAQ|NYSE|AMEX|NYSEARCA)\s*[:/]\s*([A-Z]{1,5})\b', text):
        tickers.add(m.group(1))
    for m in re.finditer(r'[a-z)]\s*\(([A-Z]{2,5})\)', text):
        if m.group(1) not in NOISE: tickers.add(m.group(1))
    for m in re.finditer(r'\$([A-Z]{2,5})\b', text):
        if m.group(1) not in NOISE: tickers.add(m.group(1))
    return tickers

async def _discover_web_scrape(query, client):
    """
    Scrape finance article pages directly via httpx.
    No DDG package needed — uses Google search redirects and direct finance URLs.
    """
    tickers = set()
    descs = {}
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

    # Scrape Seeking Alpha search
    sa_urls = [
        f"https://seekingalpha.com/search?q={query.replace(' ', '+')}&type=stocks",
    ]

    # Scrape stockanalysis.com search
    sa2_urls = [
        f"https://stockanalysis.com/actions/search/?q={query.replace(' ', '+')}",
    ]

    # Google search for finance articles (returns HTML with tickers)
    google_queries = [
        f"{query} stocks ticker site:seekingalpha.com OR site:finance.yahoo.com OR site:finviz.com",
        f"{query} publicly traded companies investing",
    ]

    # Try Google search
    for gq in google_queries:
        try:
            r = await client.get("https://www.google.com/search", params={"q": gq, "num": "15"},
                                 headers=headers, timeout=10, follow_redirects=True)
            if r.status_code == 200:
                page = r.text
                # Extract tickers from Google results page
                for t in _extract_tickers(page):
                    tickers.add(t)
                # Extract from result URLs embedded in the page
                for p in [r'finance\.yahoo\.com/quote/([A-Z]{1,5})',
                          r'finviz\.com/quote\.ashx\?t=([A-Z]{1,5})',
                          r'seekingalpha\.com/symbol/([A-Z]{1,5})',
                          r'stockanalysis\.com/stocks/([a-zA-Z]{1,5})']:
                    for m in re.finditer(p, page, re.I):
                        sym = m.group(1).upper()
                        if sym not in NOISE:
                            tickers.add(sym)
        except Exception as e:
            print(f"⚠️  Google scrape failed: {e}")

    # Try stockanalysis.com JSON search (returns structured data)
    try:
        r = await client.get(f"https://stockanalysis.com/actions/search/",
                             params={"q": query}, headers=headers, timeout=8)
        if r.status_code == 200:
            try:
                data = r.json()
                for item in (data if isinstance(data, list) else data.get("data", [])):
                    sym = item.get("s", "") or item.get("symbol", "")
                    name = item.get("n", "") or item.get("name", "")
                    if sym and len(sym) <= 5:
                        tickers.add(sym.upper())
                        descs[sym.upper()] = name
            except: pass
    except Exception as e:
        print(f"⚠️  stockanalysis search failed: {e}")

    print(f"  Web scrape: {len(tickers)} tickers found")
    return [{"t": t, "d": descs.get(t, "")} for t in tickers]


# ── Main discover endpoint ─────────────────────────────

class DiscoverPayload(BaseModel):
    query: str

@screener_router.post("/discover")
async def discover_companies(payload: DiscoverPayload):
    query = payload.query.strip()
    if not query: raise HTTPException(400, "Query cannot be empty")

    # Manual tickers?
    tokens = [t.strip() for t in re.split(r"[,\s\n]+", query) if t.strip()]
    if all(re.match(r'^[A-Z0-9.]{1,10}$', t) for t in tokens) and len(tokens) >= 2:
        return {"companies": [{"t": t, "d": ""} for t in tokens[:30]], "count": len(tokens[:30]), "source": "manual"}

    async with httpx.AsyncClient(timeout=30) as client:
        # 1. Ollama (local LLM, free, no API key)
        companies = await _discover_ollama(query, client)
        if companies:
            return {"companies": companies[:30], "count": len(companies[:30]), "source": "ollama"}

        # 2. Gemini (free, best for thematic)
        companies = await _discover_gemini(query, client)
        if companies:
            print(f"✅ Gemini found {len(companies)} companies for '{query}'")
            return {"companies": companies[:30], "count": len(companies[:30]), "source": "gemini"}

        # 2. Perplexity (if key exists)
        companies = await _discover_pplx(query, client)
        if companies:
            print(f"✅ Perplexity found {len(companies)} companies for '{query}'")
            return {"companies": companies[:30], "count": len(companies[:30]), "source": "perplexity"}

        # 3. Yahoo Finance search
        companies = await _discover_yahoo(query, client)
        if companies:
            print(f"✅ Yahoo found {len(companies)} companies for '{query}'")
            return {"companies": companies[:30], "count": len(companies[:30]), "source": "yahoo"}

        # 4. Web scraping (Google results + stockanalysis.com)
        companies = await _discover_web_scrape(query, client)
        if companies:
            print(f"✅ Web scrape found {len(companies)} companies for '{query}'")
            return {"companies": companies[:30], "count": len(companies[:30]), "source": "web"}

    raise HTTPException(404, f"No companies found for '{query}'. Try different keywords or enter tickers directly.")


# ── Company Detail ─────────────────────────────────────

# Strip AI disclaimers from any LLM response
def _strip_ai_slop(text):
    lines = text.strip().split("\n")
    cleaned = []
    for line in lines:
        low = line.lower()
        if any(p in low for p in [
            "i am an ai", "i'm an ai", "as an ai", "ai chatbot", "not financial advi",
            "not a financial", "this is not", "consult with a", "do your own",
            "this information is based on", "as of today", "as of the date",
            "subject to change", "disclaimer:", "*disclaimer", "important disclaimer",
            "please note that", "always do your own", "i cannot provide financial",
            "not investment advice", "for informational purposes",
        ]):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()

class DetailPayload(BaseModel):
    ticker: str

@screener_router.post("/detail")
async def get_company_detail(payload: DetailPayload):
    ticker = payload.ticker.strip().upper()
    detail_prompt = f"""Recent factual information about {ticker} (publicly traded company):

1. What the company does (2 sentences, factual)
2. Latest earnings results (revenue, EPS, guidance if available)
3. Recent news and events from the last 3-6 months (acquisitions, product launches, management changes, regulatory actions)
4. Key upcoming catalysts or dates (earnings date, FDA decisions, contract renewals)

Rules:
- Only include verified facts, no speculation or opinion
- Be specific with numbers and dates
- Do NOT include any disclaimers, caveats, or statements about being an AI
- Do NOT say "as of" any date or mention data currency
- Write as a factual research note, 200-300 words, plain text
- No markdown headers, just flowing paragraphs with line breaks between sections"""

    # Try Ollama first (local, free)
    async with httpx.AsyncClient(timeout=60) as client:
        try:
            health = await client.get("http://localhost:11434/api/tags", timeout=3)
            if health.status_code == 200:
                models = health.json().get("models", [])
                if models:
                    r = await client.post(OLLAMA_URL, json={
                        "model": models[0]["name"], "prompt": detail_prompt, "stream": False,
                    }, timeout=60)
                    if r.status_code == 200:
                        text = r.json().get("response", "")
                        if text.strip():
                            return {"ticker": ticker, "summary": _strip_ai_slop(text)}
        except: pass

    # Try Gemini
    gemini_key = _read_key(GEMINI_KEY_FILE, "GEMINI_API_KEY")
    if gemini_key:
        try:
            async with httpx.AsyncClient(timeout=25) as client:
                r = await client.post(f"{GEMINI_URL}?key={gemini_key}",
                    json={"contents": [{"parts": [{"text": detail_prompt}]}],
                        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1000}})
                if r.status_code == 200:
                    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                    return {"ticker": ticker, "summary": _strip_ai_slop(text)}
        except: pass

    # Try Perplexity
    pplx_key = _read_key(PPLX_KEY_FILE, "PERPLEXITY_API_KEY")
    if pplx_key:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(f"{PPLX_BASE}/chat/completions",
                    headers={"Authorization": f"Bearer {pplx_key}", "Content-Type": "application/json"},
                    json={"model": "sonar", "messages": [{"role": "user", "content": detail_prompt}],
                        "max_tokens": 1000})
                if r.status_code == 200:
                    return {"ticker": ticker, "summary": _strip_ai_slop(r.json()["choices"][0]["message"]["content"])}
        except: pass

    # Fallback: FMP description
    try:
        fmp_key = _get_fmp_key()
        async with httpx.AsyncClient(timeout=10) as client:
            data = await _fmp_get(client, "profile", fmp_key, {"symbol": ticker})
            if isinstance(data, list) and data:
                p = data[0]
                header = f"{p.get('companyName', ticker)} — {p.get('industry', '')}, {p.get('sector', '')}\n\n"
                return {"ticker": ticker, "summary": header + p.get("description", "No description.")}
    except: pass
    return {"ticker": ticker, "summary": "Could not load details. Try the Perplexity Finance or Yahoo Finance links."}


# ── FMP Financials ─────────────────────────────────────

@screener_router.get("/profile/{ticker}")
async def get_profile(ticker: str):
    key = _get_fmp_key()
    async with httpx.AsyncClient(timeout=15) as client:
        data = await _fmp_get(client, "profile", key, {"symbol": ticker})
    if isinstance(data, dict) and "__error" in data: raise HTTPException(502, data["__error"])
    if isinstance(data, list) and data: return data[0]
    raise HTTPException(404, f"No profile for {ticker}")

@screener_router.post("/batch")
async def batch_financials(tickers: list[str]):
    key = _get_fmp_key()
    results, errors = [], []
    async with httpx.AsyncClient(timeout=15) as client:
        for ticker in tickers:
            prof, rat, grw = await asyncio.gather(
                _fmp_get(client, "profile", key, {"symbol": ticker}),
                _fmp_get(client, "ratios-ttm", key, {"symbol": ticker}),
                _fmp_get(client, "financial-growth", key, {"symbol": ticker, "limit": "1"}))
            for resp in [prof, rat, grw]:
                if isinstance(resp, dict) and "Rate" in resp.get("__error", ""):
                    return {"data": results, "errors": errors + [{"ticker": ticker, "error": "Rate limited"}], "rate_limited": True}
            p = prof[0] if isinstance(prof, list) and prof else None
            r = rat[0] if isinstance(rat, list) and rat else None
            g = grw[0] if isinstance(grw, list) and grw else None
            if not p and not r and not g:
                errors.append({"ticker": ticker, "error": "No data"}); continue
            results.append({
                "ticker": ticker, "name": (p or {}).get("companyName", ticker),
                "exchange": (p or {}).get("exchangeShortName", "—"), "country": (p or {}).get("country", "—"),
                "sector": (p or {}).get("sector", "—"), "industry": (p or {}).get("industry", "—"),
                "description": (p or {}).get("description", ""),
                "marketCap": (p or {}).get("marketCap") or (p or {}).get("mktCap"),
                "price": (p or {}).get("price"),
                "peRatio": (r or {}).get("peRatioTTM"), "pbRatio": (r or {}).get("priceToBookRatioTTM"),
                "psRatio": (r or {}).get("priceToSalesRatioTTM"), "evToEbitda": (r or {}).get("enterpriseValueOverEBITDATTM"),
                "grossMargin": (r or {}).get("grossProfitMarginTTM"), "operatingMargin": (r or {}).get("operatingProfitMarginTTM"),
                "netMargin": (r or {}).get("netProfitMarginTTM"), "roe": (r or {}).get("returnOnEquityTTM"),
                "roic": (r or {}).get("returnOnCapitalEmployedTTM"),
                "revenueGrowth": (g or {}).get("revenueGrowth"), "epsGrowth": (g or {}).get("epsgrowth"),
                "netIncomeGrowth": (g or {}).get("netIncomeGrowth"),
            })
            await asyncio.sleep(0.15)
    return {"data": results, "errors": errors, "rate_limited": False}


# ── Chat (contextual follow-up) ───────────────────────

class ChatPayload(BaseModel):
    message: str
    context: str = ""  # previous companies/topic for context
    history: list = []  # [{role, content}, ...]

@screener_router.post("/chat")
async def screener_chat(payload: ChatPayload):
    """
    Chat with the LLM about the current screener results.
    Supports follow-ups like "give me more companies", "which are pure-play?", etc.
    """
    message = payload.message.strip()
    if not message: raise HTTPException(400, "Empty message")

    system = "You are a financial research assistant. Be concise and specific. When listing companies, always include stock ticker symbols. When comparing companies, use a markdown table with | separators and a header row with |---|---| dividers. Never include disclaimers about being an AI, not being a financial advisor, or suggesting the user consult a professional. Write as a research note."
    if payload.context:
        system += f"\n\nContext — the user previously searched for companies related to: {payload.context}"

    # Build messages
    messages = [{"role": "system", "content": system}]
    for h in payload.history[-10:]:  # last 10 messages for context
        messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
    messages.append({"role": "user", "content": message})

    # Try Ollama
    async with httpx.AsyncClient(timeout=90) as client:
        try:
            health = await client.get("http://localhost:11434/api/tags", timeout=3)
            if health.status_code == 200:
                models = health.json().get("models", [])
                if models:
                    # Ollama chat API
                    r = await client.post("http://localhost:11434/api/chat", json={
                        "model": models[0]["name"],
                        "messages": messages,
                        "stream": False,
                    }, timeout=90)
                    if r.status_code == 200:
                        text = r.json().get("message", {}).get("content", "")
                        if text.strip():
                            # Try to extract any new tickers from the response
                            new_tickers = _extract_tickers_from_chat(text)
                            return {"response": _strip_ai_slop(text), "new_tickers": new_tickers}
        except Exception as e:
            print(f"⚠️  Ollama chat error: {e}")

    # Fallback: Gemini
    gemini_key = _read_key(GEMINI_KEY_FILE, "GEMINI_API_KEY")
    if gemini_key:
        try:
            prompt = system + "\n\n" + "\n".join(
                f"{'User' if m['role']=='user' else 'Assistant'}: {m['content']}" for m in messages[1:]
            )
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(f"{GEMINI_URL}?key={gemini_key}", json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.4, "maxOutputTokens": 2000},
                })
                if r.status_code == 200:
                    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                    return {"response": _strip_ai_slop(text), "new_tickers": _extract_tickers_from_chat(text)}
        except: pass

    # Fallback: Perplexity
    pplx_key = _read_key(PPLX_KEY_FILE, "PERPLEXITY_API_KEY")
    if pplx_key:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(f"{PPLX_BASE}/chat/completions",
                    headers={"Authorization": f"Bearer {pplx_key}", "Content-Type": "application/json"},
                    json={"model": "sonar", "messages": messages, "max_tokens": 2000})
                if r.status_code == 200:
                    text = r.json()["choices"][0]["message"]["content"]
                    return {"response": _strip_ai_slop(text), "new_tickers": _extract_tickers_from_chat(text)}
        except: pass

    raise HTTPException(503, "No LLM available. Make sure Ollama is running.")


def _extract_tickers_from_chat(text):
    """Extract ticker symbols mentioned in chat response."""
    tickers = set()
    # Match patterns like (GLW), (NASDAQ: NVDA), $AAPL, ticker: MSFT
    for m in re.finditer(r'\b(?:NASDAQ|NYSE|AMEX)\s*[:/]\s*([A-Z]{1,5})\b', text):
        tickers.add(m.group(1))
    for m in re.finditer(r'\(([A-Z]{2,5})\)', text):
        if m.group(1) not in NOISE: tickers.add(m.group(1))
    for m in re.finditer(r'\$([A-Z]{2,5})\b', text):
        if m.group(1) not in NOISE: tickers.add(m.group(1))
    for m in re.finditer(r'\*\*([A-Z]{1,5})\*\*', text):
        if m.group(1) not in NOISE: tickers.add(m.group(1))
    for m in re.finditer(r'Ticker:\s*([A-Z]{1,5})', text):
        tickers.add(m.group(1))
    return list(tickers)
