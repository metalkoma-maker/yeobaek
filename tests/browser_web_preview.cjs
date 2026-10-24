/* Start tools/run_web_preview.py locally, then run this against port 8001.
   Exercises the actual Flask preview and a new synthetic DB, not a mock API. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const localUrl = process.env.PREVIEW_BASE_URL || 'http://127.0.0.1:8001';
const publicOrigin = process.env.PREVIEW_TUNNEL_TEST === '1' ? 'https://synthetic-browser.trycloudflare.com' : null;
const baseUrl = publicOrigin || localUrl;
async function forwardPreview(context) {
  if (!publicOrigin) return;
  // Model HTTPS termination without creating a public tunnel in tests.
  await context.route(publicOrigin + '/**', async route => {
    const url = new URL(route.request().url());
    const response = await route.fetch({ url: localUrl + url.pathname + url.search });
    await route.fulfill({ response });
  });
}
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  try {
    const context = await browser.newContext({ acceptDownloads: true });
    await forwardPreview(context);
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(baseUrl + '/');
    assert.match(await page.locator('#previewNotice').textContent(), /가짜 원고 전용/);
    assert.equal(await page.inputValue('#email'), 'mobile-test@example.com');
    await page.locator('#submitAuth').click();
    await page.locator('#workspace').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#documents .documentCard').count(), 3);
    const before = await page.locator('#documents .documentCard').evaluateAll(nodes => nodes.map(node => node.dataset.id));
    const saved = page.waitForResponse(response => response.url().endsWith('/api/manuscript-order') && response.request().method() === 'PUT');
    await page.locator('[data-id="' + before[2] + '"]').dragTo(page.locator('[data-id="' + before[0] + '"]'), { targetPosition: { x: 20, y: 5 } });
    assert.equal((await saved).status(), 200);
    await page.waitForFunction(() => !orderBusy);
    const expected = [before[2], before[0], before[1]];
    assert.deepEqual(await page.locator('#documents .documentCard').evaluateAll(nodes => nodes.map(node => node.dataset.id)), expected);
    const other = await browser.newContext();
    await forwardPreview(other);
    const otherPage = await other.newPage();
    await otherPage.goto(baseUrl + '/');
    await otherPage.locator('#submitAuth').click();
    await otherPage.locator('#workspace').waitFor({ state: 'visible' });
    assert.deepEqual(await otherPage.locator('#documents .documentCard').evaluateAll(nodes => nodes.map(node => node.dataset.id)), expected);
    await page.clock.setFixedTime(new Date('2026-10-15T03:04:05Z'));
    const pendingDownload = page.waitForEvent('download');
    await page.locator('#download').click();
    const download = await pendingDownload;
    assert.match(await fs.readFile(await download.path(), 'utf8'), /^내려받은 시각: 2026-10-15 12:04:05 \(한국시간\)/);
    await otherPage.locator('#logout').click();
    await otherPage.locator('#forgotPassword').waitFor({ state: 'visible' });
    await otherPage.locator('#forgotPassword').click();
    await otherPage.locator('#recoveryEmail').fill('mobile-test@example.com');
    await otherPage.locator('#recoveryMailSubmit').click();
    await otherPage.waitForFunction(() => document.querySelector('#recoveryMailMessage').textContent.includes('안내를 보냈습니다'));
    await otherPage.goto(baseUrl + '/_preview/mail');
    const resetLink = await otherPage.getByRole('link', { name: '비밀번호 재설정 링크 열기' }).getAttribute('href');
    assert.equal(new URL(resetLink).protocol, 'https:');
    await otherPage.goto(baseUrl + '/' + new URL(resetLink).hash);
    await otherPage.locator('#resetDialog').waitFor({ state: 'visible' });
    await otherPage.locator('#resetPassword').fill('new-test-password-123');
    await otherPage.locator('#resetPasswordAgain').fill('new-test-password-123');
    await otherPage.locator('#resetSubmit').click();
    await otherPage.waitForFunction(() => document.querySelector('#resetMessage').textContent.includes('비밀번호를 바꿨습니다'));
    await otherPage.locator('#resetClose').click();
    await otherPage.locator('#password').fill('new-test-password-123');
    await otherPage.locator('#submitAuth').click();
    await otherPage.locator('#workspace').waitFor({ state: 'visible' });
    assert.equal(await otherPage.locator('#documents .documentCard').count(), 3);
    assert.deepEqual(errors, []);
    if (process.env.PREVIEW_SCREENSHOT) await page.screenshot({ path: process.env.PREVIEW_SCREENSHOT });
    await other.close(); await context.close();
    console.log('PASS: real preview has 3 fake documents; login, drag, download and password reset work');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
