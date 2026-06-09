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

TEMPLATE_PATH = "templates/artist_card_module_wp_ready.html"
OUTPUT_PATH   = "output/artist_card_module_wp_ready.html"
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

    # MusicBrainz release context
    if raw.get("mb_has_recent_album") and raw.get("mb_latest_album_title"):
        days = raw.get("mb_days_since_last_album")
        if days is not None and days <= 90:
            parts.append(f"Touring on new album &ldquo;{raw['mb_latest_album_title']}&rdquo; ({days} days old)")
        else:
            parts.append(f"New album &ldquo;{raw['mb_latest_album_title']}&rdquo; within past year")
    elif raw.get("mb_total_albums", 0) >= 10:
        parts.append(f"Deep catalog — {raw['mb_total_albums']} studio albums")

    # Eventbrite demand signals
    if raw.get("eb_is_sold_out") and raw.get("eb_has_waitlist"):
        parts.append("Eventbrite: sold out &middot; waitlist active")
    elif raw.get("eb_is_sold_out"):
        parts.append("Eventbrite: sold out")
    elif raw.get("eb_sell_through_pct") is not None:
        pct = raw["eb_sell_through_pct"]
        if pct >= 80:
            parts.append(f"Eventbrite: {pct:.0f}% sold")
        elif pct >= 50:
            parts.append(f"Eventbrite: {pct:.0f}% sold")

    # Last.fm fan depth — surfaces for high-obsession acts
    ppl = raw.get("lastfm_plays_per_listener")
    listeners = raw.get("lastfm_listeners")
    if ppl is not None and ppl >= 200 and listeners:
        parts.append(f"Last.fm: {listeners/1_000_000:.1f}M listeners &middot; {ppl:.0f} plays/fan")
    elif listeners and listeners >= 1_000_000:
        parts.append(f"Last.fm: {listeners/1_000_000:.1f}M weekly listeners")

    # Setlist.fm ATL market strength
    atl_shows = raw.get("setlist_atl_shows_5y")
    if atl_shows is not None:
        if atl_shows == 0:
            parts.append("First ATL appearance in 5+ years")
        elif atl_shows >= 4:
            parts.append(f"Strong ATL market — {atl_shows} shows in past 5 years")
    if raw.get("setlist_sold_out_flag"):
        parts.append("Prior ATL show sold out")

    # Ticket demand signals
    if raw.get("seatgeek_floor"):
        parts.append(f"Secondary floor ${raw['seatgeek_floor']:.0f}")
    if raw.get("seatgeek_deal_score"):
        parts.append(f"SeatGeek Deal Score {raw['seatgeek_deal_score']}/100")

    # Local intent
    if raw.get("google_trends_atl"):
        parts.append(f"ATL Trends index {raw['google_trends_atl']}")
    if raw.get("bandsintown_rsvps"):
        parts.append(f"Bands in Town: {raw['bandsintown_rsvps']:,} ATL intents")

    # Wikipedia trend
    if raw.get("wikipedia_7d_trend_pct") is not None:
        trend = raw["wikipedia_7d_trend_pct"]
        direction = "+" if trend >= 0 else ""
        parts.append(f"Wikipedia 7-day trend: {direction}{trend:.0f}%")

    return " &middot; ".join(parts[:5]) if parts else f"Score {ev['score']} — updated {datetime.date.today().strftime('%b %d, %Y')}"


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

    # Guarantee all scores are ints before any sorting
    for ev in events:
        ev["score"] = int(ev.get("score") or 0)

    top_events    = events[:TOP_N]
    bottom_events = sorted(events, key=lambda e: int(e["score"]))[:BOTTOM_N]

    # Build card blocks
    top_html_parts = []
    for i, ev in enumerate(top_events):
        try:
            top_html_parts.append(build_card(ev, i+1, False))
        except Exception as e:
            print(f"  [WARN] top card {i+1} failed ({ev.get('id','?')}): {e}")
            top_html_parts.append(f"  <!-- card {i+1} failed: {e} -->")

    bottom_html_parts = []
    for i, ev in enumerate(bottom_events):
        try:
            bottom_html_parts.append(build_card(ev, i+1, True))
        except Exception as e:
            print(f"  [WARN] bottom card {i+1} failed ({ev.get('id','?')}): {e}")
            bottom_html_parts.append(f"  <!-- card {i+1} failed: {e} -->")

    top_html    = "\n".join(top_html_parts)
    bottom_html = "\n".join(bottom_html_parts)

    # Load template
    print(f"[build] Loading template from {TEMPLATE_PATH}")
    with open(TEMPLATE_PATH) as f:
        html = f.read()
    print(f"[build] Template loaded — {len(html):,} bytes")

    TOP_START    = "<!-- TOP_CARDS_START -->"
    TOP_END      = "<!-- TOP_CARDS_END -->"
    BOT_START    = "<!-- BOTTOM_CARDS_START -->"
    BOT_END      = "<!-- BOTTOM_CARDS_END -->"

    def inject_sentinel(content, start_marker, end_marker, new_cards):
        """
        Replace everything between start_marker and end_marker with
        new_cards using plain string operations — no regex, no DOTALL,
        no risk of matching JS code inside the <script> block.
        """
        s = content.find(start_marker)
        e = content.find(end_marker)
        if s == -1 or e == -1 or e <= s:
            print(f"  [WARN] Sentinel not found: {start_marker!r}")
            return content
        # Replace from end of start_marker to start of end_marker
        before = content[:s + len(start_marker)]
        after  = content[e:]
        return before + "\n" + new_cards + "\n" + after

    print(f"[build] TOP_CARDS_START present: {TOP_START in html}")
    print(f"[build] BOTTOM_CARDS_START present: {BOT_START in html}")

    html = inject_sentinel(html, TOP_START, TOP_END, top_html)
    print(f"[build] Injected {len(top_events)} top cards")

    html = inject_sentinel(html, BOT_START, BOT_END, bottom_html)
    print(f"[build] Injected {len(bottom_events)} bottom cards")

    # Update last-updated date in footer — plain string, no DOTALL
    print("[build] Updating footer date")
    today     = datetime.date.today()
    today_iso = today.isoformat()
    today_str = today.strftime("%B %-d, %Y")
    # Find the footer time element and replace it precisely
    time_marker = '<time datetime="'
    footer_pos  = html.rfind(time_marker)   # last occurrence = footer
    if footer_pos != -1:
        time_end = html.find("</time>", footer_pos) + len("</time>")
        html = (
            html[:footer_pos]
            + f'<time datetime="{today_iso}">Last updated {today_str}</time>'
            + html[time_end:]
        )

    print(f"[build] Writing output to {OUTPUT_PATH}")
    with open(OUTPUT_PATH, "w") as f:
        f.write(html)

    # Verify card counts in output
    import re as _re
    top_check = len(_re.findall(r'<article class="event-card"', html))
    bot_check = len(_re.findall(r'<article class="event-card bottom"', html))
    print(f"[build] Output verification — top cards: {top_check}  bottom cards: {bot_check}")
    print(f"[build] Wrote {OUTPUT_PATH}  ({len(top_events)} top, {len(bottom_events)} bottom events)")
    return OUTPUT_PATH


if __name__ == "__main__":
    build()
