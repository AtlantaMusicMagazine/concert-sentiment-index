"""
pipeline.py
Atlanta Music Magazine — Nightly Pipeline Orchestrator
Runs collect → score → build → upload in sequence.
Called by the GitHub Actions workflow every night at 11 PM ET.
"""

import os
import sys
import json
import base64
import datetime
import requests

import collect
import score
import build_html


# ── WordPress credentials (set as GitHub Secrets) ────────────────────────
WP_SITE_URL    = os.environ.get("WP_SITE_URL", "")       # e.g. https://atlantamusicmagazine.com
WP_USERNAME    = os.environ.get("WP_USERNAME", "")        # WordPress username
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD", "")  # WordPress Application Password
WP_PAGE_ID     = os.environ.get("WP_PAGE_ID", "")        # ID of the page to update

# If you want to upload as a file instead of updating a page's content,
# set WP_UPLOAD_MODE=file and the script will push to the media library.
WP_UPLOAD_MODE = os.environ.get("WP_UPLOAD_MODE", "page")  # "page" or "file"


def wp_auth_header():
    """Build the Basic Auth header from WP username + Application Password."""
    creds = f"{WP_USERNAME}:{WP_APP_PASSWORD}"
    token = base64.b64encode(creds.encode()).decode()
    return {"Authorization": f"Basic {token}"}


def upload_as_page_content(html_content):
    """
    Update the content of an existing WordPress page via REST API.

    Splits the full HTML output into 4 separate <!-- wp:html --> blocks
    matching the manual block structure:
      Block 1: <style> block (scoped CSS + CDN imports)
      Block 2: Top panel section + pool JSON data element
      Block 3: Bottom panel section + footer
      Block 4: <script> block (JS)

    Using 4 separate blocks matches what was manually committed and avoids
    WordPress's content sanitizer corrupting the large script/pool data
    when it's all in a single block.
    """
    if not all([WP_SITE_URL, WP_USERNAME, WP_APP_PASSWORD, WP_PAGE_ID]):
        print("[upload] Missing WordPress credentials — skipping upload.")
        print("         Set WP_SITE_URL, WP_USERNAME, WP_APP_PASSWORD, WP_PAGE_ID")
        return False

    # ── Split into 4 blocks ───────────────────────────────────────────────
    style_end    = html_content.find("</style>") + len("</style>")
    embed_start  = html_content.find('<div class="csi-embed">')
    top_sec_end  = html_content.find("</section>") + len("</section>")
    script_start = html_content.find("<script>")

    if any(x == -1 for x in [embed_start, top_sec_end, script_start]):
        print("[upload] WARN: Could not split HTML into 4 blocks — uploading as single block")
        block1, block2, block3, block4 = html_content, "", "", ""
        blocks = [block1]
    else:
        block1 = html_content[:style_end].strip()
        block2 = html_content[embed_start:top_sec_end].strip()
        block3 = html_content[top_sec_end:script_start].strip()
        block4 = html_content[script_start:].strip()
        blocks = [block1, block2, block3, block4]

    gutenberg_content = "\n\n".join(
        f"<!-- wp:html -->\n{b}\n<!-- /wp:html -->"
        for b in blocks
        if b.strip()
    )

    url = f"{WP_SITE_URL.rstrip('/')}/wp-json/wp/v2/pages/{WP_PAGE_ID}"
    headers = {
        **wp_auth_header(),
        "Content-Type": "application/json",
    }
    payload = {
        "content": gutenberg_content,   # plain string, not {"raw":...}
        "status":  "publish",
    }
    # Note: {"content": {"raw": ...}} requires 'unfiltered_html' capability
    # which Application Passwords don't grant by default. WordPress silently
    # ignores the raw field and returns 200 OK without saving anything.
    # Sending content as a plain string goes through wp_kses but DOES save.

    print(f"[upload] Updating WordPress page ID {WP_PAGE_ID} ({len(blocks)} blocks, {len(gutenberg_content):,} chars) …")
    try:
        r = requests.put(url, headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        result = r.json()
        print(f"[upload] ✓ Page updated: {result.get('link', '')}")
        print(f"[upload]   Title: {result.get('title', {}).get('rendered', 'unknown')}")
        print(f"[upload]   ID: {result.get('id', 'unknown')}")
        print(f"[upload]   Modified: {result.get('modified', 'unknown')}")

        # Purge LiteSpeed Cache after updating the page.
        site_url = WP_SITE_URL.rstrip("/")
        page_url = result.get("link", "").rstrip("/") + "/"

        for purge_url, label in [
            (f"{site_url}/wp-json/litespeed/v1/purge_url?url={page_url}", "purge_url"),
            (f"{site_url}/wp-json/litespeed/v1/purge/all",                "purge_all"),
        ]:
            try:
                pr = requests.get(
                    purge_url,
                    headers=wp_auth_header(),
                    timeout=10,
                )
                print(f"[upload]   LiteSpeed {label}: HTTP {pr.status_code}")
                if pr.status_code < 300:
                    break
            except Exception as ce:
                print(f"[upload]   LiteSpeed {label} failed: {ce}")

        # Purge Cloudflare edge cache (if CF_ZONE_ID and CF_API_TOKEN are set).
        # Cloudflare sits in front of LiteSpeed and must also be purged, otherwise
        # visitors continue to see the cached June 12 snapshot regardless of
        # LiteSpeed being cleared.
        CF_ZONE_ID  = os.environ.get("CF_ZONE_ID", "")
        CF_API_TOKEN = os.environ.get("CF_API_TOKEN", "")
        if CF_ZONE_ID and CF_API_TOKEN:
            try:
                cf_r = requests.post(
                    f"https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/purge_cache",
                    headers={
                        "Authorization": f"Bearer {CF_API_TOKEN}",
                        "Content-Type":  "application/json",
                    },
                    json={"files": [page_url]},
                    timeout=15,
                )
                print(f"[upload]   Cloudflare purge: HTTP {cf_r.status_code}")
            except Exception as cfe:
                print(f"[upload]   Cloudflare purge failed: {cfe}")
        else:
            print("[upload]   Cloudflare purge skipped (CF_ZONE_ID/CF_API_TOKEN not set)")

        return True
    except requests.exceptions.HTTPError as e:
        print(f"[upload] ✗ HTTP error: {e} — {r.text[:300]}")
        return False
    except Exception as e:
        print(f"[upload] ✗ Error: {e}")
        return False


def upload_as_media_file(html_path):
    """
    Alternative: upload the HTML file to the WordPress media library.
    Use this if you embed the dashboard via an iframe pointing to the media URL.
    """
    if not all([WP_SITE_URL, WP_USERNAME, WP_APP_PASSWORD]):
        print("[upload] Missing WordPress credentials — skipping upload.")
        return False

    url = f"{WP_SITE_URL.rstrip('/')}/wp-json/wp/v2/media"
    headers = {
        **wp_auth_header(),
        "Content-Disposition": 'attachment; filename="artist_card_module.html"',
        "Content-Type": "text/html",
    }

    print(f"[upload] Uploading HTML file to WordPress media library …")
    try:
        with open(html_path, "rb") as f:
            r = requests.post(url, headers=headers, data=f, timeout=60)
        r.raise_for_status()
        result = r.json()
        print(f"[upload] ✓ Uploaded: {result.get('source_url', '')}")
        return True
    except Exception as e:
        print(f"[upload] ✗ Error: {e}")
        return False


def write_run_log(success, errors):
    """Write a run summary to data/last_run.json for debugging."""
    log = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "success": success,
        "errors": errors,
    }
    with open("data/last_run.json", "w") as f:
        json.dump(log, f, indent=2)
    print(f"[pipeline] Run log written to data/last_run.json")


