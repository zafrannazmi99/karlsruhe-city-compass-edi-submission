"""LlamaIndex document pipeline backed by a Milvus vector collection."""

import json
from functools import lru_cache
from typing import Any

from .config import settings
from .place_categories import PLACE_TYPES_BY_CATEGORY
from .places import CLEAN_PATH


def _category_filter(categories: str | list[str] | None) -> str:
    if categories is None:
        return ""
    if isinstance(categories, str):
        categories = [categories]
    unsupported = set(categories) - PLACE_TYPES_BY_CATEGORY.keys()
    if unsupported:
        raise ValueError(f"Unsupported search category: {sorted(unsupported)[0]}")
    place_types = tuple(dict.fromkeys(
        place_type
        for category in categories
        for place_type in PLACE_TYPES_BY_CATEGORY[category]
    ))
    choices = " or ".join(f'metadata["place_type"] == {json.dumps(place_type)}' for place_type in place_types)
    return f"({choices})" if choices else ""


@lru_cache(maxsize=1)
def get_embedder():
    # Lazy loading keeps authentication and saved-trip endpoints lightweight.
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding

    return HuggingFaceEmbedding(model_name=settings.embedding_model, embed_batch_size=32, normalize=True)


def _make_milvus_client():
    from pymilvus import MilvusClient

    options = {"uri": settings.milvus_uri}
    if settings.milvus_token:
        options["token"] = settings.milvus_token
    return MilvusClient(**options)


def _place_document(place: dict[str, Any]):
    from llama_index.core import Document

    osm_type, _, osm_number = str(place["id"]).partition("/")
    return Document(
        text=place["description"],
        id_=str(place["id"]),
        metadata={
            "osm_id": str(place["id"]),
            "osm_url": f"https://www.openstreetmap.org/{osm_type}/{osm_number}",
            "name": str(place["name"]),
            "place_type": str(place["place_type"]),
            "lat": float(place["lat"]),
            "lon": float(place["lon"]),
            "tags": place.get("tags", {}),
        },
        # Keep complete OSM tags as retrieval evidence without injecting the
        # large metadata object into embeddings or prompts.
        excluded_embed_metadata_keys=["tags"],
        excluded_llm_metadata_keys=["tags"],
    )


def build_index() -> tuple[int, int]:
    """Split OSM place documents and replace the configured Milvus collection."""
    if not CLEAN_PATH.exists():
        raise FileNotFoundError("No cleaned places found. Run `python -m app.cli ingest` first.")
    places = json.loads(CLEAN_PATH.read_text(encoding="utf-8"))
    if not places:
        raise ValueError("The cleaned place file is empty. Fetch places before indexing.")

    from llama_index.core.schema import MetadataMode
    from llama_index.core.node_parser import SentenceSplitter
    from pymilvus import DataType

    documents = [_place_document(place) for place in places]
    splitter = SentenceSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        # The full OSM tags are excluded from chunk sizing, while the compact
        # attribution fields remain attached to each node and stored in Milvus.
        include_metadata=True,
    )
    nodes = splitter.get_nodes_from_documents(documents, show_progress=True)
    embeddings = get_embedder().get_text_embedding_batch(
        [node.get_content(metadata_mode=MetadataMode.EMBED) for node in nodes],
        show_progress=True,
    )

    client = _make_milvus_client()
    try:
        # Replace the collection on every full re-index so stale chunks cannot
        # survive when OSM data or chunk settings change.
        if client.has_collection(collection_name=settings.milvus_collection):
            client.drop_collection(collection_name=settings.milvus_collection)

        schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(
            field_name="id",
            datatype=DataType.VARCHAR,
            is_primary=True,
            max_length=128,
        )
        schema.add_field(
            field_name="embedding",
            datatype=DataType.FLOAT_VECTOR,
            dim=settings.embedding_dimension,
        )
        schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=16384)
        schema.add_field(field_name="metadata", datatype=DataType.JSON)

        index_params = client.prepare_index_params()
        # Unit-normalized embeddings make inner product equivalent to cosine
        # similarity; FLAT gives an exact baseline for this internship demo.
        index_params.add_index(
            field_name="embedding",
            index_type="FLAT",
            metric_type="IP",
            params={},
        )
        client.create_collection(
            collection_name=settings.milvus_collection,
            schema=schema,
            index_params=index_params,
            consistency_level="Session",
        )

        batch_size = 128
        for start in range(0, len(nodes), batch_size):
            batch_nodes = nodes[start:start + batch_size]
            batch_embeddings = embeddings[start:start + batch_size]
            rows = [
                {
                    "id": node.node_id,
                    "embedding": vector,
                    "text": node.get_content(metadata_mode=MetadataMode.NONE),
                    "metadata": node.metadata,
                }
                for node, vector in zip(batch_nodes, batch_embeddings, strict=True)
            ]
            client.insert(collection_name=settings.milvus_collection, data=rows)

        client.flush(collection_name=settings.milvus_collection)
        client.load_collection(collection_name=settings.milvus_collection)
    finally:
        client.close()

    return len(places), len(nodes)


def search_places(
    question: str,
    limit: int = 5,
    candidate_count: int | None = None,
    category: str | list[str] | None = None,
) -> list[dict[str, Any]]:
    """Retrieve relevant place chunks from Milvus and deduplicate by OSM object."""
    from llama_index.core.schema import MetadataMode

    client = _make_milvus_client()
    try:
        if not client.has_collection(collection_name=settings.milvus_collection):
            raise RuntimeError(
                f"Milvus collection '{settings.milvus_collection}' is missing. Run `python -m app.cli index`."
            )
        client.load_collection(collection_name=settings.milvus_collection)
        category_filter = _category_filter(category)
        # Keep the user's request verbatim as the semantic signal. Category
        # intent is a hard metadata filter and must never dilute the question.
        query_embedding = get_embedder().get_text_embedding(question)
        matches = client.search(
            collection_name=settings.milvus_collection,
            data=[query_embedding],
            anns_field="embedding",
            limit=candidate_count or max(limit * 4, 10),
            output_fields=["text", "metadata"],
            search_params={"metric_type": "IP", "params": {}},
            filter=category_filter,
        )[0]
    except Exception as exc:
        raise RuntimeError(f"Milvus search failed at {settings.milvus_uri}: {exc}") from exc
    finally:
        client.close()

    results: list[dict[str, Any]] = []
    result_limit = candidate_count or max(limit * 4, 10)
    seen: set[str] = set()
    for match in matches:
        entity = match.get("entity") or {}
        metadata = entity.get("metadata") or {}
        osm_id = str(metadata.get("osm_id", match.get("id", "")))
        if osm_id in seen:
            continue
        seen.add(osm_id)
        tags = metadata.get("tags") or {}
        score = float(match.get("distance", 0.0) or 0.0)
        results.append({
            "id": osm_id,
            "name": str(metadata.get("name", "Unnamed place")),
            "place_type": str(metadata.get("place_type", "Place")),
            "lat": float(metadata["lat"]),
            "lon": float(metadata["lon"]),
            "description": str(entity.get("text", "")),
            "tags": tags,
            "score": round(max(0.0, min(1.0, score)), 3),
            "source_url": metadata.get("osm_url", ""),
        })
        if len(results) >= result_limit:
            break
    return results
