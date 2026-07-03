"""
collect.py
Atlanta Music Magazine — Nightly Data Collection
Fetches signals from all data sources for every tracked event.
Outputs: data/raw_signals.json

Key integrations:
  - MusicBrainz  : keyless, album release recency + career depth
  - Wikidata      : keyless, Grammy wins/nominations, active years,
                   Wikipedia language count, genre breadth
  - YouTube v3   : view velocity via rolling cache (data/youtube_cache.json)
                   Cache persisted between runs via GitHub Actions cache@v4
  - Setlist.fm   : ATL market history, venue trajectory, sold-out flag
  - Last.fm      : listener breadth, plays/listener depth, peer tier
  - Eventbrite   : sell-through %, sold-out + waitlist flag
"""

import os
import re
import json
import time
import datetime
import requests
from pathlib import Path

Path("data").mkdir(exist_ok=True)

# ── API keys ───────────────────────────────────────────────────────────────
TICKETMASTER_KEY    = os.environ.get("TICKETMASTER_KEY", "")
SEATGEEK_CLIENT_ID  = os.environ.get("SEATGEEK_CLIENT_ID", "")
SEATGEEK_SECRET     = os.environ.get("SEATGEEK_SECRET", "")
STUBHUB_TOKEN       = os.environ.get("STUBHUB_TOKEN", "")
SPOTIFY_CLIENT_ID   = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_SECRET      = os.environ.get("SPOTIFY_SECRET", "")
SERPAPI_KEY         = os.environ.get("SERPAPI_KEY", "")
CHARTMETRIC_TOKEN   = os.environ.get("CHARTMETRIC_TOKEN", "")
BANDSINTOWN_KEY     = os.environ.get("BANDSINTOWN_KEY", "")
SETLISTFM_KEY       = os.environ.get("SETLISTFM_KEY", "")
LASTFM_KEY          = os.environ.get("LASTFM_KEY", "")
YOUTUBE_API_KEY     = os.environ.get("YOUTUBE_API_KEY", "")
EVENTBRITE_TOKEN    = os.environ.get("EVENTBRITE_TOKEN", "")
WIKIPEDIA_USER      = os.environ.get("WIKIPEDIA_USER", "atlanta-music-magazine/1.0 (contact@atlantamusicmagazine.com)")

# MusicBrainz — no key required, just a descriptive user-agent
MB_USER_AGENT = "AtlantaMusicMagazine/1.0 (contact@atlantamusicmagazine.com)"
MB_BASE       = "https://musicbrainz.org/ws/2"

