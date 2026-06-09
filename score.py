"""
score.py
Atlanta Music Magazine — Nightly Scoring Engine

Weight distribution (top-level pillars):
  30% — Current Ticket Demand
  25% — Historical Sales
  25% — Public Sentiment
  20% — Local Intent Signals

Scoring improvements for broader segmentation:

  Rec 1 — Intra-pillar rebalance toward keyless sources
    Wikipedia boosted within historical sales pillar.
    MusicBrainz (keyless) given primary weight.

  Rec 2 — Venue tier + date-proximity signal
    Encodes structural demand expectations from venue size and
    days until the show. No API key required.

  Rec 3 — Genre-tier prior
    ATL-market-calibrated baseline per genre, applied as
    15% of the sentiment pillar. No API key required.

  Rec 4 — Seed score prior
    Hand-researched scores from the dashboard seed the model
    when API data is sparse. Decays as real signals arrive.
    Weight = 80% when no signals, 10% when all signals present.
"""

import json
import math
import datetime
from pathlib import Path

Path("data").mkdir(exist_ok=True)

# ── Top-level pillar weights ──────────────────────────────────────────────
W_TICKET_DEMAND = 0.30
W_HISTORICAL    = 0.25
W_SENTIMENT     = 0.25
W_LOCAL_INTENT  = 0.20

# ── Venue capacity lookup ─────────────────────────────────────────────────
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

# ── Rec 3: Genre-tier prior ───────────────────────────────────────────────
# ATL-market-calibrated 0.0–1.0 baseline per genre.
# Derived from 3 years of Pollstar ATL gross data and the
# hand-scored dashboard values for this event window.
GENRE_DEMAND_PRIOR = {
    "Latin Pop":     0.76,
    "Pop":           0.70,
    "Hip-Hop":       0.68,
    "R&B":           0.63,
    "Multi-Genre":   0.65,
    "Country":       0.62,
    "Alt / R&B":     0.58,
    "Rock":          0.56,
    "Pop / Rock":    0.54,
    "Indie / Psych": 0.52,
    "Reggae":        0.48,
    "Indie / Alt":   0.44,
    "Classic Rock":  0.40,
    "Metalcore":     0.36,
    "Hyperpop":      0.22,
}
GENRE_PRIOR_DEFAULT = 0.50


# ── Signal availability counter ───────────────────────────────────────────
# Used by Rec 4 to determine how much to weight the seed prior.
# Each key that is non-None and non-zero counts as one available signal.
API_SIGNAL_KEYS = [
    "seatgeek_deal_score", "seatgeek_floor", "seatgeek_listing_count",
    "tm_status", "tm_floor_price",
    "spotify_popularity", "spotify_followers",
    "cm_spotify_stream_trend",
    "google_trends_atl", "bandsintown_rsvps",
    "lastfm_listeners", "lastfm_plays_per_listener",
    "setlist_atl_shows_5y", "setlist_avg_venue_cap",
    "eb_sell_through_pct", "eb_is_sold_out",
]
TOTAL_API_SIGNALS = len(API_SIGNAL_KEYS)


def count_available_signals(signals):
    """Count how many API signals returned real (non-None) data."""
    count = 0
    for key in API_SIGNAL_KEYS:
        val = signals.get(key)
        if val is not None and val is not False and val != "":
            count += 1
    return count


# ═══════════════════════════════════════════════════════════════════════════
# SIGNAL NORMALIZERS — each returns 0.0–1.0
# ═══════════════════════════════════════════════════════════════════════════

# ── Ticket demand ─────────────────────────────────────────────────────────

def norm_seatgeek_deal_score(val):
    if val is None:
        return None   # signal absent — caller handles
    return max(0.0, min(1.0, float(val) / 100))


def norm_seatgeek_floor(val):
    if val is None:
        return None
    val = float(val)
    if val <= 0:
        return 0.0
    return min(1.0, math.log1p(val) / math.log1p(500))


def norm_listing_count(val, venue_cap):
    if val is None or not venue_cap:
        return None
    ratio = float(val) / venue_cap
    return max(0.0, min(1.0, 1.0 - (ratio / 0.8)))


