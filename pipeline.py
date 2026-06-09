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

    Wraps content in a Gutenberg <!-- wp:html --> raw HTML block so
    WordPress stores and renders it exactly as-is without re-processing,
    escaping, or adding paragraph/block wrappers around it.

    The page must already exist — create it once manually, note its ID,
    and add it as the WP_PAGE_ID secret.
    """
    if not all([WP_SITE_URL, WP_USERNAME, WP_APP_PASSWORD, WP_PAGE_ID]):
        print("[upload] Missing WordPress credentials — skipping upload.")
        print("         Set WP_SITE_URL, WP_USERNAME, WP_APP_PASSWORD, WP_PAGE_ID")
        return False

    # Wrap in Gutenberg raw HTML block comment markers.
    # This tells the block editor to treat the content as a Custom HTML
    # block verbatim — no auto-paragraph, no escaping, no block conversion.
    gutenberg_wrapped = (
        "<!-- wp:html -->\n"
        + html_content.strip()
        + "\n<!-- /wp:html -->"
    )

    url = f"{WP_SITE_URL.rstrip('/')}/wp-json/wp/v2/pages/{WP_PAGE_ID}"
    headers = {
        **wp_auth_header(),
        "Content-Type": "application/json",
    }

    # Send only 'raw' — omitting 'rendered' prevents WordPress from
    # double-processing the content through its content filter hooks.
    payload = {
        "content": {
            "raw": gutenberg_wrapped,
        },
        "status": "publish",
    }

    print(f"[upload] Updating WordPress page ID {WP_PAGE_ID} …")
    try:
        r = requests.put(url, headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        result = r.json()
        print(f"[upload] ✓ Page updated: {result.get('link', '')}")
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
