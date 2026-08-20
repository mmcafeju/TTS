// ChunkEditor (Repaint) browser live test via CDP.
// Run with Windows node:  node D:\TTS\scripts\chunk_editor_browser_test.mjs
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

  // 1. Wait for the history table with the seeded generation row.
  await waitFor(
    cdp,
    `[...document.querySelectorAll('[role=button]')].some(el => (el.getAttribute('aria-label')||'').startsWith('Sample from'))`,
    'seeded generation row',
  );
  log('history row rendered');

  // 2. Click the row to start playback -> AudioPlayer + ChunkEditor mount.
  await evalValue(cdp, `(() => {
    const row = [...document.querySelectorAll('[role=button]')].find(el => (el.getAttribute('aria-label')||'').startsWith('Sample from'));
    const evt = new MouseEvent('mousedown', { bubbles: true, cancelable: true, button: 0 });
    row.dispatchEvent(evt);
  })()`);
  await sleep(500);

  // 3. Wait for chunk chips to appear (3 sentences).
  const chips = await waitFor(
    cdp,
    `(() => {
      const btns = [...document.querySelectorAll('button')].filter(b => /^\\d+·/.test(b.textContent.trim()));
      return btns.length >= 3 ? btns.map(b => b.textContent.trim()) : null;
    })()`,
    'chunk chips (3)',
  );
  log(`chunk chips: ${JSON.stringify(chips)}`);
  if (chips.length !== 3) throw new Error(`expected 3 chunk chips, got ${chips.length}`);

  // 4. Verify waveform markers are present.
  const markers = await evalValue(cdp, `(() => {
    const btns = [...document.querySelectorAll('button')].filter(b => b.getAttribute('aria-label') && /문장|Sentence/.test(b.getAttribute('aria-label')));
    return btns.length;
  })()`);
  log(`chunk markers on waveform: ${markers}`);
  if (markers < 3) throw new Error(`expected >=3 waveform markers, got ${markers}`);

  // 5. Select chunk chip #2 and verify the edit panel + prefill.
  await evalValue(cdp, `(() => {
    const btn = [...document.querySelectorAll('button')].find(b => /^2·/.test(b.textContent.trim()));
    btn.click();
  })()`);
  await sleep(500);
  const editPanel = await evalValue(cdp, `(() => {
    const input = [...document.querySelectorAll('input')].find(i => i.placeholder && /수정|Correct/.test(i.placeholder));
    if (!input) return null;
    return {
      textValue: input.value,
      hasSeed: [...document.querySelectorAll('input')].some(i => i.type === 'number' && (i.placeholder || '').includes('시드') || i.type === 'number' && i.placeholder === 'Seed (optional)'),
      hasRegenBtn: [...document.querySelectorAll('button')].some(b => /구간 재생성|Regenerate segment/.test(b.textContent.trim())),
      timeLabel: [...document.querySelectorAll('span')].some(s => /3:00|0:03|3\.0|3,0/.test(s.textContent)),
    };
  })()`);
  log(`edit panel snapshot: ${JSON.stringify(editPanel)}`);
  if (!editPanel) throw new Error('edit panel did not appear after selecting chunk 2');
  if (editPanel.textValue !== '여기 고쳐야 할 두 번째 문장이 있습니다.') {
    throw new Error(`chunk 2 text prefill wrong: "${editPanel.textValue}"`);
  }
  if (!editPanel.hasSeed) throw new Error('seed input missing');
  if (!editPanel.hasRegenBtn) throw new Error('regenerate button missing');

  // 6. Type an override into the text input and confirm state.
  await evalValue(cdp, `(() => {
    const input = [...document.querySelectorAll('input')].find(i => i.placeholder && /수정|Correct/.test(i.placeholder));
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(input, '여기 수정된 두 번째 문장이 있습니다.');
    input.dispatchEvent(new Event('input', { bubbles: true }));
  })()`);
  await sleep(300);
  const updated = await evalValue(cdp, `[...document.querySelectorAll('input')].find(i => i.placeholder && /수정|Correct/.test(i.placeholder))?.value`);
  log(`after typing, text value: ${updated}`);
  if (updated !== '여기 수정된 두 번째 문장이 있습니다.') throw new Error('text input did not update');

  // 7. Select a different chunk (chip 1) and confirm prefill resets.
  await evalValue(cdp, `(() => {
    const btn = [...document.querySelectorAll('button')].find(b => /^1·/.test(b.textContent.trim()));
    btn.click();
  })()`);
  await sleep(500);
  const chip1 = await evalValue(cdp, `[...document.querySelectorAll('input')].find(i => i.placeholder && /수정|Correct/.test(i.placeholder))?.value`);
  log(`chunk 1 prefill: ${chip1}`);
  if (chip1 !== '안녕하세요, 이것은 첫 번째 문장입니다.') throw new Error(`chunk 1 prefill wrong: "${chip1}"`);

  log(`console errors: ${consoleErrors.length === 0 ? 'none' : consoleErrors.join(' | ')}`);
  if (consoleErrors.length > 0) throw new Error('console errors present');
  cdp.close();
  log('DONE');
}

main().catch((err) => {
  console.error('FAILED:', err.message);
  process.exit(1);
});