from app.core.model_client import ModelClient
from app.database.vector_store import SearchResult


class BidAgent:
    def __init__(self, model_client: ModelClient | None = None):
        self.model_client = model_client

    @property
    def client(self) -> ModelClient:
        if self.model_client is None:
            self.model_client = ModelClient()
        return self.model_client

    def analyze(self, query: str) -> str:
        return self.client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "你是中国政府采购与咨询服务投标专家。"
                        "分析用户的标书编制需求，提取项目目标、服务范围、"
                        "关键响应点、交付成果和潜在风险。用精炼中文分点输出。"
                    ),
                },
                {"role": "user", "content": query},
            ],
            max_tokens=1200,
        )

    def generate(
        self,
        query: str,
        analysis: str,
        sources: list[SearchResult],
    ) -> str:
        context = "\n\n".join(
            (
                f"[来源{index}] 文件：{source.filename}；"
                f"相似度：{source.similarity:.3f}\n{source.content}"
            )
            for index, source in enumerate(sources, start=1)
        )
        if not context:
            context = "知识库中没有检索到可用材料。"

        return self.client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "你是资深投标文件编制专家。根据需求分析和知识库材料"
                        "起草结构清晰、可执行的中文方案。不得捏造企业业绩、"
                        "人员资质或数字；引用材料时使用[来源N]标注。"
                        "资料不足处明确写“待补充”，不要假装已知。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"原始需求：\n{query}\n\n"
                        f"需求分析：\n{analysis}\n\n"
                        f"知识库材料：\n{context}\n\n"
                        "请输出可直接继续编辑的投标方案草稿。"
                    ),
                },
            ],
        )
