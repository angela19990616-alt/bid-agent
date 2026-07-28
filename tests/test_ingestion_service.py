from app.services.ingestion_service import IngestionService


class FakeModelClient:
    def embed(self, texts):
        return [[float(index), 0.0] for index, _ in enumerate(texts)]


class FakeVectorStore:
    def __init__(self):
        self.created = None
        self.chunks = None

    def create_document(self, filename, content_type, source_type):
        self.created = (filename, content_type, source_type)
        return 42

    def add_chunks(self, document_id, chunks, embeddings):
        self.chunks = (document_id, chunks, embeddings)

    def delete_document(self, document_id):
        raise AssertionError("成功路径不应删除文档")


def test_ingest_text_document():
    store = FakeVectorStore()
    service = IngestionService(
        model_client=FakeModelClient(),
        vector_store=store,
    )

    document_id, chunk_count = service.ingest(
        filename="案例.txt",
        content_type="text/plain",
        content="项目背景\n实施方案".encode(),
    )

    assert document_id == 42
    assert chunk_count == 1
    assert store.created == ("案例.txt", "text/plain", "upload")
    assert store.chunks[0] == 42

