"""
build_html.py
Atlanta Music Magazine — Dashboard HTML Builder
Reads data/scored_events.json, generates fresh card HTML for each event,
and writes the final dashboard to output/artist_card_module_wp_ready.html.

Strategy:
  1. Load scored_events.json (produced by score.py)
  2. Inject top-20 card HTML between <!-- TOP_CARDS_START/END --> sentinels
  3. Inject bottom-20 card HTML between <!-- BOTTOM_CARDS_START/END --> sentinels
  4. Regenerate the GENRE_POOL_TOP JS block from scored data so the genre
     filter pills always stay in sync with the main panel scores
  5. Update footer date
  6. Write output/artist_card_module_wp_ready.html
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

# ── Venue capacity lookup (mirrors score.py) ──────────────────────────────
VENUE_CAPS = {
    "State Farm Arena":                                  21000,
    "Mercedes-Benz Stadium":                             71000,
    "Ameris Bank Amphitheatre":                          12000,
    "Synovus Bank Amphitheater at Chastain Park":         6900,
    "Lakewood Amphitheatre":                             19000,
    "Coca-Cola Roxy":                                     3600,
    "Truist Park":                                       41084,
    "The Eastern":                                         500,
    "Vinyl at Center Stage":                               200,
    "Piedmont Park":                                     40000,   # Shaky Knees festival grounds
}


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
    sg_deal = raw.get("seatgeek_deal_score")
    if sg_deal is not None:
        sg_deal = int(sg_deal)
        lvl = "high" if sg_deal >= 65 else ("medium" if sg_deal >= 35 else "low")
        signals.append((lvl, "SeatGeek Deal Score", f"{sg_deal}/100"))

    sg_floor = raw.get("seatgeek_floor")
    if sg_floor is not None:
        sg_floor = float(sg_floor)
        lvl = "high" if sg_floor >= 150 else ("medium" if sg_floor >= 60 else "low")
        signals.append((lvl, "Secondary floor", f"${sg_floor:.0f}"))

    gtrends = raw.get("google_trends_atl")
    if gtrends is not None:
        gtrends = int(gtrends)
        lvl = "high" if gtrends >= 65 else ("medium" if gtrends >= 35 else "low")
        signals.append((lvl, "ATL Google Trends index", str(gtrends)))

    bit = raw.get("bandsintown_rsvps")
    if bit is not None:
        bit = int(bit)
        lvl = "high" if bit >= 5000 else ("medium" if bit >= 1000 else "low")
        signals.append((lvl, "Bands in Town intent", f"{bit:,}"))

    yt_vel = raw.get("yt_view_velocity_7d")
    if yt_vel is not None:
        yt_vel = int(yt_vel)
        lvl = "high" if yt_vel >= 2_000_000 else ("medium" if yt_vel >= 500_000 else "low")
        signals.append((lvl, "YouTube 7-day views",
                         f"{yt_vel/1_000_000:.1f}M" if yt_vel >= 1_000_000
                         else f"{yt_vel:,}"))

    yt_subs = raw.get("yt_subscriber_count")
    if yt_subs is not None and int(yt_subs) > 0:
        yt_subs = int(yt_subs)
        lvl = "high" if yt_subs >= 10_000_000 else ("medium" if yt_subs >= 1_000_000 else "low")
        signals.append((lvl, "YouTube subscribers",
                         f"{yt_subs/1_000_000:.1f}M" if yt_subs >= 1_000_000
                         else f"{yt_subs:,}"))

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

    # YouTube velocity — highest-impact forward signal when available
    yt_vel = raw.get("yt_view_velocity_7d")
    if yt_vel is not None and int(yt_vel) > 0:
        yt_vel = int(yt_vel)
        vel_str = (f"{yt_vel/1_000_000:.1f}M views/week"
                   if yt_vel >= 1_000_000 else f"{yt_vel:,} views/week")
        parts.append(f"YouTube: {vel_str}")

    # MusicBrainz release context
    if raw.get("mb_has_recent_album") and raw.get("mb_latest_album_title"):
        days = raw.get("mb_days_since_last_album")
        if days is not None and int(days) <= 90:
            parts.append(f"Touring on new album &ldquo;{raw['mb_latest_album_title']}&rdquo; ({days} days old)")
        else:
            parts.append(f"New album &ldquo;{raw['mb_latest_album_title']}&rdquo; within past year")
    else:
        total_albums = raw.get("mb_total_albums")
        if total_albums is not None and int(total_albums) >= 10:
            parts.append(f"Deep catalog — {total_albums} studio albums")

    # Eventbrite demand signals
    if raw.get("eb_is_sold_out") and raw.get("eb_has_waitlist"):
        parts.append("Eventbrite: sold out &middot; waitlist active")
    elif raw.get("eb_is_sold_out"):
        parts.append("Eventbrite: sold out")
    else:
        pct = raw.get("eb_sell_through_pct")
        if pct is not None:
            pct = float(pct)
            if pct >= 50:
                parts.append(f"Eventbrite: {pct:.0f}% sold")

    # Last.fm fan depth
    ppl       = raw.get("lastfm_plays_per_listener")
    listeners = raw.get("lastfm_listeners")
    if ppl is not None and listeners is not None:
        ppl       = float(ppl)
        listeners = int(listeners)
        if ppl >= 200 and listeners > 0:
            parts.append(f"Last.fm: {listeners/1_000_000:.1f}M listeners &middot; {ppl:.0f} plays/fan")
        elif listeners >= 1_000_000:
            parts.append(f"Last.fm: {listeners/1_000_000:.1f}M weekly listeners")
    elif listeners is not None and int(listeners) >= 1_000_000:
        parts.append(f"Last.fm: {int(listeners)/1_000_000:.1f}M weekly listeners")

    # Setlist.fm ATL market strength
    atl_shows = raw.get("setlist_atl_shows_5y")
    if atl_shows is not None:
        atl_shows = int(atl_shows)
        if atl_shows == 0:
            parts.append("First ATL appearance in 5+ years")
        elif atl_shows >= 4:
            parts.append(f"Strong ATL market — {atl_shows} shows in past 5 years")
    if raw.get("setlist_sold_out_flag"):
        parts.append("Prior ATL show sold out")

    # Ticket demand signals
    sg_floor = raw.get("seatgeek_floor")
    if sg_floor is not None:
        parts.append(f"Secondary floor ${float(sg_floor):.0f}")
    sg_deal = raw.get("seatgeek_deal_score")
    if sg_deal is not None:
        parts.append(f"SeatGeek Deal Score {sg_deal}/100")

    # Local intent
    gtrends = raw.get("google_trends_atl")
    if gtrends is not None:
        parts.append(f"ATL Trends index {gtrends}")
    bit = raw.get("bandsintown_rsvps")
    if bit is not None:
        parts.append(f"Bands in Town: {int(bit):,} ATL intents")

    # Wikipedia trend
    trend = raw.get("wikipedia_7d_trend_pct")
    if trend is not None:
        trend     = float(trend)
        direction = "+" if trend >= 0 else ""
        parts.append(f"Wikipedia 7-day trend: {direction}{trend:.0f}%")

    return " &middot; ".join(parts[:5]) if parts else f"Score {ev['score']} — updated {datetime.date.today().strftime('%b %d, %Y')}"


# ── Risk flag (bottom panel) ──────────────────────────────────────────────
def build_risk(ev):
    raw = ev["raw_signals"]
    flags = []

    # Guard every comparison against None explicitly
    listing_count = raw.get("seatgeek_listing_count") or 0
    venue_cap     = ev.get("_venue_cap") or 0
    if listing_count and venue_cap:
        ratio = listing_count / venue_cap
        if ratio > 0.4:
            flags.append(f"High listing volume ({listing_count:,} available)")

    trends_atl = raw.get("google_trends_atl")
    if trends_atl is not None and int(trends_atl) < 20:
        flags.append(f"ATL Trends: {trends_atl}")

    bit_rsvps = raw.get("bandsintown_rsvps")
    if bit_rsvps is not None and int(bit_rsvps) < 500:
        flags.append(f"Bands in Town: {bit_rsvps}")

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


# ── Window constants ──────────────────────────────────────────────────────
WINDOW_START = datetime.date(2026, 6, 8)
WINDOW_END   = datetime.date(2026, 9, 20)   # extended to include Shaky Knees Sep 18-20

GENRE_POOL_START_MARKER = "  var GENRE_POOL_TOP = ["
GENRE_POOL_END_MARKER   = "  var GENRE_POOL_BOTTOM = GENRE_POOL_TOP.slice();"

# JS colour lookup for genre dots in the pool (mirrors GENRE_STYLES)
GENRE_JS_COLORS = {
    "Pop":           {"bg": "#eeedfb", "fg": "#4038b0"},
    "Latin Pop":     {"bg": "#fef6e0", "fg": "#6a4400"},
    "Country":       {"bg": "#fef6e0", "fg": "#6a4400"},
    "Hip-Hop":       {"bg": "#e8f5ee", "fg": "#134a28"},
    "R&B":           {"bg": "#e8f5ee", "fg": "#134a28"},
    "Rock":          {"bg": "#fdecea", "fg": "#721a0a"},
    "Alt / Rock":    {"bg": "#fdecea", "fg": "#721a0a"},
    "Alt / R&B":     {"bg": "#eef0ff", "fg": "#283ab0"},
    "Reggae":        {"bg": "#eef0ff", "fg": "#283ab0"},
    "Indie / Psych": {"bg": "#fde8f8", "fg": "#650c5c"},
    "Indie / Alt":   {"bg": "#fde8f8", "fg": "#650c5c"},
    "Classic Rock":  {"bg": "#fef6e0", "fg": "#6a4400"},
    "Metalcore":     {"bg": "#f2f2f4", "fg": "#36363e"},
    "Hyperpop":      {"bg": "#eef0ff", "fg": "#283ab0"},
    "Multi-Genre":   {"bg": "#eef0ff", "fg": "#283ab0"},
    "Pop / Rock":    {"bg": "#eeedfb", "fg": "#4038b0"},
    "Pop / Soul":    {"bg": "#eeedfb", "fg": "#4038b0"},
}


def _js_escape(s):
    """Encode a Python string for safe embedding in a JS double-quoted string."""
    result = []
    for ch in str(s):
        if ch == "\\":
            result.append("\\\\")
        elif ch == '"':
            result.append('\\"')
        elif ch == "'":
            result.append("\\'")
        elif ch == "\n":
            result.append("\\n")
        elif ord(ch) > 127:
            result.append(f"\\u{ord(ch):04x}")
        else:
            result.append(ch)
    return "".join(result)


def _signal_level(score_int):
    if score_int >= 65: return "high"
    if score_int >= 35: return "medium"
    return "low"


def build_genre_pool_js(events):
    """
    Build the GENRE_POOL_TOP JS variable from scored_events.json data.
    Called every build so the genre filter pills always reflect the
    current nightly scores — never stale hardcoded values.

    Filtering rules (must match the dashboard window):
      - Event date must be within WINDOW_START to WINDOW_END
      - Each event appears once per genre (no duplicates across panels)

    Signal rows per card (8 total):
      4 pillar summary rows — always present
      4 structural / data rows — keyless signals that always fire
    """
    pool_entries = []
    seen_ids = set()

    for ev in events:
        eid      = ev.get("id", "")
        date_str = ev.get("date", "")
        genre    = ev.get("genre", "")
        score    = int(ev.get("score") or 0)
        seed     = int(ev.get("seed_score") or score)

        # Skip if outside window
        try:
            show_date = datetime.date.fromisoformat(date_str)
            if not (WINDOW_START <= show_date <= WINDOW_END):
                continue
        except (ValueError, TypeError):
            continue

        # Skip duplicates (Kali Uchis appears twice with different IDs)
        dedup_key = (ev.get("name", ""), genre)
        if dedup_key in seen_ids:
            continue
        seen_ids.add(dedup_key)

        # Pillar scores
        ps      = ev.get("pillar_scores", {})
        p_sent  = int(ps.get("sentiment", 50) or 50)
        p_hist  = int(ps.get("historical_sales", 50) or 50)
        p_tick  = int(ps.get("ticket_demand", 50) or 50)
        p_local = int(ps.get("local_intent", 50) or 50)

        # Raw signals for detail rows
        raw    = ev.get("raw_signals", {})
        wiki   = raw.get("wikipedia_7d_trend_pct")
        gtrend = raw.get("google_trends_atl")
        bit    = raw.get("bandsintown_rsvps")
        sg_fl  = raw.get("seatgeek_floor")
        mb_alb = raw.get("mb_latest_album_title")
        mb_rec = raw.get("mb_has_recent_album")
        lastfm = raw.get("lastfm_listeners")

        # Build 8 signal rows
        signals = [
            [_signal_level(p_sent),  "Sentiment",      _pillar_label(p_sent)],
            [_signal_level(p_hist),  "Sales history",  _pillar_label(p_hist)],
            [_signal_level(p_tick),  "Ticket demand",  _pillar_label(p_tick)],
            [_signal_level(p_local), "Local intent",   _pillar_label(p_local)],
        ]

        # Best available detail signal (first truthy one wins)
        if wiki is not None:
            direction = "+" if float(wiki) >= 0 else ""
            signals.append(["medium", "Wikipedia 7-day",
                             f"{direction}{float(wiki):.0f}%"])
        elif mb_rec and mb_alb:
            signals.append(["high", "New album", _js_escape(mb_alb)])
        elif sg_fl is not None:
            signals.append(["medium", "Secondary floor",
                             f"${float(sg_fl):.0f}"])
        elif gtrend is not None:
            signals.append(["medium", "ATL Google Trends",
                             f"{int(gtrend)}/100"])
        else:
            # Keyless fallback — venue capacity
            cap = VENUE_CAPS.get(ev.get("venue", ""), 0)
            signals.append(["medium", "Venue capacity",
                             f"{cap:,}" if cap else "n/a"])

        if bit is not None:
            lvl = "high" if int(bit) >= 5000 else (
                  "medium" if int(bit) >= 1000 else "low")
            signals.append([lvl, "Bands in Town", f"{int(bit):,} ATL"])
        elif lastfm is not None and int(lastfm) > 0:
            lm = int(lastfm)
            signals.append(["medium", "Last.fm listeners",
                             f"{lm/1_000_000:.1f}M" if lm >= 1_000_000
                             else f"{lm:,}"])
        elif gtrend is not None and len([s for s in signals if s[1] != "ATL Google Trends"]) >= 5:
            pass
        else:
            signals.append(["medium", "Score confidence",
                             f"Seed {seed}"])

        # Cap at 8
        signals = signals[:8]

        # Insight line — pick best available data
        insight_parts = []
        if mb_rec and mb_alb:
            insight_parts.append(f"New album \u201c{mb_alb}\u201d")
        if sg_fl is not None:
            insight_parts.append(f"Secondary floor ${float(sg_fl):.0f}")
        if wiki is not None:
            direction = "+" if float(wiki) >= 0 else ""
            insight_parts.append(f"Wikipedia {direction}{float(wiki):.0f}%")
        if gtrend is not None:
            insight_parts.append(f"ATL Trends {int(gtrend)}/100")
        if not insight_parts:
            # Keyless fallback
            try:
                days_out = (show_date - datetime.date.today()).days
                if days_out >= 0:
                    insight_parts.append(f"{days_out} days to show")
            except Exception:
                pass
            insight_parts.append(f"Genre ATL index {int(_genre_prior(genre)*100)}/100")

        insight = " \u00b7 ".join(insight_parts[:4])

        # Format date for display
        try:
            y, m, d = date_str.split("-")
            MONTHS = ["Jan","Feb","Mar","Apr","May","Jun",
                      "Jul","Aug","Sep","Oct","Nov","Dec"]
            date_display = f"{MONTHS[int(m)-1]} {int(d)}"
        except Exception:
            date_display = date_str

        pool_entries.append({
            "name":     ev.get("name", ""),
            "date":     date_display,
            "venue":    ev.get("venue", ""),
            "genre":    genre,
            "score":    score,
            "signals":  signals,
            "insight":  insight,
        })

    # Build JS string
    entry_strs = []
    for e in pool_entries:
        sigs_js = ",".join(
            f'["{_js_escape(s[0])}","{_js_escape(s[1])}","{_js_escape(str(s[2]))}"]'
            for s in e["signals"]
        )
        entry_strs.append(
            f'    {{name:"{_js_escape(e["name"])}",date:"{_js_escape(e["date"])}",'
            f'venue:"{_js_escape(e["venue"])}",genre:"{_js_escape(e["genre"])}",'
            f'score:{e["score"]},signals:[{sigs_js}],'
            f'insight:"{_js_escape(e["insight"])}"}}'
        )

    pool_js = (
        "  var GENRE_POOL_TOP = [\n"
        + ",\n".join(entry_strs)
        + "\n  ];\n\n"
        "  /* Bottom pool = same events; "
        "renderGenreView sorts ascending for worst-to-best */\n"
        "  var GENRE_POOL_BOTTOM = GENRE_POOL_TOP.slice();"
    )

    print(f"[build] Genre pool: {len(pool_entries)} events, "
          f"score range {min(e['score'] for e in pool_entries)}"
          f"–{max(e['score'] for e in pool_entries)}")
    return pool_js


def _pillar_label(score_int):
    if score_int >= 65: return "High"
    if score_int >= 35: return "Medium"
    return "Low"


def _genre_prior(genre):
    """Mirror of score.py's GENRE_DEMAND_PRIOR for insight fallback."""
    priors = {
        "Latin Pop": 0.76, "Pop": 0.70, "Hip-Hop": 0.68,
        "R&B": 0.63, "Multi-Genre": 0.65, "Country": 0.62,
        "Alt / R&B": 0.58, "Rock": 0.56, "Pop / Rock": 0.54,
        "Indie / Psych": 0.52, "Reggae": 0.48, "Indie / Alt": 0.44,
        "Classic Rock": 0.40, "Metalcore": 0.36, "Hyperpop": 0.22,
    }
    return priors.get(genre, 0.50)


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

    # ── Step 3: Regenerate genre pool JS ──────────────────────────────────
    # Rebuild GENRE_POOL_TOP from current scored data so genre filter pills
    # always reflect tonight's scores, not stale hardcoded values.
    try:
        new_pool_js = build_genre_pool_js(events)
        ps = html.find(GENRE_POOL_START_MARKER)
        pe = html.find(GENRE_POOL_END_MARKER)
        if ps != -1 and pe != -1 and pe > ps:
            html = html[:ps] + new_pool_js + html[pe + len(GENRE_POOL_END_MARKER):]
            print("[build] Genre pool JS updated")
        else:
            print("[build] WARN: Genre pool markers not found — pool not updated")
    except Exception as e:
        print(f"[build] WARN: Genre pool update failed: {e} — keeping existing pool")

    # ── Step 4: Inject card sentinels ─────────────────────────────────────
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
