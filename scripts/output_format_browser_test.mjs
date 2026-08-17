// Output-format menu + help dialog browser live test via CDP.
// Run with Windows node:  node D:\TTS\scripts\output_format_browser_test.mjs
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

  // 1. Wait for the floating generate box (textarea placeholder + format select)
  await waitFor(
    cdp,
    `!!document.querySelector('textarea')`,
    'generate textarea',
  );
  log('generate box rendered');

  // 2. Verify the output-format select + options
  const format = await evalValue(cdp, `(() => {
    const spans = [...document.querySelectorAll('span')];
    const labelEl = spans.find(s => s.textContent === '출력 형식' || s.textContent === 'Output format');
    if (!labelEl) return { label: null };
    const row = labelEl.closest('.flex');
    if (!row) return { label: labelEl.textContent, select: null };
    // Radix SelectTrigger renders a <button> holding the current value text
    const trigger = row.querySelector('button[role=combobox]');
    return {
      label: labelEl.textContent,
      triggerValue: trigger ? trigger.textContent : null,
      hasHelpIcon: !!row.querySelector('button[aria-label]'),
      helpLabel: row.querySelector('button[aria-label]')?.getAttribute('aria-label') ?? null,
      fileInputs: document.querySelectorAll('input[type=file]').length,
    };
  })()`);
  log(`format select snapshot: ${JSON.stringify(format)}`);
  if (!format.label) throw new Error('output format label not found');
  if (!format.triggerValue) throw new Error('format select trigger not found');
  if (!format.hasHelpIcon) throw new Error('help icon missing');

  // 3. Open the select and list options
  await evalValue(cdp, `document.querySelector('button[role=combobox]').click()`);
  await sleep(600);
  const options = await evalValue(cdp, `[...document.querySelectorAll('[role=option]')].map(o => o.textContent)`);
  log(`format options: ${JSON.stringify(options)}`);
  const want = ['원본 (기본)', '방송용', 'CD용', 'MP3'];
  if (options.length !== 4) throw new Error(`expected 4 options, got: ${JSON.stringify(options)}`);
  for (const w of want) if (!options.includes(w)) throw new Error(`option missing: ${w}`);
  log('all 4 format options present');
  // close the listbox by pressing Escape
  await cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await sleep(300);

  // 4. Pick MP3 and confirm the trigger updates
  await evalValue(cdp, `document.querySelector('button[role=combobox]').click()`);
  await sleep(500);
  await evalValue(cdp, `(() => {
    const o = [...document.querySelectorAll('[role=option]')].find(x => x.textContent === 'MP3');
    o.click();
  })()`);
  await sleep(500);
  const afterPick = await evalValue(cdp, `document.querySelector('button[role=combobox]')?.textContent`);
  log(`after picking MP3, trigger shows: ${afterPick}`);
  if (afterPick !== 'MP3') throw new Error(`trigger did not update to MP3: ${afterPick}`);

  // 5. Open help dialog via the info icon
  await evalValue(cdp, `document.querySelector('button[aria-label="오디오 규격 도움말"]')?.click()`);
  await sleep(600);
  const dialog = await evalValue(cdp, `(() => {
    const dlg = [...document.querySelectorAll('[role=dialog]')][0];
    if (!dlg) return null;
    return {
      title: dlg.querySelector('h2')?.textContent ?? null,
      text: dlg.textContent.slice(0, 900),
      hasTable: !!dlg.querySelector('table'),
    };
  })()`);
  log(`help dialog snapshot: ${JSON.stringify(dialog)}`);
  if (!dialog) throw new Error('help dialog did not open');
  if (!dialog.hasTable) throw new Error('dialog missing spec table');
  for (const k of ['48 kHz', '44.1 kHz', '192 kbps', '-24 LUFS', '-14 LUFS', '24-bit', '16-bit', '듀얼 모노']) {
    if (!dialog.text.includes(k)) throw new Error(`dialog missing content: ${k}`);
  }
  log('help dialog shows full spec table + input source note');
  await cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await sleep(300);

  log(`console errors: ${consoleErrors.length === 0 ? 'none' : consoleErrors.join(' | ')}`);
  if (consoleErrors.length > 0) throw new Error('console errors present');
  cdp.close();
  log('DONE');
}

main().catch((err) => {
  console.error('FAILED:', err.message);
  process.exit(1);
});