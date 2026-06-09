"""
score.py
Atlanta Music Magazine — Nightly Scoring Engine
Reads raw_signals.json, applies the four-pillar weighted model,
outputs data/scored_events.json with final 0-100 scores.

Weight distribution:
  30% — Current Ticket Demand
  25% — Historical Sales
  25% — Public Sentiment
  20% — Local Intent Signals
"""

import json
import math
import datetime
from pathlib import Path

Path("data").mkdir(exist_ok=True)

# ── Weight constants ───────────────────────────────────────────────────────
W_TICKET_DEMAND   = 0.30
W_HISTORICAL      = 0.25
W_SENTIMENT       = 0.25
W_LOCAL_INTENT    = 0.20


# ── Signal normalizers ─────────────────────────────────────────────────────
# Each returns a 0.0–1.0 float representing relative strength.
# Thresholds are calibrated against the ATL market.

def norm_seatgeek_deal_score(val):
    """SeatGeek Deal Score is already 0-100."""
    if val is None:
        return 0.5   # neutral when unavailable
    return max(0.0, min(1.0, val / 100))


def norm_seatgeek_floor(val):
    """
    Higher floor price = stronger demand signal.
    $0 → 0.0, $500+ → 1.0 (log-scaled to handle outliers).
    """
    if val is None:
        return 0.4
    if val <= 0:
        return 0.0
    return min(1.0, math.log1p(val) / math.log1p(500))


def norm_listing_count(val, venue_cap):
    """
    Listing count relative to venue capacity.
    Low sell-through = high listing count = LOW demand.
    Inverted: fewer listings = higher score.
    """
    if val is None or venue_cap is None or venue_cap == 0:
        return 0.5
    ratio = val / venue_cap
    # >80% of capacity listed = very low demand (0.0)
    # <5% of capacity listed = very high demand (1.0)
    return max(0.0, min(1.0, 1.0 - (ratio / 0.8)))


def norm_tm_status(status):
    """Ticketmaster on-sale status."""
    mapping = {
        "onsale":    0.7,
        "offsale":   1.0,   # sold out
        "cancelled": 0.0,
        "postponed": 0.2,
        "":          0.5,
    }
    return mapping.get(str(status).lower(), 0.5)


def norm_spotify_popularity(val):
    """Spotify popularity is already 0-100."""
    if val is None:
        return 0.4
    return val / 100


def norm_chartmetric_trend(val):
    """
    Chartmetric 30-day stream growth percentage.
    -50% → 0.0, 0% → 0.5, +100% → 1.0
    """
    if val is None:
        return 0.5
    clamped = max(-50, min(100, val))
    return (clamped + 50) / 150


def norm_mb_recent_album(has_recent, days_since):
    """
    MusicBrainz release recency signal.
    Touring on a new album (released within 365 days of concert) is one
    of the strongest predictors of ticket demand in the historical sales pillar.

    has_recent=True, days_since 0–90:   peak commercial cycle → 1.0
    has_recent=True, days_since 91–365: active cycle → 0.75
    has_recent=False, days_since 366–730: heritage tour → 0.45
    has_recent=False, days_since 730+:  deep catalog → 0.25
    has_recent=None (no data):          neutral → 0.5
    """
    if has_recent is None:
        return 0.5
    if has_recent:
        if days_since is None:
            return 0.75
        if days_since <= 90:
            return 1.0
        return 0.75
    if days_since is None:
        return 0.45
    if days_since <= 730:
        return 0.45
    return 0.25


def norm_mb_career_depth(total_albums):
    """
    Total studio album count as a proxy for sustained commercial track record.
    1 album → emerging (0.3)
    2–4 albums → established (0.6)
    5–9 albums → proven (0.8)
    10+ albums → legacy (1.0)
    """
    if not total_albums:
        return 0.4
    if total_albums >= 10:
        return 1.0
    if total_albums >= 5:
        return 0.8
    if total_albums >= 2:
        return 0.6
    return 0.3


def norm_google_trends(val):
    """Google Trends ATL index is already 0-100."""
    if val is None:
        return 0.4
    return val / 100


