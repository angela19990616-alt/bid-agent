from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.config.settings import settings
from app.core.entity_resolution import (
    EntityResolutionContext,
    ProjectRole,
    ROLE_LABELS,
    SlotContextClassifier,
)
from app.services.entity_resolution_service import EntityResolutionService
from app.services.generation_profile_service import (
    GenerationProfile,
    GenerationProfileService,
)


@dataclass(frozen=True)
class OntologyGraph:
    title: str
    ontology_version: str
    nodes: tuple[dict[str, Any], ...]
    edges: tuple[dict[str, str], ...]
    summary: dict[str, int]


class OntologyGraphService:
    """Project a verified relational model into a rebuildable Neo4j graph."""

    def get_current_graph(self, project_id: UUID) -> dict[str, Any]:
        context = EntityResolutionService().resolve_project(project_id)
        profile = GenerationProfileService.get(project_id)
        graph = self.build_graph(context, profile)
        try:
            if not settings.neo4j_enabled:
                raise RuntimeError("Neo4j is disabled")
            self._sync_neo4j(project_id, graph)
            persisted = self._read_neo4j(project_id, graph)
            return {
                **persisted,
                "storage": "neo4j",
                "graph_status": "ready",
                "message": "关系图已由 PostgreSQL 事实库同步至 Neo4j。",
            }
        except Exception:
            # Neo4j is a projection and must never block strict fill.
            return {
                "title": graph.title,
                "ontology_version": graph.ontology_version,
                "nodes": list(graph.nodes),
                "edges": list(graph.edges),
                "summary": graph.summary,
                "storage": "postgres_projection",
                "graph_status": "degraded",
                "message": "图数据库暂不可用，当前展示关系主库的只读投影。",
            }

    @staticmethod
    def build_graph(
        context: EntityResolutionContext,
        profile: GenerationProfile,
    ) -> OntologyGraph:
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, str]] = []
        node_ids: set[str] = set()
        edge_ids: set[str] = set()

        def add_node(
            node_id: str,
            kind: str,
            label: str,
            subtitle: str | None = None,
            **details: Any,
        ) -> None:
            if node_id in node_ids:
                return
            node_ids.add(node_id)
            nodes.append({
                "id": node_id,
                "kind": kind,
                "label": label,
                "subtitle": subtitle,
                "details": details,
            })

        def add_edge(
            edge_id: str,
            source: str,
            target: str,
            relation: str,
            label: str,
        ) -> None:
            if edge_id in edge_ids:
                return
            edge_ids.add(edge_id)
            edges.append({
                "id": edge_id,
                "source": source,
                "target": target,
                "relation": relation,
                "label": label,
            })

        project_label = context.project_name or "当前投标项目"
        add_node("project", "project", project_label, "当前项目")
        add_node("response-document", "document", "投标响应文件", "严格回填目标")
        add_edge(
            "project-response-document", "project", "response-document",
            "HAS_RESPONSE_DOCUMENT", "生成",
        )

        if context.organization is not None:
            add_node(
                "bidder", "organization", context.organization.full_name,
                "当前项目投标主体",
                verified=True,
                source_location=context.organization.source_location,
            )
            add_edge(
                "project-bidder", "project", "bidder",
                "HAS_BIDDER", "投标主体",
            )
        else:
            add_node(
                "bidder", "organization", "待绑定投标主体",
                "尚未从企业事实库确认",
                verified=False,
            )
            add_edge(
                "project-bidder", "project", "bidder",
                "HAS_BIDDER", "投标主体",
            )

        people_by_id = {item.id: item for item in context.people}
        role_node_ids: dict[ProjectRole, str] = {}
        person_index: dict[UUID, str] = {}
        for assignment in context.assignments:
            role_id = f"role-{assignment.role.value.lower()}"
            role_node_ids[assignment.role] = role_id
            add_node(
                role_id, "role", ROLE_LABELS[assignment.role],
                "当前项目已绑定角色",
                status=assignment.status,
                source_location=assignment.source_location,
            )
            add_edge(
                f"project-{role_id}", "project", role_id,
                "REQUIRES_ROLE", "项目角色",
            )
            person = people_by_id.get(assignment.person_id)
            if person is None:
                continue
            person_id = person_index.setdefault(
                person.id, f"person-{len(person_index) + 1}"
            )
            add_node(
                person_id, "person", person.name,
                person.title or "已核验人员",
                verified=True,
            )
            add_edge(
                f"{role_id}-{person_id}", role_id, person_id,
                "BOUND_TO_PERSON", "绑定人员",
            )

        fields = profile.template_descriptor.get("fields") or []
        grouped: dict[
            tuple[str, str, str, str], list[dict[str, Any]]
        ] = defaultdict(list)
        for field in fields:
            section = str(field.get("document_section") or "未识别目录")
            concept = str(field.get("ontology_concept") or "UnmappedSlot")
            role = str(field.get("expected_role") or "")
            semantic_key = str(
                field.get("canonical_key")
                or field.get("display_name")
                or field.get("label")
                or "slot"
            )
            grouped[(section, concept, role, semantic_key)].append(field)

        section_ids: dict[str, str] = {}
        for (section, concept, role, _semantic_key), items in grouped.items():
            section_id = section_ids.setdefault(
                section, f"section-{len(section_ids) + 1}"
            )
            add_node(section_id, "section", section, "原模板目录")
            add_edge(
                f"document-{section_id}", "response-document", section_id,
                "CONTAINS_SECTION", "包含目录",
            )
            slot_id = f"slot-{len([n for n in nodes if n['kind'] == 'slot']) + 1}"
            first = items[0]
            count = len(items)
            add_node(
                slot_id,
                "slot",
                str(first.get("display_name") or first.get("label") or "待识别槽位"),
                f"{count} 处原模板位置" if count > 1 else "1 处原模板位置",
                ontology_concept=concept,
                relation_path=list(first.get("relation_path") or ()),
                source_locations=[
                    str(item.get("source_location") or "原模板") for item in items
                ],
                fill_strategy=str(first.get("fill_strategy") or "unresolved"),
            )
            add_edge(
                f"{section_id}-{slot_id}", section_id, slot_id,
                "CONTAINS_SLOT", "包含槽位",
            )
            if role:
                project_role = ProjectRole(role)
                role_id = role_node_ids.get(project_role)
                if role_id is None:
                    role_id = f"role-{role.lower()}"
                    role_node_ids[project_role] = role_id
                    add_node(
                        role_id, "role", ROLE_LABELS[project_role],
                        "尚待当前项目绑定",
                    )
                    add_edge(
                        f"project-{role_id}", "project", role_id,
                        "REQUIRES_ROLE", "项目角色",
                    )
                add_edge(
                    f"{slot_id}-{role_id}", slot_id, role_id,
                    "EXPECTS_ROLE", "要求角色",
                )
            elif str(first.get("expected_entity_type") or "") == "Organization":
                add_edge(
                    f"{slot_id}-bidder", slot_id, "bidder",
                    "READS_ENTITY", "读取主体属性",
                )
            elif str(first.get("expected_entity_type") or "") == "Project":
                add_edge(
                    f"{slot_id}-project", slot_id, "project",
                    "READS_ENTITY", "读取项目属性",
                )
            elif str(first.get("expected_entity_type") or "") == "Person":
                add_node(
                    "person-registry", "person", "企业人员资料库",
                    "须先确定当前行对应的人员实体",
                )
                add_edge(
                    "project-person-registry", "project", "person-registry",
                    "USES_PERSON_REGISTRY", "候选人员来源",
                )
                add_edge(
                    f"{slot_id}-person-registry", slot_id,
                    "person-registry", "EXPECTS_PERSON", "等待绑定人员",
                )
            else:
                add_edge(
                    f"{slot_id}-response-document", slot_id,
                    "response-document", "READS_DOCUMENT", "读取文档属性",
                )

        for action_index, action in enumerate(
            profile.template_descriptor.get("actions") or (), start=1
        ):
            action_id = f"action-{action_index}"
            add_node(
                action_id, "action",
                str(action.get("display_name") or "文档动作"),
                str(action.get("source_location") or "原模板"),
            )
            add_edge(
                f"document-{action_id}", "response-document", action_id,
                "REQUIRES_ACTION", "要求动作",
            )

        summary = {
            "nodes": len(nodes),
            "relations": len(edges),
            "sections": sum(item["kind"] == "section" for item in nodes),
            "slot_groups": sum(item["kind"] == "slot" for item in nodes),
            "unresolved_slots": sum(
                item["kind"] == "slot"
                and item["details"].get("fill_strategy") == "unresolved"
                for item in nodes
            ),
        }
        return OntologyGraph(
            title=f"{project_label} · 业务关系图",
            ontology_version=SlotContextClassifier.ontology_version(),
            nodes=tuple(nodes),
            edges=tuple(edges),
            summary=summary,
        )

    @staticmethod
    def _driver():
        from neo4j import GraphDatabase

        return GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )

    def _sync_neo4j(self, project_id: UUID, graph: OntologyGraph) -> None:
        project_key = str(project_id)
        nodes = [
            {
                **item,
                "details_json": json.dumps(
                    item.get("details") or {}, ensure_ascii=False
                ),
            }
            for item in graph.nodes
        ]
        with self._driver() as driver:
            with driver.session(database=settings.neo4j_database) as session:
                session.run(
                    "MATCH (n:BidOntologyNode {project_key: $project_key}) "
                    "DETACH DELETE n",
                    project_key=project_key,
                ).consume()
                session.run(
                    "UNWIND $nodes AS item "
                    "CREATE (n:BidOntologyNode {"
                    "project_key: $project_key, node_key: item.id, "
                    "kind: item.kind, label: item.label, "
                    "subtitle: item.subtitle, details_json: item.details_json})",
                    project_key=project_key,
                    nodes=nodes,
                ).consume()
                session.run(
                    "UNWIND $edges AS item "
                    "MATCH (a:BidOntologyNode {project_key: $project_key, node_key: item.source}) "
                    "MATCH (b:BidOntologyNode {project_key: $project_key, node_key: item.target}) "
                    "CREATE (a)-[:BID_RELATION {"
                    "edge_key: item.id, relation: item.relation, label: item.label}]->(b)",
                    project_key=project_key,
                    edges=list(graph.edges),
                ).consume()

    def _read_neo4j(
        self,
        project_id: UUID,
        graph: OntologyGraph,
    ) -> dict[str, Any]:
        project_key = str(project_id)
        with self._driver() as driver:
            with driver.session(database=settings.neo4j_database) as session:
                node_rows = session.run(
                    "MATCH (n:BidOntologyNode {project_key: $project_key}) "
                    "RETURN n.node_key AS id, n.kind AS kind, n.label AS label, "
                    "n.subtitle AS subtitle, n.details_json AS details_json "
                    "ORDER BY n.node_key",
                    project_key=project_key,
                ).data()
                edge_rows = session.run(
                    "MATCH (a:BidOntologyNode {project_key: $project_key})"
                    "-[r:BID_RELATION]->"
                    "(b:BidOntologyNode {project_key: $project_key}) "
                    "RETURN r.edge_key AS id, a.node_key AS source, "
                    "b.node_key AS target, r.relation AS relation, "
                    "r.label AS label ORDER BY r.edge_key",
                    project_key=project_key,
                ).data()
        return {
            "title": graph.title,
            "ontology_version": graph.ontology_version,
            "nodes": [
                {
                    "id": item["id"],
                    "kind": item["kind"],
                    "label": item["label"],
                    "subtitle": item.get("subtitle"),
                    "details": json.loads(item.get("details_json") or "{}"),
                }
                for item in node_rows
            ],
            "edges": edge_rows,
            "summary": graph.summary,
        }
