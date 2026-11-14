/* Real login UI and cookies through a locally simulated Codespaces proxy.
   Run from the repo root: node tests/browser_mobile_proxy.cjs
   Only a new temporary fake DB and loopback HTTP are used. */
const assert = require('node:assert/strict');
const http = require('node:http');
const { spawn, execFileSync } = require('node:child_process');
const { randomBytes } = require('node:crypto');
const path = require('node:path');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const origin = 'https://synthetic-cloud-8000.app.github.dev';
const env = { ...process.env, CODESPACES: 'true', CODESPACE_NAME: 'synthetic-cloud',
  EXPO_PUBLIC_TEST_API_URL: origin, YEOBAEK_TEST_RUN_ID: randomBytes(16).toString('hex') };

async function forward(route, rewrittenOrigin) {
  const request = route.request();
  const headers = await request.allHeaders();
  if (headers.origin === origin) {
    assert.ok(headers.referer.startsWith(origin + '/'));
    // Playwright pauses before Chromium adds Fetch Metadata. Model the
    // same-origin metadata retained by the forwarded browser request.
    headers['sec-fetch-site'] = 'same-origin';
    headers.origin = rewrittenOrigin;
  }
  headers.host = new URL(origin).host;
  delete headers['accept-encoding'];
  const url = new URL(request.url());
  const result = await new Promise((resolve, reject) => {
    const local = http.request({ host: '127.0.0.1', port: 8000,
      path: url.pathname + url.search, method: request.method(), headers }, response => {
      const chunks = [];
      response.on('data', chunk => chunks.push(chunk));
      response.on('end', () => resolve({ response, body: Buffer.concat(chunks) }));
    });
    local.on('error', reject);
    local.end(request.postDataBuffer());
  });
  const responseHeaders = {};
  for (const [name, value] of Object.entries(result.response.headers)) {
    if (value !== undefined && !['connection', 'transfer-encoding'].includes(name))
      responseHeaders[name] = Array.isArray(value) ? value.join('\n') : value;
  }
  await route.fulfill({ status: result.response.statusCode, headers: responseHeaders, body: result.body });
}

(async () => {
  const server = spawn(path.join(root, '.venv/bin/python'), ['-u', 'tools/run_mobile_test.py'],
    { cwd: root, env, stdio: ['ignore', 'pipe', 'pipe'] });
  let serverLog = '';
  server.stdout.on('data', chunk => { serverLog += chunk; });
  server.stderr.on('data', chunk => { serverLog += chunk; });
  let browser;
  try {
    execFileSync(path.join(root, '.venv/bin/python'),
      ['tools/check_mobile_test_server.py', String(server.pid)], { cwd: root, env, stdio: 'pipe' });
    // A different runner on the same port must fail, not launch Metro.
    assert.throws(() => execFileSync(path.join(root, '.venv/bin/python'),
      ['tools/check_mobile_test_server.py', String(server.pid)],
      { cwd: root, env: { ...env, YEOBAEK_TEST_RUN_ID: 'other-runner' }, stdio: 'pipe' }),
      /serving another runner/);
    browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium',
      headless: true, args: ['--no-sandbox'] });
    for (const rewritten of [origin, 'http://localhost:8000', 'https://localhost:8000']) {
      const context = await browser.newContext({ serviceWorkers: 'block' });
      try {
        let routeFailure;
        await context.route(origin + '/**', async route => {
          try { await forward(route, rewritten); }
          catch (error) { routeFailure = error; await route.abort(); }
        });
        const page = await context.newPage();
        await page.goto(origin + '/');
        await page.locator('#email').fill('mobile-test@example.com');
        await page.locator('#password').fill('test-password-123');
        await page.locator('#submitAuth').click();
        await page.locator('#workspace').waitFor({ state: 'visible' });
        await page.waitForFunction(() => document.querySelector('#body').value.length > 0);
        const cookie = (await context.cookies(origin)).find(item => item.name === 'novel_session');
        assert.ok(cookie && cookie.httpOnly && cookie.secure);
        const text = '가나다 ' + rewritten;
        const saved = page.waitForResponse(response => response.request().method() === 'PUT'
          && response.url().includes('/api/manuscripts/'));
        await page.locator('#body').fill(text);
        assert.equal((await saved).status(), 200);
        await page.reload();
        await page.locator('#workspace').waitFor({ state: 'visible' });
        await page.waitForFunction(expected => document.querySelector('#body').value === expected, text);
        if (routeFailure) throw routeFailure;
        console.log('Browser login, Secure cookie, autosave and reload: ' + rewritten);
      } finally { await context.close(); }
    }
  } catch (error) {
    console.error(serverLog);
    throw error;
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM');
    if (server.exitCode === null) await new Promise(resolve => server.once('exit', resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
