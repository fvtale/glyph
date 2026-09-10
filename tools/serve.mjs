// Serve public/ over HTTP for local work. No dependencies, no build step.
//
// This exists because the pages fetch their own data files, and a browser
// refuses to fetch anything when a page is opened from disk — so opening
// index.html directly shows every empty state at once and nothing else.
//
//   node tools/serve.mjs [port]

import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize, resolve } from "node:path";

const ROOT = resolve(import.meta.dirname, "..", "public");
const PORT = Number(process.argv[2] || 5199);

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".webp": "image/webp",
  ".woff2": "font/woff2",
};

createServer(async (request, response) => {
  const url = new URL(request.url, "http://localhost");
  let path = decodeURIComponent(url.pathname);
  if (path.endsWith("/")) path += "index.html";

  // Contain everything under public/: a request for ../../ is a bug or a probe,
  // and either way it gets a 403 rather than a file.
  const target = join(ROOT, normalize(path));
  if (!target.startsWith(ROOT)) {
    response.writeHead(403).end("403");
    return;
  }

  try {
    const body = await readFile(target);
    response.writeHead(200, {
      "content-type": TYPES[extname(target)] || "application/octet-stream",
      "cache-control": "no-store",
    });
    response.end(body);
  } catch {
    response.writeHead(404, { "content-type": "text/plain" }).end(`404 ${path}`);
  }
}).listen(PORT, () => console.log(`Meter on http://localhost:${PORT}/`));
