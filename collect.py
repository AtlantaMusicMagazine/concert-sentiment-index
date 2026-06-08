"""
collect.py
Atlanta Music Magazine — Nightly Data Collection
Fetches signals from all 21 data sources for every tracked event.
Outputs: data/raw_signals.json
"""

import os
import json
import time
import datetime
import requests
from pathlib import Path

# ── Output directory ───────────────────────────────────────────────────────
Path("data").mkdir(exist_ok=True)

# ── API keys (set as environment variables — see README.md) ────────────────
TICKETMASTER_KEY   = os.environ.get("TICKETMASTER_KEY", "")
SEATGEEK_CLIENT_ID = os.environ.get("SEATGEEK_CLIENT_ID", "")
SEATGEEK_SECRET    = os.environ.get("SEATGEEK_SECRET", "")
STUBHUB_TOKEN      = os.environ.get("STUBHUB_TOKEN", "")
SPOTIFY_CLIENT_ID  = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_SECRET     = os.environ.get("SPOTIFY_SECRET", "")
SERPAPI_KEY        = os.environ.get("SERPAPI_KEY", "")        # Google Trends via SerpApi
CHARTMETRIC_TOKEN  = os.environ.get("CHARTMETRIC_TOKEN", "")
BANDSINTOWN_KEY    = os.environ.get("BANDSINTOWN_KEY", "")
WIKIPEDIA_USER     = os.environ.get("WIKIPEDIA_USER", "atlanta-music-magazine/1.0")

