import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("renders the private preview access gate", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /技术方案工作台/);
  assert.match(html, /PRIVATE PREVIEW/);
  assert.match(html, /正在验证访问权限/);
  assert.doesNotMatch(html, /选择 PDF 或 DOCX 招标文件/);
  assert.doesNotMatch(html, /Your site is taking shape|Building your site/);
});

test("keeps the simplified V1 workflow in the client source", async () => {
  const [page, css, layout, worker, nginx] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../worker/index.ts", import.meta.url), "utf8"),
    readFile(new URL("../nginx.conf", import.meta.url), "utf8"),
  ]);

  assert.match(page, /upload.*requirements.*outline.*writer.*export/s);
  assert.match(page, /本章微调要求/);
  assert.match(page, /按要求重新生成/);
  assert.match(page, /READY_WORKSPACE_STATUSES/);
  assert.match(page, /ready_to_export/);
  assert.match(page, /exported/);
  assert.match(page, /Requirement/);
  assert.match(page, /Section/);
  assert.match(page, /API_BASE/);
  assert.match(page, /只需上传招标文件/);
  assert.match(page, /有“投标文件格式”.*没有格式才进入目录与方案生成/);
  assert.match(page, /查看原文定位/);
  assert.match(page, /回填结果预览/);
  assert.match(page, /evidence-modal/);
  assert.match(page, /visibleEvidenceSource/);
  assert.doesNotMatch(page, /current_project_manual_archive/);
  assert.match(page, /响应事项分析/);
  assert.match(page, /技术方案事项/);
  assert.match(page, /评分响应/);
  assert.match(page, /商务合规/);
  assert.match(page, /风险提醒/);
  assert.match(page, /转为技术方案/);
  assert.match(page, /转为商务合规/);
  assert.match(page, /查看原文依据/);
  assert.match(page, /生成本章/);
  assert.match(page, /校核并生成 Word/);
  assert.doesNotMatch(page, /执行交付审查/);
  assert.match(page, /阻断问题必须处理后才能正式导出/);
  assert.match(page, /已自动继承原模板字体/);
  assert.match(page, /不再强制替换为系统默认字体/);
  assert.match(page, /下载可读 Review/);
  assert.match(page, /recommended_for_delivery/);
  assert.doesNotMatch(page, /createProject|创建项目/);
  assert.doesNotMatch(page, /演示模式|sampleContent/);
  assert.match(page, /workspaces\/\$\{workspaceId\}/);
  assert.match(
    page,
    /!READY_WORKSPACE_STATUSES\.has\(completed\.status\)/,
  );
  assert.match(page, /完成后自动打开/);
  assert.doesNotMatch(page, /bid-agent-active-workspace/);
  assert.doesNotMatch(page, /正在恢复上次方案进度/);
  assert.doesNotMatch(page, /sessionStorage|localStorage/);
  assert.match(page, /不显示历史方案或历史导出文件/);
  assert.match(page, /预计还需/);
  assert.match(page, /历史工作量/);
  assert.doesNotMatch(page, /恢复最近一次方案/);
  assert.doesNotMatch(page, /workspaces\/recent\/latest/);
  assert.doesNotMatch(page, /attempt < 180/);
  assert.doesNotMatch(page, /处理时间较长，请稍后重新打开/);
  assert.doesNotMatch(page, /网络连接暂时中断/);
  assert.match(page, /处理进度读取失败/);
  assert.match(page, /workspaces\/\$\{workspace\.id\}\/retry/);
  assert.match(page, /继续处理/);
  assert.match(css, /@media \(max-width: 980px\)/);
  assert.match(layout, /标书智能工作台/);
  assert.match(worker, /url\.pathname\.startsWith\("\/api\/v1\/"\)/);
  assert.match(worker, /BID_AGENT_API_ORIGIN/);
  assert.match(page, /access\/status/);
  assert.match(page, /access\/invite/);
  assert.match(nginx, /proxy_read_timeout 300s/);
  assert.match(page, /本工作台仅向受邀用户开放/);
  assert.match(css, /invite-card/);
});
