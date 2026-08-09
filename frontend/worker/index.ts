/** Cloudflare Worker entry point for the vinext-starter template. */
import { handleImageOptimization, DEFAULT_DEVICE_SIZES, DEFAULT_IMAGE_SIZES } from "vinext/server/image-optimization";
import handler from "vinext/server/app-router-entry";

const BID_AGENT_API_ORIGIN = "http://101.200.154.141";

interface Env {
  ASSETS: Fetcher;
  BID_AGENT_EDGE_SECRET: string;
  DB: D1Database;
  IMAGES: {
    input(stream: ReadableStream): {
      transform(options: Record<string, unknown>): {
        output(options: { format: string; quality: number }): Promise<{ response(): Response }>;
      };
    };
  };
}

interface ExecutionContext {
  waitUntil(promise: Promise<unknown>): void;
  passThroughOnException(): void;
}

// Image security config. SVG sources with .svg extension auto-skip the
// optimization endpoint on the client side (served directly, no proxy).
// To route SVGs through the optimizer (with security headers), set
// dangerouslyAllowSVG: true in next.config.js and uncomment below:
// const imageConfig: ImageConfig = { dangerouslyAllowSVG: true };

const worker = {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/api/v1" || url.pathname.startsWith("/api/v1/")) {
      if (!env.BID_AGENT_EDGE_SECRET) {
        return Response.json(
          { error: { code: "GATEWAY_NOT_CONFIGURED", message: "服务入口尚未配置。" } },
          { status: 503 },
        );
      }
      const upstream = new URL(url.pathname + url.search, BID_AGENT_API_ORIGIN);
      const headers = new Headers(request.headers);
      headers.delete("host");
      headers.delete("cf-connecting-ip");
      headers.delete("cf-ray");
      headers.delete("cf-visitor");
      headers.set("X-Bid-Agent-Edge-Secret", env.BID_AGENT_EDGE_SECRET);

      return fetch(upstream, {
        method: request.method,
        headers,
        body: request.method === "GET" || request.method === "HEAD"
          ? undefined
          : request.body,
        redirect: "manual",
      });
    }

    if (url.pathname === "/_vinext/image") {
      const allowedWidths = [...DEFAULT_DEVICE_SIZES, ...DEFAULT_IMAGE_SIZES];
      return handleImageOptimization(request, {
        fetchAsset: (path) => env.ASSETS.fetch(new Request(new URL(path, request.url))),
        transformImage: async (body, { width, format, quality }) => {
          const result = await env.IMAGES.input(body).transform(width > 0 ? { width } : {}).output({ format, quality });
          return result.response();
        },
      }, allowedWidths);
    }

    return handler.fetch(request, env, ctx);
  },
};

export default worker;