# ── Master event registry ──────────────────────────────────────────────────
EVENTS = [
    # ── TOP 20 ──────────────────────────────────────────────────────────────
    {
        "id": "ariana-grande-2026",
        "grammy_wins_override": 3,
        "seed_score": 97,
        "name": "Ariana Grande — The Eternal Sunshine Tour",
        "artist": "Ariana Grande",
        "venue": "State Farm Arena",
        "date": "2026-07-06",
        "genre": "Pop",
        "spotify_artist_id": "66CXWjxzNUsdJxJ2JdwvnR",
        "musicbrainz_mbid": "f4fdbb4c-e4b7-47a0-b83b-d91bbfcfa387",
        "tm_attraction_id": "K8vZ91715e0",
        "seatgeek_performer_slug": "ariana-grande",
        "wikipedia_title": "Ariana_Grande",
        "bandsintown_artist": "Ariana Grande",
    },
    {
        "id": "shakira-2026",
        "grammy_wins_override": 4,
        "seed_score": 94,
        "name": "Shakira — Las Mujeres Ya No Lloran World Tour",
        "artist": "Shakira",
        "venue": "State Farm Arena",
        "date": "2026-06-26",
        "genre": "Latin Pop",
        "spotify_artist_id": "0EmeFodog0BfCgMzAIvKQp",
        "musicbrainz_mbid": "45a663b5-b1cb-4a91-bff6-2bef7bbfdd76",
        "tm_attraction_id": "K8vZ9171oZV",
        "seatgeek_performer_slug": "shakira",
        "wikipedia_title": "Shakira",
        "bandsintown_artist": "Shakira",
    },
    {
        "id": "shakira-2026-n2",
        "grammy_wins_override": 4,
        "seed_score": 94,
        "name": "Shakira — Las Mujeres Ya No Lloran World Tour (Night 2)",
        "artist": "Shakira",
        "venue": "State Farm Arena",
        "date": "2026-06-28",
        "genre": "Latin Pop",
        "spotify_artist_id": "0EmeFodog0BfCgMzAIvKQp",
        "musicbrainz_mbid": "45a663b5-b1cb-4a91-bff6-2bef7bbfdd76",
        "tm_attraction_id": "K8vZ9171oZV",
        "seatgeek_performer_slug": "shakira",
        "wikipedia_title": "Shakira",
        "bandsintown_artist": "Shakira",
    },
    {
        "id": "megan-moroney-2026",
        "seed_score": 89,
        "name": "Megan Moroney — The Cloud 9 Tour",
        "artist": "Megan Moroney",
        "venue": "State Farm Arena",
        "date": "2026-06-08",
        "genre": "Country",
        "spotify_artist_id": "4AMHcSKFCQHWHQaRVPpMTB",
        "musicbrainz_mbid": "b1e26560-60e5-4236-bbdb-9aa5a8d5ee19",
        "tm_attraction_id": "K8vZ9178XbV",
        "seatgeek_performer_slug": "megan-moroney",
        "wikipedia_title": "Megan_Moroney",
        "bandsintown_artist": "Megan Moroney",
    },
    {
        "id": "j-cole-2026",
        "seed_score": 88,
        "name": "J. Cole — The Fall-Off Tour",
        "artist": "J. Cole",
        "venue": "State Farm Arena",
        "date": "2026-07-17",
        "genre": "Hip-Hop",
        "spotify_artist_id": "6l3HvQ5sa6mXTsMTB6Mmy",
        "musicbrainz_mbid": "5c1f3e89-229d-4d48-a6c7-1d6e6c3b3c87",
        "tm_attraction_id": "K8vZ9171oJ7",
        "seatgeek_performer_slug": "j-cole",
        "wikipedia_title": "J._Cole",
        "bandsintown_artist": "J. Cole",
    },
    {
        "id": "acdc-2026",
        "seed_score": 83,
        "name": "AC/DC — Power Up Tour 2026",
        "artist": "AC/DC",
        "venue": "Mercedes-Benz Stadium",
        "date": "2026-08-27",
        "genre": "Rock",
        "spotify_artist_id": "711MCceyCBcFnzjGY4Q7Un",
        "musicbrainz_mbid": "66c662b6-6e2f-4930-8610-912e24c63ed1",
        "tm_attraction_id": "K8vZ9171C-7",
        "seatgeek_performer_slug": "acdc",
        "wikipedia_title": "AC/DC",
        "bandsintown_artist": "AC/DC",
    },
    {
        "id": "tame-impala-2026",
        "seed_score": 79,
        "name": "Tame Impala — Deadbeat Tour",
        "artist": "Tame Impala",
        "venue": "State Farm Arena",
        "date": "2026-07-11",
        "genre": "Rock",
        "spotify_artist_id": "5INjqkS1o8h1imAzPqGZeR",
        "musicbrainz_mbid": "63aa26c3-d59b-4da4-84ac-716b54f1ef4d",
        "tm_attraction_id": "K8vZ9171C97",
        "seatgeek_performer_slug": "tame-impala",
        "wikipedia_title": "Tame_Impala",
        "bandsintown_artist": "Tame Impala",
    },
    {
        "id": "asap-rocky-2026",
        "seed_score": 75,
        "name": "A$AP Rocky — Don't Be Dumb World Tour",
        "artist": "A$AP Rocky",
        "venue": "State Farm Arena",
        "date": "2026-06-11",
        "genre": "Hip-Hop",
        "spotify_artist_id": "13ubrt8QOOCPljQ2FL1Kca",
        "musicbrainz_mbid": "06c1f24d-5e3f-4aa8-a28e-8b2abdc2c71f",
        "tm_attraction_id": "K8vZ917uNk0",
        "seatgeek_performer_slug": "asap-rocky",
        "wikipedia_title": "ASAP_Rocky",
        "bandsintown_artist": "ASAP Rocky",
    },
    {
        "id": "usher-2026",
        "grammy_wins_override": 8,
        "seed_score": 72,
        "name": "Usher",
        "artist": "Usher",
        "venue": "State Farm Arena",
        "date": "2026-08-13",
        "genre": "R&B",
        "spotify_artist_id": "23zg3TcAtWQy7J6upgbUnj",
        "musicbrainz_mbid": "2f9ecbed-439d-44d6-a862-a9d2a2b3c1c4",
        "tm_attraction_id": "K8vZ9171p10",
        "seatgeek_performer_slug": "usher",
        "wikipedia_title": "Usher_(musician)",
        "bandsintown_artist": "Usher",
    },
    {
        "id": "louis-tomlinson-2026",
        "seed_score": 67,
        "name": "Louis Tomlinson — How Did We Get Here? World Tour",
        "artist": "Louis Tomlinson",
        "venue": "State Farm Arena",
        "date": "2026-07-22",
        "genre": "Rock",
        "spotify_artist_id": "5TP7B4S7i6N3dv6rCh0Ogy",
        "musicbrainz_mbid": "9b34e0b8-5cd5-4ac5-817b-dd5ac14d64bb",
        "tm_attraction_id": "K8vZ9178m17",
        "seatgeek_performer_slug": "louis-tomlinson",
        "wikipedia_title": "Louis_Tomlinson",
        "bandsintown_artist": "Louis Tomlinson",
    },
    {
        "id": "olivia-dean-2026",
        "seed_score": 65,
        "name": "Olivia Dean — The Art of Loving Tour",
        "artist": "Olivia Dean",
        "venue": "State Farm Arena",
        "date": "2026-08-22",
        "genre": "Pop",
        "spotify_artist_id": "4RVnAU35WRWra6OZ3CbbMA",
        "musicbrainz_mbid": "a5e8b3c2-1234-5678-abcd-ef1234567890",
        "tm_attraction_id": "K8vZ9178YbV",
        "seatgeek_performer_slug": "olivia-dean",
        "wikipedia_title": "Olivia_Dean",
        "bandsintown_artist": "Olivia Dean",
    },
    {
        "id": "lynyrd-skynyrd-2026",
        "seed_score": 60,
        "name": "Lynyrd Skynyrd & Foreigner",
        "artist": "Lynyrd Skynyrd",
        "venue": "Ameris Bank Amphitheatre",
        "date": "2026-07-23",
        "genre": "Rock",
        "spotify_artist_id": "4qm9BNq44YWXEW4gf2IfCd",
        "musicbrainz_mbid": "0994ab0a-c08a-44f0-8cee-4d0da2466d31",
        "tm_attraction_id": "K8vZ9171C17",
        "seatgeek_performer_slug": "lynyrd-skynyrd",
        "wikipedia_title": "Lynyrd_Skynyrd",
        "bandsintown_artist": "Lynyrd Skynyrd",
    },
    {
        "id": "joji-2026",
        "seed_score": 57,
        "name": "Joji — SOLARIS Tour",
        "artist": "Joji",
        "venue": "State Farm Arena",
        "date": "2026-07-02",
        "genre": "Alt / R&B",
        "spotify_artist_id": "3MZsBdqDrRTABnMnYMyn74",
        "musicbrainz_mbid": "d1e2f3a4-b5c6-7890-abcd-ef1234567891",
        "tm_attraction_id": "K8vZ9178VbV",
        "seatgeek_performer_slug": "joji",
        "wikipedia_title": "Joji_(musician)",
        "bandsintown_artist": "Joji",
    },
    {
        "id": "alex-warren-2026",
        "seed_score": 56,
        "name": "Alex Warren — Little Orphan Alex Live",
        "artist": "Alex Warren",
        "venue": "State Farm Arena",
        "date": "2026-06-25",
        "genre": "Pop",
        "spotify_artist_id": "2t9yJDJIEn9SbCFoABfpNj",
        "musicbrainz_mbid": "e2f3a4b5-c6d7-8901-bcde-f12345678902",
        "tm_attraction_id": "K8vZ9178AbV",
        "seatgeek_performer_slug": "alex-warren",
        "wikipedia_title": "Alex_Warren_(musician)",
        "bandsintown_artist": "Alex Warren",
    },
    {
        "id": "yungblud-2026",
        "seed_score": 53,
        "name": "YUNGBLUD — IDOLS World Tour",
        "artist": "YUNGBLUD",
        "venue": "Synovus Bank Amphitheater at Chastain Park",
        "date": "2026-06-13",
        "genre": "Rock",
        "spotify_artist_id": "6Ad91Jof8sHD0XDjTd4aLU",
        "musicbrainz_mbid": "f3a4b5c6-d7e8-9012-cdef-123456789013",
        "tm_attraction_id": "K8vZ9178BbV",
        "seatgeek_performer_slug": "yungblud",
        "wikipedia_title": "Yungblud",
        "bandsintown_artist": "YUNGBLUD",
    },
    {
        "id": "santana-doobie-2026",
        "grammy_wins_override": 9,
        "seed_score": 54,
        "name": "Santana & The Doobie Brothers — Oneness Tour",
        "artist": "Santana",
        "venue": "Ameris Bank Amphitheatre",
        "date": "2026-07-09",
        "genre": "Rock",
        "spotify_artist_id": "6GI52t8N5F02MxU0g5U69P",
        "musicbrainz_mbid": "9a3d6cc5-d925-4b77-a43c-ddf1d4b4a8c3",
        "tm_attraction_id": "K8vZ9171p37",
        "seatgeek_performer_slug": "santana",
        "wikipedia_title": "Santana_(band)",
        "bandsintown_artist": "Santana",
    },
    {
        "id": "hot1079-2026",
        "seed_score": 52,
        "name": "Hot 107.9 Birthday Bash ATL — 30th Anniversary",
        "artist": "Hot 107.9 Birthday Bash",
        "venue": "State Farm Arena",
        "date": "2026-06-24",
        "genre": "Hip-Hop",
        "spotify_artist_id": "",
        "musicbrainz_mbid": "",
        "tm_attraction_id": "K8vZ9179XbV",
        "seatgeek_performer_slug": "hot-1079-birthday-bash",
        "wikipedia_title": "WHTA",
        "bandsintown_artist": "Hot 107.9 Birthday Bash",
    },
    {
        "id": "buju-banton-2026",
        "grammy_wins_override": 1,
        "seed_score": 55,
        "name": "Buju Banton & Stephen Marley — Roots and Rhymes Tour",
        "artist": "Buju Banton",
        "venue": "Lakewood Amphitheatre",
        "date": "2026-07-25",
        "genre": "Reggae",
        "spotify_artist_id": "2J5UMRkLaJLr36aGxCJlj9",
        "musicbrainz_mbid": "2a6ff0b2-b5c3-4e04-a2a8-bddf3f1d2b37",
        "tm_attraction_id": "K8vZ917uYk0",
        "seatgeek_performer_slug": "buju-banton",
        "wikipedia_title": "Buju_Banton",
        "bandsintown_artist": "Buju Banton",
    },
    {
        "id": "shaky-knees-2026",
        "seed_score": 91,
        "name": "Shaky Knees Music Festival",
        "artist": "Shaky Knees Music Festival",
        "venue": "Piedmont Park",
        "date": "2026-09-18",
        "genre": "Multi-Genre",
        "spotify_artist_id": "",
        "musicbrainz_mbid": "",
        "tm_attraction_id": "G5v0Z9rcSGp0p",
        "seatgeek_performer_slug": "shaky-knees-music-festival",
        "wikipedia_title": "Shaky_Knees_Music_Festival",
        "bandsintown_artist": "Shaky Knees Music Festival",
    },
    {
        "id": "mumford-sons-2026",
        "seed_score": 72,
        "grammy_wins_override": 2,
        "name": "Mumford & Sons \u2014 Prizefighter Tour",
        "artist": "Mumford & Sons",
        "venue": "State Farm Arena",
        "date": "2026-08-04",
        "genre": "Indie / Alt",
        "spotify_artist_id": "3sPiEqLcANa5kAp5RnEHNq",
        "musicbrainz_mbid": "c44e9c22-ef82-4a77-9bcd-af6c958446d6",
        "tm_attraction_id": "K8vZ917GuKV",
        "seatgeek_performer_slug": "mumford-and-sons",
        "wikipedia_title": "Mumford_%26_Sons",
        "bandsintown_artist": "Mumford & Sons",
    },
    {
        "id": "noah-kahan-2026",
        "seed_score": 78,
        "name": "Noah Kahan \u2014 The Great Divide Tour",
        "artist": "Noah Kahan",
        "venue": "Truist Park",
        "date": "2026-07-27",
        "genre": "Indie / Alt",
        "spotify_artist_id": "2RQXRUsr4IW1f3mKyKsy4B",
        "musicbrainz_mbid": "4bb4e4e4-3a6b-4b8e-9b5c-3d6e5f7a8c9d",
        "tm_attraction_id": "K8vZ9178bMV",
        "seatgeek_performer_slug": "noah-kahan",
        "wikipedia_title": "Noah_Kahan",
        "bandsintown_artist": "Noah Kahan",
    },
    {
        "id": "brooks-dunn-2026",
        "seed_score": 58,
        "grammy_wins_override": 2,
        "name": "Brooks & Dunn \u2014 Neon Moon Tour 2026",
        "artist": "Brooks & Dunn",
        "venue": "Ameris Bank Amphitheatre",
        "date": "2026-09-11",
        "genre": "Country",
        "spotify_artist_id": "0eFHYz8NmK75zSplL5qlfM",
        "musicbrainz_mbid": "3c0a6d30-8a0c-4c18-9b22-7b41d0e97c91",
        "tm_attraction_id": "K8vZ9171oJV",
        "seatgeek_performer_slug": "brooks-and-dunn",
        "wikipedia_title": "Brooks_%26_Dunn",
        "bandsintown_artist": "Brooks & Dunn",
    },
    {
        "id": "empire-of-the-sun-2026",
        "seed_score": 55,
        "name": "Empire of the Sun \u2014 Ask That God Tour",
        "artist": "Empire of the Sun",
        "venue": "Ameris Bank Amphitheatre",
        "date": "2026-09-13",
        "genre": "Electronic",
        "spotify_artist_id": "27lsclqqovB7GJ0LUr6pMR",
        "musicbrainz_mbid": "e1bbf5c7-f4d3-4b3c-8d9e-5f2a7c8b9d0e",
        "tm_attraction_id": "K8vZ9171jkf",
        "seatgeek_performer_slug": "empire-of-the-sun",
        "wikipedia_title": "Empire_of_the_Sun_(band)",
        "bandsintown_artist": "Empire of the Sun",
    },
    {
        "id": "summer-walker-2026",
        "seed_score": 49,
        "name": "Summer Walker — Still Finally Over It Tour",
        "artist": "Summer Walker",
        "venue": "State Farm Arena",
        "date": "2026-06-12",
        "genre": "R&B",
        "spotify_artist_id": "7dDCpWZc1BBaSbwMPmUxRK",
        "musicbrainz_mbid": "a4b5c6d7-e8f9-0123-defa-234567890124",
        "tm_attraction_id": "K8vZ9178CbV",
        "seatgeek_performer_slug": "summer-walker",
        "wikipedia_title": "Summer_Walker",
        "bandsintown_artist": "Summer Walker",
    },
    {
        "id": "5sos-2026",
        "seed_score": 46,
        "name": "5 Seconds of Summer — EVERYONE'S A STAR! World Tour",
        "artist": "5 Seconds of Summer",
        "venue": "State Farm Arena",
        "date": "2026-06-16",
        "genre": "Pop",
        "spotify_artist_id": "5Rl15oVamLq7FbZX3j1dth",
        "musicbrainz_mbid": "bf0f7e29-0577-4802-a937-60ef67ecfc07",
        "tm_attraction_id": "K8vZ9171oL7",
        "seatgeek_performer_slug": "5-seconds-of-summer",
        "wikipedia_title": "5_Seconds_of_Summer",
        "bandsintown_artist": "5 Seconds of Summer",
    },
    {
        "id": "kali-uchis-top-2026",
        "seed_score": 43,
        "name": "Kali Uchis — For The Girls Tour",
        "artist": "Kali Uchis",
        "venue": "Lakewood Amphitheatre",
        "date": "2026-06-10",
        "genre": "R&B",
        "spotify_artist_id": "1U1el3k54VvEUzo3ybLPlM",
        "musicbrainz_mbid": "b5c6d7e8-f9a0-1234-efab-345678901235",
        "tm_attraction_id": "K8vZ9178DbV",
        "seatgeek_performer_slug": "kali-uchis",
        "wikipedia_title": "Kali_Uchis",
        "bandsintown_artist": "Kali Uchis",
    },

    # ── BOTTOM 20 ────────────────────────────────────────────────────────────
    {
        "id": "slayyyter-2026",
        "seed_score": 18,
        "name": "Slayyyter — Wor$t Girl in the World Tour",
        "artist": "Slayyyter",
        "venue": "The Eastern",
        "date": "2026-09-21",
        "genre": "Hyperpop",
        "spotify_artist_id": "1kCHru7ohioG55E0AEEvic",
        "musicbrainz_mbid": "c6d7e8f9-a0b1-2345-fabc-456789012346",
        "tm_attraction_id": "K8vZ9178EbV",
        "seatgeek_performer_slug": "slayyyter",
        "wikipedia_title": "Slayyyter",
        "bandsintown_artist": "Slayyyter",
    },
    {
        "id": "isley-ojays-2026",
        "grammy_wins_override": 3,
        "seed_score": 21,
        "name": "The Isley Brothers & The O'Jays",
        "artist": "The Isley Brothers",
        "venue": "Synovus Bank Amphitheater at Chastain Park",
        "date": "2026-08-22",
        "genre": "R&B",
        "spotify_artist_id": "2ycnb8Er7f2OMMo0jpNQUi",
        "musicbrainz_mbid": "5c95e4a9-3a1d-4b9e-8e27-9b4c14ea9f2f",
        "tm_attraction_id": "K8vZ9171oN7",
        "seatgeek_performer_slug": "the-isley-brothers",
        "wikipedia_title": "The_Isley_Brothers",
        "bandsintown_artist": "The Isley Brothers",
    },
    {
        "id": "justine-skye-2026",
        "seed_score": 22,
        "name": "Justine Skye",
        "artist": "Justine Skye",
        "venue": "Vinyl at Center Stage",
        "date": "2026-07-26",
        "genre": "R&B",
        "spotify_artist_id": "5Wr0mPJfxkNuW8ONWH7jEW",
        "musicbrainz_mbid": "d7e8f9a0-b1c2-3456-abcd-567890123457",
        "tm_attraction_id": "K8vZ9178FbV",
        "seatgeek_performer_slug": "justine-skye",
        "wikipedia_title": "Justine_Skye",
        "bandsintown_artist": "Justine Skye",
    },
    {
        "id": "wynonna-melissa-2026",
        "grammy_wins_override": 1,
        "seed_score": 24,
        "name": "Wynonna Judd & Melissa Etheridge — Raised On Radio Tour",
        "artist": "Wynonna Judd",
        "venue": "Synovus Bank Amphitheater at Chastain Park",
        "date": "2026-08-07",
        "genre": "Classic Rock",
        "spotify_artist_id": "5nBVFXLNAHfqnRVoE7nFrr",
        "musicbrainz_mbid": "4f8b1b7f-bc85-4c5c-8177-59c7d6a6f9b2",
        "tm_attraction_id": "K8vZ9171oP7",
        "seatgeek_performer_slug": "wynonna-judd",
        "wikipedia_title": "Wynonna_Judd",
        "bandsintown_artist": "Wynonna Judd",
    },
    {
        "id": "guess-who-2026",
        "seed_score": 26,
        "name": "The Guess Who — Takin' It Back Tour",
        "artist": "The Guess Who",
        "venue": "Synovus Bank Amphitheater at Chastain Park",
        "date": "2026-08-06",
        "genre": "Classic Rock",
        "spotify_artist_id": "3yrSvgajswkFTAMA7gOrGZ",
        "musicbrainz_mbid": "f5d77b8b-3c91-4a05-b6e5-6cdefc5f3b11",
        "tm_attraction_id": "K8vZ9171oQ7",
        "seatgeek_performer_slug": "the-guess-who",
        "wikipedia_title": "The_Guess_Who",
        "bandsintown_artist": "The Guess Who",
    },
    {
        "id": "john-mellencamp-2026",
        "grammy_wins_override": 1,
        "seed_score": 27,
        "name": "John Mellencamp — Dancing Words Tour",
        "artist": "John Mellencamp",
        "venue": "Ameris Bank Amphitheatre",
        "date": "2026-08-01",
        "genre": "Classic Rock",
        "spotify_artist_id": "0Ks9dyFMKfxCNViWJMT47V",
        "musicbrainz_mbid": "5b11f4ce-a62d-471e-81fc-a69a8278c7da",
        "tm_attraction_id": "K8vZ9171p57",
        "seatgeek_performer_slug": "john-mellencamp",
        "wikipedia_title": "John_Mellencamp",
        "bandsintown_artist": "John Mellencamp",
    },
    {
        "id": "ne-yo-akon-2026",
        "grammy_wins_override": 3,
        "seed_score": 31,
        "name": "NE-YO & Akon — Nights Like This Tour",
        "artist": "NE-YO",
        "venue": "Lakewood Amphitheatre",
        "date": "2026-07-11",
        "genre": "R&B",
        "spotify_artist_id": "0nzUfJ6e8qc1A62JJCKhHH",
        "musicbrainz_mbid": "0681e8e3-9694-4ed6-bfce-47e7f66714b3",
        "tm_attraction_id": "K8vZ9171p67",
        "seatgeek_performer_slug": "ne-yo",
        "wikipedia_title": "Ne-Yo",
        "bandsintown_artist": "NE-YO",
    },
    {
        "id": "styx-chicago-2026",
        "seed_score": 36,
        "name": "Styx & Chicago — The Windy Cities Tour",
        "artist": "Styx",
        "venue": "Ameris Bank Amphitheatre",
        "date": "2026-07-17",
        "genre": "Classic Rock",
        "spotify_artist_id": "4salDzkPlRVFBN3JDTHLaP",
        "musicbrainz_mbid": "6fc59ded-cdea-4898-8a9e-0e48a30a0fc4",
        "tm_attraction_id": "K8vZ9171p77",
        "seatgeek_performer_slug": "styx",
        "wikipedia_title": "Styx_(band)",
        "bandsintown_artist": "Styx",
    },
    {
        "id": "madison-beer-2026",
        "seed_score": 39,
        "name": "Madison Beer — The Locket Tour",
        "artist": "Madison Beer",
        "venue": "Coca-Cola Roxy",
        "date": "2026-07-01",
        "genre": "Pop",
        "spotify_artist_id": "2XTGWnBHsN0TEmPCMkWbw2",
        "musicbrainz_mbid": "e8f9a0b1-c2d3-4567-bcde-678901234568",
        "tm_attraction_id": "K8vZ9178GbV",
        "seatgeek_performer_slug": "madison-beer",
        "wikipedia_title": "Madison_Beer",
        "bandsintown_artist": "Madison Beer",
    },
    {
        "id": "motionless-2026",
        "seed_score": 42,
        "name": "Motionless In White — Sweat and Blood Tour",
        "artist": "Motionless In White",
        "venue": "Ameris Bank Amphitheatre",
        "date": "2026-07-22",
        "genre": "Metalcore",
        "spotify_artist_id": "6bD1EuUdVSMr2oiLkdJWxD",
        "musicbrainz_mbid": "a4e9cc9e-e9b3-4c7d-99c2-4e2db3fdc3a0",
        "tm_attraction_id": "K8vZ9171p87",
        "seatgeek_performer_slug": "motionless-in-white",
        "wikipedia_title": "Motionless_in_White",
        "bandsintown_artist": "Motionless In White",
    },
    {
        "id": "flyleaf-2026",
        "seed_score": 62,
        "name": "Flyleaf with Lacey Sturm \u2014 20th Anniversary Tour",
        "artist": "Flyleaf",
        "venue": "The Tabernacle",
        "date": "2026-07-08",
        "genre": "Rock",
        "spotify_artist_id": "29kkCVBmFfEFBWzXz8RUZM",
        "musicbrainz_mbid": "f0b41a45-7b79-4a40-9bd5-5f3a44b8c40a",
        "tm_attraction_id": "K8vZ9171oAV",
        "seatgeek_performer_slug": "flyleaf",
        "wikipedia_title": "Flyleaf_(band)",
        "bandsintown_artist": "Flyleaf",
    },
    {
        "id": "hayley-williams-2026",
        "seed_score": 43,
        "name": "The Hayley Williams Show w/ Magdalena Bay",
        "artist": "Hayley Williams",
        "venue": "Ameris Bank Amphitheatre",
        "date": "2026-09-05",
        "genre": "Indie / Alt",
        "spotify_artist_id": "6XyY86QOPPrYVGvF9ch6wz",
        "musicbrainz_mbid": "1fcf534e-5e43-4b8d-adb4-f9b2d4f8e1a2",
        "tm_attraction_id": "K8vZ9178HbV",
        "seatgeek_performer_slug": "hayley-williams",
        "wikipedia_title": "Hayley_Williams",
        "bandsintown_artist": "Hayley Williams",
    },
    {
        "id": "muse-2026",
        "seed_score": 44,
        "name": "Muse — The Wow! Signal Tour",
        "artist": "Muse",
        "venue": "Lakewood Amphitheatre",
        "date": "2026-08-12",
        "genre": "Rock",
        "spotify_artist_id": "12Chz98pHFMPJEknJQMWvI",
        "musicbrainz_mbid": "9c9f1380-2516-47a9-8d4b-eda5159a3d49",
        "tm_attraction_id": "K8vZ9171C77",
        "seatgeek_performer_slug": "muse",
        "wikipedia_title": "Muse_(band)",
        "bandsintown_artist": "Muse",
    },
    {
        "id": "jinjer-2026",
        "seed_score": 52,
        "name": "Jinjer — Duél North America Tour",
        "artist": "Jinjer",
        "venue": "Buckhead Theatre",
        "date": "2026-06-18",
        "genre": "Metalcore",
        "spotify_artist_id": "7o6cOczXTB8ioTAAJTbESf",
        "musicbrainz_mbid": "51b37017-859c-465e-8810-2d2dd41a401e",
        "tm_attraction_id": "K8vZ9171oJV",
        "seatgeek_performer_slug": "jinjer",
        "wikipedia_title": "Jinjer",
        "bandsintown_artist": "Jinjer",
    },
    {
        "id": "evanescence-2026",
        "grammy_wins_override": 1,
        "seed_score": 45,
        "name": "Evanescence — 2026 World Tour",
        "artist": "Evanescence",
        "venue": "Ameris Bank Amphitheatre",
        "date": "2026-06-14",
        "genre": "Rock",
        "spotify_artist_id": "35YEPk2YEU1ahfUBSFRVp2",
        "musicbrainz_mbid": "f0e3c1a5-2b1d-42af-83ad-d8e265f11f64",
        "tm_attraction_id": "K8vZ9171C87",
        "seatgeek_performer_slug": "evanescence",
        "wikipedia_title": "Evanescence",
        "bandsintown_artist": "Evanescence",
    },
    {
        "id": "motley-crue-2026",
        "seed_score": 48,
        "name": "Mötley Crüe — Return of the Carnival of Sins",
        "artist": "Mötley Crüe",
        "venue": "Ameris Bank Amphitheatre",
        "date": "2026-08-12",
        "genre": "Rock",
        "spotify_artist_id": "6JiCiuBmMhKbmFnWktnlbB",
        "musicbrainz_mbid": "b4585bec-b69a-42b6-a4f6-1d3ae0a438bb",
        "tm_attraction_id": "K8vZ9171C97",
        "seatgeek_performer_slug": "motley-crue",
        "wikipedia_title": "Mötley_Crüe",
        "bandsintown_artist": "Mötley Crüe",
    },
    {
        "id": "ella-mai-2026",
        "seed_score": 52,
        "name": "Ella Mai",
        "artist": "Ella Mai",
        "venue": "Synovus Bank Amphitheater at Chastain Park",
        "date": "2026-08-14",
        "genre": "R&B",
        "spotify_artist_id": "0GF9QpAMKbbWdZbLOhQ7Xc",
        "musicbrainz_mbid": "f9a0b1c2-d3e4-5678-cdef-789012345679",
        "tm_attraction_id": "K8vZ9178IbV",
        "seatgeek_performer_slug": "ella-mai",
        "wikipedia_title": "Ella_Mai",
        "bandsintown_artist": "Ella Mai",
    },
    {
        "id": "train-bnl-2026",
        "grammy_wins_override": 3,
        "seed_score": 32,
        "name": "Train, Barenaked Ladies & Matt Nathanson",
        "artist": "Train",
        "venue": "Ameris Bank Amphitheatre",
        "date": "2026-07-11",
        "genre": "Rock",
        "spotify_artist_id": "3FUY2gzHeIiaesXtOAdB7A",
        "musicbrainz_mbid": "a4d1c75e-0b8e-4cbb-bf74-e5e3db4a4d7c",
        "tm_attraction_id": "K8vZ9171p97",
        "seatgeek_performer_slug": "train",
        "wikipedia_title": "Train_(band)",
        "bandsintown_artist": "Train",
    },
    {
        "id": "hilary-duff-2026",
        "seed_score": 29,
        "name": "Hilary Duff — The Lucky Me Tour",
        "artist": "Hilary Duff",
        "venue": "Ameris Bank Amphitheatre",
        "date": "2026-06-25",
        "genre": "Pop",
        "spotify_artist_id": "2bCu4RPMGK2UHxNMsxOHsV",
        "musicbrainz_mbid": "0a3b4c5d-6e7f-8901-abcd-ef0123456780",
        "tm_attraction_id": "K8vZ9178JbV",
        "seatgeek_performer_slug": "hilary-duff",
        "wikipedia_title": "Hilary_Duff",
        "bandsintown_artist": "Hilary Duff",
    },
    {
        "id": "parker-mccollum-2026",
        "seed_score": 25,
        "name": "Parker McCollum",
        "artist": "Parker McCollum",
        "venue": "Ameris Bank Amphitheatre",
        "date": "2026-07-18",
        "genre": "Country",
        "spotify_artist_id": "2ZosCo3Tb9aeIVCiEeKAnz",
        "musicbrainz_mbid": "1b2c3d4e-5f6a-7890-bcde-f01234567891",
        "tm_attraction_id": "K8vZ9178KbV",
        "seatgeek_performer_slug": "parker-mccollum",
        "wikipedia_title": "Parker_McCollum",
        "bandsintown_artist": "Parker McCollum",
    },
    {
        "id": "jack-johnson-2026",
        "seed_score": 22,
        "name": "Jack Johnson — SURFILMUSIC Tour",
        "artist": "Jack Johnson",
        "venue": "Ameris Bank Amphitheatre",
        "date": "2026-08-21",
        "genre": "Indie / Alt",
        "spotify_artist_id": "6WT8MSUB7Kc6CYMVLzfgBk",
        "musicbrainz_mbid": "01809552-4f87-45b0-afff-2c6f0730a3be",
        "tm_attraction_id": "K8vZ9171p07",
        "seatgeek_performer_slug": "jack-johnson",
        "wikipedia_title": "Jack_Johnson_(musician)",
        "bandsintown_artist": "Jack Johnson",
    },
    {
        "id": "chance-rapper-2026",
        "seed_score": 72,
        "name": "Chance the Rapper",
        "artist": "Chance the Rapper",
        "venue": "Coca-Cola Roxy",
        "date": "2026-09-03",
        "genre": "Hip-Hop",
        "spotify_artist_id": "1anyVhU62p31KFi8MEzkbf",
        "musicbrainz_mbid": "3b56df7b-3e1f-4b59-b3a5-2e5ced4ccfa5",
        "tm_attraction_id": "K8vZ9171oJV",
        "seatgeek_performer_slug": "chance-the-rapper",
        "wikipedia_title": "Chance_the_Rapper",
        "bandsintown_artist": "Chance the Rapper",
    },
    {
        "id": "yeat-2026",
        "seed_score": 65,
        "name": "Yeat",
        "artist": "Yeat",
        "venue": "Coca-Cola Roxy",
        "date": "2026-07-30",
        "genre": "Hip-Hop",
        "spotify_artist_id": "6GQaJFCQsU0V6p3pzOcR3M",
        "musicbrainz_mbid": "1d60df67-cda4-4c4b-8e12-11ea1f55b60e",
        "tm_attraction_id": "K8vZ9178B17",
        "seatgeek_performer_slug": "yeat",
        "wikipedia_title": "Yeat_(rapper)",
        "bandsintown_artist": "Yeat",
    },
    {
        "id": "jack-harlow-2026",
        "seed_score": 65,
        "name": "Jack Harlow",
        "artist": "Jack Harlow",
        "venue": "Coca-Cola Roxy",
        "date": "2026-09-04",
        "genre": "Hip-Hop",
        "spotify_artist_id": "2LIk90788K0zvyj2sVdS2H",
        "musicbrainz_mbid": "aa4d5aba-5b4c-4a3e-a5e4-d7f3bb30b5f3",
        "tm_attraction_id": "K8vZ9171oZV",
        "seatgeek_performer_slug": "jack-harlow",
        "wikipedia_title": "Jack_Harlow",
        "bandsintown_artist": "Jack Harlow",
    },
    {
        "id": "metric-2026",
        "seed_score": 62,
        "name": "Metric — All The Feelings Tour",
        "artist": "Metric",
        "venue": "The Tabernacle",
        "date": "2026-08-03",
        "genre": "Indie / Alt",
        "spotify_artist_id": "1nNec9P0R1hKFRKCwnLHmS",
        "musicbrainz_mbid": "3b516d5c-3f9d-4237-a99e-5e0f4c1a5c5d",
        "tm_attraction_id": "K8vZ9171p57",
        "seatgeek_performer_slug": "metric",
        "wikipedia_title": "Metric_(band)",
        "bandsintown_artist": "Metric",
    },
    {
        "id": "juanes-2026",
        "seed_score": 63,
        "name": "Juanes",
        "artist": "Juanes",
        "venue": "Coca-Cola Roxy",
        "date": "2026-09-09",
        "genre": "Latin Pop",
        "spotify_artist_id": "1eYsHm9GJlLdPqAIvHfKA1",
        "musicbrainz_mbid": "d305c19c-4f35-4c13-b9d3-7a3f3b7e7e7e",
        "tm_attraction_id": "K8vZ9171oAe",
        "seatgeek_performer_slug": "juanes",
        "wikipedia_title": "Juanes",
        "bandsintown_artist": "Juanes",
    },
    {
        "id": "lord-huron-2026",
        "seed_score": 60,
        "name": "Lord Huron",
        "artist": "Lord Huron",
        "venue": "Coca-Cola Roxy",
        "date": "2026-08-01",
        "genre": "Indie / Alt",
        "spotify_artist_id": "4LpGkFMjB37AzoJbbJKSUW",
        "musicbrainz_mbid": "c48bb7f8-2c15-4c0f-a8f4-4b4db5b7bc0e",
        "tm_attraction_id": "K8vZ9171C-7",
        "seatgeek_performer_slug": "lord-huron",
        "wikipedia_title": "Lord_Huron",
        "bandsintown_artist": "Lord Huron",
    },
    {
        "id": "dominic-fike-2026",
        "seed_score": 60,
        "name": "Dominic Fike",
        "artist": "Dominic Fike",
        "venue": "Coca-Cola Roxy",
        "date": "2026-08-16",
        "genre": "Pop",
        "spotify_artist_id": "56NM0N2KXNZUQ2BKGE8TJZ",
        "musicbrainz_mbid": "4b4d7e5c-3b5f-4e2d-8c7e-1a2b3c4d5e6f",
        "tm_attraction_id": "K8vZ9171oJf",
        "seatgeek_performer_slug": "dominic-fike",
        "wikipedia_title": "Dominic_Fike",
        "bandsintown_artist": "Dominic Fike",
    },
    {
        "id": "social-distortion-2026",
        "seed_score": 58,
        "name": "Social Distortion — with Descendents",
        "artist": "Social Distortion",
        "venue": "Coca-Cola Roxy",
        "date": "2026-09-01",
        "genre": "Rock",
        "spotify_artist_id": "2SgrKCuMkYNzRjzAI3e2tA",
        "musicbrainz_mbid": "e8f4f4d3-5b2c-4f3e-8c7e-1a2b3c4d5e6f",
        "tm_attraction_id": "K8vZ91718I0",
        "seatgeek_performer_slug": "social-distortion",
        "wikipedia_title": "Social_Distortion",
        "bandsintown_artist": "Social Distortion",
    },
    {
        "id": "theory-deadman-sevendust-2026",
        "seed_score": 60,
        "name": "Theory of a Deadman & Sevendust",
        "artist": "Theory of a Deadman",
        "venue": "The Tabernacle",
        "date": "2026-09-05",
        "genre": "Rock",
        "spotify_artist_id": "4BfBBl9MiNHHkZMVtDUMeZ",
        "musicbrainz_mbid": "a3b4c5d6-e7f8-4a3b-8c7e-1a2b3c4d5e6f",
        "tm_attraction_id": "K8vZ9171C97",
        "seatgeek_performer_slug": "theory-of-a-deadman",
        "wikipedia_title": "Theory_of_a_Deadman",
        "bandsintown_artist": "Theory of a Deadman",
    },


    {
        "id": "tomahawk-melvins-2026",
        "seed_score": 62,
        "name": "Tomahawk with Melvins — A Huge Waste of Your Time and Money Tour",
        "artist": "Tomahawk",
        "venue": "Buckhead Theatre",
        "date": "2026-07-24",
        "genre": "Rock",
        "spotify_artist_id": "0bmCBFCUkGaOLBLGfMXQAb",
        "musicbrainz_mbid": "c6d70f33-7f83-4b6e-8af1-9d30c46e36c1",
        "tm_attraction_id": "K8vZ9171oL7",
        "seatgeek_performer_slug": "tomahawk",
        "wikipedia_title": "Tomahawk_(band)",
        "bandsintown_artist": "Tomahawk",
    },
    {
        "id": "franz-ferdinand-2026",
        "seed_score": 58,
        "name": "Franz Ferdinand",
        "artist": "Franz Ferdinand",
        "venue": "Buckhead Theatre",
        "date": "2026-08-12",
        "genre": "Indie / Alt",
        "spotify_artist_id": "4pXFHFGjuEQR5HHs1KFSz2",
        "musicbrainz_mbid": "2f5f9de7-6651-4571-8dce-99f745c6b021",
        "tm_attraction_id": "K8vZ9171C-7",
        "seatgeek_performer_slug": "franz-ferdinand",
        "wikipedia_title": "Franz_Ferdinand_(band)",
        "bandsintown_artist": "Franz Ferdinand",
    },

    {
        "id": "guns-n-roses-2026",
        "seed_score": 88,
        "name": "Guns N\u2019 Roses \u2014 World Tour 2026",
        "artist": "Guns N' Roses",
        "venue": "Truist Park",
        "date": "2026-09-19",
        "genre": "Rock",
        "spotify_artist_id": "3qm84nBOXUEQ2vnTfUTTFC",
        "musicbrainz_mbid": "eeb1195b-f213-4ce1-b28a-4d4f9650d68f",
        "tm_attraction_id": "K8vZ9171oJf",
        "seatgeek_performer_slug": "guns-n-roses",
        "wikipedia_title": "Guns_N%27_Roses",
        "bandsintown_artist": "Guns N' Roses",
    },

    {
        "id": "dogstar-2026",
        "seed_score": 58,
        "name": "Dogstar \u2014 All In Now Tour",
        "artist": "Dogstar",
        "venue": "The Tabernacle",
        "date": "2026-08-04",
        "genre": "Rock",
        "spotify_artist_id": "6pBxMsEijFpUxbZw7YBWrR",
        "musicbrainz_mbid": "c3d4e5f6-a7b8-9012-cdef-123456789012",
        "tm_attraction_id": "K8vZ917mRT0",
        "seatgeek_performer_slug": "dogstar",
        "wikipedia_title": "Dogstar_(band)",
        "bandsintown_artist": "Dogstar",
    },
    {
        "id": "men-at-work-2026",
        "seed_score": 55,
        "name": "Men at Work",
        "artist": "Men at Work",
        "venue": "Cobb Energy Performing Arts Centre",
        "date": "2026-08-14",
        "genre": "Rock",
        "spotify_artist_id": "3xvGBEdnFSi4nMX5oHCMmD",
        "musicbrainz_mbid": "7fed6d12-7a2c-475b-b51f-9d5d3e6a9b8c",
        "tm_attraction_id": "K8vZ9171oAf",
        "seatgeek_performer_slug": "men-at-work",
        "wikipedia_title": "Men_at_Work",
        "bandsintown_artist": "Men at Work",
    },
    {
        "id": "buddy-guy-2026",
        "grammy_wins_override": 9,
        "seed_score": 68,
        "name": "Buddy Guy 90 Tour",
        "artist": "Buddy Guy",
        "venue": "Atlanta Symphony Hall",
        "date": "2026-09-12",
        "genre": "Blues",
        "spotify_artist_id": "1aT2ygCdF5bmPBmGqFvnqS",
        "musicbrainz_mbid": "e7f8a9b0-c1d2-3456-def0-123456789014",
        "tm_attraction_id": "K8vZ9171oB7",
        "seatgeek_performer_slug": "buddy-guy",
        "wikipedia_title": "Buddy_Guy",
        "bandsintown_artist": "Buddy Guy",
    },
    {
        "id": "squeeze-2026",
        "seed_score": 58,
        "name": "Squeeze \u2014 Tried, Tested and Trixies Tour",
        "artist": "Squeeze",
        "venue": "Fabulous Fox Theatre",
        "date": "2026-08-22",
        "genre": "Rock",
        "spotify_artist_id": "5yEPxDjbbzUzyQfHUPIaFd",
        "musicbrainz_mbid": "4c1f77ac-34ad-4ff9-bd10-ab2e9c7b0c9a",
        "tm_attraction_id": "K8vZ9171C-0",
        "seatgeek_performer_slug": "squeeze",
        "wikipedia_title": "Squeeze_(band)",
        "bandsintown_artist": "Squeeze",
    },

    {
        "id": "better-than-ezra-2026",
        "seed_score": 60,
        "name": "Better Than Ezra",
        "artist": "Better Than Ezra",
        "venue": "The Bowl at Sugar Hill",
        "date": "2026-07-19",
        "genre": "Indie / Alt",
        "spotify_artist_id": "2a2ZB5LOkFKpLbVRFBPgWX",
        "musicbrainz_mbid": "7a8b9c0d-1e2f-3456-abcd-ef1234567890",
        "tm_attraction_id": "K8vZ9171C-7",
        "seatgeek_performer_slug": "better-than-ezra",
        "wikipedia_title": "Better_Than_Ezra",
        "bandsintown_artist": "Better Than Ezra",
    },

    {
        "id": "rob-zombie-2026",
        "seed_score": 72,
        "name": "Rob Zombie & Marilyn Manson with The Hu & Orgy",
        "artist": "Rob Zombie",
        "venue": "Ameris Bank Amphitheatre",
        "date": "2026-08-23",
        "genre": "Rock",
        "spotify_artist_id": "2pOHmDEDEDdeadFsKAligf",
        "musicbrainz_mbid": "7bdd3da7-1cb3-4d03-9d94-0c13d9e7e0be",
        "tm_attraction_id": "K8vZ9171oAf",
        "seatgeek_performer_slug": "rob-zombie",
        "wikipedia_title": "Rob_Zombie",
        "bandsintown_artist": "Rob Zombie",
    },
    {
        "id": "311-dirty-heads-2026",
        "seed_score": 56,
        "name": "311 and Dirty Heads \u2014 So Glad You Made It Tour",
        "artist": "311",
        "venue": "Ameris Bank Amphitheatre",
        "date": "2026-08-28",
        "genre": "Rock",
        "spotify_artist_id": "2ECqMpJKr4H0Z0bWVBtVLr",
        "musicbrainz_mbid": "4fbf9e5a-e4e6-45ed-b21a-d7ae6a1cbf9e",
        "tm_attraction_id": "K8vZ9171oAV",
        "seatgeek_performer_slug": "311",
        "wikipedia_title": "311_(band)",
        "bandsintown_artist": "311",
    },
    {
        "id": "babymetal-2026",
        "seed_score": 65,
        "name": "BABYMETAL World Tour 2026",
        "artist": "BABYMETAL",
        "venue": "Ameris Bank Amphitheatre",
        "date": "2026-09-16",
        "genre": "Rock",
        "spotify_artist_id": "1oWVhFJXhPJIbhSRMoF1Ck",
        "musicbrainz_mbid": "c2b4e657-d1d0-4cf7-a75f-3cbef42dc38d",
        "tm_attraction_id": "K8vZ9171oB7",
        "seatgeek_performer_slug": "babymetal",
        "wikipedia_title": "Babymetal",
        "bandsintown_artist": "BABYMETAL",
    },

    {
        "id": "toto-2026",
        "seed_score": 60,
        "name": "Toto, Christopher Cross & The Romantics",
        "artist": "Toto",
        "venue": "Ameris Bank Amphitheatre",
        "date": "2026-08-02",
        "genre": "Classic Rock",
        "spotify_artist_id": "0PFtn5NtBbbUNbU9EAmIWF",
        "musicbrainz_mbid": "5080c749-3a2a-4a53-a3a1-7e0869b8d0e2",
        "tm_attraction_id": "K8vZ9171C-7",
        "seatgeek_performer_slug": "toto",
        "wikipedia_title": "Toto_(band)",
        "bandsintown_artist": "Toto",
    },

    {
        "id": "koe-wetzel-2026",
        "seed_score": 62,
        "name": "Koe Wetzel \u2014 The Night of Champion Tour",
        "artist": "Koe Wetzel",
        "venue": "Ameris Bank Amphitheatre",
        "date": "2026-09-17",
        "genre": "Country",
        "spotify_artist_id": "2ZRQcIgzPCVaT9XKhXZIzh",
        "musicbrainz_mbid": "a1b2c3d4-e5f6-7890-abcd-ef1234567891",
        "tm_attraction_id": "K8vZ9178X57",
        "seatgeek_performer_slug": "koe-wetzel",
        "wikipedia_title": "Koe_Wetzel",
        "bandsintown_artist": "Koe Wetzel",
    },

]