# ── Main orchestrator ─────────────────────────────────────────────────────

def run():
    print("=" * 60)
    print(f" Atlanta Music Magazine — Nightly Pipeline")
    print(f" {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S ET')}")
    print("=" * 60)

    errors = []

    # Step 1: Collect
    print("\n[1/4] Collecting data from APIs …")
    try:
        collect.collect_all()
    except Exception as e:
        errors.append(f"collect: {e}")
        print(f"  ✗ Collection failed: {e}")
        write_run_log(False, errors)
        sys.exit(1)

    # Step 2: Score
    print("\n[2/4] Scoring events …")
    try:
        score.score_all()
    except Exception as e:
        errors.append(f"score: {e}")
        print(f"  ✗ Scoring failed: {e}")
        write_run_log(False, errors)
        sys.exit(1)

    # Step 3: Build HTML
    print("\n[3/4] Building HTML dashboard …")
    try:
        output_path = build_html.build()
    except Exception as e:
        errors.append(f"build: {e}")
        print(f"  ✗ Build failed: {e}")
        write_run_log(False, errors)
        sys.exit(1)

    # Step 4: Upload to WordPress
    print("\n[4/4] Uploading to WordPress …")
    try:
        with open("output/artist_card_module_wp_ready.html") as f:
            html_content = f.read()

        if WP_UPLOAD_MODE == "file":
            upload_as_media_file(output_path)
        else:
            upload_as_page_content(html_content)
    except Exception as e:
        errors.append(f"upload: {e}")
        print(f"  ✗ Upload failed: {e}")
        # Don't exit — the HTML was built successfully even if upload failed.
        # GitHub Actions will keep the artifact.

    write_run_log(len(errors) == 0, errors)

    print("\n" + "=" * 60)
    if errors:
        print(f" Pipeline completed with {len(errors)} error(s):")
        for err in errors:
            print(f"   • {err}")
    else:
        print(" Pipeline completed successfully ✓")
    print("=" * 60)


if __name__ == "__main__":
    run()