def norm_bandsintown_rsvps(val, venue_cap):
    """
    RSVPs relative to venue capacity.
    0 → 0.0, ≥30% of capacity → 1.0
    """
    if val is None or not venue_cap:
        return 0.4
    return min(1.0, val / (venue_cap * 0.3))


# ── Venue capacity lookup ──────────────────────────────────────────────────
VENUE_CAPS = {
    "State Farm Arena":                                       21000,
    "Mercedes-Benz Stadium":                                  71000,
    "Ameris Bank Amphitheatre":                               12000,
    "Synovus Bank Amphitheater at Chastain Park":              6900,
    "Lakewood Amphitheatre":                                  19000,
    "Coca-Cola Roxy":                                          3600,
    "Truist Park":                                            41084,
    "The Eastern":                                              500,
    "Vinyl at Center Stage":                                    200,
}


# ── Pillar scoring ─────────────────────────────────────────────────────────

def score_ticket_demand(signals):
    """
    Pillar 1 — Current Ticket Demand (30%)
    Sources: SeatGeek Deal Score, SeatGeek floor price,
             listing count vs capacity, Ticketmaster status.
    """
    components = [
        (0.35, norm_seatgeek_deal_score(signals.get("seatgeek_deal_score"))),
        (0.30, norm_seatgeek_floor(signals.get("seatgeek_floor"))),
        (0.25, norm_listing_count(
            signals.get("seatgeek_listing_count"),
            VENUE_CAPS.get(signals.get("event_meta", {}).get("venue", ""), None)
        )),
        (0.10, norm_tm_status(signals.get("tm_status", ""))),
    ]
    return sum(w * v for w, v in components)


def norm_wikipedia_trend(val):
    """
    Wikipedia 7-day vs prior 7-day pageview delta percentage.
    -100% → 0.0, 0% → 0.5, +200% → 1.0
    """
    if val is None:
        return 0.5
    clamped = max(-100, min(200, val))
    return (clamped + 100) / 300


def score_historical_sales(signals):
    """
    Pillar 2 — Historical Sales (25%)
    Sources: Spotify popularity, Wikipedia 7-day trend,
             Chartmetric stream trend, MusicBrainz release recency,
             MusicBrainz career depth (album count).

    Weight distribution within pillar:
      30% — MB release recency (touring on new album vs. catalog)
      25% — Spotify popularity (commercial track record proxy)
      20% — MB career depth (total studio albums)
      15% — Wikipedia 7-day trend (sustained public interest)
      10% — Chartmetric stream trend (recent streaming momentum)
    """
    has_recent  = signals.get("mb_has_recent_album")
    days_since  = signals.get("mb_days_since_last_album")
    total_albums = signals.get("mb_total_albums", 0)

    components = [
        (0.30, norm_mb_recent_album(has_recent, days_since)),
        (0.25, norm_spotify_popularity(signals.get("spotify_popularity"))),
        (0.20, norm_mb_career_depth(total_albums)),
        (0.15, norm_wikipedia_trend(signals.get("wikipedia_7d_trend_pct"))),
        (0.10, norm_chartmetric_trend(signals.get("cm_spotify_stream_trend"))),
    ]
    return sum(w * v for w, v in components)


def score_sentiment(signals):
    """
    Pillar 3 — Public Sentiment (25%)
    Sources: Spotify popularity (doubles as sentiment signal),
             Chartmetric streaming velocity, Google Trends (partial overlap).
    """
    components = [
        (0.45, norm_spotify_popularity(signals.get("spotify_popularity"))),
        (0.35, norm_chartmetric_trend(signals.get("cm_spotify_stream_trend"))),
        (0.20, norm_google_trends(signals.get("google_trends_atl"))),
    ]
    return sum(w * v for w, v in components)


def score_local_intent(signals):
    """
    Pillar 4 — Local Intent Signals (20%)
    Sources: Google Trends ATL DMA index,
             Bands in Town RSVP count vs venue capacity.
    """
    venue_cap = VENUE_CAPS.get(
        signals.get("event_meta", {}).get("venue", ""), None
    )
    components = [
        (0.60, norm_google_trends(signals.get("google_trends_atl"))),
        (0.40, norm_bandsintown_rsvps(signals.get("bandsintown_rsvps"), venue_cap)),
    ]
    return sum(w * v for w, v in components)


