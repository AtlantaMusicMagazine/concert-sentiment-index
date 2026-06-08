"""
build_html.py
Atlanta Music Magazine — Dashboard HTML Builder
Reads data/scored_events.json, generates fresh card HTML for each event,
and writes the final dashboard to output/artist_card_module.html.

Strategy: the dashboard HTML has two sentinel comment blocks:
  <!-- TOP_CARDS_START --> … <!-- TOP_CARDS_END -->
  <!-- BOTTOM_CARDS_START --> … <!-- BOTTOM_CARDS_END -->
This script replaces everything between those comments with freshly
generated card HTML, preserving all CSS, JS, and structural markup.
"""

import json
import math
import datetime
import re
from pathlib import Path

Path("output").mkdir(exist_ok=True)

TEMPLATE_PATH = "templates/artist_card_module.html"
OUTPUT_PATH   = "output/artist_card_module.html"
SCORES_PATH   = "data/scored_events.json"

TOP_N    = 20   # number of events in each panel
BOTTOM_N = 20


# ── Genre pill colours ────────────────────────────────────────────────────
GENRE_STYLES = {
    "Pop":           ("background:#eeedfb;color:#4038b0;"),
    "Latin Pop":     ("background:#fef6e0;color:#6a4400;"),
    "Country":       ("background:#fef6e0;color:#6a4400;"),
    "Hip-Hop":       ("background:#e8f5ee;color:#134a28;"),
    "R&B":           ("background:#e8f5ee;color:#134a28;"),
    "Rock":          ("background:#fdecea;color:#721a0a;"),
    "Alt / Rock":    ("background:#fdecea;color:#721a0a;"),
    "Alt / R&B":     ("background:#eef0ff;color:#283ab0;"),
    "Reggae":        ("background:#eef0ff;color:#283ab0;"),
    "Indie / Psych": ("background:#fde8f8;color:#650c5c;"),
    "Indie / Alt":   ("background:#fde8f8;color:#650c5c;"),
    "Classic Rock":  ("background:#fef6e0;color:#6a4400;"),
    "Metalcore":     ("background:#f2f2f4;color:#36363e;"),
    "Hyperpop":      ("background:#eef0ff;color:#283ab0;"),
    "Multi-Genre":   ("background:#eef0ff;color:#283ab0;"),
    "Pop / Rock":    ("background:#eeedfb;color:#4038b0;"),
    "Pop / Soul":    ("background:#eeedfb;color:#4038b0;"),
}
GENRE_STYLE_DEFAULT = "background:#f0f0f4;color:#333340;"


def genre_style(genre):
    return GENRE_STYLES.get(genre, GENRE_STYLE_DEFAULT)


# ── Ordinal helper ────────────────────────────────────────────────────────
def ordinal(n):
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{'th' if (n % 10) not in (1,2,3) else ['st','nd','rd'][n%10-1]}"


# ── Format date for display ───────────────────────────────────────────────
MONTH_ABBR = ["Jan","Feb","Mar","Apr","May","Jun",
               "Jul","Aug","Sep","Oct","Nov","Dec"]

def fmt_date(iso):
    """2026-07-11 → Jul 11"""
    try:
        y, m, d = iso.split("-")
        return f"{MONTH_ABBR[int(m)-1]} {int(d)}"
    except Exception:
        return iso


# ── Signal dot builder ────────────────────────────────────────────────────
def signal_dot(level):
    return f'<span class="signal-dot dot-{level.lower()}" aria-hidden="true"></span>'


