"""Shared place categories and lightweight intent parsing for search."""

import re
import unicodedata


PLACE_TYPES_BY_CATEGORY = {
    "cafe": ("Cafe", "Ice cream shop"),
    "restaurant": ("Restaurant", "Fast food restaurant", "Food court"),
    "playground": ("Playground",),
    "school": ("School", "College", "University", "Kindergarten", "Education campus"),
    "library": ("Library",),
    "healthcare": (
        "Hospital", "Clinic", "Doctor", "Dentist", "Pharmacy", "Veterinary clinic",
    ),
    "transport": (
        "Train station", "Railway halt", "Tram stop", "Subway station", "Bus stop",
        "Bus station", "Transit stop", "Ferry terminal", "Taxi stand",
        "Transit station",
    ),
    "sports": (
        "Sports centre", "Swimming pool", "Fitness centre", "Stadium", "Sports pitch",
        "Golf course", "Dog park",
    ),
    "services": (
        "Bank", "ATM", "Post office", "Public toilet", "Community centre",
        "Place of worship", "Police station", "Fire station", "Town hall",
    ),
    "stay": ("Hotel", "Hostel", "Guest house", "Camp site", "Holiday apartment"),
    "fishing": ("Fishing area",),
    "museum": ("Museum",),
    "water": ("Water feature", "Lake", "River", "Canal"),
    "attraction": (
        "Attraction", "Museum", "Art gallery", "Zoo", "Aquarium",
        "Theme park", "Viewpoint", "Historic site", "Historic monument", "Memorial",
        "Cinema", "Theatre", "Arts centre", "Place of worship",
    ),
    "park": ("Park", "Garden", "Nature reserve", "Recreation ground"),
    "shopping": (
        "Shopping centre", "Department store", "Appliance shop", "Electronics shop",
        "Supermarket", "Variety store", "Marketplace", "Book shop", "Clothing shop",
        "Convenience store", "Bakery", "Pharmacy", "Hardware shop", "Bicycle shop",
        "Sports shop", "Toy shop", "Gift shop", "Shoe shop", "Outdoor equipment shop",
    ),
}