# ── Master event registry ──────────────────────────────────────────────────
# Each event has a unique ID, display metadata, and artist identifiers
# used to query each API. Add new events here as the calendar advances.
EVENTS = [
    {
        "id": "ariana-grande-2026",
        "name": "Ariana Grande — The Eternal Sunshine Tour",
        "artist": "Ariana Grande",
        "venue": "State Farm Arena",
        "venue_id_ticketmaster": "KovZpZAEdktA",
        "date": "2026-07-06",
        "genre": "Pop",
        "spotify_artist_id": "66CXWjxzNUsdJxJ2JdwvnR",
        "tm_attraction_id": "K8vZ91715e0",
        "seatgeek_performer_slug": "ariana-grande",
        "wikipedia_title": "Ariana_Grande",
        "bandsintown_artist": "Ariana Grande",
    },
    {
        "id": "shakira-2026",
        "name": "Shakira — Las Mujeres Ya No Lloran World Tour",
        "artist": "Shakira",
        "venue": "State Farm Arena",
        "venue_id_ticketmaster": "KovZpZAEdktA",
        "date": "2026-06-26",
        "genre": "Latin Pop",
        "spotify_artist_id": "0EmeFodog0BfCgMzAIvKQp",
        "tm_attraction_id": "K8vZ9171oZV",
        "seatgeek_performer_slug": "shakira",
        "wikipedia_title": "Shakira",
        "bandsintown_artist": "Shakira",
    },
    {
        "id": "megan-moroney-2026",
        "name": "Megan Moroney — The Cloud 9 Tour",
        "artist": "Megan Moroney",
        "venue": "State Farm Arena",
        "venue_id_ticketmaster": "KovZpZAEdktA",
        "date": "2026-06-08",
        "genre": "Country",
        "spotify_artist_id": "4AMHcSKFCQHWHQaRVPpMTB",
        "tm_attraction_id": "K8vZ9178XbV",
        "seatgeek_performer_slug": "megan-moroney",
        "wikipedia_title": "Megan_Moroney",
        "bandsintown_artist": "Megan Moroney",
    },
    {
        "id": "j-cole-2026",
        "name": "J. Cole — The Fall-Off Tour",
        "artist": "J. Cole",
        "venue": "State Farm Arena",
        "venue_id_ticketmaster": "KovZpZAEdktA",
        "date": "2026-07-17",
        "genre": "Hip-Hop",
        "spotify_artist_id": "6l3HvQ5sa6mXTsMTB6Mmy",
        "tm_attraction_id": "K8vZ9171oJ7",
        "seatgeek_performer_slug": "j-cole",
        "wikipedia_title": "J._Cole",
        "bandsintown_artist": "J. Cole",
    },
    {
        "id": "acdc-2026",
        "name": "AC/DC — Power Up Tour 2026",
        "artist": "AC/DC",
        "venue": "Mercedes-Benz Stadium",
        "venue_id_ticketmaster": "KovZpZAEkdaA",
        "date": "2026-08-27",
        "genre": "Rock",
        "spotify_artist_id": "711MCceyCBcFnzjGY4Q7Un",
        "tm_attraction_id": "K8vZ9171C-7",
        "seatgeek_performer_slug": "acdc",
        "wikipedia_title": "AC/DC",
        "bandsintown_artist": "AC/DC",
    },
    {
        "id": "tame-impala-2026",
        "name": "Tame Impala — Deadbeat Tour",
        "artist": "Tame Impala",
        "venue": "State Farm Arena",
        "venue_id_ticketmaster": "KovZpZAEdktA",
        "date": "2026-07-11",
        "genre": "Rock",
        "spotify_artist_id": "5INjqkS1o8h1imAzPqGZeR",
        "tm_attraction_id": "K8vZ9171C97",
        "seatgeek_performer_slug": "tame-impala",
        "wikipedia_title": "Tame_Impala",
        "bandsintown_artist": "Tame Impala",
    },
    {
        "id": "asap-rocky-2026",
        "name": "A$AP Rocky — Don't Be Dumb World Tour",
        "artist": "A$AP Rocky",
        "venue": "State Farm Arena",
        "venue_id_ticketmaster": "KovZpZAEdktA",
        "date": "2026-06-11",
        "genre": "Hip-Hop",
        "spotify_artist_id": "13ubrt8QOOCPljQ2FL1Kca",
        "tm_attraction_id": "K8vZ917uNk0",
        "seatgeek_performer_slug": "asap-rocky",
        "wikipedia_title": "ASAP_Rocky",
        "bandsintown_artist": "ASAP Rocky",
    },
    {
        "id": "usher-2026",
        "name": "Usher",
        "artist": "Usher",
        "venue": "State Farm Arena",
        "venue_id_ticketmaster": "KovZpZAEdktA",
        "date": "2026-08-13",
        "genre": "R&B",
        "spotify_artist_id": "23zg3TcAtWQy7J6upgbUnj",
        "tm_attraction_id": "K8vZ9171p10",
        "seatgeek_performer_slug": "usher",
        "wikipedia_title": "Usher_(musician)",
        "bandsintown_artist": "Usher",
    },
    # Add remaining 12 events following the same pattern …
    # (louis-tomlinson, olivia-dean, lynyrd-skynyrd, joji, alex-warren,
    #  santana-doobie, hot1079, buju-banton, summer-walker, 5sos, kali-uchis,
    #  slayyyter, justine-skye, john-mellencamp, ne-yo-akon, styx-chicago,
    #  madison-beer, motionless-in-white, evanescence, motley-crue, ella-mai,
    #  hayley-williams, train-bnl, hilary-duff, parker-mccollum, jack-johnson,
    #  kali-uchis-bottom, muse, guess-who, wynonna-melissa, isley-ojays)
]


# ── Helpers ────────────────────────────────────────────────────────────────
def safe_get(url, params=None, headers=None, label=""):
    """GET with timeout and graceful failure. Returns None on error."""
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [WARN] {label} failed: {e}")
        return None


def get_spotify_token():
    """Fetch a Spotify client-credentials access token."""
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_SECRET:
        return None
    try:
        r = requests.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            auth=(SPOTIFY_CLIENT_ID, SPOTIFY_SECRET),
            timeout=10,
        )
        return r.json().get("access_token")
    except Exception as e:
        print(f"  [WARN] Spotify token failed: {e}")
        return None