def norm_tm_status(status):
    if not status:
        return None
    mapping = {
        "onsale": 0.65, "offsale": 1.0,
        "cancelled": 0.0, "postponed": 0.15,
    }
    return mapping.get(str(status).lower())


def norm_eb_sell_through(val):
    if val is None:
        return None
    return max(0.0, min(1.0, float(val) / 100))


def norm_eb_sold_out(is_sold_out, has_waitlist):
    if is_sold_out is None:
        return None
    if is_sold_out and has_waitlist:
        return 1.0
    if is_sold_out:
        return 0.9
    if has_waitlist:
        return 0.8
    return 0.45   # not sold out, no waitlist — below neutral


def norm_eb_ticket_tiers(num_tiers):
    if not num_tiers:
        return None
    if num_tiers >= 6:
        return 0.9
    if num_tiers >= 4:
        return 0.8
    if num_tiers >= 2:
        return 0.65
    return 0.5


# ── Rec 2: Venue tier + date proximity ───────────────────────────────────
def norm_venue_tier(venue, event_date_str):
    """
    Structural demand prior from venue size and show proximity.
    No API key required. Provides immediate score spread.

    Venue tier baselines (ATL market):
      Stadium 50K+:    0.80 — must be a major act to book this
      Arena 18–50K:    0.65 — strong demand expected
      Amphitheatre 10–18K: 0.55
      Mid-size 5–10K:  0.48
      Club <5K:        0.35 — niche or developing act

    Proximity adjustment:
      0–30 days until show: +0.12 (urgency premium)
      31–60 days:           +0.06
      61–90 days:            0.00
      90+ days:             -0.04 (far-future, demand not yet peaked)
    """
    cap = VENUE_CAPS.get(venue, 0)

    if cap >= 50000:
        base = 0.80
    elif cap >= 18000:
        base = 0.65
    elif cap >= 10000:
        base = 0.55
    elif cap >= 5000:
        base = 0.48
    elif cap > 0:
        base = 0.35
    else:
        return 0.50   # unknown venue → neutral

    # Date proximity
    try:
        show_date = datetime.date.fromisoformat(event_date_str)
        days_out  = (show_date - datetime.date.today()).days
        if days_out < 0:
            proximity = 0.0    # past show
        elif days_out <= 30:
            proximity = 0.12
        elif days_out <= 60:
            proximity = 0.06
        elif days_out <= 90:
            proximity = 0.00
        else:
            proximity = -0.04
    except (ValueError, TypeError):
        proximity = 0.0

    return max(0.0, min(1.0, base + proximity))


# ── Historical sales ──────────────────────────────────────────────────────

def norm_mb_recent_album(has_recent, days_since):
    if has_recent is None:
        return None
    if has_recent:
        if days_since is None:
            return 0.75
        days_since = int(days_since)
        if days_since <= 90:
            return 1.0
        return 0.75
    if days_since is None:
        return 0.45
    return 0.45 if int(days_since) <= 730 else 0.25


def norm_mb_career_depth(total_albums):
    if total_albums is None:
        return None
    total_albums = int(total_albums)
    if total_albums >= 10:
        return 1.0
    if total_albums >= 5:
        return 0.8
    if total_albums >= 2:
        return 0.6
    if total_albums == 1:
        return 0.35
    return 0.25   # 0 albums → no commercial track record


def norm_setlist_venue_trajectory(avg_cap, current_cap):
    if avg_cap is None or not current_cap:
        return None
    ratio = current_cap / avg_cap
    if ratio >= 1.3:
        return 1.0
    if ratio >= 0.8:
        return 0.70
    if ratio >= 0.5:
        return 0.45
    return 0.30


def norm_wikipedia_trend(val):
    if val is None:
        return None
    clamped = max(-100, min(200, float(val)))
    return (clamped + 100) / 300


def norm_chartmetric_trend(val):
    if val is None:
        return None
    clamped = max(-50, min(100, float(val)))
    return (clamped + 50) / 150


