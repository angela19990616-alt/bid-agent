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

test("renders the bid proposal workspace", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /技术方案工作台/);
  assert.match(html, /上传文件/);
  assert.match(html, /技术要点/);
  assert.match(html, /推荐目录/);
  assert.match(html, /导出 Word/);
  assert.doesNotMatch(html, /Your site is taking shape|Building your site/);
});

test("keeps the simplified V1 workflow in the client source", async () => {
  const [page, css, layout, worker] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../worker/index.ts", import.meta.url), "utf8"),
  ]);

  assert.match(page, /upload.*requirements.*outline.*writer.*export/s);
  assert.match(page, /Requirement/);
  assert.match(page, /Section/);
  assert.match(page, /API_BASE/);
  assert.match(page, /无需先建项目/);
  assert.match(page, /技术写作要点/);
  assert.match(page, /查看原文依据/);
  assert.match(page, /生成本章/);
  assert.match(page, /生成整本 Word/);
  assert.doesNotMatch(page, /createProject|创建项目/);
  assert.doesNotMatch(page, /演示模式|sampleContent/);
  assert.match(page, /workspaces\/\$\{created\.id\}/);
  assert.match(page, /completed\.status !== "outline_ready"/);
  assert.match(page, /workspaces\/\$\{workspace\.id\}\/retry/);
  assert.match(page, /继续处理/);
  assert.match(css, /@media \(max-width: 980px\)/);
  assert.match(layout, /标书智能工作台/);
  assert.match(worker, /url\.pathname\.startsWith\("\/api\/v1\/"\)/);
  assert.match(worker, /BID_AGENT_API_ORIGIN/);
});
