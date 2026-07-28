from app.core.model_client import ModelClient
from app.database.vector_store import SearchResult, VectorStore


class Retriever:
    def __init__(
        self,
        model_client: ModelClient | None = None,
        vector_store: VectorStore | None = None,
    ):
        self.model_client = model_client
        self.vector_store = vector_store or VectorStore()

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        client = self.model_client or ModelClient()
        embedding = client.embed([query])[0]
        return self.vector_store.search(embedding, limit=limit)
