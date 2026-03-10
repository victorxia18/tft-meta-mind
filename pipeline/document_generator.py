"""Convert raw scraped data into natural language documents for RAG ingestion.

Takes structured data from the tactics.tools scraper and generates readable
text documents that can be embedded and stored in the vector database.

Usage:
    python -m pipeline.document_generator
"""

import glob
import json
import logging
from collections import Counter
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class TFTDocumentGenerator:
    """Converts raw TFT data into natural language documents for RAG."""

    def __init__(self, data_dragon=None):
        self.dd = data_dragon

    def _champ_name(self, champion_id: str) -> str:
        if self.dd:
            return self.dd.champion_name(champion_id)
        return champion_id

    def _item_name(self, item_id: str) -> str:
        if self.dd:
            return self.dd.item_name(item_id)
        return item_id

    def _trait_name(self, trait_id: str) -> str:
        if self.dd:
            return self.dd.trait_name(trait_id)
        return trait_id

    def _infer_comp_name(self, carry_units: list, traits: list) -> str:
        """Infer a comp name from carry units and active traits.

        carry_units: list of [champion_id, carry_score] pairs
        traits: list of [trait_id, tier, count, avg_place] tuples
        """
        parts = []

        # Use top carry units (highest carry score) for the name
        if carry_units:
            top_carries = carry_units[:2]
            parts = [self._champ_name(c[0]) for c in top_carries]

        # If we have traits, pick the most prominent one
        if traits and len(parts) < 2:
            # Sort by count descending to find the dominant trait
            sorted_traits = sorted(traits, key=lambda t: t[2], reverse=True)
            for t in sorted_traits:
                tname = self._trait_name(t[0])
                if tname not in parts:
                    parts.append(tname)
                    break

        return " / ".join(parts) if parts else "Unknown Comp"

    def _describe_units(self, unit_ids: list[str]) -> str:
        """Turn a unit ID list (with duplicates for stars) into readable text.

        Duplicates indicate star level: 2 copies = 2-star, 3 copies = 3-star.
        """
        counts = Counter(unit_ids)
        descriptions = []
        for uid, count in counts.items():
            name = self._champ_name(uid)
            if count >= 3:
                descriptions.append(f"{name} (3-star)")
            elif count == 2:
                descriptions.append(f"{name} (2-star)")
            else:
                descriptions.append(name)
        return ", ".join(descriptions)

    def generate_meta_snapshot(self, comps_data: dict, units_data: dict,
                               date: str | None = None) -> dict:
        """Generate a daily meta overview from comp and unit stats.

        Args:
            comps_data: The 'comps' section from scraped JSON (has 'groups' key).
            units_data: The 'units' section from scraped JSON.
            date: Override date string (YYYY-MM-DD).

        Returns:
            {"text": str, "metadata": dict} for RAG ingestion.
        """
        date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

        groups = comps_data.get("groups", [])
        if not groups:
            return {
                "text": f"# TFT Meta Snapshot — {date}\n\nNo comp data available.",
                "metadata": {
                    "source": "tactics_tools",
                    "type": "meta_snapshot",
                    "date": date,
                    "patch": "current",
                },
            }

        # Build a list of processed comp groups
        processed = []
        for group in groups:
            full = group.get("full", {})
            variants = full.get("comps", [])
            if not variants:
                continue

            # Pick the most-played variant (highest count)
            best_variant = max(variants, key=lambda c: c.get("count", 0))

            count = best_variant.get("count", 0)
            if count == 0:
                continue

            avg_place = best_variant.get("place", 9.0)
            top4_rate = (best_variant.get("top4", 0) / count) * 100
            win_rate = (best_variant.get("win", 0) / count) * 100

            # Use group-level aggregate stats for the overall picture
            group_count = full.get("count", count)
            group_place = full.get("place", avg_place)

            carry_units = full.get("carryUnits", [])
            traits = full.get("traits", [])
            comp_name = self._infer_comp_name(carry_units, traits)

            unit_desc = self._describe_units(best_variant.get("units", []))

            # Top traits for this comp
            top_traits = []
            if traits:
                # Sort by count descending, take top 3
                for t in sorted(traits, key=lambda x: x[2], reverse=True)[:3]:
                    top_traits.append(self._trait_name(t[0]))

            processed.append({
                "name": comp_name,
                "avg_place": avg_place,
                "group_place": group_place,
                "top4_rate": top4_rate,
                "win_rate": win_rate,
                "count": count,
                "group_count": group_count,
                "unit_desc": unit_desc,
                "top_traits": top_traits,
            })

        # Sort by best variant's average placement
        processed.sort(key=lambda c: c["avg_place"])

        lines = [
            f"# TFT Meta Snapshot — {date}",
            "",
            "## Top Performing Team Compositions",
            "",
            "The following comps are ranked by average placement "
            "in high-elo (Grandmaster+) games.",
            "",
        ]

        for i, comp in enumerate(processed[:10], 1):
            lines.append(f"## {i}. {comp['name']}")
            lines.append(
                f"Average Placement: {comp['avg_place']:.2f} | "
                f"Top 4 Rate: {comp['top4_rate']:.1f}% | "
                f"Win Rate: {comp['win_rate']:.1f}% | "
                f"Games: {comp['count']}"
            )
            lines.append(f"Core Units: {comp['unit_desc']}")
            if comp["top_traits"]:
                lines.append(f"Key Traits: {', '.join(comp['top_traits'])}")
            lines.append(
                f"Across all variants of this archetype: "
                f"{comp['group_count']} games, "
                f"{comp['group_place']:.2f} avg placement."
            )
            lines.append("")

        text = "\n".join(lines)

        return {
            "text": text,
            "metadata": {
                "source": "tactics_tools",
                "type": "meta_snapshot",
                "date": date,
                "patch": "current",
            },
        }

    def generate_unit_document(self, units_data: dict,
                                date: str | None = None) -> dict:
        """Generate a champion tier list document from unit stats.

        Args:
            units_data: The 'units' section from scraped JSON.
            date: Override date string (YYYY-MM-DD).

        Returns:
            {"text": str, "metadata": dict} for RAG ingestion.
        """
        date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

        units = units_data.get("units", {})
        total_entries = units_data.get("totalEntries", 0)

        if not units:
            return {
                "text": f"# TFT Unit Analysis — {date}\n\nNo unit data available.",
                "metadata": {
                    "source": "tactics_tools",
                    "type": "unit_analysis",
                    "date": date,
                    "patch": "current",
                },
            }

        # Build unit list with translated names
        unit_list = []
        for uid, stats in units.items():
            unit_list.append({
                "id": uid,
                "name": self._champ_name(uid),
                "count": stats.get("count", 0),
                "place": stats.get("place", 9.0),
                "top4": stats.get("top4", 0),
                "won": stats.get("won", 0),
                "top_items": [self._item_name(i) for i in stats.get("topItems", [])[:3]],
                "star_count": stats.get("starCount", 0),
                "star_place": stats.get("starPlace", 0),
                "star_top4": stats.get("starTop4", 0),
                "star_won": stats.get("starWon", 0),
            })

        # Sort by average placement (lower = better)
        unit_list.sort(key=lambda u: u["place"])

        # Tier thresholds
        tiers = [
            ("S-Tier Units (Avg Placement < 4.0)", lambda u: u["place"] < 4.0),
            ("A-Tier Units (Avg Placement 4.0–4.3)", lambda u: 4.0 <= u["place"] < 4.3),
            ("B-Tier Units (Avg Placement 4.3–4.6)", lambda u: 4.3 <= u["place"] < 4.6),
            ("C-Tier Units (Avg Placement 4.6+)", lambda u: u["place"] >= 4.6),
        ]

        lines = [
            f"# TFT Unit Analysis — {date}",
            "",
            f"Unit performance stats based on {total_entries:,} high-elo games.",
            "",
        ]

        for tier_name, tier_filter in tiers:
            tier_units = [u for u in unit_list if tier_filter(u)]
            if not tier_units:
                continue

            for u in tier_units:
                items_str = ", ".join(u["top_items"]) if u["top_items"] else "N/A"
                lines.append(f"## {u['name']} ({tier_name})")
                line = (
                    f"Avg Place {u['place']:.2f}, "
                    f"Top 4 {u['top4']:.1f}%, Win {u['won']:.1f}%. "
                    f"Best items: {items_str}."
                )
                if u["star_count"] > 0:
                    line += (
                        f" When 3-starred ({u['star_count']} games), "
                        f"avg place drops to {u['star_place']:.2f} "
                        f"with {u['star_top4']:.1f}% top 4 rate."
                    )
                lines.append(line)
                lines.append("")

        text = "\n".join(lines)

        return {
            "text": text,
            "metadata": {
                "source": "tactics_tools",
                "type": "unit_analysis",
                "date": date,
                "patch": "current",
            },
        }


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from utils.data_dragon import DataDragon

    # Load most recent scraped data
    files = sorted(glob.glob("data/raw/tactics_tools_*.json"))
    if not files:
        print("No scraped data found in data/raw/. Run the scraper first.")
        raise SystemExit(1)

    latest = files[-1]
    print(f"Loading data from: {latest}")
    with open(latest) as f:
        raw = json.load(f)

    print("Initializing Data Dragon...")
    dd = DataDragon()

    gen = TFTDocumentGenerator(data_dragon=dd)

    comps_data = raw.get("comps", {})
    units_data = raw.get("units", {})

    print("\n" + "=" * 60)
    print("META SNAPSHOT")
    print("=" * 60)
    meta_doc = gen.generate_meta_snapshot(comps_data, units_data)
    print(meta_doc["text"])
    print(f"\n[Metadata: {meta_doc['metadata']}]")

    print("\n" + "=" * 60)
    print("UNIT ANALYSIS")
    print("=" * 60)
    unit_doc = gen.generate_unit_document(units_data)
    print(unit_doc["text"])
    print(f"\n[Metadata: {unit_doc['metadata']}]")