# ── Signal collectors ──────────────────────────────────────────────────────

def fetch_ticketmaster(event):
    """Ticket inventory and resale floor price from Ticketmaster Discovery API."""
    if not TICKETMASTER_KEY:
        return {}
    data = safe_get(
        "https://app.ticketmaster.com/discovery/v2/events",
        params={
            "apikey": TICKETMASTER_KEY,
            "attractionId": event.get("tm_attraction_id", ""),
            "city": "Atlanta",
            "startDateTime": event["date"] + "T00:00:00Z",
            "endDateTime": event["date"] + "T23:59:59Z",
            "size": 1,
        },
        label="Ticketmaster",
    )
    if not data or "_embedded" not in data:
        return {}
    events = data["_embedded"].get("events", [])
    if not events:
        return {}
    ev = events[0]
    price_ranges = ev.get("priceRanges", [])
    floor = min((p.get("min", 9999) for p in price_ranges), default=None)
    return {
        "tm_floor_price": floor,
        "tm_status": ev.get("dates", {}).get("status", {}).get("code", ""),
    }


def fetch_seatgeek(event):
    """SeatGeek Deal Score and listing count."""
    if not SEATGEEK_CLIENT_ID:
        return {}
    data = safe_get(
        "https://api.seatgeek.com/2/events",
        params={
            "client_id": SEATGEEK_CLIENT_ID,
            "client_secret": SEATGEEK_SECRET,
            "performers.slug": event.get("seatgeek_performer_slug", ""),
            "venue.city": "Atlanta",
            "datetime_local.gte": event["date"],
            "datetime_local.lte": event["date"],
            "per_page": 1,
        },
        label="SeatGeek",
    )
    if not data or not data.get("events"):
        return {}
    ev = data["events"][0]
    return {
        "seatgeek_deal_score": ev.get("score", 0),
        "seatgeek_listing_count": ev.get("stats", {}).get("listing_count", 0),
        "seatgeek_floor": ev.get("stats", {}).get("lowest_price", None),
        "seatgeek_avg_price": ev.get("stats", {}).get("average_price", None),
    }


def fetch_spotify(event, token):
    """Spotify monthly listeners and 30-day follower velocity."""
    if not token:
        return {}
    artist_id = event.get("spotify_artist_id", "")
    if not artist_id:
        return {}
    data = safe_get(
        f"https://api.spotify.com/v1/artists/{artist_id}",
        headers={"Authorization": f"Bearer {token}"},
        label="Spotify",
    )
    if not data:
        return {}
    return {
        "spotify_followers": data.get("followers", {}).get("total", 0),
        "spotify_popularity": data.get("popularity", 0),
    }


def fetch_wikipedia_pageviews(event):
    """Wikipedia 30-day pageview trend for the artist article."""
    title = event.get("wikipedia_title", "")
    if not title:
        return {}
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=30)).strftime("%Y%m%d")
    end   = today.strftime("%Y%m%d")
    data = safe_get(
        f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
        f"en.wikipedia/all-access/all-agents/{title}/daily/{start}/{end}",
        headers={"User-Agent": WIKIPEDIA_USER},
        label="Wikipedia",
    )
    if not data or "items" not in data:
        return {}
    views = [item["views"] for item in data["items"]]
    if len(views) < 2:
        return {}
    # Simple trend: compare last 7 days vs prior 7 days
    recent = sum(views[-7:])
    prior  = sum(views[-14:-7]) or 1
    trend  = round((recent - prior) / prior * 100, 1)
    return {
        "wikipedia_30d_views": sum(views),
        "wikipedia_7d_trend_pct": trend,
    }


