"""
ChromaDB index over compiled wiki pages.
Used when wiki exceeds ~50 pages (too large for direct index.md read).
For smaller wikis, the LLM reads index.md directly.
"""
import chromadb
from chromadb.utils import embedding_functions
from wiki.manager import list_wiki_pages, read_wiki_page

_client = chromadb.Client()  # in-memory, fastest for demo
_collection = None
_embed_fn = embedding_functions.DefaultEmbeddingFunction()


def get_collection():
    global _collection
    if _collection is None:
        _collection = _client.get_or_create_collection(
            name="sensei_wiki",
            embedding_function=_embed_fn,
            metadata={"hnsw:space": "cosine"}
        )
    return _collection


def index_wiki():
    """Index all wiki pages into ChromaDB."""
    col = get_collection()
    pages = list_wiki_pages()
    for page in pages:
        content = read_wiki_page(page["concept"]) or ""
        if content:
            try:
                col.upsert(
                    ids=[page["concept"]],
                    documents=[content],
                    metadatas=[{
                        "concept": page["concept"],
                        "confidence": str(page["confidence"]),
                        "tier": page["tier"]
                    }]
                )
            except Exception:
                pass


def retrieve_from_wiki(query: str, n: int = 3) -> list[dict]:
    """Retrieve relevant wiki pages for a query."""
    col = get_collection()
    try:
        count = col.count()
        if count == 0:
            return []
        results = col.query(query_texts=[query], n_results=min(n, count))
        return [
            {
                "concept": results["metadatas"][0][i]["concept"],
                "text": results["documents"][0][i],
                "confidence": float(results["metadatas"][0][i]["confidence"]),
                "distance": results["distances"][0][i]
            }
            for i in range(len(results["ids"][0]))
        ]
    except Exception:
        return []


def should_use_rag() -> bool:
    """Use RAG only when wiki exceeds 50 pages."""
    return len(list_wiki_pages()) > 50