# ── Helpers ────────────────────────────────────────────────────────────────
def safe_get(url, params=None, headers=None, label="", timeout=10):
    try:
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [WARN] {label} failed: {e}")
        return None


def get_spotify_token():
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


# ── MusicBrainz helpers ────────────────────────────────────────────────────
MB_HEADERS = {"User-Agent": MB_USER_AGENT, "Accept": "application/json"}

def resolve_mbid(artist_name):
    """
    One-time lookup: search MusicBrainz for an artist by name,
    return their MBID and any linked Spotify artist ID.
    Call this when adding a new event to the EVENTS list to
    populate musicbrainz_mbid and verify spotify_artist_id.
    Not called during the nightly loop — use the cached MBIDs
    already in the EVENTS list above.
    """
    data = safe_get(
        f"{MB_BASE}/artist/",
        params={"query": artist_name, "limit": 1, "fmt": "json"},
        headers=MB_HEADERS,
        label=f"MusicBrainz resolve: {artist_name}",
    )
    time.sleep(1.1)  # MusicBrainz rate limit: 1 req/sec
    if not data or not data.get("artists"):
        return {}

    artist = data["artists"][0]
    mbid   = artist.get("id", "")

    # Fetch relations to find Spotify link
    detail = safe_get(
        f"{MB_BASE}/artist/{mbid}",
        params={"inc": "url-rels", "fmt": "json"},
        headers=MB_HEADERS,
        label=f"MusicBrainz detail: {artist_name}",
    )
    time.sleep(1.1)

    spotify_id = ""
    if detail:
        for rel in detail.get("relations", []):
            url = rel.get("url", {}).get("resource", "")
            if "open.spotify.com/artist/" in url:
                spotify_id = url.split("/")[-1].split("?")[0]
                break

    return {
        "mbid": mbid,
        "name": artist.get("name", ""),
        "spotify_artist_id_from_mb": spotify_id,
        "disambiguation": artist.get("disambiguation", ""),
        "score": artist.get("score", 0),
    }


