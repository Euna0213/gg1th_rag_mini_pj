import uuid

from qdrant_client.models import Distance, PointStruct, VectorParams

from common.ai_model import get_embedding_model
from common.config import EMBEDDING_MODEL
from rag.cache import cached
from common.qdrant import get_qdrant_client
from rag.chunker import Chunk, chunk_law

COLLECTION = "ai_basic_law"
BATCH = 64


def _point_id(chunk: Chunk) -> str:
    """같은 조/항은 항상 같은 id가 되도록 해 재실행해도 중복 저장되지 않게 한다."""
    m = chunk.metadata
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{m['article']}|{m['paragraph']}"))


def build_vectorstore(chunks: list[Chunk] | None = None, recreate: bool = True, collection: str = COLLECTION) -> int:
    chunks = chunks if chunks is not None else chunk_law()
    client = get_qdrant_client()
    embeddings = get_embedding_model()

    vectors = []
    for i in range(0, len(chunks), BATCH):
        vectors += embeddings.embed_documents([c.text for c in chunks[i : i + BATCH]])

    if recreate and client.collection_exists(collection):
        client.delete_collection(collection)
    if not client.collection_exists(collection):
        client.create_collection(
            collection,
            vectors_config=VectorParams(size=len(vectors[0]), distance=Distance.COSINE),
        )

    client.upsert(
        collection,
        points=[
            PointStruct(id=_point_id(c), vector=v, payload={"text": c.text, **c.metadata})
            for c, v in zip(chunks, vectors)
        ],
    )
    return len(chunks)


def embed_query(query: str) -> list[float]:
    return cached("embed", [EMBEDDING_MODEL, query], lambda: get_embedding_model().embed_query(query))


def search_dense(query: str, k: int = 5, collection: str = COLLECTION):
    client = get_qdrant_client()
    vec = embed_query(query)
    return client.query_points(collection, query=vec, limit=k, with_payload=True).points
