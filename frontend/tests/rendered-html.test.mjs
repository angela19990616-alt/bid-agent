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
  assert.match(html, /标书智能工作台/);
  assert.match(html, /项目材料/);
  assert.match(html, /招标要求/);
  assert.match(html, /技术方案/);
  assert.match(html, /导出结果/);
  assert.doesNotMatch(html, /Your site is taking shape|Building your site/);
});

test("keeps the simplified V1 workflow in the client source", async () => {
  const [page, css, layout, worker] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../worker/index.ts", import.meta.url), "utf8"),
  ]);

  assert.match(page, /project.*requirements.*writer.*export/s);
  assert.match(page, /Requirement/);
  assert.match(page, /Section/);
  assert.match(page, /API_BASE/);
  assert.match(page, /提取招标要求/);
  assert.match(page, /需要响应什么/);
  assert.match(page, /招标原文依据/);
  assert.match(page, /原文位置/);
  assert.match(page, /生成一个章节/);
  assert.match(page, /生成 Word 文件/);
  assert.doesNotMatch(page, /setTimeout|演示模式|sampleContent/);
  assert.match(css, /@media \(max-width: 980px\)/);
  assert.match(layout, /标书智能工作台/);
  assert.match(worker, /url\.pathname\.startsWith\("\/api\/v1\/"\)/);
  assert.match(worker, /BID_AGENT_API_ORIGIN/);
});
