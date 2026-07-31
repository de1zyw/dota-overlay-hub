"""Aggregate 'most banned heroes' meta stat.
NOTE: OpenDota's /heroStats only tracks `pro_ban` (professional matches) -
there is no public-bracket ban field. This shows pro-scene ban rates,
not "your MMR bracket this week"."""
from opendota_client import _cached_get


def fetch_top_banned_heroes(limit=10):
    heroes = _cached_get("/heroStats", ttl=3600) or []
    ranked = sorted(heroes, key=lambda h: h.get("pro_ban", 0), reverse=True)
    return [(h["localized_name"], h.get("pro_ban", 0)) for h in ranked[:limit]]