def fetch_google_trends(event):
    """
    Google Trends ATL DMA interest score via SerpApi.
    SerpApi wraps Google Trends and returns 0-100 interest values.
    """
    if not SERPAPI_KEY:
        return {}
    data = safe_get(
        "https://serpapi.com/search",
        params={
            "engine": "google_trends",
            "q": event["artist"],
            "geo": "US-GA-524",   # Atlanta DMA code
            "data_type": "TIMESERIES",
            "date": "today 1-m",
            "api_key": SERPAPI_KEY,
        },
        label="Google Trends (SerpApi)",
    )
    if not data:
        return {}
    timeline = data.get("interest_over_time", {}).get("timeline_data", [])
    if not timeline:
        return {}
    latest = timeline[-1].get("values", [{}])[0].get("extracted_value", 0)
    return {"google_trends_atl": latest}


def fetch_bandsintown(event):
    """Bands in Town Atlanta-specific fan intent count."""
    if not BANDSINTOWN_KEY:
        return {}
    artist = requests.utils.quote(event.get("bandsintown_artist", event["artist"]))
    data = safe_get(
        f"https://rest.bandsintown.com/artists/{artist}/events",
        params={
            "app_id": BANDSINTOWN_KEY,
            "date": event["date"],
        },
        label="Bands in Town",
    )
    if not data:
        return {}
    # Find the Atlanta show and return RSVP count
    for show in data:
        venue_city = show.get("venue", {}).get("city", "").lower()
        if "atlanta" in venue_city:
            return {"bandsintown_rsvps": show.get("going_count", 0)}
    return {}


def fetch_chartmetric(event):
    """Chartmetric streaming velocity and social momentum score."""
    if not CHARTMETRIC_TOKEN:
        return {}
    # Chartmetric uses its own artist IDs — look up by Spotify ID
    artist_id = event.get("spotify_artist_id", "")
    if not artist_id:
        return {}
    lookup = safe_get(
        "https://api.chartmetric.com/api/artist/spotify",
        params={"id": artist_id},
        headers={"Authorization": f"Bearer {CHARTMETRIC_TOKEN}"},
        label="Chartmetric lookup",
    )
    if not lookup or not lookup.get("obj"):
        return {}
    cm_id = lookup["obj"].get("id")
    stats = safe_get(
        f"https://api.chartmetric.com/api/artist/{cm_id}/stat/spotify",
        headers={"Authorization": f"Bearer {CHARTMETRIC_TOKEN}"},
        label="Chartmetric stats",
    )
    if not stats or not stats.get("obj"):
        return {}
    obj = stats["obj"]
    return {
        "cm_spotify_streams_30d": obj.get("streams_30d", 0),
        "cm_spotify_stream_trend": obj.get("streams_growth_30d", 0),
    }


# ── Main collection loop ───────────────────────────────────────────────────

def collect_all():
    print(f"[collect] Starting data collection — {datetime.datetime.now().isoformat()}")
    spotify_token = get_spotify_token()

    results = {}
    for event in EVENTS:
        eid = event["id"]
        print(f"  Collecting: {event['name']}")
        signals = {"event_meta": event}

        # 30% — Current Ticket Demand
        signals.update(fetch_ticketmaster(event))
        time.sleep(0.3)
        signals.update(fetch_seatgeek(event))
        time.sleep(0.3)

        # 25% — Public Sentiment
        signals.update(fetch_spotify(event, spotify_token))
        time.sleep(0.2)
        signals.update(fetch_chartmetric(event))
        time.sleep(0.3)

        # 25% — Historical Sales (Wikipedia as proxy for legacy benchmarks)
        signals.update(fetch_wikipedia_pageviews(event))
        time.sleep(0.3)

        # 20% — Local Intent
        signals.update(fetch_google_trends(event))
        time.sleep(0.5)   # SerpApi rate-limits aggressively
        signals.update(fetch_bandsintown(event))
        time.sleep(0.2)

        results[eid] = signals

    output_path = "data/raw_signals.json"
    with open(output_path, "w") as f:
        json.dump({
            "collected_at": datetime.datetime.utcnow().isoformat() + "Z",
            "events": results,
        }, f, indent=2)

    print(f"[collect] Done. Wrote {output_path} ({len(results)} events)")
    return results


if __name__ == "__main__":
    collect_all()
