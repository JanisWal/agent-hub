#!/usr/bin/env node
// The test browser of the agents (Janis, 21.11.2026: "the AI could not test it without a browser"). Headless Chromium
// from Debian, driven by playwright-core (fixed versions in the Dockerfiles). It serves /work on 127.0.0.1 inside the
// run's container, opens a page, does the steps in the order given and prints what a person would see: the title,
// the visible text, console messages and page errors, and where the screenshot lies (the AI looks at it with its
// image tool). No internet: the browser gets no proxy, the run's network has no route out.
//
//   hub-browser index.html --click "#seven" --fill "#input=12" --press Enter --wait 300 --shot
//   hub-browser --help
"use strict";
const http = require("http");
const fs = require("fs");
const path = require("path");

const ROOT = process.env.HUB_BROWSER_ROOT || "/work";
const SHOTS = path.join(ROOT, ".hub-shots");          // never committed (runner/workspace.py NEVER_COMMIT)
const CHROMIUM = process.env.HUB_CHROMIUM || "/usr/bin/chromium";
const TEXT_MAX = 4000;
const TYPES = { ".html": "text/html", ".htm": "text/html", ".js": "text/javascript", ".mjs": "text/javascript",
  ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp", ".ico": "image/x-icon", ".wasm": "application/wasm",
  ".txt": "text/plain", ".map": "application/json" };
const HELP = `hub-browser PAGE [STEPS] - open a page of /work (or http://127.0.0.1:PORT/...) in a headless browser.
Steps, done in this order:
  --click SELECTOR        click an element (CSS selector, or text=Label)
  --fill SELECTOR=TEXT    type TEXT into a field
  --press KEY             press a key (Enter, Escape, Backspace, 7, ...)
  --wait MS               wait (at most 10000)
  --shot [NAME]           save a screenshot to /work/.hub-shots/NAME.png (default shot-N)
  --size WxH              window size, before the page opens (default 1280x800; 390x844 for a phone)
Prints the title, the visible text, console messages and page errors.`;

function serve() {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const clean = decodeURIComponent(new URL(req.url, "http://x").pathname);
      let file = path.normalize(path.join(ROOT, clean));
      if (file !== ROOT && !file.startsWith(ROOT + path.sep)) { res.writeHead(403); return res.end(); }
      if (fs.existsSync(file) && fs.statSync(file).isDirectory()) file = path.join(file, "index.html");
      fs.readFile(file, (err, data) => {
        if (err) { res.writeHead(404); return res.end("not found"); }
        res.writeHead(200, { "Content-Type": TYPES[path.extname(file).toLowerCase()] || "application/octet-stream" });
        res.end(data);
      });
    });
    server.listen(0, "127.0.0.1", () => resolve(server));
  });
}

function parse(argv) {
  const steps = [];
  let page = null, size = [1280, 800];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const next = () => { if (i + 1 >= argv.length) throw new Error(`${a} needs a value`); return argv[++i]; };
    if (a === "--help" || a === "-h") return { help: true };
    else if (a === "--click") steps.push(["click", next()]);
    else if (a === "--fill") { const v = next(); const at = v.indexOf("="); if (at < 1) throw new Error("--fill SELECTOR=TEXT"); steps.push(["fill", v.slice(0, at), v.slice(at + 1)]); }
    else if (a === "--press") steps.push(["press", next()]);
    else if (a === "--wait") steps.push(["wait", Math.min(10000, parseInt(next(), 10) || 0)]);
    else if (a === "--shot") steps.push(["shot", argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[++i] : ""]);
    else if (a === "--size") { const m = /^(\d{2,4})x(\d{2,4})$/.exec(next()); if (!m) throw new Error("--size WxH"); size = [+m[1], +m[2]]; }
    else if (!a.startsWith("--") && page === null) page = a;
    else throw new Error(`unknown: ${a}`);
  }
  if (!page) throw new Error("which page? (hub-browser --help)");
  return { page, steps, size };
}

async function main() {
  let args;
  try { args = parse(process.argv.slice(2)); } catch (e) { console.error(e.message); process.exit(2); }
  if (args.help) { console.log(HELP); return; }
  const { chromium } = require("playwright-core");
  let server = null, url = args.page;
  if (!/^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?\//.test(url)) {
    if (/^[a-z]+:/i.test(url)) { console.error("only pages of /work or of 127.0.0.1"); process.exit(2); }
    server = await serve();
    url = `http://127.0.0.1:${server.address().port}/${url.replace(/^\/?work\//, "").replace(/^\//, "")}`;
  }
  const browser = await chromium.launch({ executablePath: CHROMIUM, headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--no-proxy-server"] });
  const notes = [];
  let shots = 0, failed = false;
  try {
    const page = await browser.newPage({ viewport: { width: args.size[0], height: args.size[1] } });
    page.on("console", (m) => notes.push(`console.${m.type()}: ${m.text()}`));
    page.on("pageerror", (e) => notes.push(`page error: ${e.message}`));
    page.on("requestfailed", (r) => notes.push(`request failed: ${r.url()} (${r.failure() && r.failure().errorText})`));
    const answer = await page.goto(url, { waitUntil: "load", timeout: 20000 });
    console.log(`opened ${url} (${answer ? answer.status() : "no answer"})`);
    for (const step of args.steps) {
      try {
        if (step[0] === "click") await page.click(step[1], { timeout: 5000 });
        else if (step[0] === "fill") await page.fill(step[1], step[2], { timeout: 5000 });
        else if (step[0] === "press") await page.keyboard.press(step[1]);
        else if (step[0] === "wait") await page.waitForTimeout(step[1]);
        else if (step[0] === "shot") {
          fs.mkdirSync(SHOTS, { recursive: true });
          const name = (step[1] || `shot-${++shots}`).replace(/[^\w.-]/g, "_").replace(/\.png$/, "") + ".png";
          await page.screenshot({ path: path.join(SHOTS, name), fullPage: true });
          console.log(`screenshot: ${path.join(SHOTS, name)}`);
        }
        console.log(`ok: ${step.join(" ")}`);
      } catch (e) {
        failed = true;
        console.log(`FAILED: ${step.join(" ")}: ${e.message.split("\n")[0]}`);
      }
    }
    console.log(`title: ${await page.title()}`);
    const text = (await page.evaluate(() => document.body ? document.body.innerText : "")).trim();
    console.log(`visible text:\n${text.slice(0, TEXT_MAX)}${text.length > TEXT_MAX ? "\n[...]" : ""}`);
  } finally {
    await browser.close();
    if (server) server.close();
  }
  console.log(notes.length ? `messages:\n${notes.slice(0, 50).join("\n")}` : "messages: none");
  process.exit(failed ? 1 : 0);
}

main().catch((e) => { console.error(`hub-browser: ${e.message.split("\n")[0]}`); process.exit(1); });