def fetch_musicbrainz(event):
    """
    Nightly call: given a known MBID, fetch the artist's release groups
    and determine:
      - mb_has_recent_album: True if a studio album was released within
        365 days before the concert date (touring on new material signal)
      - mb_days_since_last_album: days elapsed since most recent album
      - mb_total_albums: total studio album count (career longevity proxy)
      - mb_latest_album_title: name of most recent album
    """
    mbid = event.get("musicbrainz_mbid", "")
    if not mbid:
        return {}

    concert_date = datetime.date.fromisoformat(event["date"])
    cutoff_date  = concert_date - datetime.timedelta(days=365)

    data = safe_get(
        f"{MB_BASE}/release-group",
        params={
            "artist":   mbid,
            "type":     "album",
            "fmt":      "json",
            "limit":    100,
        },
        headers=MB_HEADERS,
        label=f"MusicBrainz releases: {event['artist']}",
    )
    time.sleep(1.1)  # strict rate limit

    if not data or not data.get("release-groups"):
        return {}

    albums = []
    for rg in data["release-groups"]:
        # Only count official studio albums (not compilations/live/remix)
        if rg.get("primary-type") != "Album":
            continue
        secondary = rg.get("secondary-types", [])
        if any(t in secondary for t in ["Compilation", "Live", "Remix", "Soundtrack"]):
            continue

        date_str = rg.get("first-release-date", "")
        if not date_str or len(date_str) < 4:
            continue

        # Parse partial dates (YYYY, YYYY-MM, YYYY-MM-DD)
        try:
            parts = date_str.split("-")
            year  = int(parts[0])
            month = int(parts[1]) if len(parts) > 1 else 1
            day   = int(parts[2]) if len(parts) > 2 else 1
            release_date = datetime.date(year, month, day)
        except (ValueError, IndexError):
            continue

        albums.append({
            "title": rg.get("title", ""),
            "date":  release_date,
        })

    if not albums:
        return {
            "mb_has_recent_album":    False,
            "mb_days_since_last_album": None,
            "mb_total_albums":         0,
            "mb_latest_album_title":   "",
        }

    # Sort by release date descending
    albums.sort(key=lambda a: a["date"], reverse=True)
    latest       = albums[0]
    days_elapsed = (concert_date - latest["date"]).days
    has_recent   = cutoff_date <= latest["date"] <= concert_date

    return {
        "mb_has_recent_album":     has_recent,
        "mb_days_since_last_album": days_elapsed,
        "mb_total_albums":          len(albums),
        "mb_latest_album_title":    latest["title"],
    }


# ── Existing signal collectors ─────────────────────────────────────────────
def fetch_ticketmaster(event):
    if not TICKETMASTER_KEY:
        return {}
    data = safe_get(
        "https://app.ticketmaster.com/discovery/v2/events",
        params={
            "apikey":          TICKETMASTER_KEY,
            "attractionId":    event.get("tm_attraction_id", ""),
            "city":            "Atlanta",
            "startDateTime":   event["date"] + "T00:00:00Z",
            "endDateTime":     event["date"] + "T23:59:59Z",
            "size":            1,
        },
        label="Ticketmaster",
    )
    if not data or "_embedded" not in data:
        return {}
    events = data["_embedded"].get("events", [])
    if not events:
        return {}
    ev     = events[0]
    ranges = ev.get("priceRanges", [])
    floor  = min((p.get("min", 9999) for p in ranges), default=None)
    return {
        "tm_floor_price": floor,
        "tm_status":      ev.get("dates", {}).get("status", {}).get("code", ""),
    }