def compute_final_score(signals):
    """
    Combine four pillars into a final 0-100 integer score.
    All pillar functions are guaranteed to return floats via their
    normalizers, but we wrap in float() as a safety net.
    """
    try:
        p1 = float(score_ticket_demand(signals)  or 0)
        p2 = float(score_historical_sales(signals) or 0)
        p3 = float(score_sentiment(signals)      or 0)
        p4 = float(score_local_intent(signals)   or 0)

        raw = (
            W_TICKET_DEMAND * p1 +
            W_HISTORICAL    * p2 +
            W_SENTIMENT     * p3 +
            W_LOCAL_INTENT  * p4
        )
        final = max(0, min(100, round(raw * 100)))
    except Exception as e:
        print(f"  [WARN] Score computation failed, defaulting to 0: {e}")
        final = 0
        p1 = p2 = p3 = p4 = 0.0

    return final, {
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


# ── Main scoring loop ──────────────────────────────────────────────────────

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
            print(f"  [WARN] Scoring failed for {event_id}: {e} — defaulting to 0")
            final_score = 0
            pillar_scores = {
                "ticket_demand": 0,
                "historical_sales": 0,
                "sentiment": 0,
                "local_intent": 0,
            }

        # Guarantee score is always a plain int, never None or float
        final_score = int(final_score) if final_score is not None else 0

        scored.append({
            "id":           event_id,
            "name":         meta.get("name", event_id),
            "artist":       meta.get("artist", ""),
            "venue":        meta.get("venue", ""),
            "date":         meta.get("date", ""),
            "genre":        meta.get("genre", ""),
            "score":        final_score,
            "pillar_scores": pillar_scores,
            "signal_levels": {
                "ticket_demand":    determine_signal_level(pillar_scores["ticket_demand"]),
                "historical_sales": determine_signal_level(pillar_scores["historical_sales"]),
                "sentiment":        determine_signal_level(pillar_scores["sentiment"]),
                "local_intent":     determine_signal_level(pillar_scores["local_intent"]),
            },
            "raw_signals": {
                "seatgeek_deal_score":        signals.get("seatgeek_deal_score"),
                "seatgeek_floor":             signals.get("seatgeek_floor"),
                "seatgeek_avg_price":         signals.get("seatgeek_avg_price"),
                "seatgeek_listing_count":     signals.get("seatgeek_listing_count"),
                "tm_floor_price":             signals.get("tm_floor_price"),
                "tm_status":                  signals.get("tm_status"),
                "spotify_popularity":         signals.get("spotify_popularity"),
                "spotify_followers":          signals.get("spotify_followers"),
                "spotify_top_track_popularity": signals.get("spotify_top_track_popularity"),
                "cm_spotify_stream_trend":    signals.get("cm_spotify_stream_trend"),
                "google_trends_atl":          signals.get("google_trends_atl"),
                "bandsintown_rsvps":          signals.get("bandsintown_rsvps"),
                "wikipedia_30d_views":        signals.get("wikipedia_30d_views"),
                "wikipedia_7d_trend_pct":     signals.get("wikipedia_7d_trend_pct"),
                "mb_has_recent_album":        signals.get("mb_has_recent_album"),
                "mb_days_since_last_album":   signals.get("mb_days_since_last_album"),
                "mb_total_albums":            signals.get("mb_total_albums"),
                "mb_latest_album_title":      signals.get("mb_latest_album_title"),
            },
        })
        print(f"  {meta.get('name', event_id)[:50]:50s}  score={final_score:3d}")

    # Sort by score descending — all scores are guaranteed ints at this point
    scored.sort(key=lambda e: e["score"], reverse=True)

    output = {
        "scored_at": datetime.datetime.utcnow().isoformat() + "Z",
        "events": scored,
    }
    with open("data/scored_events.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"[score] Done. Scored {len(scored)} events.")
    return scored


if __name__ == "__main__":
    score_all()