def norm_spotify_popularity(val):
    if val is None:
        return None
    return float(val) / 100


# ── Sentiment / Last.fm ───────────────────────────────────────────────────

def norm_lastfm_listeners(val):
    if val is None:
        return None
    val = max(1, min(int(val), 15_000_000))
    return round(math.log10(val) / math.log10(15_000_000), 4)


def norm_lastfm_depth(plays_per_listener):
    if plays_per_listener is None:
        return None
    ppl = float(plays_per_listener)
    if ppl >= 500:
        return 1.0
    if ppl >= 200:
        return 0.85
    if ppl >= 50:
        return 0.65
    return 0.35


def norm_lastfm_peer_tier(avg_similar_listeners):
    return norm_lastfm_listeners(avg_similar_listeners)


# ── Rec 3: Genre prior ────────────────────────────────────────────────────
def norm_genre_prior(genre):
    """
    ATL-market genre demand baseline. Always returns a value (no None).
    This is a structural prior, not an API signal.
    """
    return GENRE_DEMAND_PRIOR.get(genre, GENRE_PRIOR_DEFAULT)


# ── Local intent ──────────────────────────────────────────────────────────

def norm_google_trends(val):
    if val is None:
        return None
    return float(val) / 100


def norm_bandsintown_rsvps(val, venue_cap):
    if val is None or not venue_cap:
        return None
    return min(1.0, float(val) / (venue_cap * 0.30))


def norm_setlist_atl_market(atl_shows_5y):
    if atl_shows_5y is None:
        return None
    n = int(atl_shows_5y)
    if n >= 7:
        return 1.0
    if n >= 4:
        return 0.85
    if n >= 2:
        return 0.70
    if n == 1:
        return 0.55
    return 0.35   # 0 ATL shows in 5 years → unfamiliar market


def norm_setlist_sold_out(sold_out_flag):
    if sold_out_flag is None:
        return None
    return 1.0 if sold_out_flag else 0.45


# ═══════════════════════════════════════════════════════════════════════════
# WEIGHTED AVERAGE HELPER
# Handles None values from missing signals by computing a weighted
# average over only the signals that returned real data.
# Falls back to `neutral` when ALL signals are absent.
# ═══════════════════════════════════════════════════════════════════════════

def weighted_avg(components, neutral=0.50):
    """
    components: list of (weight, value_or_None)
    Returns weighted average of non-None values.
    If all values are None, returns `neutral`.
    """
    total_w = 0.0
    total_v = 0.0
    for w, v in components:
        if v is not None:
            total_w += w
            total_v += w * v
    if total_w == 0:
        return neutral
    return total_v / total_w


# ═══════════════════════════════════════════════════════════════════════════
# FOUR SCORING PILLARS
# ═══════════════════════════════════════════════════════════════════════════

def score_ticket_demand(signals):
    """
    Pillar 1 — Current Ticket Demand (30%)

    Sources (API-dependent):
      SeatGeek Deal Score, SeatGeek floor price, listing count,
      Ticketmaster status, Eventbrite sell-through, sold-out flag,
      ticket tier count.

    Always-available (no key):
      Rec 2 — Venue tier + date proximity signal.

    Intra-pillar weights:
      25% — Venue tier + proximity  [KEYLESS — always fires]
      20% — SeatGeek Deal Score
      18% — Eventbrite sell-through / sold-out
      15% — SeatGeek floor price
      12% — Listing count vs capacity
      10% — Ticketmaster status
    """
    meta      = signals.get("event_meta", {})
    venue     = meta.get("venue", "")
    date_str  = meta.get("date", "")
    venue_cap = VENUE_CAPS.get(venue)

    components = [
        # Keyless structural signal — always 0.0–1.0
        (0.25, norm_venue_tier(venue, date_str)),

        # API signals — may be None
        (0.20, norm_seatgeek_deal_score(signals.get("seatgeek_deal_score"))),
        (0.18, norm_eb_sold_out(
                   signals.get("eb_is_sold_out"),
                   signals.get("eb_has_waitlist"))),
        (0.15, norm_seatgeek_floor(signals.get("seatgeek_floor"))),
        (0.12, norm_listing_count(signals.get("seatgeek_listing_count"), venue_cap)),
        (0.10, norm_tm_status(signals.get("tm_status"))),
    ]
    return weighted_avg(components, neutral=0.50)


