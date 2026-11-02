// Прогон ядра скачивателя в настоящем Chrome (headless, протокол DevTools). Папка — в памяти страницы.
// node run_downloader.mjs <chrome> <url> <snippet.js> <out-dir> <cdp-port>
import { spawn } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const [chrome, url, snippetPath, outDir, port] = process.argv.slice(2);
const profile = mkdtempSync(join(tmpdir(), 'kin-chrome-'));
const proc = spawn(chrome, ['--headless=new', '--no-sandbox', '--disable-gpu', `--remote-debugging-port=${port}`,
  `--user-data-dir=${profile}`, 'about:blank'], { stdio: 'ignore' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let targets;
for (let i = 0; i < 50; i++) { try { targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); if (targets.length) break; } catch {} await sleep(200); }
const page = targets.find(t => t.type === 'page');
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise(r => ws.addEventListener('open', r));
let id = 0; const pending = new Map();
ws.addEventListener('message', ev => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const evaluate = async expr => { const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) throw Error(JSON.stringify(r.result.exceptionDetails).slice(0, 400)); return r.result?.result?.value; };
const FAKE_FS = `window.__fs = window.__fs || {};
window.showDirectoryPicker = async () => ({ async getFileHandle(name, o) {
  if (!(name in __fs) && !(o && o.create)) { const e = new Error('nf'); e.name = 'NotFoundError'; throw e; }
  return { async getFile() { return new File([__fs[name] || new Blob([])], name); },
           async createWritable() { const parts = []; return { async write(d) { parts.push(d); }, async close() { __fs[name] = new Blob(parts); }, async abort() {} }; } };
} });`;
const snippet = readFileSync(snippetPath, 'utf8');
await send('Page.enable'); await send('Runtime.enable');
await send('Page.navigate', { url }); await sleep(1500);
const results = [];
for (let run = 1; run <= 2; run++) {
  await evaluate(FAKE_FS); await evaluate(snippet);
  await evaluate(`document.querySelector('#kinship-download-panel [data-a="start"]').click(); true`);
  let status = '';
  for (let i = 0; i < 150; i++) {
    await sleep(200);
    status = await evaluate(`(() => { const p = document.getElementById('kinship-download-panel'); return p.dataset.running === 'false' ? p.querySelector('[data-s]').textContent : ''; })()`);
    if (status) break;
  }
  results.push(status);
}
const files = await evaluate(`(async () => { const out = {}; for (const [k, b] of Object.entries(__fs)) {
  const u = new Uint8Array(await b.arrayBuffer()); let s = ''; for (const x of u) s += String.fromCharCode(x); out[k] = btoa(s); } return out; })()`);
mkdirSync(outDir, { recursive: true });
for (const [k, v] of Object.entries(files)) writeFileSync(join(outDir, k), Buffer.from(v, 'base64'));
console.log(JSON.stringify({ runs: results, files: Object.keys(files).sort() }));
ws.close(); proc.kill();