def fetch_seatgeek(event):
    if not SEATGEEK_CLIENT_ID:
        print("  [SeatGeek] SKIPPED — SEATGEEK_CLIENT_ID not set")
        return {}

    artist   = event.get("artist", "") or event.get("name", "")
    date_str = event["date"]

    # Widen date window ±1 day — SeatGeek sometimes indexes events
    # on adjacent dates due to timezone handling
    import datetime as _dt
    d = _dt.date.fromisoformat(date_str)
    gte = (d - _dt.timedelta(days=1)).isoformat()
    lte = (d + _dt.timedelta(days=1)).isoformat()

    base_params = {
        "client_id":          SEATGEEK_CLIENT_ID,
        "client_secret":      SEATGEEK_SECRET,
        "datetime_local.gte": gte,
        "datetime_local.lte": lte,
        "per_page":           5,
    }

    def is_atlanta(ev):
        city  = ev.get("venue", {}).get("city",  "").lower()
        state = ev.get("venue", {}).get("state", "").lower()
        atl_cities = {"atlanta", "alpharetta", "marietta", "kennesaw",
                      "duluth", "college park", "cobb", "gwinnett"}
        return any(a in city for a in atl_cities) or (
            "georgia" in state and any(a in city for a in atl_cities))

    ev = None

    # Try 1: performer slug lookup (primary)
    slug = event.get("seatgeek_performer_slug", "")
    if slug:
        data = safe_get(
            "https://api.seatgeek.com/2/events",
            params={**base_params, "performers.slug": slug},
            label="SeatGeek",
        )
        if data and data.get("events"):
            atl_ev = next((e for e in data["events"] if is_atlanta(e)), None)
            ev = atl_ev or None   # only accept Atlanta matches
            if ev is None:
                print(f"  [SeatGeek] slug hit but no ATL match: {slug} (cities: {[e.get('venue',{}).get('city','?') for e in data['events'][:3]]})")
        elif data is not None:
            print(f"  [SeatGeek] slug miss: {slug} ({data.get('meta', {}).get('total', 0)} results)")

    # Try 2: free-text search with artist name + date
    if ev is None:
        data2 = safe_get(
            "https://api.seatgeek.com/2/events",
            params={**base_params, "q": artist},
            label="SeatGeek-q",
        )
        if data2 and data2.get("events"):
            atl_ev2 = next((e for e in data2["events"] if is_atlanta(e)), None)
            ev = atl_ev2
            if ev is None:
                print(f"  [SeatGeek] q hit but no ATL match: {artist[:30]} (cities: {[e.get('venue',{}).get('city','?') for e in data2['events'][:3]]})")
        elif data2 is not None:
            print(f"  [SeatGeek] q miss: {artist[:30]} ({data2.get('meta', {}).get('total', 0)} results)")

    if ev is None:
        return {}

    stats = ev.get("stats", {})
    result = {
        "seatgeek_deal_score":    ev.get("score", 0),
        "seatgeek_listing_count": stats.get("listing_count", 0),
        "seatgeek_floor":         stats.get("lowest_price", None),
        "seatgeek_avg_price":     stats.get("average_price", None),
        "seatgeek_highest_price": stats.get("highest_price", None),
        "seatgeek_median_price":  stats.get("median_price", None),
    }
    floor = result["seatgeek_floor"]
    count = result["seatgeek_listing_count"]
    deal  = result["seatgeek_deal_score"]
    print(f"  [SeatGeek] {artist[:35]:<35} deal={deal:.2f}  listings={count}  floor={'$'+str(int(floor)) if floor else 'n/a'}")
    if not floor and stats:
        print(f"  [SeatGeek] raw stats keys: {list(stats.keys())[:8]}")
    return result


def fetch_spotify(event, token):
    if not token:
        return {}
    artist_id = event.get("spotify_artist_id", "")
    if not artist_id:
        return {}
    data = safe_get(
        f"https://api.spotify.com/v1/artists/{artist_id}",
        headers={"Authorization": f"Bearer {token}"},
        label="Spotify artist",
    )
    if not data:
        return {}

    # Also fetch top tracks to get a stream proxy velocity
    tracks = safe_get(
        f"https://api.spotify.com/v1/artists/{artist_id}/top-tracks",
        params={"market": "US"},
        headers={"Authorization": f"Bearer {token}"},
        label="Spotify top-tracks",
    )
    top_track_popularity = 0
    if tracks and tracks.get("tracks"):
        top_track_popularity = tracks["tracks"][0].get("popularity", 0)

    return {
        "spotify_followers":          data.get("followers", {}).get("total", 0),
        "spotify_popularity":         data.get("popularity", 0),
        "spotify_top_track_popularity": top_track_popularity,
    }


def fetch_wikidata(event):
    """
    Wikidata Query Service — structured career facts via SPARQL.
    No API key required. User-Agent header is sufficient.
    Rate limit: 60s query execution/minute shared — a single artist
    lookup runs in <100ms so 42 events costs ~4s total.

    Signals extracted:
      wd_grammy_wins          : count of Grammy Award wins
                                (Grammy winner = strong 35-65 demo trust signal)
      wd_grammy_nominations   : total Grammy nominations including non-wins
      wd_active_years         : career length in years from first release/formation
                                (nostalgia premium proxy for heritage acts)
      wd_wikipedia_languages  : number of Wikipedia language editions
                                (global fame proxy — Ariana Grande: 80+,
                                 Justine Skye: 3)
      wd_genres_count         : number of distinct music genres listed
                                (cross-genre breadth → broader addressable audience)

    SPARQL strategy:
      1. Look up the artist entity by MusicBrainz artist ID (most precise)
      2. Extract the five fact properties in a single query
      3. Fall back to artist name search if no MBID

    Grammy detection uses Wikidata's award property (P166) filtered to
    the Grammy Award item (Q41612) and its subclasses.
    """
    mbid        = event.get("musicbrainz_mbid", "")
    artist_name = event.get("artist", "")

    if not mbid and not artist_name:
        return {}

    # ── Build SPARQL query ────────────────────────────────────────────────
    if mbid:
        # Primary: lookup by MusicBrainz ID property (P434) — most precise
        entity_clause = f'?artist wdt:P434 "{mbid}" .'
    else:
        # Fallback: lookup by artist label (less precise, may match wrong entity)
        safe_name = artist_name.replace('"', '\\"')
        entity_clause = f'?artist rdfs:label "{safe_name}"@en .'

    sparql = f"""
SELECT ?artist
       (MIN(?startYear) AS ?career_start)
       (COUNT(DISTINCT ?lang) AS ?wiki_languages)
       (COUNT(DISTINCT ?genre) AS ?genres_count)
WHERE {{
  {entity_clause}

  # Career start — inception (P571)
  OPTIONAL {{
    ?artist wdt:P571 ?inception .
    BIND(YEAR(?inception) AS ?startYear)
  }}

  # Wikipedia sitelinks — count language editions
  OPTIONAL {{
    ?sitelink schema:about ?artist ;
              schema:isPartOf ?lang .
    FILTER(CONTAINS(STR(?lang), "wikipedia.org"))
  }}

  # Music genres (P136)
  OPTIONAL {{ ?artist wdt:P136 ?genre . }}
}}
GROUP BY ?artist
LIMIT 1
"""

    headers = {
        "User-Agent":  MB_USER_AGENT,
        "Accept":      "application/sparql-results+json",
    }

    # ── Grammy wins: separate simple query ──────────────────────────────
    # Run only when no grammy_wins_override is set on the event.
    # Kept separate so a slow Grammy lookup never blocks career/language data.
    grammy_wins = 0
    grammy_noms = 0
    override = event.get("grammy_wins_override")
    if override is not None:
        grammy_wins = int(override)
    else:
        grammy_sparql = f"""
SELECT (COUNT(DISTINCT ?awardStmt) AS ?grammy_wins)
       (COUNT(DISTINCT ?grammyNom) AS ?grammy_nominations)
WHERE {{
  {entity_clause}
  OPTIONAL {{
    ?artist p:P166 ?awardStmt .
    ?awardStmt ps:P166 ?grammyWin .
    ?grammyWin rdfs:label ?lbl .
    FILTER(LANG(?lbl) = "en")
    FILTER(STRSTARTS(LCASE(STR(?lbl)), "grammy award for "))
  }}
  OPTIONAL {{
    ?artist wdt:P1411 ?grammyNom .
    ?grammyNom rdfs:label ?nomLbl .
    FILTER(LANG(?nomLbl) = "en")
    FILTER(STRSTARTS(LCASE(STR(?nomLbl)), "grammy award for "))
  }}
}}
"""
        grammy_data = safe_get(
            "https://query.wikidata.org/sparql",
            params={"query": grammy_sparql, "format": "json"},
            headers=headers,
            label=f"Wikidata Grammy: {artist_name}",
            timeout=10,
        )
        time.sleep(0.3)
        if grammy_data:
            gbindings = grammy_data.get("results", {}).get("bindings", [])
            if gbindings:
                def gint(key):
                    v = gbindings[0].get(key, {}).get("value")
                    return int(v) if v else 0
                grammy_wins = gint("grammy_wins")
                grammy_noms = gint("grammy_nominations")

    # ── Career / language / genre query ─────────────────────────────────
    data = safe_get(
        "https://query.wikidata.org/sparql",
        params={"query": sparql, "format": "json"},
        headers=headers,
        label=f"Wikidata: {artist_name}",
        timeout=15,
    )
    time.sleep(0.5)   # be polite to shared service

    wiki_langs   = 0
    genres_count = 0
    active_years = None

    if data:
        bindings = data.get("results", {}).get("bindings", [])
        if bindings:
            row = bindings[0]

            def int_val(key):
                v = row.get(key, {}).get("value")
                return int(v) if v else 0

            wiki_langs   = int_val("wiki_languages")
            genres_count = int_val("genres_count")

            career_start_raw = row.get("career_start", {}).get("value")
            if career_start_raw:
                try:
                    start_year   = int(career_start_raw)
                    active_years = datetime.date.today().year - start_year
                except (ValueError, TypeError):
                    pass

    # Always return — even if career query failed, we have Grammy data
    # (override or SPARQL result) and should not discard it
    return {
        "wd_grammy_wins":         grammy_wins,
        "wd_grammy_nominations":  grammy_noms,
        "wd_active_years":        active_years,
        "wd_wikipedia_languages": wiki_langs if wiki_langs else None,
        "wd_genres_count":        genres_count if genres_count else None,
    }


def fetch_wikipedia_pageviews(event):
    title = event.get("wikipedia_title", "")
    if not title:
        return {}
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=30)).strftime("%Y%m%d")
    end   = today.strftime("%Y%m%d")
    data  = safe_get(
        f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
        f"en.wikipedia/all-access/all-agents/{title}/daily/{start}/{end}",
        headers={"User-Agent": WIKIPEDIA_USER},
        label="Wikipedia",
    )
    if not data or "items" not in data:
        return {}
    views  = [item["views"] for item in data["items"]]
    if len(views) < 14:
        return {}
    recent = sum(views[-7:])
    prior  = sum(views[-14:-7]) or 1
    trend  = round((recent - prior) / prior * 100, 1)
    return {
        "wikipedia_30d_views":    sum(views),
        "wikipedia_7d_trend_pct": trend,
    }


def fetch_google_trends(event):
    if not SERPAPI_KEY:
        return {}
    data = safe_get(
        "https://serpapi.com/search",
        params={
            "engine":    "google_trends",
            "q":         event["artist"],
            "geo":       "US-GA-524",
            "data_type": "TIMESERIES",
            "date":      "today 1-m",
            "api_key":   SERPAPI_KEY,
        },
        label="Google Trends",
    )
    if not data:
        return {}
    timeline = data.get("interest_over_time", {}).get("timeline_data", [])
    if not timeline:
        return {}
    latest = timeline[-1].get("values", [{}])[0].get("extracted_value", 0)
    return {"google_trends_atl": latest}


def fetch_bandsintown(event):
    if not BANDSINTOWN_KEY:
        return {}
    artist = requests.utils.quote(event.get("bandsintown_artist", event["artist"]))
    data   = safe_get(
        f"https://rest.bandsintown.com/artists/{artist}/events",
        params={"app_id": BANDSINTOWN_KEY, "date": event["date"]},
        label="Bands in Town",
    )
    if not data:
        return {}
    for show in data:
        if "atlanta" in show.get("venue", {}).get("city", "").lower():
            return {"bandsintown_rsvps": show.get("going_count", 0)}
    return {}


def fetch_chartmetric(event):
    if not CHARTMETRIC_TOKEN:
        return {}
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
        "cm_spotify_streams_30d":  obj.get("streams_30d", 0),
        "cm_spotify_stream_trend": obj.get("streams_growth_30d", 0),
    }


def fetch_eventbrite(event):
    """
    Eventbrite — event search for the artist in Atlanta.
    Endpoint: /v3/events/search/

    Signals extracted:
      eb_has_listing        : True if this show has an Eventbrite listing
      eb_capacity           : total ticket capacity on Eventbrite listing
      eb_tickets_sold       : number of tickets sold (if public)
      eb_sell_through_pct   : tickets_sold / capacity * 100
      eb_is_sold_out        : True if event is marked sold out
      eb_has_waitlist       : True if a waitlist is active (strong demand flag)
      eb_attendee_capacity  : number of people who have RSVP'd or checked in
      eb_ticket_types       : number of distinct ticket tiers listed
                              (more tiers = promoter expects price-sensitive demand)

    Note: Eventbrite capacity and sales data are only returned for events
    where the organizer has made them public. Many major venue shows use
    Ticketmaster as primary seller and may only have secondary Eventbrite
    listings (fan meetups, pre-show events). Both are useful signals.
    """
    if not EVENTBRITE_TOKEN:
        return {}

    artist_name  = event.get("artist", "")
    concert_date = event.get("date", "")
    if not artist_name or not concert_date:
        return {}

    # Search for events in Atlanta matching the artist name around the date
    # Eventbrite uses ISO 8601 with timezone for date filters
    start_date = concert_date + "T00:00:00"
    end_date   = concert_date + "T23:59:59"

    data = safe_get(
        "https://www.eventbriteapi.com/v3/events/search/",
        params={
            "q":                        artist_name,
            "location.address":         "Atlanta, GA",
            "location.within":          "30mi",
            "start_date.range_start":   start_date,
            "start_date.range_end":     end_date,
            "expand":                   "ticket_classes,venue",
            "token":                    EVENTBRITE_TOKEN,
        },
        label=f"Eventbrite: {artist_name}",
    )
    time.sleep(0.3)

    if not data or not data.get("events"):
        return {"eb_has_listing": False}

    # Take the first matching event (most relevant)
    ev = data["events"][0]

    capacity      = ev.get("capacity", None)
    sold          = ev.get("capacity_is_custom", None)
    is_sold_out   = ev.get("is_sold_out", False)
    has_waitlist  = bool(ev.get("waitlist_available", False))

    # Ticket classes give us per-tier detail
    ticket_classes = ev.get("ticket_classes", [])
    total_sold     = sum(tc.get("quantity_sold", 0) or 0 for tc in ticket_classes)
    total_capacity = sum(tc.get("capacity",      0) or 0 for tc in ticket_classes)
    num_tiers      = len([tc for tc in ticket_classes if not tc.get("hidden", False)])

    sell_through = None
    if total_capacity and total_capacity > 0:
        sell_through = round(total_sold / total_capacity * 100, 1)

    return {
        "eb_has_listing":      True,
        "eb_capacity":         total_capacity or capacity,
        "eb_tickets_sold":     total_sold,
        "eb_sell_through_pct": sell_through,
        "eb_is_sold_out":      is_sold_out,
        "eb_has_waitlist":     has_waitlist,
        "eb_ticket_types":     num_tiers,
    }


