from app.workflows.bid_workflow import graph

result = graph.invoke(
    {
        "query":"帮我写一份污水处理厂技术方案",
        "analysis":"",
        "retrieval":"",
        "answer":""
    }
)

print("\n======================")

print(result["answer"])

print("======================")
