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
SCORES_PATH      = "data/scored_events.json"
RANK_CACHE_PATH  = "data/rank_history.json"


def load_rank_cache():
    """
    Load yesterday's rank positions and first-seen dates from disk.
    Schema: {event_id: {"rank": int, "panel": "top"|"bottom",
                         "first_seen": "YYYY-MM-DD"}}
    Persisted between runs via GitHub Actions cache@v4.
    """
    try:
        with open(RANK_CACHE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_rank_cache(cache):
    """Write updated rank cache to disk for tomorrow's delta calculation."""
    with open(RANK_CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)


def compute_delta(event_id, new_rank, panel, cache):
    """
    Compute rank delta vs yesterday and detect new entries.
    Returns (delta_class, delta_label, aria_label).
      delta_class : "up" | "down" | "flat" | "new"
      delta_label : "↑3" | "↓1" | "—" | "NEW"
      aria_label  : screen-reader description
    """
    prior = cache.get(event_id)

    if prior is None or prior.get("panel") != panel:
        return "new", "NEW", "New entry"

    prior_rank = prior.get("rank")
    if prior_rank is None:
        return "flat", "\u2014", "Unchanged"

    delta = prior_rank - new_rank   # positive = moved up
    if delta > 0:
        return "up",   f"\u2191{delta}", f"Up {delta} spot{'s' if delta != 1 else ''}"
    if delta < 0:
        return "down", f"\u2193{abs(delta)}", f"Down {abs(delta)} spot{'s' if abs(delta) != 1 else ''}"
    return "flat", "\u2014", "Unchanged"


def update_rank_cache(event_id, new_rank, panel, cache, today_str):
    """Update cache entry with tonight's rank. Always call after compute_delta."""
    prior = cache.get(event_id, {})
    cache[event_id] = {
        "rank":       new_rank,
        "panel":      panel,
        "first_seen": prior.get("first_seen", today_str),
    }

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
    "Lakewood Amphitheatre":                             18920,   # 7K seated + 12K lawn
    "Coca-Cola Roxy":                                     3600,
    "The Eastern":                                         500,
    "Vinyl at Center Stage":                               200,
    "Truist Park":                                       41084,   # Noah Kahan sold-out stadium show
    "Bobby Dodd Stadium":                              55000,
    "Gas South Arena":                                 13100,
    "Fabulous Fox Theatre":                            4665,
    "Cobb Energy Performing Arts Centre":              2750,
    "The Tabernacle":                                  2600,
    "Variety Playhouse":                               1000,
    "Terminal West":                                   900,
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

    wd_grammys = raw.get("wd_grammy_wins")
    if wd_grammys is not None and int(wd_grammys) > 0:
        n = int(wd_grammys)
        signals.append(("high", "Grammy wins", str(n)))

    wd_langs = raw.get("wd_wikipedia_languages")
    if wd_langs is not None and int(wd_langs) >= 10:
        signals.append(("high" if int(wd_langs) >= 31 else "medium",
                         "Wikipedia editions", str(int(wd_langs))))

    deezer = raw.get("deezer_fans")
    if deezer is not None and int(deezer) >= 100_000:
        d = int(deezer)
        lvl = "high" if d >= 10_000_000 else ("medium" if d >= 1_000_000 else "low")
        signals.append((lvl, "Deezer fans",
                        f"{d/1_000_000:.1f}M" if d >= 1_000_000 else f"{d:,}"))

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
    """
    Build the insight line shown on each card.
    Signals are selected in priority order — most editorially compelling first.
    Capped at 5 fragments joined by middot separators.

    Priority order:
      1. Album cycle context (touring on new album / latest album title)
      2. Grammy wins (high trust signal for casual buyers)
      3. Grammy nominations (for non-winners with nomination history)
      4. Waitlist / sold-out status (clearest demand signal)
      5. Career longevity (10+ years — nostalgia premium)
      6. Tour scale (setlist tour show count)
      7. YouTube velocity (current cultural acceleration)
      8. Eventbrite sell-through %
      9. Last.fm depth (plays/listener ratio)
     10. ATL market history
     11. Bands in Town RSVPs
     12. Spotify top track popularity
     13. Secondary market floor price
     14. Wikipedia trend
    """
    raw   = ev["raw_signals"]
    parts = []

    # ── 1. Album cycle context ─────────────────────────────────────────
    mb_title = raw.get("mb_latest_album_title")
    mb_days  = raw.get("mb_days_since_last_album")
    mb_rec   = raw.get("mb_has_recent_album")
    mb_total = raw.get("mb_total_albums")

    if mb_rec and mb_title:
        if mb_days is not None and int(mb_days) <= 120:
            parts.append(f"Touring on new album \u201c{mb_title}\u201d")
        else:
            parts.append(f"New album \u201c{mb_title}\u201d in past year")
    elif mb_title and mb_days is not None and int(mb_days) <= 730:
        parts.append(f"Latest: \u201c{mb_title}\u201d")
    elif mb_total is not None and int(mb_total) >= 10:
        parts.append(f"{int(mb_total)}-album catalog")

    # ── 2. Grammy wins ─────────────────────────────────────────────────
    wd_wins = raw.get("wd_grammy_wins")
    if wd_wins is not None and int(wd_wins) > 0:
        n = int(wd_wins)
        parts.append(f"{n}-time Grammy winner" if n > 1 else "Grammy winner")

    # ── 3. Grammy nominations (non-winners only) ───────────────────────
    wd_noms = raw.get("wd_grammy_nominations")
    if (wd_wins is None or int(wd_wins or 0) == 0) and wd_noms is not None and int(wd_noms) >= 3:
        parts.append(f"{int(wd_noms)}\u00d7 Grammy nominated")

    # ── 4. Waitlist / sold-out ─────────────────────────────────────────
    if raw.get("eb_is_sold_out") and raw.get("eb_has_waitlist"):
        parts.append("Sold out \u00b7 waitlist active")
    elif raw.get("eb_is_sold_out"):
        parts.append("Sold out")
    elif raw.get("eb_has_waitlist"):
        parts.append("Waitlist active")

    # ── 5. Career longevity (10+ years) ───────────────────────────────
    wd_years = raw.get("wd_active_years")
    if wd_years is not None:
        y = int(wd_years)
        if y >= 10:
            parts.append(f"Touring for {y} years")

    # ── 6. Tour scale ──────────────────────────────────────────────────
    tour_shows = raw.get("setlist_tour_shows_total")
    if tour_shows is not None and int(tour_shows) >= 20:
        parts.append(f"{int(tour_shows)}-date world tour")

    # ── 7. YouTube velocity ────────────────────────────────────────────
    yt_vel = raw.get("yt_view_velocity_7d")
    if yt_vel is not None and int(yt_vel) >= 100_000:
        yt_vel = int(yt_vel)
        vel_str = (f"{yt_vel/1_000_000:.1f}M views/week"
                   if yt_vel >= 1_000_000 else f"{yt_vel/1_000:.0f}K views/week")
        parts.append(f"YouTube: {vel_str}")

    # ── 8. Eventbrite sell-through ─────────────────────────────────────
    pct = raw.get("eb_sell_through_pct")
    if pct is not None and not raw.get("eb_is_sold_out"):
        pct = float(pct)
        if pct >= 80:
            parts.append(f"Eventbrite: {pct:.0f}% sold")
        elif pct >= 50:
            parts.append(f"Eventbrite: {pct:.0f}% sold")

    # ── 9. Last.fm depth ───────────────────────────────────────────────
    ppl       = raw.get("lastfm_plays_per_listener")
    listeners = raw.get("lastfm_listeners")
    if ppl is not None and listeners is not None:
        ppl       = float(ppl)
        listeners = int(listeners)
        if ppl >= 200 and listeners >= 500_000:
            parts.append(f"Last.fm: {listeners/1_000_000:.1f}M listeners \u00b7 {ppl:.0f} plays/fan")
        elif listeners >= 1_000_000:
            parts.append(f"Last.fm: {listeners/1_000_000:.1f}M listeners")
    elif listeners is not None and int(listeners) >= 1_000_000:
        parts.append(f"Last.fm: {int(listeners)/1_000_000:.1f}M listeners")

    # ── 10. ATL market history ─────────────────────────────────────────
    atl_shows = raw.get("setlist_atl_shows_5y")
    genre     = (ev.get("genre") or "").lower()
    amm_date  = raw.get("amm_article_date", "") or ""

    # Genres where Setlist.fm coverage is unreliable — 0 ATL shows likely
    # reflects a data gap, not a genuine first appearance
    SETLIST_UNRELIABLE_GENRES = {
        "pop", "latin", "r&b", "hip-hop", "hip hop",
        "country", "electronic", "dance",
    }
    setlist_unreliable = any(g in genre for g in SETLIST_UNRELIABLE_GENRES)

    if atl_shows is not None:
        n = int(atl_shows)
        if n == 0:
            # Suppress "First ATL show" when:
            #   a) Genre is one where Setlist.fm undercounts (pop/latin/R&B etc.)
            #   b) An AMM article exists — it proves a recent Atlanta show occurred
            if not setlist_unreliable and not amm_date:
                parts.append("First ATL show in 5+ years")
        elif n >= 6:
            parts.append(f"{n} ATL shows in past 5 years")
    if raw.get("setlist_sold_out_flag"):
        parts.append("Prior ATL show sold out")

    # ── 11. Bands in Town RSVPs ────────────────────────────────────────
    bit = raw.get("bandsintown_rsvps")
    if bit is not None and int(bit) >= 500:
        parts.append(f"{int(bit):,} ATL fans tracking")

    # ── 12. Spotify top track popularity ──────────────────────────────
    sp_top = raw.get("spotify_top_track_popularity")
    if sp_top is not None and int(sp_top) >= 80:
        parts.append(f"Spotify top track: {sp_top}/100")

    # ── 13. Secondary market floor ────────────────────────────────────
    sg_floor = raw.get("seatgeek_floor")
    if sg_floor is not None and float(sg_floor) >= 50:
        parts.append(f"Secondary floor ${float(sg_floor):.0f}")

    # ── 14. Wikipedia trend ────────────────────────────────────────────
    trend = raw.get("wikipedia_7d_trend_pct")
    if trend is not None:
        trend = float(trend)
        if abs(trend) >= 15:   # only show meaningful movements
            direction = "+" if trend >= 0 else ""
            parts.append(f"Wikipedia {direction}{trend:.0f}% this week")

    # Return joined parts; empty string when no signals fire
    # (Score fallback removed — it surfaced debug data in production cards)
    return " \u00b7 ".join(parts[:5])


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


# ── Bottom panel display multiplier ──────────────────────────────────────
# Applied at display time only — underlying score in scored_events.json
# is unchanged. Scales bottom panel scores by 0.65 to push them into a
# visually distinct 20–33 range vs the top panel's 53–88 range.
BOTTOM_DISPLAY_MULTIPLIER = 0.65

# Curated bottom panel event IDs — fixed editorial set of "soft demand" events.
# These events are excluded from the top panel and appear only in the bottom panel.
BOTTOM_PANEL_IDS = {
    "slayyyter-2026", "isley-ojays-2026", "justine-skye-2026",
    "wynonna-melissa-2026", "guess-who-2026", "john-mellencamp-2026",
    "ne-yo-akon-2026", "styx-chicago-2026", "5sos-2026",
    "madison-beer-2026", "motionless-2026", "hayley-williams-2026",
    "muse-2026", "evanescence-2026", "motley-crue-2026",
    "ella-mai-2026", "train-bnl-2026", "hilary-duff-2026",
    "parker-mccollum-2026", "jack-johnson-2026",
}


# ── Card HTML builder ─────────────────────────────────────────────────────
def build_card(ev, rank, is_bottom=False, delta_class="flat", delta_label="\u2014", delta_aria="Unchanged"):
    accent  = "#2a58a0" if is_bottom else "#5a50d4"
    bar_bg  = "#c0d0ed" if is_bottom else "#d8d6f8"
    bc      = " bottom" if is_bottom else ""
    score   = ev["score"]

    # Display score: bottom panel events are scaled down visually to
    # create clear separation from the top panel range.
    display_score = (max(1, round(score * BOTTOM_DISPLAY_MULTIPLIER))
                     if is_bottom else score)

    meta         = ev
    date_display = fmt_date(meta.get("date", ""))
    date_iso     = meta.get("date", "")
    rank_label   = (f"Ranked {ordinal(rank)}" +
                    (" least popular" if is_bottom else "") +
                    f", updated tonight. {delta_aria}.")
    signals_html = build_signals_html(ev)
    insight      = build_insight(ev)
    risk_html    = ""
    if is_bottom:
        risk_text = build_risk(ev)
        if risk_text:
            risk_html = f'\n      <p class="card-risk">{risk_text}</p>'

    raw       = ev.get("raw_signals", {})
    amm_title = raw.get("amm_article_title", "") or ""
    amm_url   = raw.get("amm_article_url", "") or ""
    amm_date  = raw.get("amm_article_date", "") or ""

    # Derive display date from the article URL slug — more reliable than the
    # stored amm_article_date which may reflect a WordPress re-index date
    # rather than the original publish date (e.g. all showing "Feb 2025").
    # AMM slugs encode the real date: "...august-24-2022" → "Aug 2022"
    if amm_url:
        _slug_months = {
            "january":"01","february":"02","march":"03","april":"04",
            "may":"05","june":"06","july":"07","august":"08",
            "september":"09","october":"10","november":"11","december":"12",
        }
        _dm = re.search(
            r"(january|february|march|april|may|june|july|august"
            r"|september|october|november|december)-(\d{1,2})-(20\d{2})(?:-|/|$)",
            amm_url,
        )
        if _dm:
            try:
                _d = datetime.date(int(_dm.group(3)),
                                   int(_slug_months[_dm.group(1)]),
                                   int(_dm.group(2)))
                amm_date = _d.strftime("%b %Y")
            except (ValueError, KeyError):
                pass   # keep stored amm_date as fallback
    if amm_title and amm_url:
        amm_strip = (
            f'\n  <div class="amm-strip">'
            f'<div class="amm-icon"><i class="ti ti-camera" aria-hidden="true"></i></div>'
            f'<div class="amm-text">'
            f'<div class="amm-eyebrow">Prior Atlanta Music Magazine coverage</div>'
            f'<div class="amm-headline"><a href="{amm_url}" target="_blank" rel="noopener">{amm_title}</a></div>'
            f'</div>'
            f'<div class="amm-date">{amm_date}</div>'
            f'</div>'
        )
    else:
        amm_strip = ""

    safe_id = re.sub(r"[^a-z0-9]", "-", ev["id"].lower())
    card_id = f"event-{'b' if is_bottom else ''}{rank}-{safe_id}"

    return f"""\
  <article class="event-card{bc}" aria-labelledby="{card_id}-title" itemscope itemtype="https://schema.org/MusicEvent">
    <meta itemprop="startDate" content="{date_iso}">
    <div class="card-rank-wrap" aria-label="{rank_label}">
      <span class="rank-num" aria-hidden="true">{rank}</span>
      <span class="rank-delta delta-{delta_class}" aria-hidden="true">{delta_label}</span>
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
    <div class="card-score" aria-label="Popularity score: {display_score} out of 100">      <span class="score-label" aria-hidden="true">Score</span>
      <span class="score-value" style="color:{accent};" aria-hidden="true">{display_score}</span>
      <div class="score-bar-track" style="background:{bar_bg};" role="progressbar" aria-valuenow="{display_score}" aria-valuemin="0" aria-valuemax="100" aria-label="Score {display_score} out of 100">
        <div class="score-bar-fill" style="width:{display_score}%;background:{accent};"></div>
      </div>
    </div>{amm_strip}
  </article>"""


# ── Window constants ──────────────────────────────────────────────────────
WINDOW_START = datetime.date(2026, 6, 8)
WINDOW_END   = datetime.date(2026, 9, 21)   # extended to include Shaky Knees Sep 18-20 and Slayyyter Sep 21

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
    skipped_window = []
    skipped_dup    = []

    # Debug: log first few event dates to diagnose window filter issues
    if events:
        sample = [(ev.get("id","?"), ev.get("date","?")) for ev in events[:5]]
        print(f"[build] Genre pool received {len(events)} events. Sample dates: {sample}")
    else:
        print("[build] Genre pool received EMPTY events list")

    for ev in events:
        eid      = ev.get("id", "")
        date_str = ev.get("date", "")
        genre    = ev.get("genre", "")
        score    = int(ev.get("score") or 0)
        seed     = int(ev.get("seed_score") or score)

        # Apply bottom panel multiplier for genre pool display scores
        is_bot_panel  = eid in BOTTOM_PANEL_IDS
        display_score = max(1, round(score * BOTTOM_DISPLAY_MULTIPLIER)) if is_bot_panel else score

        # Skip if outside window
        try:
            show_date = datetime.date.fromisoformat(date_str)
            if not (WINDOW_START <= show_date <= WINDOW_END):
                skipped_window.append(f"{eid} ({date_str})")
                continue
        except (ValueError, TypeError):
            skipped_window.append(f"{eid} (bad date: {date_str!r})")
            continue

        # Skip duplicates (Kali Uchis appears twice with different IDs)
        dedup_key = (ev.get("name", ""), genre)
        if dedup_key in seen_ids:
            skipped_dup.append(eid)
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
            "name":          ev.get("name", ""),
            "date":          date_display,
            "venue":         ev.get("venue", ""),
            "genre":         genre,
            "score":         score,
            "display_score": display_score,
            "delta_class":   ev.get("_delta_class", "flat"),
            "delta_label":   ev.get("_delta_label", "\u2014"),
            "signals":       signals,
            "insight":       insight,
        })

    # Build JS string
    import json as _json
    entry_strs = []
    for e in pool_entries:
        obj = {
            "name":       e["name"],
            "date":       e["date"],
            "venue":      e["venue"],
            "genre":      e["genre"],
            "score":      e["display_score"],
            "deltaClass": e["delta_class"],
            "deltaLabel": e["delta_label"],
            "signals":    e["signals"],
            "insight":    e["insight"],
        }
        entry_strs.append("    " + _json.dumps(obj, ensure_ascii=False))

    pool_js = (
        "  var GENRE_POOL_TOP = [\n"
        + ",\n".join(entry_strs)
        + "\n  ];\n\n"
        "  /* Bottom pool = same events; "
        "renderGenreView sorts ascending for worst-to-best */\n"
        "  var GENRE_POOL_BOTTOM = GENRE_POOL_TOP.slice();"
    )

    if skipped_window:
        print(f"[build] Genre pool: {len(skipped_window)} events outside window {WINDOW_START}–{WINDOW_END}:")
        for s in skipped_window[:5]:
            print(f"  skipped: {s}")
    if skipped_dup:
        print(f"[build] Genre pool: {len(skipped_dup)} duplicates removed")

    if not pool_entries:
        print(f"[build] WARN: Genre pool is empty — no events matched window. "
              f"Input events: {len(events)}, window: {WINDOW_START}–{WINDOW_END}")
        # Return minimal valid JS so the dashboard doesn't break
        return (
            "  var GENRE_POOL_TOP = [];\n\n"
            "  /* Bottom pool = same events */\n"
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

    # Filter to only future in-window events for the main panels
    # Past events (date < today) are removed regardless of score
    today_date = datetime.date.today()
    def in_window(ev):
        try:
            d = datetime.date.fromisoformat(ev.get("date", ""))
            return d >= today_date and d <= WINDOW_END
        except (ValueError, TypeError):
            return False

    future_events = [ev for ev in events if in_window(ev)]
    past_count    = len(events) - len(future_events)
    if past_count:
        print(f"[build] Filtered {past_count} past/out-of-window events from main panels")

    # ── Top panel: highest-scoring future in-window events ───────────────
    # Top 20 by score descending, excluding events reserved for bottom panel
    top_candidates  = [ev for ev in future_events if ev.get("id") not in BOTTOM_PANEL_IDS]
    top_events      = top_candidates[:TOP_N]

    # ── Bottom panel: curated soft-demand events, sorted score ascending ──
    # Fixed set of events editorially designated as the "softest demand"
    # tier — not simply the lowest scorers from all events, which would
    # bleed top-panel events into the bottom ranking.
    bot_candidates  = [ev for ev in future_events if ev.get("id") in BOTTOM_PANEL_IDS]
    bottom_events   = sorted(bot_candidates, key=lambda e: int(e["score"]))[:BOTTOM_N]

    print(f"[build] Top panel: {len(top_events)} events  "
          f"(score range {top_events[-1]['score']}–{top_events[0]['score']})")
    print(f"[build] Bottom panel: {len(bottom_events)} events  "
          f"(score range {bottom_events[0]['score']}–{bottom_events[-1]['score']})"
          if bottom_events else "[build] Bottom panel: 0 events")

    # Load yesterday's rank cache for delta computation
    rank_cache = load_rank_cache()
    today_str  = datetime.date.today().isoformat()

    # Build card blocks
    top_html_parts = []
    for i, ev in enumerate(top_events):
        rank = i + 1
        dc, dl, da = compute_delta(ev["id"], rank, "top", rank_cache)
        update_rank_cache(ev["id"], rank, "top", rank_cache, today_str)
        ev["_delta_class"] = dc
        ev["_delta_label"] = dl
        try:
            top_html_parts.append(build_card(ev, rank, False, dc, dl, da))
        except Exception as e:
            print(f"  [WARN] top card {i+1} failed ({ev.get('id','?')}): {e}")
            top_html_parts.append(f"  <!-- card {i+1} failed: {e} -->")

    bottom_html_parts = []
    for i, ev in enumerate(bottom_events):
        rank = i + 1
        dc, dl, da = compute_delta(ev["id"], rank, "bottom", rank_cache)
        update_rank_cache(ev["id"], rank, "bottom", rank_cache, today_str)
        ev["_delta_class"] = dc
        ev["_delta_label"] = dl
        try:
            bottom_html_parts.append(build_card(ev, rank, True, dc, dl, da))
        except Exception as e:
            print(f"  [WARN] bottom card {rank} failed ({ev.get('id','?')}): {e}")
            bottom_html_parts.append(f"  <!-- card {rank} failed: {e} -->")

    # Persist updated rank cache for tomorrow's delta calculation
    save_rank_cache(rank_cache)
    new_count = sum(1 for ev in list(top_events)+list(bottom_events)
                    if ev.get("_delta_class") == "new")
    print(f"[build] Rank cache saved. New entries tonight: {new_count}")

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
    # Rebuild GENRE_POOL_TOP as a <script type="application/json"> element.
    # This avoids WordPress HTML-encoding the large JS object literal when it
    # is inlined inside the main <script> block, which breaks the genre filter.
    # Block 4's main script reads it back via JSON.parse on the element ID.
    try:
        new_pool_js = build_genre_pool_js(events)
        # Extract the JS array literal (between [ and ])
        arr_s = new_pool_js.find("[")
        arr_e = new_pool_js.rfind("]") + 1
        pool_array = new_pool_js[arr_s:arr_e] if arr_s != -1 else "[]"
        # Strip newlines and escape single quotes — the pool is embedded inside
        # a single-quoted JS string literal, which breaks on unescaped ' or newlines.
        pool_array = pool_array.replace("\n", "").replace("\r", "").replace("'", "\\'")

        # Inject <script type="application/json"> just before TOP_CARDS_START
        # Embed pool JSON directly in the <script> block using a sentinel.
        # WordPress.com strips/caches away <template> and <script type=json>
        # elements, but the main <script> block content survives intact.
        # Using JSON.parse(string) is safe — WordPress cannot corrupt a JSON
        # string inside a JS assignment.
        POOL_INLINE_MARKER = "/*CSI_POOL_DATA_START*/"
        POOL_INLINE_END    = "/*CSI_POOL_DATA_END*/"
        if POOL_INLINE_MARKER in html:
            # Replace existing pool marker in script block
            ps = html.find(POOL_INLINE_MARKER)
            pe = html.find(POOL_INLINE_END) + len(POOL_INLINE_END)
            new_pool_inline = (
                POOL_INLINE_MARKER
                + pool_array
                + POOL_INLINE_END
            )
            html = html[:ps] + new_pool_inline + html[pe:]
            print(f"[build] Pool data embedded in script block ({len(pool_array):,} chars)")
        else:
            print("[build] WARN: Pool inline marker not found — pool not updated")
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
