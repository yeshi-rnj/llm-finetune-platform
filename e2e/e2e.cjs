// Real-browser end-to-end test. Run: node e2e/e2e.cjs   (needs playwright + chromium, python3 with backend deps)
const { chromium } = require("playwright");
const { spawn } = require("child_process");
const http = require("http");
const fs = require("fs");
const os = require("os");
const path = require("path");
const assert = require("assert");

const ROOT = path.resolve(__dirname, "..");
const API_PORT = 8123, ALLOWED_PORT = 5174, DENIED_PORT = 5175;
const results = [];
async function step(name, fn) {
  try { await fn(); results.push(["PASS", name]); console.log("PASS", name); }
  catch (e) { results.push(["FAIL", name, e.message]); console.log("FAIL", name, "\n     ", e.message.split("\n")[0]); }
}

function makeCsv() {
  const pos = ["great", "excellent", "love", "wonderful", "fantastic", "happy"], neg = ["terrible", "awful", "hate", "horrible", "worst", "sad"];
  const fill = ["the", "product", "service", "really", "was", "very", "today", "this"];
  let s = "text,label\n", r = 7;
  const rnd = () => (r = (r * 1103515245 + 12345) % 2147483648) / 2147483648;
  const pick = (a, n) => Array.from({ length: n }, () => a[Math.floor(rnd() * a.length)]).join(" ");
  for (let i = 0; i < 40; i++) { s += `"${pick(fill, 4)} ${pick(pos, 2)}",positive\n"${pick(fill, 4)} ${pick(neg, 2)}",negative\n`; }
  return s;
}

function staticServer(port, apiBase) {  // simulates a separate dev-server origin (no CSP) for the CORS test
  const srv = http.createServer((req, res) => {
    const u = req.url.split("?")[0];
    if (u === "/config.js") { res.setHeader("Content-Type", "application/javascript"); return res.end(`window.APP_CONFIG=${JSON.stringify({ apiBase })};`); }
    const f = path.join(ROOT, "frontend", u === "/" ? "index.html" : u);
    if (!f.startsWith(path.join(ROOT, "frontend")) || !fs.existsSync(f)) { res.statusCode = 404; return res.end(); }
    res.setHeader("Content-Type", f.endsWith(".js") ? "application/javascript" : f.endsWith(".css") ? "text/css" : "text/html");
    res.end(fs.readFileSync(f));
  });
  return new Promise((ok) => srv.listen(port, "localhost", () => ok(srv)));
}

async function waitHealthy(url) {
  for (let i = 0; i < 50; i++) { try { const r = await fetch(url); if (r.ok) return; } catch (e) {} await new Promise((r) => setTimeout(r, 200)); }
  throw new Error("server did not start");
}

