import json
from uuid import uuid4

from app.agents.requirement_agent import RequirementAgent


class FakeModelClient:
    def __init__(self, response):
        self.response = response
        self.messages = None

    def chat(self, messages, **kwargs):
        self.messages = messages
        return json.dumps(self.response, ensure_ascii=False)


class SequencedModelClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append(messages)
        response = next(self.responses)
        if isinstance(response, str):
            return response
        return json.dumps(response, ensure_ascii=False)


class MemoryCheckpoint:
    def __init__(self):
        self.items = {}

    def load(self, project_id, fingerprint):
        return self.items.get((project_id, fingerprint))

    def save(
        self,
        project_id,
        fingerprint,
        rule_checksum,
        result,
    ):
        self.items[(project_id, fingerprint)] = result


def source(text):
    return {
        "id": uuid4(),
        "content": text,
        "locator_kind": "paragraph",
        "page_no": None,
        "paragraph_start": 25,
        "paragraph_end": 25,
    }


def test_toc_and_chapter_labels_are_never_sent_to_model():
    noisy = source("第四章 供应商资格证明材料19")
    heading = source("第四章 供应商资格证明材料")
    real = source("响应文件中必须载明不少于90天的有效期。")
    fake = FakeModelClient({"requirements": []})
    agent = RequirementAgent(fake)

    agent.extract([noisy, heading, real])

    prompt = fake.messages[1]["content"]
    assert "第四章 供应商资格证明材料19" not in prompt
    assert "响应文件中必须载明" in prompt


def test_agent_returns_action_title_summary_and_exact_evidence():
    original = "本项目响应文件有效期为90天，响应文件中必须载明。"
    fake = FakeModelClient(
        {
            "requirements": [
                {
                    "source_ref": "S1",
                    "title": "载明90天响应文件有效期",
                    "requirement": (
                        "供应商应在响应文件中载明不少于90天的有效期。"
                    ),
                    "type": "compliance",
                    "importance": "high",
                    "confidence": 0.94,
                    "evidence": "响应文件中必须载明",
                }
            ]
        }
    )

    result = RequirementAgent(fake).extract([source(original)])

    assert len(result) == 1
    assert result[0].title == "载明90天响应文件有效期"
    assert result[0].normalized_text.startswith("供应商应")
    assert result[0].quote == "响应文件中必须载明"
    assert result[0].requirement_type == "compliance"


def test_non_actionable_model_output_is_rejected():
    fake = FakeModelClient(
        {
            "requirements": [
                {
                    "source_ref": "S1",
                    "title": "供应商资格证明材料",
                    "requirement": "第四章供应商资格证明材料",
                    "type": "qualification",
                    "importance": "medium",
                    "confidence": 0.55,
                    "evidence": "供应商资格证明材料",
                }
            ]
        }
    )

    assert RequirementAgent(fake).extract(
        [source("供应商资格证明材料")]
    ) == []


def test_service_list_without_subject_is_sent_with_heading_context():
    heading = source("★二、服务内容及要求")
    subheading = source("（一）委托咨询服务内容：")
    service = source("1.编制本项目的可行性研究报告。")
    fake = FakeModelClient({"requirements": []})

    RequirementAgent(fake).extract([heading, subheading, service])

    prompt = fake.messages[1]["content"]
    assert "编制本项目的可行性研究报告" in prompt
    assert "委托咨询服务内容" in prompt


def test_internal_evaluator_instruction_is_rejected():
    original = "谈判小组不得未经澄清直接将供应商响应文件作无效处理。"
    fake = FakeModelClient(
        {
            "requirements": [
                {
                    "source_ref": "S1",
                    "title": "不得未经澄清作无效处理",
                    "requirement": (
                        "供应商不得未经澄清直接被作无效响应处理。"
                    ),
                    "type": "compliance",
                    "importance": "medium",
                    "confidence": 0.8,
                    "evidence": original,
                }
            ]
        }
    )

    assert RequirementAgent(fake).extract([source(original)]) == []


def test_scoring_point_has_rule_driven_fallback_when_model_omits_it():
    fake = FakeModelClient({"requirements": []})
    original = "技术方案总体设计完整、架构合理、理解深入的，得10分。"

    result = RequirementAgent(fake).extract(
        [source("第三章 评分办法"), source(original)]
    )

    assert len(result) == 1
    assert result[0].requirement_type == "scoring"
    assert result[0].normalized_text.startswith("供应商应")
    assert result[0].quote == original


def test_nontechnical_evaluation_rows_do_not_become_scoring_points():
    fake = FakeModelClient({"requirements": []})
    rows = [
        source("4 | 低于成本价；不正当竞争预防措施 | 供应商须说明"),
        source("5 | 谈判保证金 | 本项目不收取谈判保证金"),
        source("13 | 品牌型号说明 | 以上内容不作为技术评审因素"),
    ]

    assert RequirementAgent(fake).extract(
        [source("第三章 评审办法"), *rows]
    ) == []


def test_malformed_large_batch_is_retried_in_smaller_batches():
    valid = {
        "requirements": [
            {
                "source_ref": "S1",
                "title": "提交项目实施计划",
                "requirement": "供应商应提交项目实施计划。",
                "type": "technical",
                "importance": "high",
                "confidence": 0.9,
                "evidence": "供应商须提交项目实施计划。",
            }
        ]
    }
    client = SequencedModelClient(['{"requirements":[', valid])
    agent = RequirementAgent(
        client,
        batch_size=30,
        recovery_batch_size=8,
    )

    result = agent.extract([source("供应商须提交项目实施计划。")])

    assert len(result) == 1
    assert result[0].title == "提交项目实施计划"
    assert len(client.calls) == 2
    assert "上一次响应不是合法 JSON" in client.calls[1][1]["content"]


def test_malformed_recovery_batch_keeps_scoring_fallback():
    client = SequencedModelClient(
        ['{"requirements":[', '{"requirements":[']
    )
    original = "技术方案完整、理解准确、措施可行的，得10分。"

    result = RequirementAgent(
        client,
        recovery_batch_size=8,
    ).extract([source("第三章 评分办法"), source(original)])

    assert len(result) == 1
    assert result[0].requirement_type == "scoring"
    assert result[0].quote == original


def test_retry_reuses_completed_extraction_batch_without_model_call():
    response = {
        "requirements": [
            {
                "source_ref": "S1",
                "title": "提交项目实施计划",
                "requirement": "供应商应提交项目实施计划。",
                "type": "technical",
                "importance": "high",
                "confidence": 0.9,
                "evidence": "供应商须提交项目实施计划。",
            }
        ]
    }
    checkpoint = MemoryCheckpoint()
    first_client = SequencedModelClient([response])
    project_id = uuid4()
    sources = [source("供应商须提交项目实施计划。")]

    first = RequirementAgent(
        first_client,
        checkpoint_service=checkpoint,
    ).extract(sources, project_id=project_id)
    second_client = SequencedModelClient([])
    second = RequirementAgent(
        second_client,
        checkpoint_service=checkpoint,
    ).extract(sources, project_id=project_id)

    assert first == second
    assert len(first_client.calls) == 1
    assert second_client.calls == []
