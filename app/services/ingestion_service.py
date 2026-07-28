from app.config.settings import settings
from app.core.model_client import ModelClient
from app.database.vector_store import VectorStore
from app.services.document_service import extract_text, split_text


class IngestionService:
    def __init__(
        self,
        model_client: ModelClient | None = None,
        vector_store: VectorStore | None = None,
    ):
        self.model_client = model_client
        self.vector_store = vector_store or VectorStore()

    def ingest(
        self,
        filename: str,
        content_type: str | None,
        content: bytes,
        source_type: str = "upload",
    ) -> tuple[int, int]:
        text = extract_text(filename, content)
        chunks = split_text(
            text,
            chunk_size=settings.chunk_size,
            overlap=settings.chunk_overlap,
        )
        client = self.model_client or ModelClient()
        embeddings = client.embed(chunks)
        document_id = self.vector_store.create_document(
            filename=filename,
            content_type=content_type,
            source_type=source_type,
        )
        try:
            self.vector_store.add_chunks(document_id, chunks, embeddings)
        except Exception:
            self.vector_store.delete_document(document_id)
            raise
        return document_id, len(chunks)

