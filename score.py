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


def norm_setlist_atl_market(atl_shows_5y):
    """
    Number of Atlanta-area shows in the past 5 years.
    Measures local market strength — artists who return to ATL regularly
    have an established local fanbase that converts reliably.
    0 shows → unknown/new to market (0.4 neutral)
    1 show  → occasional visitor (0.5)
    2–3     → regular (0.7)
    4–6     → strong local draw (0.85)
    7+      → ATL anchor market (1.0)
    """
    if atl_shows_5y is None:
        return 0.4
    if atl_shows_5y >= 7:
        return 1.0
    if atl_shows_5y >= 4:
        return 0.85
    if atl_shows_5y >= 2:
        return 0.7
    if atl_shows_5y == 1:
        return 0.5
    return 0.4


def norm_setlist_venue_trajectory(avg_venue_cap, current_venue_cap):
    """
    Average historical venue capacity vs. current show's venue capacity.
    Ratio > 1: artist is graduating to larger venues → ascending demand (1.0)
    Ratio ~1:  stable market position (0.7)
    Ratio < 1: artist playing smaller than historical average → declining (0.3)
    """
    if avg_venue_cap is None or not current_venue_cap:
        return 0.5
    ratio = current_venue_cap / avg_venue_cap
    if ratio >= 1.3:
        return 1.0   # graduating up
    if ratio >= 0.8:
        return 0.7   # stable
    if ratio >= 0.5:
        return 0.45  # declining
    return 0.3       # significant downsize


def norm_setlist_sold_out(sold_out_flag):
    """Prior ATL show sold out → strong local demand signal."""
    return 1.0 if sold_out_flag else 0.5


def norm_lastfm_listeners(val):
    """
    Last.fm weekly unique listeners — breadth of active audience.
    Scaled against ATL-market-relevant thresholds (log scale).
    <100K   → niche (0.2)
    100K–1M → emerging mainstream (0.5)
    1M–5M   → mainstream (0.75)
    5M–15M  → major (0.9)
    15M+    → global superstar (1.0)
    """
    if not val:
        return 0.4
    import math
    # log scale: log10(15M) ≈ 7.18 as ceiling
    clamped = max(1, min(val, 15_000_000))
    return round(math.log10(clamped) / math.log10(15_000_000), 3)


def norm_lastfm_depth(plays_per_listener):
    """
    Plays-per-listener ratio — fan obsession depth.
    Low  (<50):   casual listeners, lower ticket conversion
    Mid  (50–200): engaged fans
    High (200–500): obsessive fans, strong ticket conversion
    Very high (500+): cult following
    """
    if plays_per_listener is None:
        return 0.5
    if plays_per_listener >= 500:
        return 1.0
    if plays_per_listener >= 200:
        return 0.85
    if plays_per_listener >= 50:
        return 0.65
    return 0.35


def norm_lastfm_peer_tier(avg_similar_listeners):
    """
    Average listener count of top 3 similar artists.
    Measures which commercial tier the artist competes in.
    If their peers are major artists, they likely are too.
    Uses same log scale as norm_lastfm_listeners.
    """
    return norm_lastfm_listeners(avg_similar_listeners)


def norm_eb_sell_through(sell_through_pct):
    """
    Eventbrite sell-through percentage.
    0%   → no demand (0.0)
    50%  → moderate (0.5)
    80%  → strong (0.85)
    100% → sold out (1.0)
    None → no listing / data unavailable (0.5 neutral)
    """
    if sell_through_pct is None:
        return 0.5
    return max(0.0, min(1.0, sell_through_pct / 100))


def norm_eb_sold_out(is_sold_out, has_waitlist):
    """
    Sold-out flag + waitlist flag — binary demand ceiling signals.
    Sold out with waitlist: 1.0 (maximum demand signal)
    Sold out, no waitlist:  0.9
    Not sold out:           0.5 (fall through to sell-through normalizer)
    """
    if is_sold_out and has_waitlist:
        return 1.0
    if is_sold_out:
        return 0.9
    if has_waitlist:
        return 0.8
    return 0.5


