from .vector_store import build_index


def main() -> None:
    place_count, chunk_count = build_index()
    print(f"Indexed {place_count} places as {chunk_count} chunks in Milvus.")


if __name__ == "__main__":
    main()
