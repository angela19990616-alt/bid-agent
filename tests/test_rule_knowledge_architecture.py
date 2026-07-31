from dataclasses import replace
from uuid import uuid4

from app.agents.document_validator import DocumentValidator
from app.agents.proposal_planner import ProposalPlanner
from app.agents.requirement_agent import AgentRequirement
from app.agents.requirement_reviewer import RequirementReviewer
from app.knowledge.engine import EnterpriseKnowledgeEngine
from app.rules.engine import RuleEngine
from app.core.model_routing import ModelRoutingRules
from app.services.document_service import SourceSegment
from app.services.section_service import SectionService


def test_default_rules_are_external_versioned_and_valid():
    engine = RuleEngine()

    extraction = engine.load_default("extraction")
    knowledge = engine.load_default("knowledge")
    proposal_memory = engine.load_default("proposal_memory")
    response_strategy = engine.load_default("response_strategy")
    writing = engine.load_default("writing")
    compliance = engine.load_default("compliance")

    assert extraction.version == 4
    assert extraction.content["proposal_mapping"]
    assert (
        knowledge.content["matching"]["source_role_weights"][
            "response_content"
        ]
        > knowledge.content["matching"]["source_role_weights"][
            "qualification_file"
        ]
    )
    assert proposal_memory.content["usage"]["prohibited"]
    assert response_strategy.content["hard_rules"]
    assert writing.version == 6
    assert compliance.version == 4
    assert writing.content["policies"]["allow_invented_capability"] is False
    assert (
        writing.content["knowledge_category_policy"]["historical_bid"]
        .startswith("仅可参考结构")
    )
    assert compliance.content["checks"]
    assert len(extraction.checksum) == 64


def test_model_routing_rules_are_external_and_bounded():
    routing = ModelRoutingRules.load()

    assert routing.max_attempts == 10
    assert len(routing.model_pool) >= 10
    assert routing.max_billable_failures == 2
    assert routing.models_for_task("writing", "primary") == [
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        "qwen3.7-plus",
        "qwen-max",
        "glm-5",
        "deepseek-v3",
        "qwen3-max",
        "qwen-plus-latest",
        "qwen3.7-flash",
        "qwen3.5-plus",
    ]
    assert routing.models_for_task("classification", "primary") == [
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "qwen3.7-plus",
        "qwen-max",
        "glm-5",
        "deepseek-v3",
        "qwen3-max",
        "deepseek-v3.2",
        "qwen3-235b-a22b-instruct-2507",
        "deepseek-r1-distill-qwen-32b",
    ]
    assert routing.models_for_task("extraction", "primary")[:2] == [
        "deepseek-v4-flash",
        "qwen3.7-plus",
    ]
    assert routing.is_retryable(RuntimeError("额度不足"))
    assert not routing.is_retryable(RuntimeError("业务字段缺失"))


def test_document_validator_uses_loaded_extraction_rule():
    rules = RuleEngine().load_default("extraction")
    segments = [
        SourceSegment(
            text=(
                "本采购文件要求供应商编制响应文件，响应采购需求和技术要求。"
                "评审采用评分办法，成交后按合同交付并组织验收。" * 8
            ),
            locator_kind="paragraph",
            paragraph_start=1,
            paragraph_end=1,
        ),
        SourceSegment(
            text="投标人应提交服务方案和实施计划。",
            locator_kind="paragraph",
            paragraph_start=2,
            paragraph_end=2,
        ),
    ]

    result = DocumentValidator().validate(
        "招标文件.docx", segments, rules
    )

    assert result.is_valid is True
    assert result.score >= 0.5


def test_reviewer_and_planner_are_rule_driven():
    extraction = RuleEngine().load_default("extraction")
    writing = RuleEngine().load_default("writing")
    requirement = AgentRequirement(
        source_id=uuid4(),
        title="提交项目实施进度计划",
        normalized_text="供应商应提交项目实施进度计划。",
        quote="供应商须提交项目实施进度计划。",
        requirement_type="technical",
        importance="high",
        confidence=0.9,
    )

    reviewed = RequirementReviewer().review([requirement], extraction)[0]
    planned = ProposalPlanner().plan(
        [
            {
                "id": uuid4(),
                "target_chapter": reviewed.target_chapter,
                "need_generation": reviewed.need_generation,
            }
        ],
        writing,
    )

    assert reviewed.target_chapter == "实施计划与进度安排"
    assert reviewed.need_generation is True
    assert planned[0].title == "实施计划与进度安排"


def test_specific_proposal_mapping_precedes_generic_implementation_word():
    extraction = RuleEngine().load_default("extraction")
    requirement = AgentRequirement(
        source_id=uuid4(),
        title="提供培训实施方案",
        normalized_text="供应商须提供培训实施方案。",
        quote="供应商须提供培训实施方案。",
        requirement_type="delivery",
        importance="high",
        confidence=0.9,
    )

    reviewed = RequirementReviewer().review([requirement], extraction)[0]

    assert reviewed.target_chapter == "培训方案"