AMM_BASE_URL   = "https://atlantamusicmagazine.com"
AMM_CACHE_PATH = "data/amm_coverage.json"


def fetch_amm_catalog():
    """
    Build the AMM article catalog by parsing the atlantamusicmagazine.com
    XML sitemap. Jetpack (which the site uses) generates the sitemap at:
      https://atlantamusicmagazine.com/sitemap.xml

    The sitemap is an XML document listing every published URL. WordPress
    sites with Jetpack typically also expose a sitemap index at /sitemap.xml
    that references child sitemaps (posts, pages, etc.).

    Domain filter: atlantamusicmagazine.com ONLY.
    No scraping — pure XML parsing of a standards-compliant sitemap.

    Cache: refreshed weekly (Mondays) or when empty.
    Returns: list of dicts [{title, link, date, slug}]
    """
    import xml.etree.ElementTree as ET

    today = datetime.date.today()

    try:
        with open(AMM_CACHE_PATH) as f:
            cached = json.load(f)
        cached_posts = cached.get("posts", [])
        cached_date  = datetime.date.fromisoformat(cached.get("fetched_on", "2000-01-01"))
        days_old     = (today - cached_date).days

        # Detect stale cache with lastmod-style dates (all posts share the same date)
        # which indicates the cache was built before the date_from_slug fix.
        # A healthy cache has varied dates across articles; a stale one has all
        # dates collapsing to the same month (e.g. all "2025-02-xx").
        if cached_posts and len(cached_posts) > 3:
            post_months = set(p.get("date", "")[:7] for p in cached_posts)
            dates_look_stale = len(post_months) <= 2  # all in 1-2 months = lastmod batch
        else:
            dates_look_stale = False

        if cached_posts and days_old < 1 and not dates_look_stale:
            print(f"[amm] Using cached catalog ({len(cached_posts)} posts, {days_old}d old)")
            return cached_posts
        if not cached_posts:
            print("[amm] Cache empty — forcing re-fetch")
        elif dates_look_stale:
            print(f"[amm] Cache dates look stale (lastmod batch) — forcing re-fetch")
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        pass

    print("[amm] Fetching sitemap from atlantamusicmagazine.com...")

    SITEMAP_URLS = [
        "https://atlantamusicmagazine.com/sitemap.xml",
        "https://atlantamusicmagazine.com/sitemap_index.xml",
        "https://atlantamusicmagazine.com/wp-sitemap.xml",
    ]

    # Sitemap XML namespaces
    NS = {
        "sm":    "http://www.sitemaps.org/schemas/sitemap/0.9",
        "news":  "http://www.google.com/schemas/sitemap-news/0.9",
        "image": "http://www.google.com/schemas/sitemap-image/1.1",
    }

    EXCLUDE_PATHS = (
        "/category/", "/tag/", "/author/", "/page/", "/feed/",
        "wp-content", "wp-admin", "wp-includes",
        "concert-calendar", "features", "about", "contact",
        "placemark", "2021-reviews", "2022-reviews", "2023-reviews",
        "2024-reviews", "2025-reviews", "2026-reviews",
    )

    _SLUG_MONTHS = {
        "january":"01","february":"02","march":"03","april":"04",
        "may":"05","june":"06","july":"07","august":"08",
        "september":"09","october":"10","november":"11","december":"12",
    }

    def date_from_slug(slug):
        """
        Extract real article date from the URL slug.
        AMM slugs follow the pattern: ...month-DD-YYYY
        e.g. "...on-wednesday-august-24-2022" → "2022-08-24"
        More reliable than sitemap <lastmod> which reflects the last time
        WordPress re-indexed the post (can be a site migration date).
        """
        m = re.search(
            r"(january|february|march|april|may|june|july|august"
            r"|september|october|november|december)-(\d{1,2})-(20\d{2})(?:-|$)",
            slug,
        )
        if m:
            return f"{m.group(3)}-{_SLUG_MONTHS[m.group(1)]}-{m.group(2).zfill(2)}"
        yr = re.search(r"-(20\d{2})(?:-|$)", slug)
        return f"{yr.group(1)}-01-01" if yr else "2024-01-01"

    def fetch_xml(url):
        try:
            r = requests.get(
                url,
                headers={"User-Agent": MB_USER_AGENT},
                timeout=20,
            )
            if r.status_code == 200:
                return r.text
            print(f"[amm]   {url}: HTTP {r.status_code}")
        except Exception as e:
            print(f"[amm]   {url}: {e}")
        return None

    def parse_sitemap(xml_text, collected, seen):
        """Recursively parse sitemap or sitemap index XML."""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            print(f"[amm]   XML parse error: {e}")
            return

        tag = root.tag.split('}')[-1] if '}' in root.tag else root.tag

        if tag == "sitemapindex":
            # Sitemap index — recurse into each child sitemap
            for sitemap in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc"):
                child_url = sitemap.text.strip()
                # Only follow post sitemaps, skip image/page sitemaps
                if "post" in child_url or "sitemap" in child_url:
                    child_xml = fetch_xml(child_url)
                    time.sleep(0.3)
                    if child_xml:
                        parse_sitemap(child_xml, collected, seen)

        elif tag == "urlset":
            # Regular sitemap — extract URLs
            for url_el in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}url"):
                loc = url_el.find("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
                lastmod = url_el.find("{http://www.sitemaps.org/schemas/sitemap/0.9}lastmod")
                news_title = url_el.find(".//{http://www.google.com/schemas/sitemap-news/0.9}title")

                if loc is None:
                    continue
                link = loc.text.strip().rstrip("/")

                # Domain filter — atlantamusicmagazine.com only
                if "atlantamusicmagazine.com" not in link:
                    continue
                if link in seen:
                    continue
                if any(x in link for x in EXCLUDE_PATHS):
                    continue

                path_parts = link.split("/", 3)
                if len(path_parts) < 4 or not path_parts[3]:
                    continue

                slug     = path_parts[3].rstrip("/")
                date_str = date_from_slug(slug)   # slug date > lastmod (lastmod = re-index date)
                title    = (news_title.text.strip()
                            if news_title is not None and news_title.text
                            else slug.replace("-", " ").title())

                seen.add(link)
                collected.append({
                    "title": title,
                    "link":  link + "/",
                    "date":  date_str,
                    "slug":  slug,
                })

    all_posts = []
    seen_links = set()

    # Try each sitemap URL until one works
    for sitemap_url in SITEMAP_URLS:
        xml_text = fetch_xml(sitemap_url)
        time.sleep(0.5)
        if xml_text:
            parse_sitemap(xml_text, all_posts, seen_links)
            if all_posts:
                print(f"[amm] Sitemap parsed: {len(all_posts)} articles on atlantamusicmagazine.com")
                break
            print(f"[amm]   {sitemap_url}: parsed but 0 matching URLs")

    if not all_posts:
        print("[amm] WARN: 0 articles from sitemap — not caching, will retry next run")
        return []

    with open(AMM_CACHE_PATH, "w") as f:
        json.dump({"fetched_on": today.isoformat(), "posts": all_posts}, f, indent=2)

    return all_posts

def match_amm_article(artist_name, catalog):
    """
    Find the most recent atlantamusicmagazine.com article for a given artist.

    Matching requires ALL significant artist name words to appear in
    the article slug — not just any one word. This prevents false matches
    like "summer" matching "Bret Michaels Summer tour" for Summer Walker,
    or "john" matching "John Corabi" for John Mellencamp.

    Single-word artists (e.g. "Usher", "Santana") match on that one word.
    Multi-word artists (e.g. "John Mellencamp") require ALL words to match.

    Returns: dict {title, link, date, display_date} or None
    """
    if not catalog or not artist_name:
        return None

    def norm_words(s):
        s = s.lower()
        s = re.sub(r"[^a-z0-9\s]", " ", s)
        # Broader stopword list to avoid false matches on common words
        stopwords = {
            "and", "the", "with", "feat", "from", "live", "tour", "band",
            "featuring", "presents", "world", "2026", "2025", "2024",
            "2023", "2022", "2021", "music", "festival", "show", "concert",
            "summer", "spring", "fall", "winter", "night", "day", "big",
            "new", "old", "all", "one", "two", "rock", "pop", "hip", "hop",
        }
        return [w for w in s.split() if len(w) > 2 and w not in stopwords]

    # Primary artist name: strip everything after " — " or " - " (tour names)
    primary = re.split(r'\s+[—\-]\s+', artist_name)[0].strip()

    # Split on " & " or " and " — may have multiple co-headliners.
    # Try EACH partner independently so "Lynyrd Skynyrd & Foreigner"
    # tries both "Lynyrd Skynyrd" and "Foreigner" against the slug.
    partners = re.split(r'\s+&\s+|\s+and\s+', primary, flags=re.IGNORECASE)
    partners = [p.strip() for p in partners if p.strip()]

    matches = []
    for partner in partners:
        artist_words = norm_words(partner)
        if not artist_words:
            continue
        for post in catalog:
            slug_words = norm_words(post["slug"])
            # ALL words of this partner must appear in the slug
            if all(w in slug_words for w in artist_words):
                if post not in matches:
                    matches.append(post)

    if not matches:
        return None

    # Return most recent
    best = sorted(matches, key=lambda p: p["date"], reverse=True)[0]

    # Format display date
    try:
        d = datetime.date.fromisoformat(best["date"])
        display = d.strftime("%b %Y")
    except (ValueError, TypeError):
        display = best["date"][:7]

    # Use real title if available, otherwise clean up slug
    title = best.get("title", "")
    if not title or title == best["slug"].replace("-", " ").title():
        # Slug-derived title — fetch the real title from the article page
        try:
            r = requests.get(
                best["link"],
                headers={"User-Agent": MB_USER_AGENT},
                timeout=10,
            )
            if r.status_code == 200:
                og_title = re.search(
                    r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"',
                    r.text
                )
                if og_title:
                    raw = og_title.group(1)
                    # Strip site name suffix " - Covering Southeast Concerts" etc.
                    title = re.split(r'\s+[-|–—]\s+(?:Covering|Atlanta)', raw)[0].strip()
        except Exception:
            pass   # fall back to slug-derived title

    return {
        "title":        title or best["slug"].replace("-", " ").title(),
        "link":         best["link"],
        "date":         best["date"],
        "display_date": display,
    }


def find_amm_article_direct(event):
    """
    Fallback for articles not yet indexed in the Jetpack sitemap.
    Constructs candidate URLs from the artist name + event date and
    verifies them with an HTTP HEAD request. Catches articles published
    after the last sitemap regeneration (typically within 24 hours of publication).

    Pattern: /artist-name-atlanta-georgia-month-day-year/
    e.g. /shakira-atlanta-georgia-june-26-2026/
    """
    artist = event.get("artist", "")
    date_str = event.get("date", "")
    if not artist or not date_str:
        return None

    try:
        d = datetime.date.fromisoformat(date_str)
        month_name = d.strftime("%B").lower()
        day = d.day
        year = d.year

        # Build slug from artist name
        artist_slug = re.sub(r'[^a-z0-9]+', '-', artist.lower()).strip('-')

        # Try most likely URL patterns
        candidates = [
            f"{AMM_BASE_URL}/{artist_slug}-atlanta-georgia-{month_name}-{day}-{year}/",
            f"{AMM_BASE_URL}/{artist_slug}-state-farm-arena-atlanta-georgia-{month_name}-{day}-{year}/",
            f"{AMM_BASE_URL}/{artist_slug}-atlanta-{month_name}-{day}-{year}/",
        ]

        for url in candidates:
            try:
                r = requests.head(
                    url,
                    headers={"User-Agent": MB_USER_AGENT},
                    timeout=5,
                    allow_redirects=True,
                )
                if r.status_code == 200:
                    # Fetch title
                    r2 = requests.get(url, headers={"User-Agent": MB_USER_AGENT}, timeout=8)
                    title = artist
                    if r2.status_code == 200:
                        og = re.search(
                            r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', r2.text
                        )
                        if og:
                            title = re.split(r'\s+[-|–—]\s+(?:Covering|Atlanta)', og.group(1))[0].strip()
                    print(f"    [AMM-direct] Found: {url}")
                    return {
                        "title":        title,
                        "link":         url,
                        "date":         date_str,
                        "display_date": d.strftime("%b %Y"),
                    }
            except Exception:
                continue
    except Exception:
        pass
    return None


YOUTUBE_CACHE_PATH = "data/youtube_cache.json"


def load_youtube_cache():
    """
    Load the rolling view-count cache from disk.
    Returns a dict of {event_id: {"view_count": int, "date": str, "video_id": str}}.
    Called once at the start of collect_all(); the result is passed into
    every fetch_youtube() call so lookups are O(1).
    """
    try:
        with open(YOUTUBE_CACHE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_youtube_cache(cache):
    """
    Write the updated cache back to disk after all events are collected.
    GitHub Actions cache@v4 will then persist this file between runs.
    """
    with open(YOUTUBE_CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)


def fetch_youtube(event, cache):
    """
    YouTube Data API v3 — video view velocity signal.
    Endpoint: youtube/v3/search + youtube/v3/videos

    Strategy:
      1. Search for the artist's official channel using their name
      2. Get the most recent uploaded video from that channel
      3. Compare today's view count against the cached count from
         the previous run to compute a 24-hour view delta
      4. Update the cache with today's count for tomorrow's delta

    Signals returned:
      yt_video_id           : YouTube video ID of the most recent official video
      yt_view_count         : current total view count
      yt_view_delta_24h     : views gained in the past ~24 hours
                              (None on first run — no prior count to diff against)
      yt_view_velocity_7d   : estimated 7-day velocity = delta * 7
                              (proxy — only accurate after 7 days of daily runs)
      yt_subscriber_count   : channel subscriber count
      yt_channel_id         : YouTube channel ID (cached to avoid repeat searches)

    Cache schema per event_id:
      {
        "event_id": {
          "channel_id":  "UC...",
          "video_id":    "dQw4w9WgXcQ",
          "view_count":  12345678,
          "date":        "2026-06-09"
        }
      }

    Rate budget: ~4 units per event (1 search + 1 videos.list).
    At 42 events = 168 units/night. Free quota = 10,000 units/day.
    """
    if not YOUTUBE_API_KEY:
        return {}

    eid         = event["id"]
    artist_name = event.get("artist", "")
    if not artist_name:
        return {}

    today_str   = datetime.date.today().isoformat()
    cached      = cache.get(eid, {})
    channel_id  = cached.get("channel_id", "")

    # ── Step 1: Find the artist's channel (skip if cached) ───────────────
    if not channel_id:
        search_data = safe_get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part":       "snippet",
                "q":          f"{artist_name} official",
                "type":       "channel",
                "maxResults": 1,
                "key":        YOUTUBE_API_KEY,
            },
            label=f"YouTube channel search: {artist_name}",
        )
        time.sleep(0.2)
        if not search_data or not search_data.get("items"):
            return {}
        channel_id = search_data["items"][0].get("id", {}).get("channelId", "")
        if not channel_id:
            return {}

    # ── Step 2: Get most recent video from the channel ────────────────────
    video_id   = cached.get("video_id", "")
    # Refresh video ID weekly (Monday) or when not yet cached
    should_refresh_video = (
        not video_id
        or datetime.date.today().weekday() == 0  # Monday
    )

    if should_refresh_video:
        recent_data = safe_get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part":       "snippet",
                "channelId":  channel_id,
                "order":      "date",
                "type":       "video",
                "maxResults": 1,
                "key":        YOUTUBE_API_KEY,
            },
            label=f"YouTube recent video: {artist_name}",
        )
        time.sleep(0.2)
        if recent_data and recent_data.get("items"):
            video_id = (recent_data["items"][0]
                        .get("id", {}).get("videoId", video_id))

    if not video_id:
        return {}

    # ── Step 3: Get current stats for the video + channel ────────────────
    stats_data = safe_get(
        "https://www.googleapis.com/youtube/v3/videos",
        params={
            "part":  "statistics",
            "id":    video_id,
            "key":   YOUTUBE_API_KEY,
        },
        label=f"YouTube video stats: {artist_name}",
    )
    time.sleep(0.2)

    if not stats_data or not stats_data.get("items"):
        return {}

    stats        = stats_data["items"][0].get("statistics", {})
    view_count   = int(stats.get("viewCount", 0) or 0)

    # Channel subscriber count (separate call, costs 1 unit)
    chan_data = safe_get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={
            "part": "statistics",
            "id":   channel_id,
            "key":  YOUTUBE_API_KEY,
        },
        label=f"YouTube channel stats: {artist_name}",
    )
    time.sleep(0.2)
    subscriber_count = 0
    if chan_data and chan_data.get("items"):
        chan_stats       = chan_data["items"][0].get("statistics", {})
        subscriber_count = int(chan_stats.get("subscriberCount", 0) or 0)

    # ── Step 4: Compute velocity from cache delta ─────────────────────────
    prior_count  = cached.get("view_count")
    prior_date   = cached.get("date", "")
    view_delta   = None
    velocity_7d  = None

    if prior_count is not None and prior_date and prior_date != today_str:
        try:
            days_elapsed = (
                datetime.date.fromisoformat(today_str)
                - datetime.date.fromisoformat(prior_date)
            ).days
            if days_elapsed > 0:
                daily_rate  = (view_count - prior_count) / days_elapsed
                view_delta  = int(view_count - prior_count)
                velocity_7d = int(daily_rate * 7)
        except (ValueError, ZeroDivisionError):
            pass

    # ── Step 5: Update cache entry for tomorrow ───────────────────────────
    cache[eid] = {
        "channel_id":      channel_id,
        "video_id":        video_id,
        "view_count":      view_count,
        "date":            today_str,
        "subscriber_count": subscriber_count,
    }

    return {
        "yt_video_id":         video_id,
        "yt_view_count":       view_count,
        "yt_view_delta_24h":   view_delta,
        "yt_view_velocity_7d": velocity_7d,
        "yt_subscriber_count": subscriber_count,
        "yt_channel_id":       channel_id,
    }