def score_historical_sales(signals):
    """
    Pillar 2 — Historical Sales (25%)

    Sources:
      MusicBrainz release recency [KEYLESS]
      MusicBrainz career depth    [KEYLESS]
      Setlist.fm venue trajectory [key required]
      Wikipedia 7-day trend       [KEYLESS]
      Spotify popularity          [key required]
      Chartmetric stream trend    [key required]

    Intra-pillar weights (Rec 1 — boosted toward keyless sources):
      30% — MusicBrainz release recency  [KEYLESS]
      22% — Wikipedia 7-day trend        [KEYLESS — boosted from 10%]
      20% — MusicBrainz career depth     [KEYLESS — boosted from 15%]
      15% — Setlist.fm venue trajectory
      08% — Spotify popularity
      05% — Chartmetric stream trend
    """
    venue       = signals.get("event_meta", {}).get("venue", "")
    current_cap = VENUE_CAPS.get(venue)

    components = [
        (0.30, norm_mb_recent_album(
                   signals.get("mb_has_recent_album"),
                   signals.get("mb_days_since_last_album"))),
        (0.22, norm_wikipedia_trend(signals.get("wikipedia_7d_trend_pct"))),
        (0.20, norm_mb_career_depth(signals.get("mb_total_albums"))),
        (0.15, norm_setlist_venue_trajectory(
                   signals.get("setlist_avg_venue_cap"), current_cap)),
        (0.08, norm_spotify_popularity(signals.get("spotify_popularity"))),
        (0.05, norm_chartmetric_trend(signals.get("cm_spotify_stream_trend"))),
    ]
    return weighted_avg(components, neutral=0.50)


def score_sentiment(signals):
    """
    Pillar 3 — Public Sentiment (25%)

    Sources:
      Rec 3 — Genre-tier prior   [KEYLESS — always fires]
      Spotify popularity          [key required]
      Last.fm listener breadth    [key required]
      Last.fm fan depth           [key required]
      Last.fm peer tier           [key required]
      Chartmetric stream trend    [key required]

    Intra-pillar weights:
      20% — Genre-tier prior     [KEYLESS — always fires]
      20% — Spotify popularity
      20% — Last.fm listener breadth
      18% — Last.fm fan depth (plays/listener)
      12% — Chartmetric stream trend
      10% — Last.fm peer tier
    """
    genre = signals.get("event_meta", {}).get("genre", "")

    components = [
        # Genre prior — always returns a value
        (0.20, norm_genre_prior(genre)),

        # API signals
        (0.20, norm_spotify_popularity(signals.get("spotify_popularity"))),
        (0.20, norm_lastfm_listeners(signals.get("lastfm_listeners"))),
        (0.18, norm_lastfm_depth(signals.get("lastfm_plays_per_listener"))),
        (0.12, norm_chartmetric_trend(signals.get("cm_spotify_stream_trend"))),
        (0.10, norm_lastfm_peer_tier(signals.get("lastfm_similar_listeners"))),
    ]
    return weighted_avg(components, neutral=0.50)


def score_local_intent(signals):
    """
    Pillar 4 — Local Intent Signals (20%)

    Sources:
      Google Trends ATL DMA       [SerpApi key required]
      Setlist.fm ATL market       [Setlist key required]
      Bands in Town RSVPs         [key required]
      Setlist.fm sold-out flag    [Setlist key required]

    Intra-pillar weights:
      35% — Google Trends ATL
      28% — Setlist.fm ATL market history
      25% — Bands in Town RSVPs
      12% — Setlist.fm prior ATL sold-out
    """
    venue_cap = VENUE_CAPS.get(
        signals.get("event_meta", {}).get("venue", ""), None)

    components = [
        (0.35, norm_google_trends(signals.get("google_trends_atl"))),
        (0.28, norm_setlist_atl_market(signals.get("setlist_atl_shows_5y"))),
        (0.25, norm_bandsintown_rsvps(signals.get("bandsintown_rsvps"), venue_cap)),
        (0.12, norm_setlist_sold_out(signals.get("setlist_sold_out_flag"))),
    ]
    return weighted_avg(components, neutral=0.50)


