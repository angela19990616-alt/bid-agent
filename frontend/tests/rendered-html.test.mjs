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
  const [page, css, layout] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(page, /materials.*requirements.*proposal.*export/s);
  assert.match(page, /Requirement/);
  assert.match(page, /Section/);
  assert.match(page, /原文依据/);
  assert.match(page, /逐章生成/);
  assert.match(page, /自动校核/);
  assert.match(page, /下载技术方案演示稿/);
  assert.match(css, /@media \(max-width: 900px\)/);
  assert.match(layout, /标书智能工作台/);
});
