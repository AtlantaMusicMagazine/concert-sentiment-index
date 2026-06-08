# Atlanta Music Magazine — Nightly Dashboard Pipeline

Automated pipeline that refreshes the concert popularity dashboard every night at 11 PM ET. Runs entirely on GitHub Actions (free tier) — no server required.

---

## How it works

```
11:00 PM ET every night
        │
        ▼
GitHub Actions wakes up
        │
        ├─ collect.py   — calls all APIs, saves raw_signals.json
        ├─ score.py     — applies weighted model, saves scored_events.json
        ├─ build_html.py — injects scores into dashboard HTML template
        └─ pipeline.py  — uploads finished HTML to your WordPress page
```

The finished HTML file is pushed to a WordPress page via the REST API. Your site visitors see the updated rankings the next time the page loads after midnight.

---

## One-time setup (do this once, takes about 45 minutes)

### Step 1 — Create a GitHub repository

1. Go to [github.com](https://github.com) and create a free account if you don't have one.
2. Click **New repository**. Name it something like `atl-music-dashboard`. Set it to **Private**.
3. Upload all these files into the repository root. The folder structure must be:

```
your-repo/
├── .github/
│   └── workflows/
│       └── nightly.yml
├── templates/
│   └── artist_card_module.html   ← your current dashboard HTML goes here
├── data/                          ← created automatically by the pipeline
├── output/                        ← created automatically by the pipeline
├── collect.py
├── score.py
├── build_html.py
├── pipeline.py
├── requirements.txt
└── README.md
```

> **Important:** Copy your current `artist_card_module.html` into the `templates/` folder. The pipeline reads it as the base template and injects fresh card data between the sentinel comments.

4. Add sentinel comments to `templates/artist_card_module.html` so the builder knows where to inject cards. Find the first top panel `<article>` tag and the last one, and wrap them:

```html
<!-- TOP_CARDS_START -->
  <article class="event-card" ...> ... </article>
  ... (all 20 top cards) ...
<!-- TOP_CARDS_END -->
```

Do the same for the bottom panel:

```html
<!-- BOTTOM_CARDS_START -->
  <article class="event-card bottom" ...> ... </article>
  ... (all 20 bottom cards) ...
<!-- BOTTOM_CARDS_END -->
```

---

### Step 2 — Get your API keys

You need accounts with each service below. All have free tiers sufficient for one nightly run.

#### Ticketmaster Discovery API
**Cost:** Free (5,000 calls/day free tier)
1. Go to [developer.ticketmaster.com](https://developer.ticketmaster.com)
2. Click **Get Your API Key** → create an account → create an app
3. Copy the **Consumer Key** — this is your `TICKETMASTER_KEY`

#### SeatGeek API
**Cost:** Free (requires approval)
1. Go to [platform.seatgeek.com](https://platform.seatgeek.com)
2. Register for API access — approval usually takes 1–3 business days
3. Once approved, note your **Client ID** (`SEATGEEK_CLIENT_ID`) and **Client Secret** (`SEATGEEK_SECRET`)

#### StubHub API
**Cost:** Free (partner program)
1. Go to [developer.stubhub.com](https://developer.stubhub.com)
2. Apply for API access — this can take up to a week
3. Once approved, generate an access token (`STUBHUB_TOKEN`)
> Note: StubHub's API is the hardest to get access to. The pipeline will run without it — SeatGeek covers the ticket demand pillar adequately on its own.

#### Spotify Web API
**Cost:** Free
1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
2. Log in with your Spotify account → **Create app**
3. Name: "ATL Music Dashboard", Redirect URI: `http://localhost` (doesn't matter)
4. Copy **Client ID** (`SPOTIFY_CLIENT_ID`) and **Client secret** (`SPOTIFY_SECRET`)

#### SerpApi (Google Trends)
**Cost:** Free tier: 100 searches/month. Paid: $50/month for 5,000 searches.
The free tier gives you ~3 searches per day — enough for one nightly run of up to 3 events. For all 20+ events you'll need the $50/month plan.
1. Go to [serpapi.com](https://serpapi.com) → create a free account
2. Copy your **API Key** (`SERPAPI_KEY`)
> **Alternative (free):** If SerpApi cost is a concern, you can skip Google Trends entirely. The local intent pillar will then rely solely on Bands in Town RSVPs, and the score will still be directionally correct.

#### Chartmetric
**Cost:** Free tier available (limited calls)
1. Go to [chartmetric.com](https://chartmetric.com) → request API access
2. Note your **API token** (`CHARTMETRIC_TOKEN`)
> Like StubHub, Chartmetric access requires approval. The pipeline runs fine without it — Spotify popularity data covers the sentiment pillar adequately.

#### Bands in Town
**Cost:** Free
1. Go to [artists.bandsintown.com/api](https://artists.bandsintown.com/api)
2. Request an app ID — approval is usually same-day
3. Your app ID is your `BANDSINTOWN_KEY`

#### Wikipedia
**No API key needed.** Wikipedia's REST API is open. You just need to provide a user-agent string identifying your app, which is already hardcoded in the workflow as `atlanta-music-magazine/1.0`.

---

### Step 3 — Configure WordPress

The pipeline updates a WordPress page via the REST API using Application Passwords (built into WordPress since version 5.6).

1. **Create the dashboard page** in WordPress:
   - Go to Pages → Add New
   - Title: "Concert Popularity Tracker" (or whatever you want)
   - Set the page template to **Full Width** (or your theme's equivalent) so there's no sidebar
   - Publish it
   - Note the page ID — you can find it in the URL when editing the page: `post=XXXX`

2. **Create an Application Password:**
   - Go to Users → Profile (or the user you want the pipeline to run as)
   - Scroll to **Application Passwords** near the bottom
   - Under "New Application Password Name" type: `GitHub Pipeline`
   - Click **Add New Application Password**
   - **Copy the password immediately** — it's only shown once. It looks like: `xxxx xxxx xxxx xxxx xxxx xxxx`
   - Remove the spaces when pasting it into GitHub Secrets

3. **Disable the default WordPress editor for this page** (optional but recommended):
   The REST API will push raw HTML. If the Gutenberg editor tries to re-parse it on next save, it may add block wrapper divs. Install the plugin **Classic Editor** and set that one page to use Classic Editor to avoid this.

---

### Step 4 — Add secrets to GitHub

Go to your GitHub repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.

Add each of these:

| Secret name | Where to get it |
|---|---|
| `TICKETMASTER_KEY` | Ticketmaster developer portal |
| `SEATGEEK_CLIENT_ID` | SeatGeek platform portal |
| `SEATGEEK_SECRET` | SeatGeek platform portal |
| `STUBHUB_TOKEN` | StubHub developer portal (optional) |
| `SPOTIFY_CLIENT_ID` | Spotify developer dashboard |
| `SPOTIFY_SECRET` | Spotify developer dashboard |
| `CHARTMETRIC_TOKEN` | Chartmetric API portal (optional) |
| `SERPAPI_KEY` | serpapi.com dashboard (optional) |
| `BANDSINTOWN_KEY` | Bands in Town API portal |
| `WP_SITE_URL` | Your site URL, e.g. `https://atlantamusicmagazine.com` |
| `WP_USERNAME` | Your WordPress username |
| `WP_APP_PASSWORD` | The Application Password you just created (no spaces) |
| `WP_PAGE_ID` | The numeric ID of your dashboard page |

---

### Step 5 — Test it manually

Before waiting for 11 PM, trigger the pipeline manually:

1. Go to your GitHub repository → **Actions** tab
2. Click **Nightly Dashboard Refresh** in the left sidebar
3. Click **Run workflow** → **Run workflow**
4. Watch the logs — each step will print its status
5. If successful, go to your WordPress page and check that the content updated

If something fails, click the failed step to see the error log. Common issues are listed in the Troubleshooting section below.

---

## Adding new events

Open `collect.py` and add a new entry to the `EVENTS` list following the existing format. The key fields are:

- `id` — a unique slug, e.g. `"morgan-wallen-2026"`
- `name` — display name exactly as it should appear on the card
- `artist` — artist name for API queries
- `venue` — must match a key in `score.py`'s `VENUE_CAPS` dictionary exactly
- `date` — ISO format `YYYY-MM-DD`
- `genre` — must match a key in `build_html.py`'s `GENRE_STYLES` dictionary
- `spotify_artist_id` — find this in the Spotify URL when viewing the artist page
- `tm_attraction_id` — find this via the Ticketmaster Discovery API or in the event URL
- `seatgeek_performer_slug` — the slug from the SeatGeek URL for that artist
- `wikipedia_title` — the exact Wikipedia article title (underscores, not spaces)
- `bandsintown_artist` — artist name exactly as Bands in Town spells it

---

## Troubleshooting

**Pipeline runs but WordPress page doesn't update**
Check that `WP_PAGE_ID` is the correct page ID (not post ID). Confirm the Application Password has no spaces. Make sure the WordPress REST API is enabled (it's on by default — some security plugins disable it).

**"collect failed" error**
One of the APIs returned an error. Check the logs for which source failed. The pipeline has graceful fallbacks — a single API failure won't stop scoring. But if all APIs fail (e.g. no keys set), scoring will use neutral 0.5 values for everything.

**Scores look wrong / all the same**
This usually means API keys aren't set — the scoring engine uses 0.5 neutral values for every missing signal, which produces scores in the 45–55 range for everything. Check that your GitHub Secrets are named exactly as listed above (case-sensitive).

**GitHub Actions isn't running at 11 PM**
GitHub's cron scheduler can run up to 30 minutes late on busy days. This is normal. If it consistently doesn't run, check the **Actions** tab to see if workflows are disabled for your repository.

**The page looks broken after upload**
WordPress may have re-encoded some HTML characters. Try switching that page to the Classic Editor (see Step 3). Alternatively, use `WP_UPLOAD_MODE=file` to upload as a standalone HTML file and embed it on your page via an `<iframe>`.

---

## File reference

| File | Purpose |
|---|---|
| `collect.py` | Fetches raw signals from all API sources |
| `score.py` | Applies the weighted scoring model |
| `build_html.py` | Generates the dashboard HTML from scored data |
| `pipeline.py` | Orchestrates all steps + WordPress upload |
| `.github/workflows/nightly.yml` | GitHub Actions scheduler (runs at 11 PM ET) |
| `templates/artist_card_module.html` | Your dashboard HTML template |
| `data/raw_signals.json` | Raw API responses (generated nightly) |
| `data/scored_events.json` | Computed scores (generated nightly) |
| `data/last_run.json` | Last run status log |
| `output/artist_card_module.html` | Final built dashboard (generated nightly) |
