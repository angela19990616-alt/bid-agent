from app.database.vector_store import SearchResult
from app.workflows.controlled_pipeline import STAGES


def test_response_strategy_stage_is_part_of_controlled_workflow():
    assert "response_strategy_analysis" in STAGES
    assert STAGES.index("proposal_classification") < STAGES.index(
        "response_strategy_analysis"
    ) < STAGES.index("load_enterprise_knowledge")
from app.workflows.bid_workflow import build_graph


class FakeAgent:
    def analyze(self, query):
        return f"已分析：{query}"

    def generate(self, query, analysis, sources):
        return f"方案：{query}；{analysis}；来源数：{len(sources)}"


class FakeRetriever:
    def search(self, query, limit=5):
        return [
            SearchResult(
                chunk_id=1,
                document_id=2,
                filename="案例.docx",
                content="历史案例内容",
                similarity=0.9,
                metadata={},
            )
        ][:limit]


def test_bid_workflow_runs_all_steps():
    graph = build_graph(agent=FakeAgent(), retriever=FakeRetriever())
    result = graph.invoke(
        {
            "query": "帮我写一份污水处理厂技术方案",
            "analysis": "",
            "retrieval": "",
            "answer": "",
            "retrieval_limit": 5,
            "sources": [],
        }
    )

    assert result["analysis"].startswith("已分析")
    assert result["retrieval"] == "检索到 1 条知识库材料"
    assert result["sources"][0].filename == "案例.docx"
    assert "来源数：1" in result["answer"]