# ═══════════════════════════════════════════════════════════════════════════
# REC 4: SEED SCORE PRIOR + FINAL SCORE COMPUTATION
# ═══════════════════════════════════════════════════════════════════════════

def compute_final_score(signals):
    """
    Combine four pillars into a final 0-100 integer score.

    Rec 4 — Seed score prior:
    The hand-researched seed_score from each event's EVENTS entry
    anchors the model when API data is sparse. Its weight decays
    linearly from 0.75 (no API signals) to 0.10 (all signals present).

    Formula:
      available = signals actually returned by APIs (0–16)
      seed_weight = max(0.10, 0.75 - (available/total) * 0.65)
      model_weight = 1 - seed_weight
      final = seed_weight * seed_score + model_weight * model_score
    """
    try:
        p1 = float(score_ticket_demand(signals)   or 0)
        p2 = float(score_historical_sales(signals) or 0)
        p3 = float(score_sentiment(signals)        or 0)
        p4 = float(score_local_intent(signals)     or 0)

        model_score_raw = (
            W_TICKET_DEMAND * p1 +
            W_HISTORICAL    * p2 +
            W_SENTIMENT     * p3 +
            W_LOCAL_INTENT  * p4
        )
        model_score = model_score_raw * 100   # 0–100 scale

        # Seed prior (Rec 4)
        seed_score = float(
            signals.get("event_meta", {}).get("seed_score", 50) or 50
        )
        available     = count_available_signals(signals)
        seed_weight   = max(0.10, 0.75 - (available / TOTAL_API_SIGNALS) * 0.65)
        model_weight  = 1.0 - seed_weight

        final = max(0, min(100, round(
            seed_weight * seed_score + model_weight * model_score
        )))

    except Exception as e:
        print(f"  [WARN] Score computation failed, defaulting to seed: {e}")
        seed_score = float(
            signals.get("event_meta", {}).get("seed_score", 50) or 50
        )
        final = int(seed_score)
        p1 = p2 = p3 = p4 = 0.0

    return int(final), {
        "ticket_demand":    round(p1 * 100),
        "historical_sales": round(p2 * 100),
        "sentiment":        round(p3 * 100),
        "local_intent":     round(p4 * 100),
    }


def determine_signal_level(score):
    """Map a 0-100 pillar score to High / Medium / Low."""
    if score >= 65:
        return "High"
    elif score >= 35:
        return "Medium"
    return "Low"


# ═══════════════════════════════════════════════════════════════════════════
# MAIN SCORING LOOP
# ═══════════════════════════════════════════════════════════════════════════

