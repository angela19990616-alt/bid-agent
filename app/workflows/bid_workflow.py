from langgraph.graph import END, StateGraph

from app.agents.bid_agent import BidAgent
from app.rag.retriever import Retriever
from app.workflows.state import AgentState


def build_graph(
    agent: BidAgent | None = None,
    retriever: Retriever | None = None,
):
    bid_agent = agent or BidAgent()
    knowledge_retriever = retriever or Retriever()

    def analyze(state: AgentState) -> dict:
        return {"analysis": bid_agent.analyze(state["query"])}

    def retrieve(state: AgentState) -> dict:
        sources = knowledge_retriever.search(
            state["query"],
            limit=state.get("retrieval_limit", 5),
        )
        summary = (
            f"检索到 {len(sources)} 条知识库材料"
            if sources
            else "未检索到知识库材料"
        )
        return {"sources": sources, "retrieval": summary}

    def generate(state: AgentState) -> dict:
        return {
            "answer": bid_agent.generate(
                query=state["query"],
                analysis=state["analysis"],
                sources=state.get("sources", []),
            )
        }

    builder = StateGraph(AgentState)
    builder.add_node("analysis", analyze)
    builder.add_node("retrieve", retrieve)
    builder.add_node("generate", generate)
    builder.set_entry_point("analysis")
    builder.add_edge("analysis", "retrieve")
    builder.add_edge("retrieve", "generate")
    builder.add_edge("generate", END)
    return builder.compile()


graph = build_graph()