(async () => {
  const data = fs.mkdtempSync(path.join(os.tmpdir(), "ft-e2e-"));
  const server = spawn("python3", ["-m", "app"], {
    cwd: path.join(ROOT, "backend"),
    env: { ...process.env, DATA_DIR: data, PORT: String(API_PORT), LOG_REQUESTS: "0", JWT_SECRET: "e".repeat(40),
           CORS_ORIGINS: `http://localhost:${ALLOWED_PORT}`, FRONTEND_DIR: path.join(ROOT, "frontend") },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let serverLog = ""; server.stderr.on("data", (d) => (serverLog += d)); server.stdout.on("data", (d) => (serverLog += d));
  await waitHealthy(`http://127.0.0.1:${API_PORT}/api/health`);
  const allowed = await staticServer(ALLOWED_PORT, `http://127.0.0.1:${API_PORT}`);
  const denied = await staticServer(DENIED_PORT, `http://127.0.0.1:${API_PORT}`);
  const browser = await chromium.launch();
  const base = `http://127.0.0.1:${API_PORT}`;

  const newPage = async (ctx) => {
    const page = await ctx.newPage();
    page.problems = [];
    page.on("pageerror", (e) => page.problems.push("pageerror: " + e.message));
    page.on("console", (m) => { if (m.type() === "error") page.problems.push("console: " + m.text()); });
    page.on("dialog", (d) => d.accept());
    return page;
  };
  const signup = async (page, email, url = base) => {
    await page.goto(url + "/");
    await page.waitForSelector("#auth-email");
    await page.fill("#auth-email", email); await page.fill("#auth-password", "password123");
    await page.click("#btn-register");
    await page.waitForSelector("#proj-name");
  };

  const ctxA = await browser.newContext();
  const A = await newPage(ctxA);
  let projectUrl, modelUrl;

  await step("unauthenticated visit redirects to login", async () => {
    await A.goto(base + "/#/projects");
    await A.waitForSelector("#auth-email");
    assert.ok(A.url().endsWith("#/login"), A.url());
  });
  await step("login with wrong credentials shows an error and stays on login", async () => {
    await A.fill("#auth-email", "nobody@example.com"); await A.fill("#auth-password", "wrongwrong");
    await A.click("#btn-login");
    await A.waitForSelector(".flash.error");
    assert.match(await A.textContent(".flash.error"), /Invalid email or password/);
  });
  await step("register new user (button) lands on projects page", async () => {
    await signup(A, "alice@example.com");
    assert.match(await A.textContent("#no-projects"), /No projects yet/);
  });
  await step("create project (form submit via Enter key) navigates to project page", async () => {
    await A.fill("#proj-name", "Sentiment <b>demo</b>"); await A.fill("#proj-desc", "e2e");
    await A.press("#proj-name", "Enter");
    await A.waitForSelector("#project-title");
    assert.strictEqual(await A.textContent("#project-title"), "Sentiment <b>demo</b>");   // escaped, not rendered as HTML
    assert.strictEqual(await A.locator("#project-title b").count(), 0);
    projectUrl = A.url();
  });
  await step("uploading without choosing a file shows a message", async () => {
    await A.click("#btn-upload");
    assert.match(await A.textContent(".flash.error"), /Choose a CSV/);
  });
  await step("uploading an invalid CSV shows the server's validation error", async () => {
    await A.setInputFiles("#ds-file", { name: "bad.csv", mimeType: "text/csv", buffer: Buffer.from("a,b\n1,2\n") });
    await A.click("#btn-upload");
    await A.waitForSelector(".flash.error");
    assert.match(await A.textContent(".flash.error"), /'text' and 'label'/);
  });
  await step("uploading a valid CSV lists the dataset", async () => {
    await A.setInputFiles("#ds-file", { name: "reviews.csv", mimeType: "text/csv", buffer: Buffer.from(makeCsv()) });
    await A.click("#btn-upload");
    await A.waitForSelector("#datasets-table");
    assert.match(await A.textContent("#datasets-table"), /reviews\.csv.*80/s);
  });
  await step("training job is submitted and reaches 'succeeded' (UI polls)", async () => {
    await A.fill("#job-name", "sentiment-v1");
    await A.click("#btn-train");
    await A.waitForSelector("#jobs-table .badge");
    await A.waitForSelector("#jobs-table .badge.succeeded", { timeout: 60000 });
    assert.match(await A.textContent("#jobs-table"), /accuracy \d+\.\d%/);
    await A.waitForSelector("#models-table");
    assert.match(await A.textContent("#models-table"), /sentiment-v1/);
  });
  await step("lora job without torch fails visibly with an actionable message", async () => {
    await A.selectOption("#job-method", "lora-causal-lm");
    await A.click("#btn-train");
    await A.waitForSelector("#jobs-table .badge.failed", { timeout: 30000 });
    assert.match(await A.textContent("#jobs-table"), /requires torch, transformers and peft/);
  });
  await step("model page: evaluation runs and shows metrics + confusion matrix", async () => {
    await A.click("#models-table a");
    await A.waitForSelector("#model-title");
    modelUrl = A.url();
    await A.click("#btn-evaluate");
    await A.waitForSelector("#eval-accuracy");
    const acc = parseFloat((await A.textContent("#eval-accuracy")).match(/([\d.]+)%/)[1]);
    assert.ok(acc >= 90, "accuracy " + acc);
    assert.ok((await A.locator("table.cm tr").count()) === 3);
  });
  await step("model page: inference returns labels for each line", async () => {
    await A.fill("#predict-input", "this was excellent and wonderful\nawful terrible broken\n<script>alert(1)</script> love it");
    await A.click("#btn-predict");
    await A.waitForSelector("#predict-table");
    const rows = await A.locator("#predict-table tr").allTextContents();
    assert.match(rows[1], /positive/); assert.match(rows[2], /negative/);
    assert.strictEqual(await A.locator("#predict-table script").count(), 0);
  });
  await step("breadcrumb link returns to the project; project list link works", async () => {
    await A.click("text=← Project"); await A.waitForSelector("#project-title");
    await A.click("header.top >> text=Projects"); await A.waitForSelector("#projects-table");
  });
  await step("logout returns to login and protects pages; login again works", async () => {
    await A.click("#btn-logout"); await A.waitForSelector("#auth-email");
    await A.goto(projectUrl); await A.waitForSelector("#auth-email");
    await A.fill("#auth-email", "alice@example.com"); await A.fill("#auth-password", "password123");
    await A.click("#btn-login"); await A.waitForSelector("#projects-table");
  });
  await step("expired/invalid token is handled: UI returns to login", async () => {
    await A.evaluate(() => localStorage.setItem("token", "garbage"));
    await A.reload(); await A.waitForSelector("#auth-email");
  });
  await step("no JS errors / CSP violations in the same-origin run", async () => {
    const real = A.problems.filter((p) => !/status of (4\d\d)/.test(p));  // expected 4xx from negative tests
    assert.deepStrictEqual(real, []);
  });

  // ---- isolation through the real UI
  const ctxB = await browser.newContext();
  const B = await newPage(ctxB);
  await step("user B cannot open user A's project or model via direct URL", async () => {
    await signup(B, "bob@example.com");
    assert.match(await B.textContent("#no-projects"), /No projects yet/);
    const errorText = (re) => B.waitForFunction((src) => { const el = document.querySelector("#page-error"); return el && new RegExp(src).test(el.textContent); }, re, { timeout: 10000 });
    await B.goto(projectUrl); await errorText("Project not found");
    await B.goto(modelUrl); await errorText("Model not found");
  });
  await step("delete project from UI (confirm dialog) removes it", async () => {
    await B.goto(base + "/#/projects"); await B.waitForSelector("#proj-name");
    await B.fill("#proj-name", "temp"); await B.click("#btn-create-project");
    await B.waitForSelector("#project-title");
    await B.goto(base + "/#/projects"); await B.waitForSelector("#projects-table");
    await B.click("#projects-table button[data-action=delete-project]");
    await B.waitForSelector("#no-projects");
  });

  // ---- CORS in a real browser
  const ctxC = await browser.newContext();
  const C = await newPage(ctxC);
  await step("CORS: page on an allowed other origin can register, create project, call API", async () => {
    await signup(C, "carol@example.com", `http://localhost:${ALLOWED_PORT}`);
    await C.fill("#proj-name", "cors-ok"); await C.click("#btn-create-project");
    await C.waitForSelector("#project-title");
    assert.strictEqual(await C.textContent("#project-title"), "cors-ok");
  });
  const ctxD = await browser.newContext();
  const D = await newPage(ctxD);
  await step("CORS: page on a NOT-allowed origin is blocked by the browser", async () => {
    await D.goto(`http://localhost:${DENIED_PORT}/`); await D.waitForSelector("#auth-email");
    await D.fill("#auth-email", "dave@example.com"); await D.fill("#auth-password", "password123");
    await D.click("#btn-register");
    await D.waitForSelector(".flash.error");
    assert.match(await D.textContent(".flash.error"), /Failed to fetch|NetworkError|Load failed/i);
    assert.ok(D.problems.some((p) => /CORS|Access-Control|blocked/i.test(p)), "expected a CORS console error: " + D.problems.join(" | "));
  });
  await step("denied origin: preflight blocked the POST, so no account was created", async () => {
    const r = await fetch(base + "/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: "dave@example.com", password: "password123" }) });
    assert.strictEqual(r.status, 401);
  });

  await browser.close(); allowed.close(); denied.close(); server.kill();
  fs.rmSync(data, { recursive: true, force: true });
  const failed = results.filter((r) => r[0] === "FAIL");
  console.log(`\n${results.length - failed.length}/${results.length} browser steps passed`);
  if (failed.length) { console.log("server log tail:\n" + serverLog.slice(-800)); process.exit(1); }
})().catch((e) => { console.error("HARNESS ERROR", e); process.exit(2); });
