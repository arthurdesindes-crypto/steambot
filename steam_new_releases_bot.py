#!/usr/bin/env python3
"""
Steam New Releases -> Discord Webhook
"""

import json
import os
import re
import time
from pathlib import Path

import requests

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "COLLE_TON_WEBHOOK_ICI")

STEAM_LANG = "french"
STEAM_CC = "FR"

SEEN_FILE = Path(__file__).parent / "seen_releases.json"

MAX_POSTS_PER_RUN = 7

GENRE_KEYWORDS = [
    "horror",
    "co-op",
    "coop",
    "adventure",
    "strategy",
    "simulation",
]

SLEEP_BETWEEN_CALLS = 1.5

HIDDEN_GEMS_ENABLED = True
MAX_HIDDEN_GEMS_PER_RUN = 3
HIDDEN_GEMS_MIN_POSITIVE_RATIO = 0.85
HIDDEN_GEMS_MAX_OWNERS = 3_000_000
HIDDEN_GEMS_MIN_REVIEWS = 50


def load_seen_ids() -> set:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen_ids(seen_ids: set) -> None:
    SEEN_FILE.write_text(json.dumps(sorted(seen_ids)))


def fetch_new_releases() -> list:
    url = "https://store.steampowered.com/api/featuredcategories/"
    params = {"l": STEAM_LANG, "cc": STEAM_CC}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data.get("new_releases", {}).get("items", [])


def fetch_app_details(app_id: int) -> dict | None:
    url = "https://store.steampowered.com/api/appdetails"
    params = {"appids": app_id, "l": STEAM_LANG, "cc": STEAM_CC}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    entry = data.get(str(app_id))
    if not entry or not entry.get("success"):
        return None

    d = entry["data"]
    app_type = d.get("type", "game")
    genres = [g["description"] for g in d.get("genres", [])]
    categories = [c["description"] for c in d.get("categories", [])]

    price_overview = d.get("price_overview")
    if price_overview:
        price_str = price_overview.get("final_formatted", "Prix inconnu")
    elif d.get("is_free"):
        price_str = "Gratuit"
    else:
        price_str = "Prix non annoncé"

    release_date = d.get("release_date", {}).get("date", "Date inconnue")

    return {
        "name": d.get("name", "Jeu inconnu"),
        "type": app_type,
        "url": f"https://store.steampowered.com/app/{app_id}",
        "header_image": d.get("header_image"),
        "short_description": d.get("short_description", ""),
        "genres": genres,
        "categories": categories,
        "price": price_str,
        "release_date": release_date,
    }


EXCLUDE_KEYWORDS = [
    "anime",
    "hentai",
    "ecchi",
    "nudity",
    "sexual content",
    "waifu",
    "harem",
    "visual novel",
    "2d",
    "pixel",
    "pixel art",
    "side-scroller",
    "platformer",
]

ALLOWED_NAME_PATTERN = re.compile(
    r"^[a-zA-Z0-9À-ÖØ-öø-ÿ\s\-:!?'\",.&()/+™®©_%#*\[\]]*$"
)


def has_disallowed_characters(name: str) -> bool:
    return not bool(ALLOWED_NAME_PATTERN.match(name))


def matches_exclude_filter(details: dict) -> bool:
    if has_disallowed_characters(details.get("name", "")):
        return True
    haystack = " ".join(
        details.get("genres", [])
        + details.get("categories", [])
        + [details.get("short_description", "")]
    ).lower()
    return any(keyword.lower() in haystack for keyword in EXCLUDE_KEYWORDS)


def matches_genre_filter(details: dict) -> bool:
    if not GENRE_KEYWORDS:
        return True
    haystack = " ".join(
        details.get("genres", [])
        + details.get("categories", [])
        + [details.get("short_description", "")]
    ).lower()
    return any(keyword.lower() in haystack for keyword in GENRE_KEYWORDS)


GENRE_EMOJIS = {
    "horror": "🕯️",
    "aventure": "🗺️", "adventure": "🗺️",
    "stratégie": "♟️", "strategy": "♟️",
    "simulation": "🛠️",
    "coop": "🤝", "co-op": "🤝",
    "action": "💥",
    "rpg": "🐉",
    "indie": "✨",
}


def pick_genre_emoji(details: dict) -> str:
    haystack = " ".join(details.get("genres", []) + details.get("categories", [])).lower()
    for keyword, emoji in GENRE_EMOJIS.items():
        if keyword in haystack:
            return emoji
    return "🎮"


