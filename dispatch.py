#!/usr/bin/env python3
"""
The Closing Bell — Daily Market Dispatch to Telegram
====================================================
1. Fetch latest US market closes via yfinance
2. (Optional) Use Claude API to write a 2-sentence editorial note
3. Render template.html → PNG via headless Chromium
4. Push image + summary caption to your Telegram chat
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
import yfinance as yf
from playwright.sync_api import sync_playwright

# ─── Config ────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT  = os.environ.get("TELEGRAM_CHAT_ID")
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY")          # optional
CLAUDE_MODEL   = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

ROOT       = Path(__file__).parent
TEMPLATE   = ROOT / "template.html"
RENDERED   = ROOT / "rendered.html"
OUTPUT_PNG = ROOT / "dispatch.png"

# Edit this to track different markets / sectors
TICKERS = {
    "sp500":  "^GSPC",
    "nasdaq": "^IXIC",
    "dow":    "^DJI",
    "vix":    "^VIX",
    "usdjpy": "JPY=X",
    "tech":   "XLK",     # Tech sector ETF
    "energy": "XLE",     # Energy sector ETF
}


# ─── Data ──────────────────────────────────────────────────────────
def fetch_market_data():
    """Pull last 2 closes for each ticker, compute % change."""
    print("→ Fetching market data...")
    df = yf.download(
        list(TICKERS.values()),
        period="7d",
        auto_adjust=False,
        progress=False,
    )["Close"].dropna(how="all")

    if len(df) < 2:
        raise RuntimeError(f"Not enough data: only {len(df)} rows returned")

    prev_row, curr_row = df.iloc[-2], df.iloc[-1]
    out = {}
    for name, tkr in TICKERS.items():
        prev = float(prev_row[tkr])
        curr = float(curr_row[tkr])
        change = (curr - prev) / prev * 100
        out[name] = {"level": curr, "change": change}

    date_str = df.index[-1].strftime("%Y-%m-%d")
    return out, date_str


def vix_regime(v):
    if v < 15:  return "Calm"
    if v < 20:  return "Quiet"
    if v < 30:  return "Elevated"
    return "Stressed"


def sector_sentiment(change):
    if change > 1.0:  return "Bullish"
    if change < -1.0: return "Bearish"
    return "Neutral"


# ─── Closing note ──────────────────────────────────────────────────
def write_closing_note(data, date_str):
    """Use Claude to write a 1-2 sentence editorial note. Falls back to a
    simple rule-based summary if no API key is provided."""

    indices = {k: data[k] for k in ("sp500", "nasdaq", "dow")}
    leader = max(indices, key=lambda k: indices[k]["change"])
    leader_name = {"sp500": "S&P 500", "nasdaq": "NASDAQ", "dow": "Dow Jones"}[leader]
    leader_chg = indices[leader]["change"]

    if not ANTHROPIC_KEY:
        if leader_chg > 0.5:
            tone = "broad rally"
        elif leader_chg < -0.5:
            tone = "broad decline"
        else:
            tone = "mixed session"
        return (
            f"Markets close in a {tone} with {leader_name} leading at "
            f"{leader_chg:+.2f}%. VIX at {data['vix']['level']:.2f}, "
            f"USD/JPY at {data['usdjpy']['level']:.2f}."
        )

    # Lazy import so the script still runs without the package installed
    from anthropic import Anthropic
    client = Anthropic(api_key=ANTHROPIC_KEY)

    prompt = f"""You are the editor of a daily financial newspaper called "The Closing Bell".

Today's US market close ({date_str}):
• S&P 500:   {data['sp500']['level']:.2f}  ({data['sp500']['change']:+.2f}%)
• NASDAQ:    {data['nasdaq']['level']:.2f} ({data['nasdaq']['change']:+.2f}%)
• Dow Jones: {data['dow']['level']:.2f}    ({data['dow']['change']:+.2f}%)
• USD/JPY:   {data['usdjpy']['level']:.2f} ({data['usdjpy']['change']:+.2f}%)
• VIX:       {data['vix']['level']:.2f}    ({data['vix']['change']:+.2f}%)
• Tech XLK:  {data['tech']['change']:+.2f}%
• Energy XLE:{data['energy']['change']:+.2f}%