def norm_eb_ticket_tiers(num_tiers):
    """
    Number of distinct ticket price tiers.
    More tiers = promoter expecting price-sensitive demand spectrum.
    1 tier: simple GA or single price (0.5)
    2–3:    standard tiered (0.65)
    4–5:    high-demand show with premium/VIP tiers (0.8)
    6+:     complex demand — multiple VIP packages (0.9)
    """
    if not num_tiers:
        return 0.5
    if num_tiers >= 6:
        return 0.9
    if num_tiers >= 4:
        return 0.8
    if num_tiers >= 2:
        return 0.65
    return 0.5


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
             listing count vs capacity, Ticketmaster status,
             Eventbrite sell-through, Eventbrite sold-out/waitlist,
             Eventbrite ticket tier count.

    Weight distribution:
      25% — SeatGeek Deal Score (composite secondary market signal)
      20% — SeatGeek floor price (secondary market floor)
      20% — Eventbrite sell-through % (primary market pace)
      15% — Eventbrite sold-out / waitlist flag
      10% — Listing count vs. venue capacity (inverse — fewer = more demand)
      10% — Ticketmaster on-sale status
    """
    components = [
        (0.25, norm_seatgeek_deal_score(signals.get("seatgeek_deal_score"))),
        (0.20, norm_seatgeek_floor(signals.get("seatgeek_floor"))),
        (0.20, norm_eb_sell_through(signals.get("eb_sell_through_pct"))),
        (0.15, norm_eb_sold_out(
            signals.get("eb_is_sold_out", False),
            signals.get("eb_has_waitlist", False),
        )),
        (0.10, norm_listing_count(
            signals.get("seatgeek_listing_count"),
            VENUE_CAPS.get(signals.get("event_meta", {}).get("venue", ""), None),
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
    Sources: MusicBrainz release recency, Spotify popularity,
             MusicBrainz career depth, Setlist.fm venue trajectory,
             Wikipedia trend, Chartmetric stream trend.

    Weight distribution:
      25% — MB release recency (touring on new album vs. catalog)
      20% — Spotify popularity (commercial track record proxy)
      20% — Setlist.fm venue trajectory (growing / stable / declining)
      15% — MB career depth (total studio albums)
      10% — Wikipedia 7-day trend
      10% — Chartmetric stream trend
    """
    venue       = signals.get("event_meta", {}).get("venue", "")
    current_cap = VENUE_CAPS.get(venue)

    components = [
        (0.25, norm_mb_recent_album(
            signals.get("mb_has_recent_album"),
            signals.get("mb_days_since_last_album"),
        )),
        (0.20, norm_spotify_popularity(signals.get("spotify_popularity"))),
        (0.20, norm_setlist_venue_trajectory(
            signals.get("setlist_avg_venue_cap"),
            current_cap,
        )),
        (0.15, norm_mb_career_depth(signals.get("mb_total_albums", 0))),
        (0.10, norm_wikipedia_trend(signals.get("wikipedia_7d_trend_pct"))),
        (0.10, norm_chartmetric_trend(signals.get("cm_spotify_stream_trend"))),
    ]
    return sum(w * v for w, v in components)


def score_sentiment(signals):
    """
    Pillar 3 — Public Sentiment (25%)
    Sources: Spotify popularity, Last.fm listener breadth,
             Last.fm fan depth (plays/listener), Last.fm peer tier,
             Chartmetric stream trend.

    Weight distribution:
      30% — Spotify popularity (mainstream commercial signal)
      25% — Last.fm listener breadth (active weekly audience size)
      20% — Last.fm fan depth (plays-per-listener obsession ratio)
      15% — Chartmetric stream trend (30-day momentum)
      10% — Last.fm peer tier (similar artist commercial level)
    """
    components = [
        (0.30, norm_spotify_popularity(signals.get("spotify_popularity"))),
        (0.25, norm_lastfm_listeners(signals.get("lastfm_listeners"))),
        (0.20, norm_lastfm_depth(signals.get("lastfm_plays_per_listener"))),
        (0.15, norm_chartmetric_trend(signals.get("cm_spotify_stream_trend"))),
        (0.10, norm_lastfm_peer_tier(signals.get("lastfm_similar_listeners"))),
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
                "setlist_atl_shows_5y":       signals.get("setlist_atl_shows_5y"),
                "setlist_avg_venue_cap":      signals.get("setlist_avg_venue_cap"),
                "setlist_tour_shows_total":   signals.get("setlist_tour_shows_total"),
                "setlist_sold_out_flag":      signals.get("setlist_sold_out_flag"),
                "lastfm_listeners":           signals.get("lastfm_listeners"),
                "lastfm_playcount":           signals.get("lastfm_playcount"),
                "lastfm_plays_per_listener":  signals.get("lastfm_plays_per_listener"),
                "lastfm_on_tour":             signals.get("lastfm_on_tour"),
                "lastfm_similar_listeners":   signals.get("lastfm_similar_listeners"),
                "eb_has_listing":             signals.get("eb_has_listing"),
                "eb_capacity":               signals.get("eb_capacity"),
                "eb_tickets_sold":           signals.get("eb_tickets_sold"),
                "eb_sell_through_pct":       signals.get("eb_sell_through_pct"),
                "eb_is_sold_out":            signals.get("eb_is_sold_out"),
                "eb_has_waitlist":           signals.get("eb_has_waitlist"),
                "eb_ticket_types":           signals.get("eb_ticket_types"),
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
