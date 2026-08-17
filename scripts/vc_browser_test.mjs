// VC tab browser live test via Chrome DevTools Protocol (headless Chrome, CDP port 9222).
// Run with Windows node:  node D:\TTS\scripts\vc_browser_test.mjs
import { setTimeout as sleep } from 'node:timers/promises';

const CDP_HTTP = 'http://127.0.0.1:9222';
const APP_URL = 'http://127.0.0.1:5173/vc';
const SOURCE_FILE = 'D:\\TTS\\data\\vc\\test_uploads\\test_voice1.wav';
const POLL_MS = 2000;
const MAX_WAIT_MS = 120000;

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
  if (res.exceptionDetails) {
    throw new Error(`eval failed: ${JSON.stringify(res.exceptionDetails)}`);
  }
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
  // 1. Create a fresh page target
  let target;
  let created = false;
  try {
    const resp = await fetch(`${CDP_HTTP}/json/new?about:blank`, { method: 'PUT' });
    target = await resp.json();
    created = true;
  } catch {
    const resp = await fetch(`${CDP_HTTP}/json/new?about:blank`);
    target = await resp.json();
    created = true;
  }
  if (!created) throw new Error('could not create page target');
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
  await cdp.send('DOM.enable');

  // 2. Navigate
  log(`navigating to ${APP_URL}`);
  await cdp.send('Page.navigate', { url: APP_URL });

  // 3. Wait for the app shell + VC model table to render with our model
  await waitFor(
    cdp,
    `(function(){
      const rows = [...document.querySelectorAll('table tr')];
      return rows.some(r => r.textContent.includes('e2e_test_model'));
    })()`,
    'e2e_test_model row in models table',
  );
  log('models table shows e2e_test_model');

  // 4. Confirm engine-ready badge text and model select auto-selected
  const snapshot = await evalValue(cdp, `({
    h1: document.querySelector('h1')?.textContent ?? null,
    badges: [...document.querySelectorAll('span,div')].map(e => e.textContent ?? '').filter(t => /RTX|GPU|Engine|엔진/.test(t)).slice(0, 5),
    fileInputs: document.querySelectorAll('input[type=file]').length,
    convertSelectText: (() => {
      const inputs = [...document.querySelectorAll('input[type=file]')];
      if (inputs.length < 2) return null;
      const card = inputs[1].closest('.rounded-lg.border');
      return card ? card.textContent.slice(0, 300) : null;
    })(),
  })`);
  log(`page snapshot: ${JSON.stringify(snapshot, null, 2)}`);

  // 5. Set the source audio file on the convert panel's file input (2nd one)
  const doc = await cdp.send('DOM.getDocument', { depth: -1 });
  const qsa = await cdp.send('DOM.querySelectorAll', {
    nodeId: doc.root.nodeId,
    selector: 'input[type=file]',
  });
  log(`found ${qsa.nodeIds.length} file inputs`);
  if (qsa.nodeIds.length < 2) throw new Error('convert source file input not found');
  await cdp.send('DOM.setFileInputFiles', {
    nodeId: qsa.nodeIds[1],
    files: [SOURCE_FILE],
  });
  await sleep(500);
  const fileLabel = await evalValue(cdp, `(() => {
    const inputs = [...document.querySelectorAll('input[type=file]')];
    const card = inputs[1].closest('.rounded-lg.border');
    return card.textContent.slice(0, 300);
  })()`);
  log(`after set files, convert card text: ${JSON.stringify(fileLabel)}`);

  // 6. Click the convert start button (last button inside the convert card)
  const clicked = await evalValue(cdp, `(() => {
    const inputs = [...document.querySelectorAll('input[type=file]')];
    const card = inputs[1].closest('.rounded-lg.border');
    if (!card) return 'no card';
    const buttons = [...card.querySelectorAll('button')];
    const btn = buttons[buttons.length - 1];
    if (!btn) return 'no button';
    if (btn.disabled) return 'button disabled';
    btn.click();
    return 'clicked: ' + btn.textContent.trim();
  })()`);
  log(`convert click: ${clicked}`);

  // 7. Wait for job to reach done and result link to appear
  log('waiting for conversion job to complete...');
  const resultHref = await waitFor(
    cdp,
    `(() => {
      const a = document.querySelector('a[href*="/vc/results/"]');
      return a ? a.href : null;
    })()`,
    'result link (conversion done)',
  );
  log(`RESULT LINK: ${resultHref}`);

  // 8. Fetch the result file over HTTP and verify it is a valid wav
  const res = await fetch(resultHref);
  const buf = Buffer.from(await res.arrayBuffer());
  const isWav = buf.length > 44 && buf.toString('ascii', 0, 4) === 'RIFF' && buf.toString('ascii', 8, 12) === 'WAVE';
  log(`result fetch status=${res.status} size=${buf.length} wav=${isWav}`);

  // 9. Report jobs table + console errors
  const jobsText = await evalValue(cdp, `(() => {
    const tables = [...document.querySelectorAll('table')];
    const last = tables[tables.length - 1];
    return last ? last.textContent : null;
  })()`);
  log(`jobs table: ${JSON.stringify(jobsText)}`);
  log(`console errors: ${consoleErrors.length === 0 ? 'none' : consoleErrors.join(' | ')}`);

  cdp.close();
  log('DONE');
}

main().catch((err) => {
  console.error('FAILED:', err.message);
  process.exit(1);
});