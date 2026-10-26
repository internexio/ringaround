"""
Google Places Text Search directory provider (Places API v1, Nov 2023+).

Searches for contractors by category + zip code. Returns only results that
have a phone number. Deduplicates by phone to avoid calling the same
business twice from different search result pages.

Requires: GOOGLE_PLACES_API_KEY env var.

Category → search query mapping covers the main home service verticals.
Add entries to CATEGORY_QUERIES as you expand to new markets.
"""
from __future__ import annotations
import os
import re
import httpx
from ringaround.models import Contractor, ProjectRequest

_PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
_FIELD_MASK = (
    "places.id,"
    "places.displayName,"
    "places.nationalPhoneNumber,"
    "places.formattedAddress,"
    "places.rating,"
    "places.userRatingCount"
)

# category value → human search phrase
CATEGORY_QUERIES: dict[str, str] = {
    "bathroom_remodel":     "bathroom remodel contractor",
    "kitchen_remodel":      "kitchen remodel contractor",
    "roofing":              "roofing contractor",
    "hvac":                 "HVAC contractor",
    "plumbing":             "plumber",
    "electrical":           "electrician",
    "painting":             "painting contractor",
    "flooring":             "flooring contractor",
    "windows_doors":        "window and door replacement contractor",
    "landscaping":          "landscaping contractor",
    "concrete_masonry":     "concrete masonry contractor",
    "gutters":              "gutter installation contractor",
    "insulation":           "insulation contractor",
    "solar":                "solar panel installer",
    "deck_patio":           "deck and patio contractor",
    # restaurant intel
    "restaurant_supply":    "restaurant supply distributor",
    # auto
    "auto_repair":          "auto repair shop",
    # dental
    "dental_lab":           "dental laboratory",
}

_E164_RE = re.compile(r"^\+?1?\d{10}$")


def _normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return None


class GooglePlacesProvider:
    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.getenv("GOOGLE_PLACES_API_KEY")

    async def find_contractors(
        self,
        project: ProjectRequest,
        limit: int = 20,
    ) -> list[Contractor]:
        if not self._api_key:
            raise RuntimeError("GOOGLE_PLACES_API_KEY not set")

        query_phrase = CATEGORY_QUERIES.get(
            project.category,
            f"{project.category.replace('_', ' ')} contractor",
        )
        text_query = f"{query_phrase} near {project.zip_code}"

        contractors: list[Contractor] = []
        seen_phones: set[str] = set()

        # Places API returns up to 20 per page; two pages covers 40 candidates
        page_token: str | None = None
        for _ in range(2):
            if len(contractors) >= limit:
                break
            payload: dict = {
                "textQuery": text_query,
                "locationBias": {
                    "circle": {
                        "center": {"latitude": 0, "longitude": 0},  # overridden by zip query
                        "radius": 80467,  # 50 miles in metres
                    }
                },
                "maxResultCount": min(20, limit - len(contractors)),
                "languageCode": "en",
            }
            if page_token:
                payload["pageToken"] = page_token

            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self._api_key,
                "X-Goog-FieldMask": _FIELD_MASK,
            }

            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(_PLACES_URL, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
            except Exception:
                break

            for place in data.get("places", []):
                raw_phone = place.get("nationalPhoneNumber", "")
                if not raw_phone:
                    continue
                phone = _normalize_phone(raw_phone)
                if not phone or phone in seen_phones:
                    continue
                seen_phones.add(phone)

                name = place.get("displayName", {}).get("text", "Unknown")
                # Extract zip from formatted address as a best-effort
                address = place.get("formattedAddress", "")
                zip_match = re.search(r"\b(\d{5})\b", address)
                zip_code = zip_match.group(1) if zip_match else project.zip_code

                contractors.append(Contractor(
                    name=name,
                    phone=phone,
                    zip_code=zip_code,
                    category=project.category,
                    source="google_places",
                    place_id=place.get("id"),
                ))
                if len(contractors) >= limit:
                    break

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        return contractors