def build_embed(app_id: int, details: dict) -> dict:
    emoji = pick_genre_emoji(details)
    tags = " • ".join(details["genres"][:4]) if details["genres"] else "Genre non précisé"
    extra_tags = [t for t in details["categories"] if "Coop" in t or "Multi" in t or "Solo" in t]

    description = details["short_description"][:280].strip()
    if len(details["short_description"]) > 280:
        description += "…"

    fields = [
        {"name": "🏷️ Genre", "value": tags, "inline": True},
        {"name": "💶 Prix", "value": details["price"], "inline": True},
        {"name": "📅 Sortie", "value": details["release_date"], "inline": True},
    ]
    if extra_tags:
        fields.append({"name": "👥 Mode", "value": ", ".join(extra_tags[:3]), "inline": True})

    return {
        "title": f"{emoji} {details['name']}",
        "url": details["url"],
        "description": description,
        "color": 0x66C0F4,
        "image": {"url": details["header_image"]} if details["header_image"] else None,
        "fields": fields,
        "footer": {"text": f"Steam • App ID {app_id}"},
    }


def post_to_discord(embed: dict) -> None:
    if not DISCORD_WEBHOOK_URL or "COLLE_TON_WEBHOOK_ICI" in DISCORD_WEBHOOK_URL:
        raise RuntimeError(
            "Le webhook Discord n'est pas configuré. "
            "Définis la variable d'environnement DISCORD_WEBHOOK_URL."
        )
    resp = requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]}, timeout=15)
    resp.raise_for_status()


def fetch_hidden_gem_candidates(seen_ids: set, pages: int = 2) -> list:
    candidates = []
    for page in range(pages):
        try:
            resp = requests.get(
                "https://steamspy.com/api.php",
                params={"request": "all", "page": page},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError):
            continue

        for app_id_str, info in data.items():
            app_id = int(app_id_str)
            if app_id in seen_ids:
                continue

            positive = info.get("positive", 0)
            negative = info.get("negative", 0)
            total_reviews = positive + negative
            if total_reviews < HIDDEN_GEMS_MIN_REVIEWS:
                continue

            ratio = positive / total_reviews
            if ratio < HIDDEN_GEMS_MIN_POSITIVE_RATIO:
                continue

            owners_str = info.get("owners", "0 .. 0")
            try:
                owners_upper = int(owners_str.split("..")[-1].replace(",", "").strip())
            except ValueError:
                continue
            if owners_upper > HIDDEN_GEMS_MAX_OWNERS:
                continue

            candidates.append((ratio, app_id))

    candidates.sort(reverse=True)
    return [app_id for _, app_id in candidates]


def build_hidden_gem_embed(app_id: int, details: dict) -> dict:
    embed = build_embed(app_id, details)
    embed["title"] = f"💎 Pépite méconnue — {details['name']}"
    embed["color"] = 0xF1C40F
    return embed


def post_hidden_gems(seen_ids: set) -> int:
    if not HIDDEN_GEMS_ENABLED:
        return 0

    posted = 0
    candidate_ids = fetch_hidden_gem_candidates(seen_ids)

    for app_id in candidate_ids:
        if posted >= MAX_HIDDEN_GEMS_PER_RUN:
            break
        if app_id in seen_ids:
            continue

        details = fetch_app_details(app_id)
        time.sleep(SLEEP_BETWEEN_CALLS)

        if details is None or details.get("type") != "game":
            seen_ids.add(app_id)
            continue

        if matches_exclude_filter(details) or not matches_genre_filter(details):
            seen_ids.add(app_id)
            continue

        embed = build_hidden_gem_embed(app_id, details)
        post_to_discord(embed)

        seen_ids.add(app_id)
        posted += 1
        print(f"Pépite postée : {details['name']} ({app_id})")

    return posted


def main() -> None:
    seen_ids = load_seen_ids()
    new_releases = fetch_new_releases()

    posted_count = 0
    for item in new_releases:
        app_id = item.get("id")
        if app_id is None or app_id in seen_ids:
            continue
        if posted_count >= MAX_POSTS_PER_RUN:
            break

        details = fetch_app_details(app_id)
        time.sleep(SLEEP_BETWEEN_CALLS)

        if details is None:
            seen_ids.add(app_id)
            continue

        if details.get("type") != "game":
            seen_ids.add(app_id)
            print(f"Ignoré (pas un jeu, type={details.get('type')}) : {details['name']}")
            continue

        if matches_exclude_filter(details):
            seen_ids.add(app_id)
            print(f"Ignoré (exclu) : {details['name']}")
            continue

        if not matches_genre_filter(details):
            seen_ids.add(app_id)
            print(f"Ignoré (genre non voulu) : {details['name']}")
            continue

        embed = build_embed(app_id, details)
        post_to_discord(embed)

        seen_ids.add(app_id)
        posted_count += 1
        print(f"Posté : {details['name']} ({app_id})")

    save_seen_ids(seen_ids)
    print(f"Terminé. {posted_count} nouvelle(s) sortie(s) postée(s).")

    gems_posted = post_hidden_gems(seen_ids)
    save_seen_ids(seen_ids)
    print(f"{gems_posted} pépite(s) méconnue(s) postée(s).")


if __name__ == "__main__":
    main()
