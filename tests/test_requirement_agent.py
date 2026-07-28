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