def build_signals_html(ev):
    """
    Build the 8-signal <ul> from scored event data.
    4 summary signals + 4 raw data points.
    """
    sl = ev["signal_levels"]
    raw = ev["raw_signals"]
    signals = [
        (sl["sentiment"],       "Sentiment",      sl["sentiment"]),
        (sl["historical_sales"],"Sales history",  sl["historical_sales"]),
        (sl["ticket_demand"],   "Ticket demand",  sl["ticket_demand"]),
        (sl["local_intent"],    "Local intent",   sl["local_intent"]),
    ]

    # Dynamic detail signals based on available raw data
    if raw.get("seatgeek_deal_score") is not None:
        lvl = "high" if raw["seatgeek_deal_score"] >= 65 else ("medium" if raw["seatgeek_deal_score"] >= 35 else "low")
        signals.append((lvl, "SeatGeek Deal Score", f"{raw['seatgeek_deal_score']}/100"))
    if raw.get("seatgeek_floor") is not None:
        lvl = "high" if raw["seatgeek_floor"] >= 150 else ("medium" if raw["seatgeek_floor"] >= 60 else "low")
        signals.append((lvl, "Secondary floor", f"${raw['seatgeek_floor']:.0f}"))
    if raw.get("google_trends_atl") is not None:
        lvl = "high" if raw["google_trends_atl"] >= 65 else ("medium" if raw["google_trends_atl"] >= 35 else "low")
        signals.append((lvl, "ATL Google Trends index", str(raw["google_trends_atl"])))
    if raw.get("bandsintown_rsvps") is not None:
        lvl = "high" if raw["bandsintown_rsvps"] >= 5000 else ("medium" if raw["bandsintown_rsvps"] >= 1000 else "low")
        signals.append((lvl, "Bands in Town intent", f"{raw['bandsintown_rsvps']:,}"))

    # Cap at 8 signals
    signals = signals[:8]

    items = ""
    for level, label, value in signals:
        lvl = level.lower() if isinstance(level, str) else level
        items += (
            f'<li class="signal" role="listitem">'
            f'{signal_dot(lvl)}'
            f'<span>{label}: <strong>{value}</strong></span></li>'
        )
    return f'<ul class="card-signals" aria-label="Demand signals" role="list">{items}</ul>'


def build_insight(ev):
    """Generate a one-line insight string from available signal data."""
    raw   = ev["raw_signals"]
    parts = []

    if raw.get("seatgeek_floor"):
        parts.append(f"Secondary floor ${raw['seatgeek_floor']:.0f}")
    if raw.get("seatgeek_deal_score"):
        parts.append(f"SeatGeek Deal Score {raw['seatgeek_deal_score']}/100")
    if raw.get("google_trends_atl"):
        parts.append(f"ATL Trends index {raw['google_trends_atl']}")
    if raw.get("bandsintown_rsvps"):
        parts.append(f"Bands in Town: {raw['bandsintown_rsvps']:,} ATL intents")
    if raw.get("wikipedia_7d_trend_pct") is not None:
        trend = raw["wikipedia_7d_trend_pct"]
        direction = "+" if trend >= 0 else ""
        parts.append(f"Wikipedia 7-day trend: {direction}{trend:.0f}%")

    return " &middot; ".join(parts) if parts else f"Score {ev['score']} — updated {datetime.date.today().strftime('%b %d, %Y')}"


# ── Risk flag (bottom panel) ──────────────────────────────────────────────
def build_risk(ev):
    raw = ev["raw_signals"]
    flags = []
    if raw.get("seatgeek_listing_count", 0) and ev.get("_venue_cap"):
        ratio = raw["seatgeek_listing_count"] / ev["_venue_cap"]
        if ratio > 0.4:
            flags.append(f"High listing volume ({raw['seatgeek_listing_count']:,} available)")
    if raw.get("google_trends_atl", 50) < 20:
        flags.append(f"ATL Trends: {raw['google_trends_atl']}")
    if raw.get("bandsintown_rsvps", 9999) < 500:
        flags.append(f"Bands in Town: {raw.get('bandsintown_rsvps', 'n/a')}")
    return " &middot; ".join(flags[:3]) if flags else ""


