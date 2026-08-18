// Help & tutorial panel browser live test via CDP.
// Run with Windows node:  node D:\TTS\scripts\help_browser_test.mjs
import { setTimeout as sleep } from 'node:timers/promises';

const CDP_HTTP = 'http://127.0.0.1:9222';
const APP_URL = 'http://localhost:5173/';
const POLL_MS = 1000;
const MAX_WAIT_MS = 60000;

class CDP {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl);
    this.id = 0;
    this.pending = new Map();
  }
  async connect() {
    await new Promise((resolve, reject) => {
      this.ws.onopen = resolve;
      this.ws.onerror = reject;
    });
    this.ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(JSON.stringify(msg.error)));
        else resolve(msg.result);
      }
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  close() {
    try { this.ws.close(); } catch {}
  }
}

async function evalValue(cdp, expression) {
  const res = await cdp.send('Runtime.evaluate', {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  if (res.exceptionDetails) throw new Error(`eval failed: ${JSON.stringify(res.exceptionDetails)}`);
  return res.result.value;
}

async function waitFor(cdp, expression, label, timeout = MAX_WAIT_MS) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const val = await evalValue(cdp, expression);
    if (val) return val;
    await sleep(POLL_MS);
  }
  throw new Error(`TIMEOUT waiting for: ${label}`);
}

function log(msg) {
  console.log(`[${new Date().toISOString()}] ${msg}`);
}

async function main() {
  const resp = await fetch(`${CDP_HTTP}/json/new?about:blank`, { method: 'PUT' });
  const target = await resp.json();
  log(`page target: ${target.id}`);

  const cdp = new CDP(target.webSocketDebuggerUrl);
  await cdp.connect();
  log('CDP connected');

  const consoleErrors = [];
  cdp.ws.addEventListener('message', (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.method === 'Runtime.exceptionThrown') {
      consoleErrors.push(JSON.stringify(msg.params.exceptionDetails?.exception?.description || msg.params.exceptionDetails));
    } else if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
      consoleErrors.push(msg.params.args.map((a) => a.value ?? a.description ?? '').join(' '));
    }
  });

  await cdp.send('Runtime.enable');
  await cdp.send('Page.enable');

  log(`navigating to ${APP_URL}`);
  await cdp.send('Page.navigate', { url: APP_URL });

  // 1. Wait for the sidebar + help icon (aria-label = 도움말/Help)
  await waitFor(
    cdp,
    `[...document.querySelectorAll('a[aria-label]')].some(a => a.getAttribute('aria-label') === '도움말' || a.getAttribute('aria-label') === 'Help')`,
    'sidebar help icon',
  );
  log('sidebar help icon present');

  // 2. Click the help icon -> /help route
  await evalValue(cdp, `[...document.querySelectorAll('a[aria-label]')].find(a => a.getAttribute('aria-label') === '도움말' || a.getAttribute('aria-label') === 'Help').click()`);
  await waitFor(cdp, `location.pathname === '/help'`, 'navigate to /help');
  log('navigated to /help');

  // 3. Verify help title + subtitle
  const header = await waitFor(cdp, `(() => {
    const h1 = document.querySelector('h1');
    return h1 && h1.textContent === '도움말' ? { title: h1.textContent, hasSub: !!document.querySelector('header p') } : null;
  })()`, 'help title');
  log(`help header: ${JSON.stringify(header)}`);
  if (!header || !header.hasSub) throw new Error('help title/subtitle missing');

  // 4. Feature menu (left) — should list 8 features, first shows 병기
  const features = await evalValue(cdp, `[...document.querySelectorAll('nav button')].map(b => b.textContent.trim())`);
  log(`feature menu (${features.length}): ${JSON.stringify(features)}`);
  if (features.length !== 8) throw new Error(`expected 8 features, got ${features.length}`);
  if (features[0] !== '음성 합성 (Text-to-Speech, TTS)') {
    throw new Error(`병기 missing in first feature title: "${features[0]}"`);
  }

  // 5. Right detail panel — default selected (generate): description + terms + tutorial btn
  const detail = await evalValue(cdp, `(() => {
    const right = [...document.querySelectorAll('section')].find(s => s.getAttribute('aria-label') === '관련 용어');
    return {
      h2: document.querySelector('h2')?.textContent ?? null,
      hasDesc: !!document.querySelector('p.text-sm'),
      terms: right ? [...right.querySelectorAll('div')].filter(d => d.className.includes('border-border')).map(d => d.textContent.trim().replace(/\\s+/g, ' ')) : [],
      hasTutorial: [...document.querySelectorAll('a')].some(a => a.textContent.includes('튜토리얼 메뉴로 이동')),
      tutorialHref: (() => { const a = [...document.querySelectorAll('a')].find(a => a.textContent.includes('튜토리얼 메뉴로 이동')); return a ? a.getAttribute('href') : null; })(),
    };
  })()`);
  log(`detail panel: ${JSON.stringify(detail)}`);
  if (!detail.h2) throw new Error('detail title missing');
  if (!detail.hasDesc) throw new Error('detail description missing');
  if (!detail.terms || detail.terms.length !== 5) throw new Error(`expected 5 terms, got ${detail.terms.length}`);
  if (!detail.terms[0].includes('음성 합성') || !detail.terms[0].includes('Text-to-Speech')) {
    throw new Error(`term 병기 wrong: ${detail.terms[0]}`);
  }
  if (!detail.hasTutorial) throw new Error('tutorial button missing');
  log(`tutorial href: ${detail.tutorialHref}`);

  // 6. Switch feature to "음성 변환" and verify panel updates + tutorial route changes
  await evalValue(cdp, `[...document.querySelectorAll('nav button')].find(b => b.textContent.includes('음성 변환')).click()`);
  await sleep(400);
  const vc = await evalValue(cdp, `(() => {
    const right = [...document.querySelectorAll('section')].find(s => s.getAttribute('aria-label') === '관련 용어');
    const a = [...document.querySelectorAll('a')].find(a => a.textContent.includes('튜토리얼 메뉴로 이동'));
    return {
      h2: document.querySelector('h2')?.textContent ?? null,
      terms: right ? right.querySelectorAll('div').length : 0,
      href: a ? a.getAttribute('href') : null,
    };
  })()`);
  log(`after switching to VC: ${JSON.stringify(vc)}`);
  if (!vc.h2 || !vc.h2.includes('음성 변환')) throw new Error(`VC detail not shown: ${vc.h2}`);
  if (vc.href !== '/vc') throw new Error(`VC tutorial href wrong: ${vc.href}`);

  // 7. Click the tutorial button -> navigates to /vc
  await evalValue(cdp, `[...document.querySelectorAll('a')].find(a => a.textContent.includes('튜토리얼 메뉴로 이동')).click()`);
  await waitFor(cdp, `location.pathname === '/vc'`, 'navigate to /vc via tutorial link');
  log('tutorial link navigated to /vc');

  log(`console errors: ${consoleErrors.length === 0 ? 'none' : consoleErrors.join(' | ')}`);
  if (consoleErrors.length > 0) throw new Error('console errors present');
  cdp.close();
  log('DONE');
}

main().catch((err) => {
  console.error('FAILED:', err.message);
  process.exit(1);
});