_INTENT_PATTERNS = {
    "cafe": re.compile(r"\b(?:caf[eé]s?|coffee(?:\s*house|\s*shop)?|espresso|tea\s+shop|ice[- ]cream)\b"),
    "restaurant": re.compile(r"\b(?:restaurants?|dining|sushi|ramen|pizza|burgers?|lunch|dinner|eat(?:ing)?\s+(?:out|place)|food)\b"),
    "playground": re.compile(r"\b(?:playgrounds?|play\s+areas?|swings?)\b"),
    "school": re.compile(
        r"\b(?:schools?|kindergartens?|colleges?|universit(?:y|ies)|daycares?|campuses|education)\b"
    ),
    "library": re.compile(r"\b(?:libraries|library)\b"),
    "healthcare": re.compile(
        r"\b(?:hospitals?|clinics?|doctors?|dentists?|pharmacies|pharmacy|chemists?|vets?|"
        r"veterinarians?|medical\s+cent(?:er|re)s?)\b"
    ),
    "transport": re.compile(
        r"\b(?:(?:train|railway|subway|metro|tram|bus)\s+stations?|bus\s+stops?|tram\s+stops?|"
        r"transit|public\s+transport|ferry\s+terminals?|taxi\s+stands?)\b"
    ),
    "sports": re.compile(
        r"\b(?:sports?\s+(?:cent(?:er|re)s?|grounds?|fields?)|swimming\s+pools?|fitness\s+"
        r"cent(?:er|re)s?|stadiums?|golf\s+courses?|dog\s+parks?)\b"
    ),
    "services": re.compile(
        r"\b(?:banks?|atms?|post\s+offices?|public\s+toilets?|restrooms?|community\s+"
        r"cent(?:er|re)s?|places\s+of\s+worship|police\s+stations?|fire\s+stations?|town\s+halls?)\b"
    ),
    "stay": re.compile(r"\b(?:hotels?|hostels?|guest\s+houses?|camp\s+sites?|holiday\s+apartments?)\b"),
    "fishing": re.compile(r"\b(?:fishing|angling|fishery|fishing\s+areas?)\b"),
    "museum": re.compile(r"\b(?:museums?|musuems?|musuem|exhibitions?)\b"),
    "water": re.compile(r"\b(?:waterfronts?|lakes?|rivers?|canals?|water\s+features?|place\s+by\s+(?:the\s+)?water)\b"),
    "attraction": re.compile(
        r"\b(?:attractions?|sightseeing|tourist\s+spots?|landmarks?|must[- ]see|cinemas?|"
        r"movie\s+theaters?|movie\s+theatres?|theaters?|theatres?|art\s+galleries?|zoos?|"
        r"aquariums?|theme\s+parks?|viewpoints?)\b"
    ),
    "park": re.compile(r"\b(?:parks?|gardens?|nature\s+reserves?|green\s+spaces?|picnic\s+spots?)\b"),
    "shopping": re.compile(
        r"\b(?:shopping|buy|purchase|supermarkets?|department\s+stores?|shopping\s+"
        r"(?:centres?|centers?|malls?)|malls?|electronics|appliances?|washing\s+machines?|"
        r"refrigerators?|dishwashers?|book\s+shops?|bookstores?|clothing\s+shops?|"
        r"convenience\s+stores?|bakeries|baker(?:y)?|hardware\s+shops?|bicycle\s+shops?|"
        r"sports\s+shops?|toy\s+shops?|gift\s+shops?|shoe\s+shops?|pharmacies|"
        r"outdoor\s+equipment\s+shops?|stores?|shop\s+for)\b"
    ),
}


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _category_mentions(question: str) -> tuple[list[str], list[str]]:
    normalized = _normalize(question)
    matches = []
    for category, pattern in _INTENT_PATTERNS.items():
        for match in pattern.finditer(normalized):
            prefix = normalized[max(0, match.start() - 30):match.start()]
            is_location_context = re.search(
                r"\b(?:near|around|by|close\s+to|next\s+to|beside)\s+(?:(?:the|a|an|my)\s+)?(?:city\s+)?$",
                prefix,
            )
            matches.append((match.start(), category, bool(is_location_context)))
    # Coffee shop and tea shop are cafes, not retail shopping destinations.
    if re.search(r"\b(?:coffee|tea)\s+shop\b", normalized):
        matches = [item for item in matches if item[1] != "shopping"]
    target_matches = [item for item in matches if not item[2]]
    targets = list(dict.fromkeys(category for _, category, _ in sorted(target_matches)))
    mentioned = list(dict.fromkeys(category for _, category, _ in sorted(matches)))
    return targets, mentioned


def infer_categories(question: str) -> list[str]:
    """Find explicit place types, preserving their order of mention."""
    targets, mentioned = _category_mentions(question)
    return targets or mentioned


def effective_categories(question: str, focus_category: str | None) -> tuple[list[str], str]:
    """Use explicit request intent first; apply the focus chip only as a fallback."""
    requested, mentioned = _category_mentions(question)
    if requested:
        return requested, "prompt"
    if focus_category:
        return [focus_category], "focus"
    if mentioned:
        return mentioned, "prompt"
    return [], "all"


def category_label(category: str) -> str:
    return {
        "cafe": "Cafés",
        "restaurant": "Restaurants",
        "playground": "Playgrounds",
        "school": "Schools and universities",
        "library": "Libraries",
        "healthcare": "Healthcare",
        "transport": "Transport",
        "sports": "Sports and recreation",
        "services": "Public services",
        "stay": "Places to stay",
        "fishing": "Fishing areas",
        "museum": "Museums",
        "water": "Waterfronts and water features",
        "attraction": "Attractions",
        "park": "Parks",
        "shopping": "Shopping",
    }.get(category, category.replace("_", " ").title())