def score_all():
    print(f"[score] Starting scoring — {datetime.datetime.now().isoformat()}")

    with open("data/raw_signals.json") as f:
        raw = json.load(f)

    scored = []
    for event_id, signals in raw["events"].items():
        meta = signals.get("event_meta", {})
        try:
            final_score, pillar_scores = compute_final_score(signals)
        except Exception as e:
            print(f"  [WARN] Scoring failed for {event_id}: {e} — using seed")
            final_score  = int(meta.get("seed_score", 50) or 50)
            pillar_scores = {
                "ticket_demand": 0, "historical_sales": 0,
                "sentiment": 0,     "local_intent": 0,
            }

        final_score = int(final_score) if final_score is not None else 50

        available = count_available_signals(signals)
        seed_w    = round(max(0.10, 0.75 - (available/TOTAL_API_SIGNALS)*0.65), 2)

        scored.append({
            "id":           event_id,
            "name":         meta.get("name", event_id),
            "artist":       meta.get("artist", ""),
            "venue":        meta.get("venue", ""),
            "date":         meta.get("date", ""),
            "genre":        meta.get("genre", ""),
            "score":        final_score,
            "seed_score":   meta.get("seed_score", 50),
            "api_signals_available": available,
            "seed_weight_used": seed_w,
            "pillar_scores": pillar_scores,
            "signal_levels": {
                "ticket_demand":    determine_signal_level(pillar_scores["ticket_demand"]),
                "historical_sales": determine_signal_level(pillar_scores["historical_sales"]),
                "sentiment":        determine_signal_level(pillar_scores["sentiment"]),
                "local_intent":     determine_signal_level(pillar_scores["local_intent"]),
            },
            "raw_signals": {
                "seatgeek_deal_score":          signals.get("seatgeek_deal_score"),
                "seatgeek_floor":               signals.get("seatgeek_floor"),
                "seatgeek_avg_price":           signals.get("seatgeek_avg_price"),
                "seatgeek_listing_count":       signals.get("seatgeek_listing_count"),
                "tm_floor_price":               signals.get("tm_floor_price"),
                "tm_status":                    signals.get("tm_status"),
                "spotify_popularity":           signals.get("spotify_popularity"),
                "spotify_followers":            signals.get("spotify_followers"),
                "spotify_top_track_popularity": signals.get("spotify_top_track_popularity"),
                "cm_spotify_stream_trend":      signals.get("cm_spotify_stream_trend"),
                "google_trends_atl":            signals.get("google_trends_atl"),
                "bandsintown_rsvps":            signals.get("bandsintown_rsvps"),
                "wikipedia_30d_views":          signals.get("wikipedia_30d_views"),
                "wikipedia_7d_trend_pct":       signals.get("wikipedia_7d_trend_pct"),
                "mb_has_recent_album":          signals.get("mb_has_recent_album"),
                "mb_days_since_last_album":     signals.get("mb_days_since_last_album"),
                "mb_total_albums":              signals.get("mb_total_albums"),
                "mb_latest_album_title":        signals.get("mb_latest_album_title"),
                "setlist_atl_shows_5y":         signals.get("setlist_atl_shows_5y"),
                "setlist_avg_venue_cap":        signals.get("setlist_avg_venue_cap"),
                "setlist_tour_shows_total":     signals.get("setlist_tour_shows_total"),
                "setlist_sold_out_flag":        signals.get("setlist_sold_out_flag"),
                "lastfm_listeners":             signals.get("lastfm_listeners"),
                "lastfm_playcount":             signals.get("lastfm_playcount"),
                "lastfm_plays_per_listener":    signals.get("lastfm_plays_per_listener"),
                "lastfm_on_tour":               signals.get("lastfm_on_tour"),
                "lastfm_similar_listeners":     signals.get("lastfm_similar_listeners"),
                "eb_has_listing":               signals.get("eb_has_listing"),
                "eb_capacity":                  signals.get("eb_capacity"),
                "eb_tickets_sold":              signals.get("eb_tickets_sold"),
                "eb_sell_through_pct":          signals.get("eb_sell_through_pct"),
                "eb_is_sold_out":               signals.get("eb_is_sold_out"),
                "eb_has_waitlist":              signals.get("eb_has_waitlist"),
                "eb_ticket_types":              signals.get("eb_ticket_types"),
            },
        })
        print(
            f"  {meta.get('name', event_id)[:48]:48s}"
            f"  score={final_score:3d}"
            f"  seed_w={seed_w:.2f}"
            f"  api={available}/{TOTAL_API_SIGNALS}"
        )

    scored.sort(key=lambda e: e["score"], reverse=True)

    output = {
        "scored_at": datetime.datetime.utcnow().isoformat() + "Z",
        "events":    scored,
    }
    with open("data/scored_events.json", "w") as f:
        json.dump(output, f, indent=2)

    scores = [e["score"] for e in scored]
    print(f"[score] Done. {len(scored)} events scored.")
    print(f"[score] Score range: {min(scores)}–{max(scores)}  "
          f"mean: {sum(scores)/len(scores):.1f}")
    return scored


if __name__ == "__main__":
    score_all()