def test_scoring_words_do_not_override_technical_requirement_type():
    extraction = RuleEngine().load_default("extraction")
    requirement = AgentRequirement(
        source_id=uuid4(),
        title="系统备份功能",
        normalized_text="系统应具备每日备份功能。",
        quote="技术评分表要求系统应具备每日备份功能。",
        requirement_type="technical",
        importance="high",
        confidence=0.9,
    )

    reviewed = RequirementReviewer().review_one(requirement, extraction)

    assert reviewed.target_chapter == "服务范围与工作内容"


def test_requirement_type_controls_scoring_and_compliance_routing():
    extraction = RuleEngine().load_default("extraction")
    scoring = AgentRequirement(
        source_id=uuid4(),
        title="实施计划评分",
        normalized_text="实施计划完整可行得分。",
        quote="实施计划完整可行得分。",
        requirement_type="scoring",
        importance="high",
        confidence=0.9,
    )
    qualification = AgentRequirement(
        source_id=uuid4(),
        title="项目经理资格证明",
        normalized_text="项目经理须提供资格证明。",
        quote="项目经理须提供资格证明。",
        requirement_type="qualification",
        importance="high",
        confidence=0.9,
    )

    scored = RequirementReviewer().review_one(scoring, extraction)
    qualified = RequirementReviewer().review_one(
        qualification, extraction
    )

    assert scored.target_chapter == "技术评分点响应"
    assert scored.need_generation is True
    assert qualified.target_chapter is None
    assert qualified.need_generation is False


def test_reviewer_routing_defaults_are_project_configurable():
    extraction = RuleEngine().load_default("extraction")
    content = {
        **extraction.content,
        "proposal_routing_defaults": {
            **extraction.content["proposal_routing_defaults"],
            "technical": {
                "target_chapter": "咨询服务总体方案",
                "relevance": "medium",
                "need_generation": True,
            },
        },
    }
    project_rules = replace(extraction, content=content)
    requirement = AgentRequirement(
        source_id=uuid4(),
        title="提交总体咨询方案",
        normalized_text="供应商应提交总体咨询方案。",
        quote="供应商应提交总体咨询方案。",
        requirement_type="technical",
        importance="high",
        confidence=0.9,
    )

    reviewed = RequirementReviewer().review_one(
        requirement, project_rules
    )

    assert reviewed.target_chapter == "咨询服务总体方案"
    assert reviewed.proposal_relevance == "medium"
    assert reviewed.need_generation is True


def test_writer_prompt_receives_rule_and_pre_matched_knowledge_boundary():
    rules = RuleEngine().load_default("writing")
    messages = SectionService._messages(
        "实施计划与进度安排",
        [
            {
                "id": "R1",
                "normalized_text": "供应商应提交实施计划。",
                "quote": "须提交实施计划。",
            }
        ],
        [],
        rules,
    )

    assert rules.checksum
    assert "本次已加载的版本化写作规则" in messages[0]["content"]
    assert "Matched Knowledge" in messages[1]["content"]
    assert "无匹配企业知识" in messages[1]["content"]
    assert "不得用行业惯例猜测" in messages[0]["content"]


def test_knowledge_matching_terms_support_chinese_ngrams():
    query = EnterpriseKnowledgeEngine._terms("智慧文旅实施计划")
    content = EnterpriseKnowledgeEngine._terms("文旅项目实施经验")

    assert query & content


def test_knowledge_matching_excludes_current_document(monkeypatch):
    current_document_id = uuid4()
    engine = EnterpriseKnowledgeEngine()
    monkeypatch.setattr(
        engine,
        "list_active",
        lambda: [
            {
                "id": uuid4(),
                "category": "historical_bid",
                "title": "智慧文旅历史标书",
                "content": "智慧文旅项目实施计划",
                "metadata": {"document_id": str(current_document_id)},
                "source_document_id": current_document_id,
            }
        ],
    )

    matches = engine.match(
        section_title="实施计划",
        requirements=[],
        exclude_document_ids={current_document_id},
        rules=RuleEngine().load_default("knowledge"),
    )

    assert matches == []


def test_knowledge_matching_prefers_response_content_role(monkeypatch):
    engine = EnterpriseKnowledgeEngine()
    shared = {
        "category": "historical_bid",
        "title": "同项目历史文件",
        "content": "智慧文旅专项债券实施方案进度计划质量保障",
        "permission_scope": "organization_private",
        "version": 1,
        "checksum": "a" * 64,
        "source_document_id": None,
        "source_project_id": None,
    }
    monkeypatch.setattr(
        engine,
        "list_active",
        lambda: [
            {
                **shared,
                "id": uuid4(),
                "metadata": {"source_role": "qualification_file"},
            },
            {
                **shared,
                "id": uuid4(),
                "metadata": {"source_role": "response_content"},
            },
        ],
    )

    matches = engine.match(
        section_title="实施计划与进度安排",
        requirements=[],
        rules=RuleEngine().load_default("knowledge"),
    )

    assert matches
    assert matches[0].metadata["source_role"] == "response_content"
    assert all(
        item.metadata["source_role"] != "qualification_file"
        for item in matches
    )
