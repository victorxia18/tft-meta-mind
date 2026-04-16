"""Translate Riot API IDs to human-readable names using Data Dragon.

Maps champion IDs, item IDs, and trait IDs to their display names
using Riot's Data Dragon CDN.

Usage:
    python -m utils.data_dragon
"""

import logging
import requests

logger = logging.getLogger(__name__)

DDRAGON_BASE = "https://ddragon.leagueoflegends.com"

# Manual overrides for special unit IDs that Data Dragon doesn't resolve.
MANUAL_CHAMPION_OVERRIDES = {
    "TFT17_Reksai": "Rek'Sai",
    # Old set - kept for reference
    # "TFT16_AnnieTibbers": "Annie & Tibbers",
}


class DataDragon:
    """Fetches and caches TFT static data from Riot's Data Dragon CDN."""

    def __init__(self):
        self.version = self._get_latest_version()
        self._champions: dict | None = None
        self._items: dict | None = None
        self._traits: dict | None = None

    def _get_latest_version(self) -> str:
        url = f"{DDRAGON_BASE}/api/versions.json"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()[0]

    def _fetch_json(self, filename: str) -> dict:
        url = f"{DDRAGON_BASE}/cdn/{self.version}/data/en_US/{filename}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()

    # ── Lazy-loaded lookups ──────────────────────────

    @property
    def champions(self) -> dict[str, dict]:
        """Map keyed by short ID (e.g. 'TFT16_Fizz') -> {"name", "cost"}."""
        if self._champions is None:
            data = self._fetch_json("tft-champion.json")
            self._champions = {}
            for key, champ in data.get("data", {}).items():
                # DDragon keys look like:
                #   Maps/Shipping/Map22/Sets/TFTSet16/Shop/TFT16_Fizz
                # Extract the short ID after the last '/'
                short_id = key.rsplit("/", 1)[-1] if "/" in key else key
                self._champions[short_id] = {
                    "name": champ.get("name", short_id),
                    "cost": champ.get("tier", 0),
                }
        return self._champions

    @property
    def items(self) -> dict[str, dict]:
        """Map keyed by multiple forms of item ID -> {"name"}."""
        if self._items is None:
            data = self._fetch_json("tft-item.json")
            self._items = {}
            for key, item in data.get("data", {}).items():
                name = item.get("name", key)
                # Store under the full DDragon key
                short_key = key.rsplit("/", 1)[-1] if "/" in key else key
                self._items[short_key] = {"name": name}
                # Also store under the short name without TFT_Item_ prefix
                # e.g. "TFT_Item_PowerGauntlet" -> also keyed as "PowerGauntlet"
                for prefix in ("TFT_Item_", "TFT_Item_Artifact_"):
                    if short_key.startswith(prefix):
                        bare = short_key[len(prefix):]
                        self._items[bare] = {"name": name}
        return self._items

    @property
    def traits(self) -> dict[str, dict]:
        """Map keyed by short trait ID (e.g. 'TFT16_Void') -> {"name"}."""
        if self._traits is None:
            data = self._fetch_json("tft-trait.json")
            self._traits = {}
            for key, trait in data.get("data", {}).items():
                short_id = key.rsplit("/", 1)[-1] if "/" in key else key
                self._traits[short_id] = {"name": trait.get("name", short_id)}
        return self._traits

    # ── Simple lookup methods ────────────────────────

    def champion_name(self, champion_id: str) -> str:
        """Return human name for a champion ID, or the raw ID if unknown."""
        if champion_id in MANUAL_CHAMPION_OVERRIDES:
            return MANUAL_CHAMPION_OVERRIDES[champion_id]
        return self.champions.get(champion_id, {}).get("name", champion_id)

    def champion_cost(self, champion_id: str) -> int:
        """Return the gold cost of a champion, or 0 if unknown."""
        return self.champions.get(champion_id, {}).get("cost", 0)

    def item_name(self, item_id: str) -> str:
        """Return human name for an item ID, or the raw ID if unknown."""
        return self.items.get(str(item_id), {}).get("name", str(item_id))

    def trait_name(self, trait_id: str) -> str:
        """Return human name for a trait ID, or the raw ID if unknown."""
        return self.traits.get(trait_id, {}).get("name", trait_id)


if __name__ == "__main__":
    print("Initializing Data Dragon...")
    dd = DataDragon()
    print(f"Version: {dd.version}")
    print(f"Loaded {len(dd.champions)} champions, {len(dd.items)} items, {len(dd.traits)} traits")

    # Sample champion lookups
    print("\n--- Champion Lookups ---")
    for cid in ["TFT17_Briar", "TFT17_Belveth", "TFT17_MissFortune", "TFT17_Akali", "TFT17_Bard", "FakeChamp123"]:
        print(f"  {cid} -> {dd.champion_name(cid)} (cost {dd.champion_cost(cid)})")

    # Sample item lookups
    print("\n--- Item Lookups ---")
    for iid in ["PowerGauntlet", "ThiefsGloves", "MadredsBloodrazor", "Bloodthirster", "FakeItem999"]:
        print(f"  {iid} -> {dd.item_name(iid)}")

    # Sample trait lookups
    print("\n--- Trait Lookups ---")
    for tid in ["TFT17_Void", "TFT17_Magus", "TFT17_Warden", "FakeTrait"]:
        print(f"  {tid} -> {dd.trait_name(tid)}")
