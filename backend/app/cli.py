"""Command-line interface for ingesting, indexing and asking the RAG system."""

import argparse
import asyncio
from collections import Counter
import json
import sys
from pathlib import Path

from .config import PROJECT_ROOT
from .ollama import grounded_answer
from .place_categories import effective_categories
from .places import SNAPSHOT_METADATA_PATH, fetch_places, load_local_osm
from .place_verification import use_recent_snapshot, verify_recommendations
from .routing import plan_route
from .vector_store import build_index, search_places


def _ingest(args: argparse.Namespace) -> int:
    if args.file:
        source_count, place_count = load_local_osm(args.file)
        source = str(args.file)
    else:
        source_count, place_count = fetch_places()
        metadata = json.loads(SNAPSHOT_METADATA_PATH.read_text(encoding="utf-8"))
        source = {
            "overpass": "OpenStreetMap Overpass full-area refresh",
            "photon_partial": "Photon partial OpenStreetMap lookup",
            "photon_partial_merge": "Photon partial lookup merged with the previous OSM dataset",
        }.get(metadata.get("source"), "OpenStreetMap local import")
    print(f"Source: {source}")
    print(f"Read {source_count} source records and saved {place_count} geolocated places to data/places.json.")
    saved_places = json.loads((PROJECT_ROOT / "data" / "places.json").read_text(encoding="utf-8"))
    counts = Counter(place.get("place_type", "Place") for place in saved_places)
    healthcare = sum(counts[name] for name in ("Hospital", "Clinic", "Doctor", "Dentist", "Pharmacy", "Veterinary clinic"))
    libraries = counts["Library"]
    transit = sum(counts[name] for name in ("Train station", "Railway halt", "Tram stop", "Subway station", "Bus stop", "Bus station", "Transit stop", "Transit station"))
    print(
        "Coverage check — education: "
        f"schools {counts['School']}, colleges {counts['College']}, universities {counts['University']}, "
        f"kindergartens {counts['Kindergarten']}, campuses {counts['Education campus']}; "
        f"libraries {libraries}, healthcare {healthcare}, transit {transit}."
    )
    print("Next: python -m app.cli index")
    return 0


def _index(_args: argparse.Namespace) -> int:
    place_count, chunk_count = build_index()
    print(f"Indexed {place_count} places as {chunk_count} chunks in the Milvus collection.")
    print("Next: python -m app.cli ask \"Find a cafe near Europaplatz\"")
    return 0


def _ask(args: argparse.Namespace) -> int:
    question = args.question or input("What would you like to find in Karlsruhe? ").strip()
    if not question:
        print("Please enter a question with at least three characters.", file=sys.stderr)
        return 2
    categories, _intent_source = effective_categories(question, None)
    candidates = search_places(
        question,
        args.limit,
        candidate_count=max(args.limit * 12, 60),
        category=categories or None,
    )
    places, verification = asyncio.run(
        verify_recommendations(candidates, limit=args.limit, expected_categories=categories)
    )
    if not places and verification["mode"] == "osm_unavailable":
        places, verification = use_recent_snapshot(
            candidates,
            verification,
            limit=args.limit,
            candidate_limit=max(args.limit * 4, 20),
            expected_categories=categories,
        )
    places, route = plan_route(places, args.origin, limit=args.limit)
    answer, model_status = grounded_answer(
        question, places, route, use_llm=verification["mode"] != "osm_snapshot"
    )

    if args.json:
        print(json.dumps({
            "question": question,
            "retrieved_contexts": places,
            "route": route,
            "answer": answer,
            "model_status": model_status,
            "verification": verification,
        }, ensure_ascii=False, indent=2))
        return 0

    print(f"\nQuestion: {question}")
    print(f"Place data status: {verification['message']}")
    print(f"Starting point: {route['origin']['label']}")
    print("\nRetrieved context:")
    if not places:
        print("  No matching place records were retrieved.")
    for place in places:
        print(
            f"  {place['route_order']}. {place['name']} — {place['place_type']} "
            f"(semantic score {place['score']:.3f}; {place['leg_distance_km']:.2f} km from previous stop)"
        )
        print(f"     {place['description']}")
        print(f"     OSM source: {place['source_url']}")
    distance_label = "walking route" if route["mode"] == "walking" else "straight-line estimate"
    print(f"\nSuggested route: {route['distance_km']:.2f} km {distance_label}")
    print(f"  {route['disclaimer']}")
    print(f"\nRecommendation ({model_status}):\n{answer}")
    return 0


