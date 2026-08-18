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

// Collect all rows (label + value) inside a section by aria-label.
const SPECS_SNIPPET = (label) => `(() => {
  const section = [...document.querySelectorAll('section')].find(s => s.getAttribute('aria-label') === ${JSON.stringify(label)});
  if (!section) return null;
  return [...section.querySelectorAll('div')].filter(d => d.className.includes('border-border')).map(d => d.textContent.trim().replace(/\\s+/g, ' '));
})()`;

// All <ol> steps text: ["title - body", ...]
const STEPS_SNIPPET = `(() => {
  const ol = document.querySelector('ol');
  if (!ol) return null;
  return [...ol.querySelectorAll('li')].map(li => li.textContent.trim().replace(/\\s+/g, ' '));
})()`;

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

  // 1. Sidebar help icon
  await waitFor(
    cdp,
    `[...document.querySelectorAll('a[aria-label]')].some(a => a.getAttribute('aria-label') === '도움말' || a.getAttribute('aria-label') === 'Help')`,
    'sidebar help icon',
  );
  log('sidebar help icon present');

  // 2. Navigate to /help
  await evalValue(cdp, `[...document.querySelectorAll('a[aria-label]')].find(a => a.getAttribute('aria-label') === '도움말' || a.getAttribute('aria-label') === 'Help').click()`);
  await waitFor(cdp, `location.pathname === '/help'`, 'navigate to /help');
  log('navigated to /help');

  // 3. Title
  await waitFor(cdp, `document.querySelector('h1')?.textContent === '도움말'`, 'help title');
  log('help title OK');

  // 4. Left menu: overview(1) + features(8) + tutorials(5) = 14
  const nav = await waitFor(cdp, `(() => {
    const b = [...document.querySelectorAll('nav button')];
    return b.length >= 14 ? b.map(x => x.textContent.trim().replace(/\\s+/g, ' ')) : null;
  })()`, 'nav items');
  log(`nav (${nav.length}): ${JSON.stringify(nav)}`);
  if (nav.length !== 14) throw new Error(`expected 14 nav items, got ${nav.length}`);
  if (!nav[0].includes('앱 개요')) throw new Error(`overview missing at nav[0]: ${nav[0]}`);
  if (!nav[1].includes('음성 합성 (Text-to-Speech, TTS)')) throw new Error(`병기 missing: ${nav[1]}`);
  const tutCount = nav.filter((x) => /\b[1-5]$/.test(x.trim())).length;
  if (tutCount < 5) throw new Error(`expected 5 tutorial badges, got ${tutCount}`);

  // 5. Overview panel (default selection): key features (batch chunking first) + specs
  const overviewFeatures = await waitFor(cdp, `(() => {
    const section = [...document.querySelectorAll('section')].find(s => s.getAttribute('aria-label') === '주요 특징');
    if (!section) return null;
    return [...section.querySelectorAll('div')].filter(d => d.className.includes('border-border')).map(d => d.textContent.trim().replace(/\\s+/g, ' '));
  })()`, 'overview features');
  log(`overview features (${overviewFeatures.length}): ${JSON.stringify(overviewFeatures)}`);
  if (overviewFeatures.length !== 5) throw new Error(`expected 5 overview features, got ${overviewFeatures.length}`);
  if (!overviewFeatures[0].includes('장문 자동 분할 · 순차 생성')) throw new Error(`batch chunking feature missing: ${overviewFeatures[0]}`);

  const overviewSpecs = await waitFor(cdp, SPECS_SNIPPET('생성 규격 (안정권)'), 'overview specs');
  log(`overview specs (${overviewSpecs.length}): ${JSON.stringify(overviewSpecs)}`);
  if (overviewSpecs.length !== 5) throw new Error(`expected 5 overview specs, got ${overviewSpecs.length}`);
  if (!overviewSpecs[0].includes('최대 50,000자')) throw new Error(`text limit wrong: ${overviewSpecs[0]}`);
  if (!overviewSpecs[3].includes('상한 없음')) throw new Error(`duration spec wrong: ${overviewSpecs[3]}`);

  // 6. Switch to a feature (음성 변환) — related tutorial card + jump href
  await evalValue(cdp, `[...document.querySelectorAll('nav button')].find(b => b.textContent.includes('음성 변환')).click()`);
  await sleep(300);
  const vcFeature = await evalValue(cdp, `(() => {
    const h2 = document.querySelector('h2')?.textContent ?? null;
    const card = [...document.querySelectorAll('section')].find(s => s.getAttribute('aria-label') === '연결된 튜토리얼');
    const a = [...document.querySelectorAll('a')].find(a => a.textContent.includes('해당 메뉴로 이동'));
    return { h2, hasCard: !!card, cardText: card ? card.textContent.replace(/\\s+/g, ' ').trim() : null, href: a ? a.getAttribute('href') : null };
  })()`);
  log(`VC feature panel: ${JSON.stringify(vcFeature)}`);
  if (!vcFeature.h2?.includes('음성 변환')) throw new Error(`VC panel not shown: ${vcFeature.h2}`);
  if (!vcFeature.hasCard || !vcFeature.cardText.includes('RVC 음성 변환')) throw new Error(`VC related tutorial missing: ${vcFeature.cardText}`);
  if (vcFeature.href !== '/vc') throw new Error(`VC jump href wrong: ${vcFeature.href}`);

  // 7. Tutorial 1 — 보이스 클로닝: high-quality spec + 8 steps
  await evalValue(cdp, `[...document.querySelectorAll('nav button')].find(b => b.textContent.includes('보이스 클로닝')).click()`);
  await sleep(300);
  const cloneSpecs = await waitFor(cdp, SPECS_SNIPPET('고품질 음성 규격'), 'clone specs');
  const cloneSteps = await evalValue(cdp, STEPS_SNIPPET);
  log(`clone specs (${cloneSpecs.length}): ${JSON.stringify(cloneSpecs)}`);
  log(`clone steps (${cloneSteps.length})`);
  if (cloneSpecs.length !== 5) throw new Error(`expected 5 clone specs, got ${cloneSpecs.length}`);
  if (!cloneSpecs[0].includes('10~30초')) throw new Error(`duration spec wrong: ${cloneSpecs[0]}`);
  if (!cloneSpecs[0].includes('최대 30초')) throw new Error(`max 30s missing: ${cloneSpecs[0]}`);
  if (cloneSteps.length !== 8) throw new Error(`expected 8 clone steps, got ${cloneSteps.length}`);
  if (!cloneSteps[0].includes('준비')) throw new Error(`first clone step wrong: ${cloneSteps[0]}`);

  // 8. Tutorial 3 — RVC 음성 변환: 6 steps
  await evalValue(cdp, `[...document.querySelectorAll('nav button')].find(b => b.textContent.includes('RVC 음성 변환')).click()`);
  await sleep(300);
  const vcSteps = await waitFor(cdp, STEPS_SNIPPET, 'vc tutorial steps');
  log(`vc steps (${vcSteps.length})`);
  if (vcSteps.length !== 6) throw new Error(`expected 6 vc steps, got ${vcSteps.length}`);

  // 9. Tutorial 4 — 전달 지시사항: example specs + 5 steps
  await evalValue(cdp, `[...document.querySelectorAll('nav button')].find(b => b.textContent.includes('전달 지시사항')).click()`);
  await sleep(300);
  const instructSpecs = await waitFor(cdp, SPECS_SNIPPET('지시 예제'), 'instruct specs');
  const instructSteps = await evalValue(cdp, STEPS_SNIPPET);
  log(`instruct specs (${instructSpecs.length}): ${JSON.stringify(instructSpecs)}`);
  if (instructSpecs.length !== 5) throw new Error(`expected 5 instruct specs, got ${instructSpecs.length}`);
  if (!instructSpecs[0].includes('신나고 들뜬')) throw new Error(`emotion example missing: ${instructSpecs[0]}`);
  if (!instructSpecs[4].includes('500자')) throw new Error(`instruct max 500자 missing: ${instructSpecs[4]}`);
  if (instructSteps.length !== 5) throw new Error(`expected 5 instruct steps, got ${instructSteps.length}`);

  // 10. Tutorial 5 — 장문 텍스트 생성: specs + 5 steps
  await evalValue(cdp, `[...document.querySelectorAll('nav button')].find(b => b.textContent.includes('장문 텍스트 생성')).click()`);
  await sleep(300);
  const longSpecs = await waitFor(cdp, SPECS_SNIPPET('장문 생성 규격'), 'long-text specs');
  const longSteps = await evalValue(cdp, STEPS_SNIPPET);
  log(`long-text specs (${longSpecs.length}): ${JSON.stringify(longSpecs)}`);
  if (longSpecs.length !== 3) throw new Error(`expected 3 long-text specs, got ${longSpecs.length}`);
  if (!longSpecs[0].includes('50,000자')) throw new Error(`long-text limit missing: ${longSpecs[0]}`);
  if (longSteps.length !== 5) throw new Error(`expected 5 long-text steps, got ${longSteps.length}`);

  // 11. Jump from tutorial 1 -> /voices
  await evalValue(cdp, `[...document.querySelectorAll('nav button')].find(b => b.textContent.includes('보이스 클로닝')).click()`);
  await sleep(300);
  await evalValue(cdp, `[...document.querySelectorAll('a')].find(a => a.textContent.includes('해당 메뉴로 이동')).click()`);
  await waitFor(cdp, `location.pathname === '/voices'`, 'navigate to /voices');
  log('tutorial jump navigated to /voices');

  // 12. Open voice creation dialog -> high-quality spec box visible in clone flow
  await waitFor(cdp, `[...document.querySelectorAll('button')].some(b => b.textContent.trim() === '새 음성' || b.textContent.trim() === 'New Voice')`, 'new voice button');
  await evalValue(cdp, `[...document.querySelectorAll('button')].find(b => b.textContent.trim() === '새 음성' || b.textContent.trim() === 'New Voice').click()`);
  const qgTitle = await waitFor(cdp, `[...document.querySelectorAll('span,div')].some(el => el.textContent.trim() === '고품질 음성 규격' || el.textContent.trim() === 'High-quality Voice Spec')`, 'quality spec box title');
  log(`quality guide box present: ${qgTitle}`);
  const qgRows = await evalValue(cdp, `(() => {
    const box = [...document.querySelectorAll('div')].find(d => d.textContent.includes('고품질 음성 규격') || d.textContent.includes('High-quality Voice Spec'));
    if (!box) return null;
    return box.textContent.replace(/\\s+/g, ' ').trim();
  })()`);
  log(`quality guide content: ${qgRows}`);
  if (!qgRows || !qgRows.includes('10~30초') || !qgRows.includes('한 사람의 목소리')) {
    throw new Error(`quality guide rows incomplete: ${qgRows}`);
  }
  // Close dialog
  await evalValue(cdp, `(() => { const d = document.querySelector('[role="dialog"]'); if (d) { const ev = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }); document.dispatchEvent(ev); } return true; })()`);
  await sleep(300);

  // 13. Long-text hint on the generate box: type >800 chars -> hint with count + link
  await evalValue(cdp, `location.href = '/'; true`);
  await waitFor(cdp, `location.pathname === '/'`, 'back to /');
  await waitFor(cdp, `[...document.querySelectorAll('textarea')].length > 0`, 'generate textarea');
  const longText = '안녕하세요. 이것은 장문 생성을 확인하기 위한 테스트 문장입니다. '.repeat(80);
  await evalValue(cdp, `(() => {
    const tas = [...document.querySelectorAll('textarea')];
    const ta = tas.find(t => t.placeholder && !t.placeholder.includes('참조') && !t.placeholder.includes('지시'));
    if (!ta) throw new Error('no generate textarea');
    ta.click();
    const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
    setter.call(ta, ${JSON.stringify(longText)});
    ta.dispatchEvent(new Event('input', { bubbles: true }));
    return ta.value.length;
  })()`);
  const hint = await waitFor(cdp, `(() => {
    const el = [...document.querySelectorAll('div')].find(d => d.textContent.includes('장문') && d.textContent.includes('순차 생성'));
    return el ? el.textContent.replace(/\\s+/g, ' ').trim() : null;
  })()`, 'long-text hint');
  log(`long-text hint: ${hint}`);
  if (!hint.includes(String(longText.length))) throw new Error(`hint count wrong: ${hint}`);
  if (!hint.includes('분할 한도')) throw new Error(`hint limit info missing: ${hint}`);
  const helpLink = await evalValue(cdp, `(() => { const a = [...document.querySelectorAll('a')].find(a => a.textContent.includes('도움말')); return a ? a.getAttribute('href') : null; })()`);
  log(`hint help link: ${helpLink}`);
  if (helpLink !== '/help') throw new Error(`hint help link wrong: ${helpLink}`);

  log(`console errors: ${consoleErrors.length === 0 ? 'none' : consoleErrors.join(' | ')}`);
  if (consoleErrors.length > 0) throw new Error('console errors present');
  cdp.close();
  log('DONE');
}

main().catch((err) => {
  console.error('FAILED:', err.message);
  process.exit(1);
});
