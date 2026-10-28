from .places import fetch_places


def main() -> None:
    raw_count, clean_count = fetch_places()
    print(f"Downloaded {raw_count} OSM objects; saved {clean_count} places with coordinates.")


if __name__ == "__main__":
    main()