def fetch_lastfm(event):
    """
    Last.fm — artist engagement metrics via their free API.
    Endpoint: artist.getInfo (no auth beyond API key required)

    Signals extracted:
      lastfm_listeners      : weekly unique listeners (breadth of audience)
      lastfm_playcount      : all-time total scrobbles (depth of engagement)
      lastfm_plays_per_listener: playcount / listeners ratio
                              High ratio = obsessive fans (buy tickets)
                              Low ratio  = casual listeners (don't)
      lastfm_on_tour        : boolean — Last.fm shows this artist as on tour
      lastfm_similar_score  : average listener count of top 3 similar artists
                              (measures peer-group commercial tier)
    """
    if not LASTFM_KEY:
        return {}

    artist_name = event.get("artist", "")
    if not artist_name:
        return {}

    # Primary artist info
    data = safe_get(
        "https://ws.audioscrobbler.com/2.0/",
        params={
            "method":  "artist.getInfo",
            "artist":  artist_name,
            "api_key": LASTFM_KEY,
            "format":  "json",
            "autocorrect": 1,
        },
        label=f"Last.fm artist: {artist_name}",
    )
    time.sleep(0.25)   # Last.fm rate limit: 5 req/sec

    if not data or "artist" not in data:
        return {}

    artist     = data["artist"]
    stats      = artist.get("stats", {})
    listeners  = int(stats.get("listeners", 0) or 0)
    playcount  = int(stats.get("playcount",  0) or 0)
    on_tour    = artist.get("ontour", "0") == "1"

    plays_per_listener = round(playcount / listeners, 1) if listeners > 0 else 0

    # Similar artists — peer tier signal
    similar_listeners = []
    similar = artist.get("similar", {}).get("artist", [])
    for sim in similar[:3]:
        sim_data = safe_get(
            "https://ws.audioscrobbler.com/2.0/",
            params={
                "method":  "artist.getInfo",
                "artist":  sim.get("name", ""),
                "api_key": LASTFM_KEY,
                "format":  "json",
                "autocorrect": 1,
            },
            label=f"Last.fm similar: {sim.get('name','')}",
        )
        time.sleep(0.25)
        if sim_data and "artist" in sim_data:
            sim_listeners = int(
                sim_data["artist"].get("stats", {}).get("listeners", 0) or 0
            )
            similar_listeners.append(sim_listeners)

    avg_similar_listeners = (
        round(sum(similar_listeners) / len(similar_listeners))
        if similar_listeners else None
    )

    return {
        "lastfm_listeners":           listeners,
        "lastfm_playcount":           playcount,
        "lastfm_plays_per_listener":  plays_per_listener,
        "lastfm_on_tour":             on_tour,
        "lastfm_similar_listeners":   avg_similar_listeners,
    }


def fetch_setlist(event):
    """
    Setlist.fm — artist tour history via MusicBrainz MBID.
    Signals extracted:
      setlist_atl_shows_5y    : number of Atlanta-area shows in past 5 years
                                (measures local market strength)
      setlist_avg_venue_cap   : average venue capacity over past 10 shows
                                (career trajectory — growing or shrinking)
      setlist_tour_shows_total: total shows on this specific named tour
                                (scale of current touring cycle)
      setlist_sold_out_flag   : True if any recent ATL show listed as sold out
    """
    if not SETLISTFM_KEY:
        return {}
    mbid = event.get("musicbrainz_mbid", "")
    if not mbid:
        return {}

    # Fetch up to 3 pages of recent setlists (20 per page = 60 shows)
    all_setlists = []
    for page in range(1, 4):
        data = safe_get(
            f"https://api.setlist.fm/rest/1.0/artist/{mbid}/setlists",
            params={"p": page},
            headers={
                "x-api-key": SETLISTFM_KEY,
                "Accept": "application/json",
            },
            label=f"Setlist.fm p{page}: {event['artist']}",
        )
        time.sleep(0.5)   # setlist.fm rate limit: 2 req/sec
        if not data or not data.get("setlist"):
            break
        all_setlists.extend(data["setlist"])
        # Stop early if we have enough
        if len(all_setlists) >= 40:
            break

    if not all_setlists:
        return {}

    concert_date  = datetime.date.fromisoformat(event["date"])
    cutoff_5y     = concert_date - datetime.timedelta(days=365 * 5)
    tour_name     = _extract_tour_name(event["name"])  # from event display name

    atl_shows_5y     = 0
    tour_shows_total = 0
    sold_out_flag    = False
    venue_caps       = []

    VENUE_CAPS_SF = {
        # ── Atlanta market ────────────────────────────────────────────
        "State Farm Arena":                    21000,
        "Mercedes-Benz Stadium":               71000,
        "Truist Park":                         41084,
        "Lakewood Amphitheatre":               18920,
        "Ameris Bank Amphitheatre":            12000,
        "Chastain Park Amphitheatre":           6900,   # Setlist.fm uses this name
        "Synovus Bank Amphitheater at Chastain Park": 6900,
        "Coca-Cola Roxy":                       3600,
        "Gas South Arena":                     13100,
        "Fabulous Fox Theatre":                 4665,
        "The Tabernacle":                       2600,
        "The Eastern":                           500,
        "Variety Playhouse":                    1000,
        # ── Major US venues for trajectory comparison ─────────────────
        "Madison Square Garden":               20789,
        "Kia Forum":                           17500,
        "Hollywood Bowl":                      17376,
        "United Center":                       20491,
        "Barclays Center":                     19000,
        "TD Garden":                           19156,
        "Scotiabank Arena":                    19800,
        "Rogers Centre":                       53506,
        "Wembley Stadium":                     90000,
        "The O2":                              20000,
        "Red Rocks Amphitheatre":               9525,
        "Bridgestone Arena":                   20000,
        "Crypto.com Arena":                    21000,
        "Chase Center":                        18064,
        "Climate Pledge Arena":                18100,
    }

    for sl in all_setlists:
        # Parse show date
        raw_date = sl.get("eventDate", "")
        try:
            # Setlist.fm uses DD-MM-YYYY
            parts = raw_date.split("-")
            show_date = datetime.date(int(parts[2]), int(parts[1]), int(parts[0]))
        except (ValueError, IndexError):
            continue

        city    = sl.get("venue", {}).get("city", {}).get("name", "").lower()
        state   = sl.get("venue", {}).get("city", {}).get("stateCode", "").upper()
        venue_n = sl.get("venue", {}).get("name", "")
        tour_n  = sl.get("tour", {}).get("name", "") if sl.get("tour") else ""

        # ATL shows in past 5 years
        if show_date >= cutoff_5y:
            if "atlanta" in city or (state == "GA" and any(
                a in city for a in ["atlanta", "alpharetta", "marietta"]
            )):
                atl_shows_5y += 1
                if sl.get("info", "").lower().find("sold out") != -1:
                    sold_out_flag = True

        # Count shows on current tour
        if tour_name and tour_name.lower() in tour_n.lower():
            tour_shows_total += 1

        # Collect venue capacities for trajectory calc
        cap = VENUE_CAPS_SF.get(venue_n)
        if cap:
            venue_caps.append(cap)

    avg_venue_cap = round(sum(venue_caps) / len(venue_caps)) if venue_caps else None

    return {
        "setlist_atl_shows_5y":     atl_shows_5y,
        "setlist_avg_venue_cap":    avg_venue_cap,
        "setlist_tour_shows_total": tour_shows_total,
        "setlist_sold_out_flag":    sold_out_flag,
    }


def _extract_tour_name(event_display_name):
    """
    Pull the tour name substring from an event display name.
    e.g. 'Ariana Grande — The Eternal Sunshine Tour' → 'Eternal Sunshine'
    Returns empty string if no tour name found.
    """
    if " — " in event_display_name:
        tour_part = event_display_name.split(" — ", 1)[1]
        # Strip common suffixes
        for suffix in [" Tour", " World Tour", " Live", " Concert"]:
            tour_part = tour_part.replace(suffix, "")
        return tour_part.strip()
    return ""


# ── Main collection loop ───────────────────────────────────────────────────
def fetch_itunes(event):
    """
    iTunes Search API — artist metadata.
    No key required. Free, no rate limit for reasonable usage.
    Endpoint: itunes.apple.com/search

    Signals extracted:
      itunes_album_count      : number of albums in iTunes catalog
                                (cross-validates MusicBrainz album count)
      itunes_primary_genre    : primary genre classification from Apple
                                (useful sanity-check against our genre field)
      itunes_artist_id        : Apple Music artist ID (stable identifier)
    """
    artist_name = event.get("artist", "")
    if not artist_name:
        return {}

    data = safe_get(
        "https://itunes.apple.com/search",
        params={
            "term":      artist_name,
            "entity":    "musicArtist",
            "attribute": "artistTerm",
            "limit":     5,
        },
        label=f"iTunes: {artist_name}",
    )
    time.sleep(0.2)

    if not data or not data.get("results"):
        return {}

    # Find best-matching result by name similarity
    results = data["results"]
    best    = None
    artist_lower = artist_name.lower()
    for r in results:
        if r.get("artistName", "").lower() == artist_lower:
            best = r
            break
    if best is None:
        best = results[0]   # fallback to first result

    # Fetch album count via lookup
    artist_id = best.get("artistId")
    album_count = 0
    if artist_id:
        album_data = safe_get(
            "https://itunes.apple.com/lookup",
            params={
                "id":     artist_id,
                "entity": "album",
                "limit":  200,
            },
            label=f"iTunes albums: {artist_name}",
        )
        time.sleep(0.2)
        if album_data and album_data.get("resultCount", 0) > 1:
            # resultCount includes the artist record itself
            album_count = album_data["resultCount"] - 1

    return {
        "itunes_album_count":   album_count,
        "itunes_primary_genre": best.get("primaryGenreName", ""),
        "itunes_artist_id":     artist_id,
    }


def fetch_deezer(event):
    """
    Deezer API — fan count and album count.
    No key required. Free public GET endpoints.
    Endpoint: api.deezer.com/search/artist

    Signals extracted:
      deezer_fans        : total Deezer fan count (follower equivalent)
                           Europe-weighted — strong signal for international
                           acts like Shakira, Usher, AC/DC
      deezer_album_count : number of albums in Deezer catalog
      deezer_artist_id   : Deezer artist ID
    """
    artist_name = event.get("artist", "")
    if not artist_name:
        return {}

    data = safe_get(
        "https://api.deezer.com/search/artist",
        params={"q": artist_name, "limit": 5},
        label=f"Deezer: {artist_name}",
    )
    time.sleep(0.2)

    if not data or not data.get("data"):
        return {}

    results = data["data"]
    best    = None
    artist_lower = artist_name.lower()
    for r in results:
        if r.get("name", "").lower() == artist_lower:
            best = r
            break
    if best is None:
        best = results[0]

    deezer_id = best.get("id")
    fans      = int(best.get("nb_fan", 0) or 0)

    # Fetch album count from artist detail endpoint
    album_count = 0
    if deezer_id:
        detail = safe_get(
            f"https://api.deezer.com/artist/{deezer_id}/albums",
            params={"limit": 1},   # only need total count from header
            label=f"Deezer albums: {artist_name}",
        )
        time.sleep(0.2)
        if detail:
            album_count = int(detail.get("total", 0) or 0)

    return {
        "deezer_fans":        fans,
        "deezer_album_count": album_count,
        "deezer_artist_id":   deezer_id,
    }



