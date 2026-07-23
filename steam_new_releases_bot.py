#!/usr/bin/env python3
"""
Steam New Releases -> Discord Webhook

Ce script :
1. Interroge l'API publique de Steam pour récupérer les jeux "nouvelles sorties".
2. Pour chaque jeu pas encore posté, récupère les détails (genre, prix, date de sortie).
3. Poste un joli embed dans un salon Discord via un webhook.
4. Mémorise les jeux déjà postés dans un fichier JSON pour ne jamais les reposter.

À lancer périodiquement (ex: toutes les 30 min) via cron ou un timer systemd.
"""

import json
import os
import time
from pathlib import Path

import requests

# ----------------------------------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------------------------------

# Colle ici l'URL de ton webhook Discord (Paramètres du salon > Intégrations > Webhooks)
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "COLLE_TON_WEBHOOK_ICI")

# Langue et devise utilisées pour interroger Steam (fr = français, cc=FR pour les prix en euros)
STEAM_LANG = "french"
STEAM_CC = "FR"

# Fichier qui garde en mémoire les jeux déjà annoncés, pour ne jamais les reposter
SEEN_FILE = Path(__file__).parent / "seen_releases.json"

# Nombre max de nouveaux jeux à annoncer en une seule exécution
# (évite de spammer le salon si le script n'a pas tourné depuis longtemps)
MAX_POSTS_PER_RUN = 10

# Pause entre deux appels à l'API Steam (pour rester correct avec leurs serveurs)
SLEEP_BETWEEN_CALLS = 1.5


# ----------------------------------------------------------------------------
# LOGIQUE
# ----------------------------------------------------------------------------

def load_seen_ids() -> set:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen_ids(seen_ids: set) -> None:
    SEEN_FILE.write_text(json.dumps(sorted(seen_ids)))


def fetch_new_releases() -> list:
    """Récupère la liste des nouvelles sorties depuis la page d'accueil Steam."""
    url = "https://store.steampowered.com/api/featuredcategories/"
    params = {"l": STEAM_LANG, "cc": STEAM_CC}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data.get("new_releases", {}).get("items", [])


def fetch_app_details(app_id: int) -> dict | None:
    """Récupère genre, prix, description et date de sortie pour un jeu donné."""
    url = "https://store.steampowered.com/api/appdetails"
    params = {"appids": app_id, "l": STEAM_LANG, "cc": STEAM_CC}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    entry = data.get(str(app_id))
    if not entry or not entry.get("success"):
        return None

    d = entry["data"]

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
        "url": f"https://store.steampowered.com/app/{app_id}",
        "header_image": d.get("header_image"),
        "short_description": d.get("short_description", ""),
        "genres": genres,
        "categories": categories,
        "price": price_str,
        "release_date": release_date,
    }


def build_embed(app_id: int, details: dict) -> dict:
    tags = ", ".join(details["genres"][:4]) if details["genres"] else "Genre non précisé"
    extra_tags = [t for t in details["categories"] if "Coop" in t or "Multi" in t or "Solo" in t]

    fields = [
        {"name": "Genre", "value": tags, "inline": True},
        {"name": "Prix", "value": details["price"], "inline": True},
        {"name": "Sortie", "value": details["release_date"], "inline": True},
    ]
    if extra_tags:
        fields.append({"name": "Mode", "value": ", ".join(extra_tags[:3]), "inline": True})

    return {
        "title": f"🎮 {details['name']}",
        "url": details["url"],
        "description": details["short_description"][:300],
        "color": 0x1B2838,  # bleu Steam
        "image": {"url": details["header_image"]} if details["header_image"] else None,
        "fields": fields,
        "footer": {"text": f"App ID: {app_id} • Steam"},
    }


def post_to_discord(embed: dict) -> None:
    if not DISCORD_WEBHOOK_URL or "COLLE_TON_WEBHOOK_ICI" in DISCORD_WEBHOOK_URL:
        raise RuntimeError(
            "Le webhook Discord n'est pas configuré. "
            "Définis la variable d'environnement DISCORD_WEBHOOK_URL."
        )
    resp = requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]}, timeout=15)
    resp.raise_for_status()


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
            # On marque quand même comme vu pour ne pas boucler dessus indéfiniment
            seen_ids.add(app_id)
            continue

        embed = build_embed(app_id, details)
        post_to_discord(embed)

        seen_ids.add(app_id)
        posted_count += 1
        print(f"Posté : {details['name']} ({app_id})")

    save_seen_ids(seen_ids)
    print(f"Terminé. {posted_count} nouveau(x) jeu(x) posté(s).")


if __name__ == "__main__":
    main()
