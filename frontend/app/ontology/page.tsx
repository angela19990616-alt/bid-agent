"use client";

import { useEffect, useMemo, useState } from "react";

type GraphNode = {
  id: string;
  kind: "project" | "organization" | "document" | "section" | "slot" | "role" | "person" | "action";
  label: string;
  subtitle: string | null;
  details: {
    relation_path?: string[];
    source_locations?: string[];
    fill_strategy?: string;
  };
};

type GraphEdge = {
  id: string;
  source: string;
  target: string;
  relation: string;
  label: string;
};

type Graph = {
  title: string;
  ontology_version: string;
  storage: "neo4j" | "postgres_projection";
  graph_status: "ready" | "degraded";
  message: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  summary: Record<string, number>;
};

const columns: Record<GraphNode["kind"], number> = {
  project: 0,
  organization: 0,
  document: 0,
  section: 1,
  slot: 2,
  role: 3,
  person: 4,
  action: 3,
};

const kindLabels: Record<GraphNode["kind"], string> = {
  project: "项目",
  organization: "主体",
  document: "投标文件",
  section: "原模板目录",
  slot: "待填槽位",
  role: "业务角色",
  person: "已核验人员",
  action: "签章动作",
};

export default function OntologyPage() {
  const [graph, setGraph] = useState<Graph | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<GraphNode | null>(null);

  useEffect(() => {
    fetch("/api/v1/ontology/graph", { credentials: "same-origin" })
      .then(async (response) => {
        if (!response.ok) {
          const payload = await response.json().catch(() => ({}));
          throw new Error(payload?.error?.message || "暂时无法读取业务关系图。");
        }
        return response.json();
      })
      .then((payload: Graph) => setGraph(payload))
      .catch((reason: Error) => setError(reason.message));
  }, []);

  const layout = useMemo(() => {
    if (!graph) return { nodes: [], positions: new Map<string, { x: number; y: number }>(), width: 1320, height: 720 };
    const grouped = new Map<number, GraphNode[]>();
    graph.nodes.forEach((node) => {
      const column = columns[node.kind];
      grouped.set(column, [...(grouped.get(column) || []), node]);
    });
    const positions = new Map<string, { x: number; y: number }>();
    const nodes = graph.nodes.map((node) => {
      const column = columns[node.kind];
      const siblings = grouped.get(column) || [];
      const index = siblings.findIndex((item) => item.id === node.id);
      const x = 36 + column * 256;
      const y = 48 + index * 112;
      positions.set(node.id, { x, y });
      return { ...node, x, y };
    });
    const largest = Math.max(...[...grouped.values()].map((items) => items.length), 5);
    return { nodes, positions, width: 1320, height: Math.max(720, largest * 112 + 70) };
  }, [graph]);

  return (
    <main className="ontology-page">
      <header className="ontology-header">
        <div>
          <span>BUSINESS ONTOLOGY</span>
          <h1>{graph?.title || "投标业务关系图"}</h1>
          <p>从原模板目录开始，查看每个空位对应的项目、主体、角色和属性。图数据库只保存可重建关系，不保存身份证号、电话或密钥。</p>
        </div>
        <a href="/">返回工作台</a>
      </header>

      {error && <section className="ontology-empty"><h2>暂时没有可查看的关系图</h2><p>{error}</p><a href="/">先上传招标文件</a></section>}
      {!graph && !error && <section className="ontology-empty"><h2>正在建立业务关系图…</h2><p>系统正在读取当前会话的严格回填结果。</p></section>}

      {graph && (
        <>
          <section className="ontology-summary">
            <div><b>{graph.summary.nodes || 0}</b><span>业务节点</span></div>
            <div><b>{graph.summary.relations || 0}</b><span>关系</span></div>
            <div><b>{graph.summary.sections || 0}</b><span>原模板目录</span></div>
            <div><b>{graph.summary.slot_groups || 0}</b><span>同类槽位组</span></div>
            <div className={graph.summary.unresolved_slots ? "warning" : "ready"}><b>{graph.summary.unresolved_slots || 0}</b><span>待确认关系</span></div>
          </section>
          <section className={`ontology-storage ${graph.graph_status}`}>
            <b>{graph.storage === "neo4j" ? "Neo4j 图投影已连接" : "关系主库只读降级"}</b>
            <span>{graph.message} · Ontology {graph.ontology_version}</span>
          </section>
          <section className="ontology-legend">
            {Object.entries(kindLabels).map(([kind, label]) => <span key={kind} data-kind={kind}>{label}</span>)}
          </section>
          <section className="ontology-canvas-shell">
            <div className="ontology-canvas" style={{ width: layout.width, height: layout.height }}>
              <svg width={layout.width} height={layout.height} aria-label="投标业务关系连线">
                <defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" /></marker></defs>
                {graph.edges.map((edge) => {
                  const source = layout.positions.get(edge.source);
                  const target = layout.positions.get(edge.target);
                  if (!source || !target) return null;
                  const x1 = source.x + 208;
                  const y1 = source.y + 36;
                  const x2 = target.x;
                  const y2 = target.y + 36;
                  const bend = Math.max(40, (x2 - x1) / 2);
                  return <path key={edge.id} d={`M${x1},${y1} C${x1 + bend},${y1} ${x2 - bend},${y2} ${x2},${y2}`} markerEnd="url(#arrow)" />;
                })}
              </svg>
              {layout.nodes.map((node) => (
                <button
                  key={node.id}
                  className="ontology-node"
                  data-kind={node.kind}
                  style={{ left: node.x, top: node.y }}
                  onClick={() => setSelected(node)}
                >
                  <small>{kindLabels[node.kind]}</small>
                  <strong>{node.label}</strong>
                  <span>{node.subtitle}</span>
                </button>
              ))}
            </div>
          </section>
        </>
      )}

      {selected && (
        <div className="ontology-detail-backdrop" onClick={() => setSelected(null)}>
          <article className="ontology-detail" onClick={(event) => event.stopPropagation()}>
            <header><div><small>{kindLabels[selected.kind]}</small><h2>{selected.label}</h2></div><button onClick={() => setSelected(null)} aria-label="关闭">×</button></header>
            <p>{selected.subtitle}</p>
            {(selected.details.relation_path || []).length > 0 && <div><span>实际取值关系</span><strong>{selected.details.relation_path?.join(" → ")}</strong></div>}
            {(selected.details.source_locations || []).length > 0 && <div><span>原模板位置</span><ul>{selected.details.source_locations?.map((item) => <li key={item}>{item}</li>)}</ul></div>}
            <small>页面不展示数据库主键、UUID、身份证号、电话或内部字段。</small>
          </article>
        </div>
      )}
    </main>
  );
}