DEMO_QUERIES = (
    {"question": "Find a sushi restaurant near my starting point", "origin": "49.0093, 8.4020"},
    {"question": "Plan an afternoon with two kids: find attractions and playgrounds", "origin": "49.0093, 8.4020"},
    {"question": "Where can I shop for a washing machine or household appliance?", "origin": "49.0093, 8.4020"},
    {"question": "Find a relaxed cafe for a coffee break", "origin": "49.0093, 8.4020"},
    {"question": "Suggest an outdoor visit with a park and a place by water", "origin": "49.0093, 8.4020"},
)


def _demo(args: argparse.Namespace) -> int:
    reports = []
    for item in DEMO_QUERIES:
        categories, _intent_source = effective_categories(item["question"], None)
        candidates = search_places(
            item["question"],
            5,
            candidate_count=60,
            category=categories or None,
        )
        places, verification = asyncio.run(
            verify_recommendations(candidates, limit=5, expected_categories=categories)
        )
        if not places and verification["mode"] == "osm_unavailable":
            places, verification = use_recent_snapshot(
                candidates,
                verification,
                limit=5,
                candidate_limit=20,
                expected_categories=categories,
            )
        places, route = plan_route(places, item["origin"], limit=5)
        answer, model_status = grounded_answer(
            item["question"], places, route, use_llm=verification["mode"] != "osm_snapshot"
        )
        report = {
            "question": item["question"],
            "origin": route["origin"],
            "retrieved_contexts": places,
            "route": route,
            "answer": answer,
            "model_status": model_status,
            "verification": verification,
        }
        reports.append(report)
        print(f"\n{len(reports)}. {item['question']}")
        print("   Retrieved: " + (", ".join(f"{p['name']} ({p['place_type']})" for p in places) or "no matching records"))
        print(f"   Model: {model_status}")
        print(f"   Verification: {verification['mode']} ({verification['verified_count']} live records)")
        print(f"   Answer: {answer}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved all five contexts, routes and answers to {args.output}")
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="city-compass",
        description="Karlsruhe City Compass — OSM ingestion, Milvus indexing and grounded RAG search.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest", help="Download OSM places or load a local OSM JSON export")
    ingest.add_argument("--file", type=Path, help="Overpass JSON or cleaned place JSON to ingest")
    ingest.set_defaults(handler=_ingest)

    index = commands.add_parser("index", help="Chunk place documents and build the Milvus vector index")
    index.set_defaults(handler=_index)

    ask = commands.add_parser("ask", help="Retrieve place context, suggest a route and generate an answer")
    ask.add_argument("question", nargs="?", help="Natural-language request; omitted means prompt interactively")
    ask.add_argument("--origin", help="Start location name or latitude,longitude (default: city centre)")
    ask.add_argument("--limit", type=int, choices=range(1, 11), default=5, metavar="1-10")
    ask.add_argument("--json", action="store_true", help="Print machine-readable contexts, route and answer")
    ask.set_defaults(handler=_ask)

    demo = commands.add_parser("demo", help="Run the five evaluation questions and save their full evidence and answers")
    demo.add_argument("--output", type=Path, default=PROJECT_ROOT / "examples" / "demo_results.json")
    demo.set_defaults(handler=_demo)
    return parser


def main() -> int:
    args = make_parser().parse_args()
    try:
        return args.handler(args)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