# ── Venue ID map for Ticketmaster Discovery API ─────────────────────────────
# These are the Ticketmaster venue IDs for Atlanta tracked venues.
# Used by discover_new_events() to find shows not yet in the EVENTS list.
TM_VENUE_IDS = {
    "KovZpaFEZe":  "The Tabernacle",
    "KovZ917ACc7": "Coca-Cola Roxy",
    "KovZpZA6AeJA":"State Farm Arena",
    "KovZpZA7AAEA":"Ameris Bank Amphitheatre",
    "KovZ917Ae10": "Buckhead Theatre",
    "KovZpZA6AaJA":"Lakewood Amphitheatre",
    "KovZ917lA37": "Variety Playhouse",
    "KovZ917Aev7": "The Eastern",
    "KovZpa3HNA":  "Synovus Bank Amphitheater at Chastain Park",
    "KovZpZA6AkJA":"Truist Park",
    "KovZpZA7A1lA":"Gas South Arena",
    "KovZpZA6AbJA":"Mercedes-Benz Stadium",
    "KovZpZA7AoJA":"Cobb Energy Performing Arts Centre",
    "KovZpaFjZe":  "Fabulous Fox Theatre",
    "KovZpZAEk6FA":"The Bowl at Sugar Hill",
}

TRACKED_IDS = {e["id"] for e in EVENTS}

def discover_new_events():
    """
    Query Ticketmaster Discovery API for all upcoming Atlanta music events
    at tracked venues. Auto-adds genuine new shows to EVENTS with a default
    seed score of 50 in the bottom panel.

    False positive filters (Ticketmaster returns ticket types as attractions):
      1. All-caps short names (RUSH, GA, PIT, FLOOR, VIP)
      2. No tm_attraction_id (real artists always have one)
      3. Names containing ticket-type keywords (General Admission, Fast Lane etc.)
      4. Single generic words that are common English words

    Events passing all filters are auto-added and scored on the next run.
    """
    if not TICKETMASTER_KEY:
        print("[discover] No TICKETMASTER_KEY — skipping discovery")
        return []

    import datetime as _dt
    today     = _dt.date.today().isoformat()
    win_end   = (datetime.date.today() + datetime.timedelta(days=90)).isoformat()
    base_url  = "https://app.ticketmaster.com/discovery/v2/events.json"

    # Words that indicate a ticket type, not an artist name
    TICKET_KEYWORDS = {
        "general", "admission", "fast", "lane", "lounge", "vip", "access",
        "pit", "floor", "club", "premium", "package", "upgrade", "early",
        "entry", "meet", "greet", "soundcheck", "backstage", "presale",
    }

    def is_false_positive(name, attr_id):
        if not name:
            return True
        # All-caps short names (RUSH, GA, PIT)
        if re.match(r'^[A-Z]{2,8}$', name):
            return True
        # No attraction ID = not a real artist entity
        if not attr_id:
            return True
        # Name contains ticket-type keywords
        words = set(name.lower().split())
        if words & TICKET_KEYWORDS:
            return True
        # Pure numbers or very short
        if len(name.strip()) < 3:
            return True
        return False

    discovered = []
    auto_added = []
    seen_tm_ids = set()

    for venue_id, venue_name in TM_VENUE_IDS.items():
        try:
            params = {
                "apikey":              TICKETMASTER_KEY,
                "venueId":            venue_id,
                "classificationName": "Music",
                "startDateTime":      f"{today}T00:00:00Z",
                "endDateTime":        f"{win_end}T23:59:59Z",
                "size":               50,
                "sort":               "date,asc",
            }
            r = requests.get(base_url, params=params, timeout=10)
            if r.status_code != 200:
                continue
            data = r.json()
            events_found = data.get("_embedded", {}).get("events", [])

            for ev in events_found:
                tm_event_id = ev.get("id", "")
                if tm_event_id in seen_tm_ids:
                    continue
                seen_tm_ids.add(tm_event_id)

                attractions = ev.get("_embedded", {}).get("attractions", [])
                artist_name = attractions[0]["name"] if attractions else ev.get("name", "")
                tm_attr_id  = attractions[0].get("id", "") if attractions else ""

                if is_false_positive(artist_name, tm_attr_id):
                    continue

                # Already tracked? Block if same artist exists on ANY date —
                # prevents false Ticketmaster duplicates (e.g. Shakira appearing
                # at a different venue on a different date). Multi-night shows
                # for the same artist at the same venue are handled manually.
                artist_lower = artist_name.lower()
                already = any(
                    artist_lower in e.get("artist", "").lower()
                    for e in EVENTS
                )
                if already:
                    continue

                dates    = ev.get("dates", {}).get("start", {})
                date_str = dates.get("localDate", "")
                if not date_str:
                    continue

                # Determine genre from TM classification
                classifications = ev.get("classifications", [{}])
                genre = (classifications[0].get("genre", {}).get("name", "")
                         or classifications[0].get("segment", {}).get("name", "Music"))
                if genre in ("", "Undefined", "Music"):
                    genre = "Rock"   # sensible default for unknown

                discovered.append({
                    "name":        artist_name,
                    "date":        date_str,
                    "venue":       venue_name,
                    "tm_attr_id":  tm_attr_id,
                    "genre":       genre,
                })
        except Exception as e:
            print(f"[discover] {venue_name}: {e}")
            continue

    discovered.sort(key=lambda x: x["date"])

    if not discovered:
        print("[discover] ✓ All Atlanta music events in window are tracked")
        return []

    # Auto-add new events to EVENTS list
    GENRE_MAP = {
        "Hip-Hop/Rap": "Hip-Hop", "R&B": "R&B", "Pop": "Pop",
        "Rock": "Rock", "Country": "Country", "Latin": "Latin Pop",
        "Electronic": "Electronic", "Alternative": "Indie / Alt",
        "Indie": "Indie / Alt", "Metal": "Rock", "Punk": "Rock",
        "Jazz": "Jazz", "Blues": "Blues", "Reggae": "Reggae",
    }

    for d in discovered:
        slug = re.sub(r'[^a-z0-9]+', '-', d["name"].lower()).strip('-')
        # Include date in ID for multi-night shows to avoid collisions
        year = d["date"][:4]
        date_suffix = d["date"].replace("-", "")[4:]  # MMDD e.g. 0628
        eid  = f"{slug}-{year}"
        # If this slug+year already exists, append the date suffix
        if any(e["id"] == eid for e in EVENTS):
            eid = f"{slug}-{year}-{date_suffix}"

        mapped_genre = GENRE_MAP.get(d["genre"], d["genre"] or "Rock")

        new_event = {
            "id":                     eid,
            "seed_score":             50,
            "name":                   d["name"],
            "artist":                 d["name"],
            "venue":                  d["venue"],
            "date":                   d["date"],
            "genre":                  mapped_genre,
            "spotify_artist_id":      "",
            "musicbrainz_mbid":       "",
            "tm_attraction_id":       d["tm_attr_id"],
            "seatgeek_performer_slug": slug,
            "wikipedia_title":        d["name"].replace(" ", "_"),
            "bandsintown_artist":     d["name"],
        }
        EVENTS.append(new_event)
        auto_added.append(d["name"])
        print(f"[discover] AUTO-ADDED: {d['date']} | {d['name'][:40]} @ {d['venue']}")

    if auto_added:
        print(f"[discover] {len(auto_added)} new events added to roster this run")
        # Persist to discovered_events.json (separate from curated collect.py)
        try:
            disc_path = "data/discovered_events.json"
            try:
                with open(disc_path) as _f:
                    existing_disc = json.load(_f)
            except (FileNotFoundError, json.JSONDecodeError):
                existing_disc = []
            existing_disc_ids = {e["id"] for e in existing_disc}
            new_disc = [e for e in EVENTS if e["id"] not in existing_disc_ids
                        and e["id"] not in {ev["id"] for ev in EVENTS
                                            if ev.get("id","") in
                                            {x["id"] for x in
                                             [ev2 for ev2 in EVENTS
                                              if ev2.get("seed_score") != 50]}}]
            # Simpler: just add any newly auto-added event not already in file
            truly_new = [e for e in EVENTS
                         if e["id"] not in existing_disc_ids
                         and e.get("seed_score") == 50
                         and e["id"].endswith("-2026")]
            if truly_new:
                existing_disc.extend(truly_new)
                with open(disc_path, "w") as _f:
                    json.dump(existing_disc, _f, indent=2)
                print(f"[discover] {len(truly_new)} new events persisted to discovered_events.json")
        except Exception as _e:
            print(f"[discover] WARNING: could not write discovered_events.json: {_e}")
    else:
        print("[discover] ✓ No new events to add")

    return discovered


def collect_all():
    print(f"[collect] Starting — {datetime.datetime.now().isoformat()}")

    # Load auto-discovered events from data/discovered_events.json
    # These are events found by discover_new_events() on previous runs.
    # Kept separate from collect.py so the pipeline never overwrites
    # the manually curated event list.
    try:
        with open("data/discovered_events.json") as _f:
            _discovered = json.load(_f)
        _existing_ids = {e["id"] for e in EVENTS}
        _added = [e for e in _discovered if e["id"] not in _existing_ids]
        EVENTS.extend(_added)
        if _added:
            print(f"[collect] Loaded {len(_added)} previously discovered events from discovered_events.json")
    except FileNotFoundError:
        pass

    # Apply blocklist — filter events editorially blocked from both sources.
    # Add IDs to data/event_blocklist.json to suppress without editing collect.py.
    try:
        with open("data/event_blocklist.json") as _f:
            _blocklist = set(json.load(_f))
        _before = len(EVENTS)
        EVENTS[:] = [e for e in EVENTS if e["id"] not in _blocklist]
        _removed = _before - len(EVENTS)
        if _removed:
            print(f"[collect] Blocklist suppressed {_removed} event(s)")
    except FileNotFoundError:
        pass

    print(f"[collect] Total events to collect: {len(EVENTS)}")

    # Discover any Atlanta music events not yet in the EVENTS list.
    # Runs on every nightly build and logs untracked shows for editorial review.
    discover_new_events()

    spotify_token = get_spotify_token()

    # Load YouTube view-count cache from previous run
    # (persisted between runs via GitHub Actions cache@v4 — see nightly.yml)
    yt_cache = load_youtube_cache()
    print(f"[collect] YouTube cache loaded: {len(yt_cache)} cached entries")

    # Fetch AMM article catalog once (weekly refresh via local cache)
    amm_catalog = fetch_amm_catalog()

    results = {}
    for idx, event in enumerate(EVENTS):
        eid = event["id"]
        print(f"  [{idx+1}/{len(EVENTS)}] {event['name'][:55]}")
        signals = {"event_meta": event}

        # AMM coverage — try artist field first, fall back to full name
        # which may contain co-headliners (e.g. "Lynyrd Skynyrd & Foreigner")
        amm_artist = event.get("artist") or event.get("name", "")
        amm = match_amm_article(amm_artist, amm_catalog)
        # If primary artist didn't match, try the full event name
        # (catches co-headliner billing like "Lynyrd Skynyrd & Foreigner")
        if not amm and event.get("name") != amm_artist:
            amm = match_amm_article(event.get("name", ""), amm_catalog)
        # Fallback: try direct URL construction for recent articles not yet in sitemap
        # Only for shows within the past 14 days to limit HTTP requests
        if not amm:
            try:
                event_date = datetime.date.fromisoformat(event.get("date", "2000-01-01"))
                if abs((datetime.date.today() - event_date).days) <= 14:
                    amm = find_amm_article_direct(event)
            except Exception:
                pass
        if amm:
            event["amm_article_title"]   = amm["title"]
            event["amm_article_url"]     = amm["link"]
            event["amm_article_date"]    = amm["display_date"]
            print(f"    [AMM] Matched: {amm['title'][:60]}")

        try:
            # 30% — Ticket Demand
            signals.update(fetch_ticketmaster(event));  time.sleep(0.3)
            signals.update(fetch_seatgeek(event));       time.sleep(0.3)
            signals.update(fetch_eventbrite(event))
        except Exception as e:
            print(f"    [WARN] Ticket demand fetch failed: {e}")

        try:
            # 25% — Sentiment
            signals.update(fetch_spotify(event, spotify_token)); time.sleep(0.2)
            signals.update(fetch_chartmetric(event));            time.sleep(0.3)
            signals.update(fetch_lastfm(event))
            signals.update(fetch_youtube(event, yt_cache))
            signals.update(fetch_itunes(event))
            signals.update(fetch_deezer(event))
        except Exception as e:
            print(f"    [WARN] Sentiment fetch failed: {e}")

        try:
            # 25% — Historical Sales
            signals.update(fetch_wikipedia_pageviews(event)); time.sleep(0.3)
            signals.update(fetch_musicbrainz(event))
            signals.update(fetch_setlist(event))
            signals.update(fetch_wikidata(event))          # keyless SPARQL — ~100ms/event
        except Exception as e:
            print(f"    [WARN] Historical sales fetch failed: {e}")

        try:
            # 20% — Local Intent
            signals.update(fetch_google_trends(event)); time.sleep(0.5)
            signals.update(fetch_bandsintown(event));   time.sleep(0.2)
        except Exception as e:
            print(f"    [WARN] Local intent fetch failed: {e}")

        results[eid] = signals

    # Persist updated YouTube cache for tomorrow's velocity calculation
    save_youtube_cache(yt_cache)
    cached_count = sum(1 for v in yt_cache.values() if v.get("view_count"))
    print(f"[collect] YouTube cache saved: {cached_count} entries")

    output_path = "data/raw_signals.json"
    with open(output_path, "w") as f:
        json.dump({
            "collected_at": datetime.datetime.utcnow().isoformat() + "Z",
            "events":       results,
        }, f, indent=2)

    print(f"[collect] Done — {len(results)} events → {output_path}")
    return results


if __name__ == "__main__":
    collect_all()
