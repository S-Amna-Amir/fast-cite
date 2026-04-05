from __future__ import annotations

import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.config import settings


def get_client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)


def delete_collection_if_exists(client: QdrantClient) -> bool:
    """Remove the FastCite vector collection from Qdrant. Returns True if it existed and was deleted."""
    name = settings.qdrant_collection
    if not client.collection_exists(name):
        return False
    client.delete_collection(collection_name=name)
    return True


def ensure_collection(client: QdrantClient, recreate: bool = False) -> None:
    name = settings.qdrant_collection
    exists = client.collection_exists(name)
    if recreate and exists:
        client.delete_collection(name)
        exists = False
    if not exists:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(
                size=settings.embedding_dimensions,
                distance=Distance.COSINE,
            ),
        )


def collection_point_count(client: QdrantClient) -> int:
    info = client.get_collection(settings.qdrant_collection)
    return int(info.points_count)


def upsert_chunks(
    client: QdrantClient,
    embeddings: list[list[float]],
    payloads: list[dict],
) -> None:
    if not embeddings:
        return
    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=vec,
            payload=payload,
        )
        for vec, payload in zip(embeddings, payloads, strict=True)
    ]
    client.upsert(collection_name=settings.qdrant_collection, points=points)


def search(
    client: QdrantClient,
    query_vector: list[float],
    limit: int,
) -> list[dict]:
    hits = client.query_points(
        collection_name=settings.qdrant_collection,
        query=query_vector,
        limit=limit,
        with_payload=True,
    ).points
    out: list[dict] = []
    for p in hits:
        payload = p.payload or {}
        payload["_score"] = getattr(p, "score", None)
        out.append(payload)
    return out