# ── Card HTML builder ─────────────────────────────────────────────────────
def build_card(ev, rank, is_bottom=False):
    accent  = "#2a58a0" if is_bottom else "#5a50d4"
    bar_bg  = "#c0d0ed" if is_bottom else "#d8d6f8"
    bc      = " bottom" if is_bottom else ""
    score   = ev["score"]
    meta    = ev
    date_display = fmt_date(meta.get("date", ""))
    date_iso     = meta.get("date", "")
    rank_label   = f"Ranked {ordinal(rank)}" + (" least popular" if is_bottom else "") + ", updated tonight"
    signals_html = build_signals_html(ev)
    insight      = build_insight(ev)
    risk_html    = ""
    if is_bottom:
        risk_text = build_risk(ev)
        if risk_text:
            risk_html = f'\n      <p class="card-risk">{risk_text}</p>'

    safe_id = re.sub(r"[^a-z0-9]", "-", ev["id"].lower())
    card_id = f"event-{'b' if is_bottom else ''}{rank}-{safe_id}"

    return f"""\
  <article class="event-card{bc}" aria-labelledby="{card_id}-title" itemscope itemtype="https://schema.org/MusicEvent">
    <meta itemprop="startDate" content="{date_iso}">
    <div class="card-rank-wrap" aria-label="{rank_label}">
      <span class="rank-num" aria-hidden="true">{rank}</span>
      <span class="rank-delta delta-flat" aria-hidden="true">&#8212;</span>
    </div>
    <div class="card-body">
      <h3 class="card-title" id="{card_id}-title" itemprop="name">{meta['name']}</h3>
      <div class="card-meta">
        <span class="card-meta-text"><time datetime="{date_iso}">{date_display}</time> &middot; <span itemprop="location" itemscope itemtype="https://schema.org/MusicVenue"><span itemprop="name">{meta['venue']}</span></span></span>
        <span class="genre-pill" style="{genre_style(meta['genre'])}" itemprop="genre">{meta['genre']}</span>
      </div>
      {signals_html}
      <p class="card-insight" itemprop="description">{insight}</p>{risk_html}
    </div>
    <div class="card-score" aria-label="Popularity score: {score} out of 100">
      <span class="score-label" aria-hidden="true">Score</span>
      <span class="score-value" style="color:{accent};" aria-hidden="true">{score}</span>
      <div class="score-bar-track" style="background:{bar_bg};" role="progressbar" aria-valuenow="{score}" aria-valuemin="0" aria-valuemax="100" aria-label="Score {score} out of 100">
        <div class="score-bar-fill" style="width:{score}%;background:{accent};"></div>
      </div>
    </div>
  </article>"""


# ── Main build ────────────────────────────────────────────────────────────
def build():
    print(f"[build] Building HTML — {datetime.datetime.now().isoformat()}")

    with open(SCORES_PATH) as f:
        data = json.load(f)

    events = data["events"]   # already sorted by score descending

    # Debug: print all scores before sorting
    print("[build] Event scores before sort:")
    for ev in events:
        print(f"  {ev.get('id','?'):40s}  score={ev.get('score')!r}")

    # Coerce any None scores to 0 before sorting to avoid comparison errors
    for ev in events:
        if ev.get("score") is None:
            ev["score"] = 0

    top_events    = events[:TOP_N]
    bottom_events = sorted(events, key=lambda e: e["score"])[:BOTTOM_N]

    # Build card blocks
    top_html    = "\n".join(build_card(ev, i+1, False) for i, ev in enumerate(top_events))
    bottom_html = "\n".join(build_card(ev, i+1, True)  for i, ev in enumerate(bottom_events))

    # Load template
    with open(TEMPLATE_PATH) as f:
        html = f.read()

    # Inject top cards
    html = re.sub(
        r"<!-- TOP_CARDS_START -->.*?<!-- TOP_CARDS_END -->",
        f"<!-- TOP_CARDS_START -->\n{top_html}\n<!-- TOP_CARDS_END -->",
        html,
        flags=re.DOTALL,
    )

    # Inject bottom cards
    html = re.sub(
        r"<!-- BOTTOM_CARDS_START -->.*?<!-- BOTTOM_CARDS_END -->",
        f"<!-- BOTTOM_CARDS_START -->\n{bottom_html}\n<!-- BOTTOM_CARDS_END -->",
        html,
        flags=re.DOTALL,
    )

    # Update last-updated date in footer
    today = datetime.date.today().isoformat()
    html = re.sub(
        r'<time datetime="[\d-]+">[^<]+</time>(?=\s*</p>)',
        f'<time datetime="{today}">Last updated {datetime.date.today().strftime("%B %-d, %Y")}</time>',
        html,
    )

    with open(OUTPUT_PATH, "w") as f:
        f.write(html)

    print(f"[build] Wrote {OUTPUT_PATH}  ({len(top_events)} top, {len(bottom_events)} bottom events)")
    return OUTPUT_PATH


if __name__ == "__main__":
    build()