Write the closing editorial note in exactly 2 sentences, max 45 words total.
Editorial newspaper voice — observational and dry, not breathless.
Mention the day's leader and one notable cross-market signal (yen move,
sector divergence, vol regime, etc.).
No emojis. No headers. No quotation marks. Just the prose."""

    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip().strip('"').strip("'")


# ─── Render ────────────────────────────────────────────────────────
def build_payload(data, date_str, note):
    return {
        "date": date_str,
        "issueNumber": f"{datetime.now().timetuple().tm_yday:03d}",
        "indices": [
            {"name": "S&P 500",   "level": round(data["sp500"]["level"], 2),  "change": round(data["sp500"]["change"], 2)},
            {"name": "NASDAQ",    "level": round(data["nasdaq"]["level"], 2), "change": round(data["nasdaq"]["change"], 2)},
            {"name": "Dow Jones", "level": round(data["dow"]["level"], 2),    "change": round(data["dow"]["change"], 2)},
        ],
        "forex": {
            "pair":   "USD/JPY",
            "value":  round(data["usdjpy"]["level"], 2),
            "change": round(data["usdjpy"]["change"], 2),
        },
        "vix": {
            "value":  round(data["vix"]["level"], 2),
            "change": round(data["vix"]["change"], 2),
            "regime": vix_regime(data["vix"]["level"]),
        },
        "sectors": [
            {"name": "Technology", "change": round(data["tech"]["change"], 2),
             "sentiment": sector_sentiment(data["tech"]["change"])},
            {"name": "Energy",     "change": round(data["energy"]["change"], 2),
             "sentiment": sector_sentiment(data["energy"]["change"])},
        ],
        "closingNote": note,
    }


def render_html(payload):
    template = TEMPLATE.read_text(encoding="utf-8")
    rendered = template.replace("__DATA_JSON__", json.dumps(payload, ensure_ascii=False))
    RENDERED.write_text(rendered, encoding="utf-8")
    return RENDERED


def render_png(html_path):
    print("→ Rendering PNG via headless Chromium...")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": 640, "height": 1200},
            device_scale_factor=3,
        )
        page.goto(f"file://{html_path.absolute()}")
        page.wait_for_load_state("networkidle")
        # Wait for chart + fonts; degrade gracefully if CDN is slow/blocked
        try:
            page.wait_for_function("window.__chartReady === true", timeout=8000)
        except Exception:
            print("⚠ chartReady signal didn't fire — proceeding anyway")
        page.wait_for_timeout(800)
        page.locator(".shell").screenshot(path=str(OUTPUT_PNG))
        browser.close()
    return OUTPUT_PNG


# ─── Telegram ──────────────────────────────────────────────────────
def send_telegram(image_path, payload):
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT):
        print("⚠ Telegram credentials missing — saved PNG locally only.")
        print(f"  PNG: {image_path}")
        return

    idx = {i["name"]: i for i in payload["indices"]}
    caption = (
        f"<b>The Closing Bell</b> · {payload['date']}\n\n"
        f"<code>S&amp;P 500   {idx['S&P 500']['level']:>10,.2f}  {idx['S&P 500']['change']:+.2f}%</code>\n"
        f"<code>NASDAQ      {idx['NASDAQ']['level']:>10,.2f}  {idx['NASDAQ']['change']:+.2f}%</code>\n"
        f"<code>Dow Jones   {idx['Dow Jones']['level']:>10,.2f}  {idx['Dow Jones']['change']:+.2f}%</code>\n\n"
        f"<i>{payload['closingNote']}</i>"
    )

    print("→ Sending to Telegram...")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    with open(image_path, "rb") as f:
        r = requests.post(
            url,
            data={"chat_id": TELEGRAM_CHAT, "caption": caption, "parse_mode": "HTML"},
            files={"photo": f},
            timeout=30,
        )
    if not r.ok:
        print(f"✗ Telegram error {r.status_code}: {r.text}")
        r.raise_for_status()
    print(f"✓ Sent to chat {TELEGRAM_CHAT}")


# ─── Main ──────────────────────────────────────────────────────────
def main():
    data, date_str = fetch_market_data()
    print(f"  Latest close: {date_str}")

    note = write_closing_note(data, date_str)
    print(f"  Note: {note}")

    payload = build_payload(data, date_str, note)
    html_path = render_html(payload)
    png_path = render_png(html_path)
    send_telegram(png_path, payload)

    print("✓ Dispatch complete.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"✗ Failed: {e}", file=sys.stderr)
        sys.exit(1)
