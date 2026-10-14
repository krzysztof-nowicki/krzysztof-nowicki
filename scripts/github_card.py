#!/usr/bin/env python3
"""Gothic GitHub stats card (SVG) for a profile README.

Fetches public data for a GitHub user from the REST API (urllib only, no token
needed):

* public repository count and followers,
* top languages by bytes across the user's non-fork repositories,
* total stars and the most recent push.

It then renders a dark, crimson-and-gold SVG card with plain string templating.
Rate limits (HTTP 403/429), unknown users and network errors are reported with a
clear message instead of a traceback; ``--offline`` skips the network and draws
the card from built-in sample data so you can tweak the look first.

Set GITHUB_TOKEN in your environment (optional) to raise the rate limit from 60 to
5000 requests per hour; the token is only sent to api.github.com.

Usage:  python github_card.py --help
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

USERNAME = "krzysztof-nowicki"
COLORS = {
    "bg": "#0c0d13",        # card background
    "panel": "#14151e",     # inner panel
    "border": "#c9a24a",    # gold frame
    "title": "#f0cf7a",     # title text (bright gold)
    "accent": "#d8263d",    # crimson highlights
    "accent_dark": "#a3172a",
    "text": "#e9e1cf",      # parchment text
    "muted": "#8d8a99",     # labels
}
# Which stats to draw, in order.  Allowed: repos, followers, stars, last_push, languages
SHOW_STATS = ["repos", "followers", "stars", "last_push", "languages"]
TOP_LANGUAGES = 5          # how many languages in the bar
MAX_REPOS_FOR_LANGUAGES = 30  # API calls spent on language data (one per repo)
LANGUAGE_COLORS = ["#d8263d", "#c9a24a", "#e9e1cf", "#a3172a", "#f0cf7a", "#6b6a7a"]
# ===========================================================================

API = "https://api.github.com"
PLACEHOLDER = "githubber"

SAMPLE_DATA: dict[str, Any] = {
    "repos": 24, "followers": 58, "stars": 131, "last_push": "2026-03-02T21:14:00Z",
    "languages": {"Python": 482_000, "C++": 301_000, "C": 118_000, "JavaScript": 64_000, "Shell": 12_000, "HTML": 9_000},
}


class GitHubError(Exception):
    """A problem talking to GitHub, with a message that is safe to show the user."""


def api_get(path: str) -> Any:
    req = urllib.request.Request(API + path, headers={"Accept": "application/vnd.github+json",
                                                      "User-Agent": "gothic-github-card"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (403, 429) and e.headers.get("X-RateLimit-Remaining") == "0":
            reset = e.headers.get("X-RateLimit-Reset")
            when = datetime.fromtimestamp(int(reset), timezone.utc).strftime("%H:%M UTC") if reset else "later"
            raise GitHubError(f"GitHub rate limit reached; try again after {when} or set GITHUB_TOKEN.") from None
        if e.code == 404:
            raise GitHubError(f"GitHub says not found ({path}). Check the username.") from None
        raise GitHubError(f"GitHub returned HTTP {e.code} for {path}.") from None
    except urllib.error.URLError as e:
        raise GitHubError(f"Network problem ({e.reason}). Use --offline for the sample card.") from None
    except (TimeoutError, json.JSONDecodeError) as e:
        raise GitHubError(f"Could not read the response from GitHub ({type(e).__name__}).") from None


def fetch_stats(user: str) -> dict[str, Any]:
    profile = api_get(f"/users/{user}")
    repos: list[dict[str, Any]] = []
    for page in range(1, 4):  # up to 300 repos
        chunk = api_get(f"/users/{user}/repos?per_page=100&type=owner&sort=pushed&page={page}")
        repos += chunk
        if len(chunk) < 100:
            break
    own = [r for r in repos if not r.get("fork")]
    langs: dict[str, int] = {}
    for r in own[:MAX_REPOS_FOR_LANGUAGES]:
        for name, n in api_get(f"/repos/{user}/{r['name']}/languages").items():
            langs[name] = langs.get(name, 0) + n
    pushes = [r["pushed_at"] for r in own if r.get("pushed_at")]
    return {
        "repos": profile.get("public_repos", len(repos)),
        "followers": profile.get("followers", 0),
        "stars": sum(r.get("stargazers_count", 0) for r in own),
        "last_push": max(pushes) if pushes else None,
        "languages": langs,
    }


def human_date(iso: str | None) -> str:
    if not iso:
        return "never"
    when = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc) - when).days
    ago = "today" if days <= 0 else f"{days} day{'s' if days != 1 else ''} ago"
    return f"{when:%d %b %Y} ({ago})"


def render_svg(user: str, data: dict[str, Any], offline: bool) -> str:
    c = COLORS
    w, h = 560, 270
    out: list[str] = []
    add = out.append
    add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" '
        f'aria-label="GitHub stats card for {escape(user)}">')
    add(f'<title>GitHub stats for {escape(user)}</title>')
    add('<defs>'
        f'<linearGradient id="glow" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{c["accent_dark"]}" stop-opacity="0.35"/>'
        f'<stop offset="1" stop-color="{c["bg"]}" stop-opacity="0"/></linearGradient></defs>')
    add(f'<rect width="{w}" height="{h}" rx="6" fill="{c["bg"]}"/>')
    add(f'<rect width="{w}" height="90" rx="6" fill="url(#glow)"/>')
    # double gold frame with corner ornaments
    add(f'<rect x="6" y="6" width="{w - 12}" height="{h - 12}" rx="3" fill="none" stroke="{c["border"]}" stroke-width="2"/>')
    add(f'<rect x="12" y="12" width="{w - 24}" height="{h - 24}" rx="2" fill="none" stroke="{c["border"]}" stroke-width="0.8" opacity="0.6"/>')
    for cx, cy in [(12, 12), (w - 12, 12), (12, h - 12), (w - 12, h - 12)]:
        add(f'<path d="M{cx} {cy - 6} L{cx + 6} {cy} L{cx} {cy + 6} L{cx - 6} {cy} Z" fill="{c["accent"]}" stroke="{c["border"]}" stroke-width="1"/>')
    # title
    font = "Cinzel, 'Palatino Linotype', Georgia, serif"
    add(f'<text x="{w / 2}" y="52" text-anchor="middle" font-family="{font}" font-size="26" font-weight="700" '
        f'letter-spacing="2" fill="{c["title"]}">{escape(user)}</text>')
    add(f'<text x="{w / 2}" y="72" text-anchor="middle" font-family="{font}" font-size="11" letter-spacing="4" '
        f'fill="{c["muted"]}">CHRONICLE OF COMMITS{" (SAMPLE)" if offline else ""}</text>')
    add(f'<path d="M150 82 H{w / 2 - 10} M{w / 2 + 10} 82 H{w - 150}" stroke="{c["border"]}" stroke-width="1"/>')
    add(f'<path d="M{w / 2} 77 L{w / 2 + 5} 82 L{w / 2} 87 L{w / 2 - 5} 82 Z" fill="{c["accent"]}"/>')

    # number stats in a row
    tiles = [("repos", "REPOSITORIES", str(data["repos"])), ("followers", "FOLLOWERS", str(data["followers"])),
             ("stars", "STARS EARNED", str(data["stars"]))]
    tiles = [t for t in tiles if t[0] in SHOW_STATS]
    for i, (_, label, value) in enumerate(tiles):
        x = 40 + i * (w - 80) / max(len(tiles), 1)
        add(f'<text x="{x:.0f}" y="122" font-family="{font}" font-size="30" font-weight="700" fill="{c["accent"]}">{escape(value)}</text>')
        add(f'<text x="{x:.0f}" y="140" font-family="{font}" font-size="10" letter-spacing="2" fill="{c["muted"]}">{label}</text>')
    y = 168
    if "last_push" in SHOW_STATS:
        add(f'<text x="40" y="{y}" font-family="{font}" font-size="10" letter-spacing="2" fill="{c["muted"]}">LAST PUSH</text>')
        add(f'<text x="120" y="{y}" font-family="{font}" font-size="13" fill="{c["text"]}">{escape(human_date(data["last_push"]))}</text>')
        y += 28
    if "languages" in SHOW_STATS:
        langs = sorted(data["languages"].items(), key=lambda kv: kv[1], reverse=True)[:TOP_LANGUAGES]
        total = sum(data["languages"].values()) or 1   # share of ALL bytes; any remainder stays dark ("other")
        bar_x, bar_w = 40, w - 80
        add(f'<clipPath id="bar"><rect x="{bar_x}" y="{y - 10}" width="{bar_w}" height="10" rx="2"/></clipPath>')
        add(f'<rect x="{bar_x}" y="{y - 10}" width="{bar_w}" height="10" rx="2" fill="{c["panel"]}"/>')
        add('<g clip-path="url(#bar)">')
        x = float(bar_x)
        for i, (name, n) in enumerate(langs):
            seg = bar_w * n / total
            add(f'<rect x="{x:.1f}" y="{y - 10}" width="{seg:.1f}" height="10" fill="{LANGUAGE_COLORS[i % len(LANGUAGE_COLORS)]}"/>')
            x += seg
        add('</g>')
        lx = float(bar_x)
        for i, (name, n) in enumerate(langs):
            col = LANGUAGE_COLORS[i % len(LANGUAGE_COLORS)]
            label = f"{name} {100 * n / total:.0f}%"
            add(f'<rect x="{lx:.0f}" y="{y + 12}" width="8" height="8" fill="{col}"/>')
            add(f'<text x="{lx + 13:.0f}" y="{y + 20}" font-family="{font}" font-size="11" fill="{c["text"]}">{escape(label)}</text>')
            lx += 13 + 6.5 * len(label) + 12
    add('</svg>')
    return "\n".join(out)


def main() -> int:
    p = argparse.ArgumentParser(description="Render a gothic GitHub stats card as SVG.")
    p.add_argument("--user", default=USERNAME, help="GitHub username (default: USERNAME from CONFIG)")
    p.add_argument("--offline", action="store_true", help="skip the network and use built-in sample data")
    p.add_argument("--out", default=None, help="output file name inside output/ (default github_card.svg)")
    args = p.parse_args()

    if args.offline:
        data = SAMPLE_DATA
    else:
        if args.user == PLACEHOLDER:
            print(f'Set USERNAME in the CONFIG block (or pass --user NAME); "{PLACEHOLDER}" is only a placeholder.\n'
                  "Tip: try --offline to see the card with sample data.", file=sys.stderr)
            return 2
        try:
            data = fetch_stats(args.user)
        except GitHubError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    svg = render_svg(args.user, data, args.offline)
    out_dir = Path(__file__).resolve().parent / "output"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / (args.out or "github_card.svg")
    out.write_text(svg, encoding="utf-8")
    top = ", ".join(f"{k} {v / sum(data['languages'].values()) * 100:.0f}%" for k, v in
                    sorted(data["languages"].items(), key=lambda kv: kv[1], reverse=True)[:TOP_LANGUAGES]) or "none"
    print(f"{args.user}: {data['repos']} repos, {data['followers']} followers, {data['stars']} stars; languages: {top}")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
