/* kinship-kit — общее ядро скачивателя сканов из онлайн-архивов (вставка в консоль браузера).
 *
 * Собирается вместе с адаптером сайта командой: kin downloader build <адаптер>.
 * Адаптер описывает только особенности сайта; всё остальное здесь:
 *   панель «Выбрать папку и начать / Остановить», журнал _kinship-download.json с sha256 (повторный запуск в ту же папку
 *   пропускает проверенные файлы и докачивает остальное), повторы с паузами и Retry-After, остановка, распознавание
 *   входа/проверки «я не робот» (остановка — проходит человек), проверка формата и размера изображения,
 *   реквизиты каждого файла и понятный итог _kinship-download.txt.
 * Скрипт работает только в браузере пользователя, с его входом на сайт; никуда, кроме этого сайта и выбранной папки,
 * данные не отправляет.
 */
function kinDownloader(adapter) {
  'use strict';
  const CORE_VERSION = 1;
  const JOURNAL = '_kinship-download.json', SUMMARY = '_kinship-download.txt';
  const PANEL_ID = 'kinship-download-panel';
  const err = adapter.check && adapter.check();
  if (err) throw Error(err);
  const old = document.getElementById(PANEL_ID);
  if (old?.dataset.running === 'true') throw Error('Сначала остановите предыдущий запуск (кнопка «Остановить»).');
  old?.remove();

  /* ---------- панель ---------- */
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const panel = document.createElement('div');
  panel.id = PANEL_ID;
  panel.style.cssText = 'position:fixed;top:12px;left:12px;z-index:2147483647;background:#fff;color:#111;padding:16px 18px;' +
    'border:2px solid #7a4b1d;border-radius:10px;font:15px/1.5 system-ui,sans-serif;max-width:460px;box-shadow:0 4px 25px rgba(0,0,0,.35)';
  const fields = (adapter.fields ? adapter.fields() : []).map(f =>
    `<label style="margin-right:10px">${esc(f.label)} <input data-f="${esc(f.id)}" type="${f.type || 'text'}" value="${esc(f.value)}"` +
    `${f.min != null ? ` min="${f.min}"` : ''}${f.max != null ? ` max="${f.max}"` : ''} style="width:${f.width || 80}px"></label>`).join('');
  panel.innerHTML = `<b>${esc(adapter.title)}</b> <small style="color:#666">· адаптер ${esc(adapter.id)} v${esc(adapter.version)} · ядро v${CORE_VERSION}</small>
    <p style="margin:6px 0">${esc(adapter.note || 'Скачает файлы в выбранную папку без изменения. Уже проверенные пропустит — продолжать можно в той же папке.')}</p>
    ${fields ? `<p style="margin:6px 0">${fields}</p>` : ''}
    <p style="margin:6px 0"><button data-a="start">Выбрать папку и начать</button> <button data-a="stop">Остановить</button></p>
    <p data-s style="margin:6px 0">${esc(adapter.ready || 'Готов к запуску.')}</p>`;
  document.body.append(panel);
  const statusEl = panel.querySelector('[data-s]');
  const status = t => { statusEl.textContent = t; };
  const value = id => panel.querySelector(`[data-f="${id}"]`)?.value;

  /* ---------- помощники ---------- */
  let stopped = false, controller = null;
  panel.querySelector('[data-a="stop"]').onclick = () => { stopped = true; controller?.abort(); status('Остановка, сохраняю журнал…'); };
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const fatal = m => Object.assign(new Error(m), { fatal: true });
  const checkStop = () => { if (stopped) throw new DOMException('Остановлено', 'AbortError'); };
  const clean = v => String(v ?? '').replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').replace(/\s+/g, ' ').replace(/[. ]+$/g, '').trim();
  const sha256 = async blob => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', await blob.arrayBuffer())),
    b => b.toString(16).padStart(2, '0')).join('');
  const CAPTCHA = /showcaptcha|smartcaptcha|recaptcha|hcaptcha|подтвердите,? что вы не робот|я не робот|are you a robot/i;
  const LOGIN = /login|signin|logon|auth/i;

  async function sleepStoppable(ms) { const until = Date.now() + ms; while (!stopped && Date.now() < until) await wait(Math.min(300, until - Date.now())); }

  // запрос с повторами: 429/5xx/сеть — до 4 попыток с паузами; вход, капча, чужой адрес — остановка
  async function request(url, options = {}, kind = 'blob', allow = adapter.allow) {
    const u = new URL(url, location.href);
    if (allow && !allow(u)) throw fatal('Неожиданный адрес запроса: ' + u.origin + u.pathname + '. Остановлено.');
    for (let attempt = 0; attempt < 4; attempt++) {
      checkStop(); let timer;
      try {
        controller = new AbortController(); timer = setTimeout(() => controller?.abort(), 180000);
        const ref = new URL(location.href); ref.hash = '';
        const r = await fetch(u.href, { credentials: 'same-origin', referrer: ref.href, referrerPolicy: 'same-origin',
          cache: 'no-store', ...options, signal: controller.signal });
        if ([401, 403].includes(r.status)) throw fatal(`Нет доступа (HTTP ${r.status}). Войдите на сайт и запустите снова в ту же папку.`);
        if (!r.ok) throw Object.assign(new Error('HTTP ' + r.status), { retryable: r.status === 429 || r.status >= 500,
          retryAfter: Number(r.headers.get('Retry-After')) || 0 });
        const dest = new URL(r.url);
        if (dest.href !== u.href && (LOGIN.test(dest.pathname) || (allow && !allow(dest))))
          throw fatal('Сайт перенаправил запрос (' + dest.origin + dest.pathname + '): проверьте вход на сайт.');
        if (kind === 'blob') {
          const blob = await r.blob();
          if (/text\/html/i.test(blob.type)) {
            const text = await blob.slice(0, 3000).text();
            if (CAPTCHA.test(text)) throw fatal('Сайт попросил подтвердить, что вы не робот. Пройдите проверку вручную и запустите снова в ту же папку.');
          }
          return blob;
        }
        const text = await r.text();
        if (CAPTCHA.test(text)) throw fatal('Сайт попросил подтвердить, что вы не робот. Пройдите проверку вручную и запустите снова в ту же папку.');
        return kind === 'json' ? JSON.parse(text) : text;
      } catch (e) {
        if (stopped || e.fatal) throw e;
        const retry = e.retryable || ['TypeError', 'AbortError', 'TimeoutError'].includes(e.name);
        if (!retry || attempt === 3) throw e;
        clearTimeout(timer); timer = null;
        const delay = Math.max([2000, 6000, 15000][attempt], (e.retryAfter || 0) * 1000);
        status(`Сбой запроса (${e.message}). Повтор ${attempt + 2}/4 через ${Math.ceil(delay / 1000)} сек.`);
        await sleepStoppable(delay);
      } finally { clearTimeout(timer); controller = null; }
    }
  }

  // размер и формат изображения по байтам (без перекодирования файла)
  async function imageInfo(blob) {
    const b = new Uint8Array(await blob.slice(0, 1024 * 1024).arrayBuffer());
    if (b.length >= 24 && b[0] === 137 && b[1] === 80 && b[2] === 78 && b[3] === 71) {
      const v = new DataView(b.buffer); return { width: v.getUint32(16), height: v.getUint32(20), ext: 'png' };
    }
    if (b[0] === 255 && b[1] === 216) {
      let i = 2;
      while (i + 8 < b.length) {
        if (b[i++] !== 255) continue;
        while (b[i] === 255) i++;
        const m = b[i++]; if (m === 217 || m === 218) break;
        if (m === 1 || (m >= 208 && m <= 215)) continue;
        const len = (b[i] << 8) | b[i + 1]; if (len < 2) break;
        if ([192, 193, 194, 195, 197, 198, 199, 201, 202, 203, 205, 206, 207].includes(m))
          return { width: (b[i + 5] << 8) | b[i + 6], height: (b[i + 3] << 8) | b[i + 4], ext: 'jpg' };
        i += len;
      }
    }
    if (b[0] === 0x25 && b[1] === 0x50 && b[2] === 0x44 && b[3] === 0x46) return { width: 0, height: 0, ext: 'pdf' };
    if (/^image\//i.test(blob.type)) {
      const bmp = await createImageBitmap(blob);
      const ext = /webp/i.test(blob.type) ? 'webp' : /tiff/i.test(blob.type) ? 'tif' : /gif/i.test(blob.type) ? 'gif' : null;
      const out = { width: bmp.width, height: bmp.height, ext }; bmp.close();
      if (ext) return out;
    }
    const text = (await blob.slice(0, 1500).text()).replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').slice(0, 200);
    throw Error(`Сервер вернул не изображение (${blob.type || 'формат не указан'}): ${text}`);
  }

  /* ---------- хранилище: папка (Chrome, Edge) или загрузки браузера ---------- */
  async function folderStore() {
    const dir = await window.showDirectoryPicker({ mode: 'readwrite' });
    const write = async (name, data) => {
      const h = await dir.getFileHandle(name, { create: true }), w = await h.createWritable();
      try { await w.write(data); await w.close(); } catch (e) { await w.abort().catch(() => {}); throw fatal('Не удалось сохранить ' + name + ': ' + e.message); }
    };
    const read = async name => { try { return await (await dir.getFileHandle(name)).getFile(); } catch (e) { if (e.name === 'NotFoundError') return null; throw e; } };
    return { kind: 'folder', write, read };
  }
  function downloadStore() {  // Firefox/Safari: файлы уходят в «Загрузки»; продолжение — по журналу в памяти браузера
    const key = 'kinship-download:' + adapter.id + ':' + location.host;
    const write = async (name, data) => {
      const a = document.createElement('a'); a.href = URL.createObjectURL(data instanceof Blob ? data : new Blob([data]));
      a.download = name; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 60000);
      await wait(400);
    };
    const read = async name => { if (name !== JOURNAL) return null; try { const t = localStorage.getItem(key); return t ? new Blob([t]) : null; } catch (e) { return null; } };
    const remember = j => { try { localStorage.setItem(key, j); } catch (e) {} };
    return { kind: 'downloads', write, read, remember };
  }

  /* ---------- журнал и итог ---------- */
  function summaryText(j) {
    const out = [`${adapter.title} — выгрузка kinship-kit`, `Сайт: ${j.site}`, `Адаптер: ${adapter.id} v${adapter.version}, ядро v${CORE_VERSION}`,
      `Обновлено: ${j.updated}`, 'Тексты расшифровок сохранены с сайта без исправлений.', ''];
    j.order.forEach((key, i) => {
      const r = j.records[key] || {};
      out.push('='.repeat(72), `${i + 1}. ${r.title || key}`);
      for (const [k, label] of [['reference', 'Шифр'], ['archive', 'Архив'], ['page', 'Страница на сайте'], ['date', 'Даты']]) if (r[k]) out.push(`${label}: ${r[k]}`);
      if (r.status === 'saved') out.push(`Файл: ${r.fileName}`, `Размер: ${r.width} × ${r.height}, ${r.bytes} байт` + (r.quality === 'preview' ? ' — УМЕНЬШЕННАЯ КОПИЯ: ' + (r.reason || '') : ''));
      else out.push('Файл: НЕ ВЫГРУЖЕН', `Причина: ${r.error || 'ожидает выгрузки'}`);
      if (r.text) out.push('Расшифровка:', r.text);
      out.push('');
    });
    return '﻿' + out.join('\n').replace(/\r?\n/g, '\r\n');
  }

  panel.querySelector('[data-a="start"]').onclick = async () => {
    if (panel.dataset.running === 'true') return;
    const opts = {}; for (const f of (adapter.fields ? adapter.fields() : [])) opts[f.id] = value(f.id);
    if (adapter.validate) { const m = adapter.validate(opts); if (m) { status(m); return; } }
    let store;
    try { store = window.showDirectoryPicker ? await folderStore() : downloadStore(); }
    catch { status('Выбор папки отменён.'); return; }
    stopped = false; panel.dataset.running = 'true';
    let saved = 0, skipped = 0, errors = 0, summary = '';
    let journal = { format: 'kinship-kit-download', version: 1, adapter: { id: adapter.id, version: adapter.version, title: adapter.title },
      core: CORE_VERSION, site: location.origin, started: new Date().toISOString(), updated: '', order: [], records: {} };
    const checkpoint = async () => {
      journal.updated = new Date().toISOString();
      const text = JSON.stringify(journal, null, 2);
      if (store.kind === 'folder') { await store.write(JOURNAL, text); await store.write(SUMMARY, summaryText(journal)); }
      else store.remember(text);
    };
    const ctx = { request, imageInfo, status, wait, fatal, clean, checkStop, options: opts, sleep: sleepStoppable,
      get stopped() { return stopped; } };
    try {
      const prev = await store.read(JOURNAL);
      if (prev) {
        const data = JSON.parse(await prev.text());
        if (data.format !== 'kinship-kit-download' || data.version !== 1 || typeof data.records !== 'object')
          throw fatal('В папке журнал другого формата. Выберите пустую папку или папку этой выгрузки.');
        if (data.adapter?.id !== adapter.id) throw fatal(`Эта папка — выгрузка «${data.adapter?.title}». Для другого сайта выберите другую папку.`);
        journal = { ...journal, started: data.started, order: data.order || [], records: data.records };
      }
      for await (const item of adapter.items(ctx)) {
        checkStop();
        if (!journal.order.includes(item.key)) journal.order.push(item.key);
        const rec = journal.records[item.key];
        if (rec?.status === 'saved' && store.kind === 'folder') {
          const f = await store.read(rec.fileName);
          if (f && f.size === rec.bytes && await sha256(f) === rec.sha256) { skipped++; status(`Проверен ранее сохранённый: ${rec.fileName}`); continue; }
        } else if (rec?.status === 'saved' && store.kind === 'downloads') { skipped++; continue; }
        status(`${journal.order.length}: ${item.title || item.key} — загрузка… Сохранено: ${saved}, пропущено: ${skipped}, ошибок: ${errors}`);
        try {
          const got = await adapter.fetch(item, ctx);
          checkStop();
          const info = await imageInfo(got.blob);
          if (got.expect && (got.expect.width !== info.width || got.expect.height !== info.height) && got.quality !== 'preview')
            throw Error(`Ожидался размер ${got.expect.width} × ${got.expect.height}, получено ${info.width} × ${info.height}. Файл не сохранён.`);
          const base = clean(adapter.fileName ? adapter.fileName(item, got) : item.key).slice(0, 150) + (got.quality === 'preview' ? '-preview' : '');
          const fileName = base + '.' + info.ext, digest = await sha256(got.blob);
          if (store.kind === 'folder') {
            const existing = await store.read(fileName);
            if (existing && await sha256(existing) !== digest && rec?.fileName !== fileName)
              throw fatal(`В папке уже есть другой файл ${fileName}. Выберите пустую папку или папку этой выгрузки.`);
          }
          await store.write(fileName, got.blob);
          journal.records[item.key] = { status: 'saved', fileName, bytes: got.blob.size, sha256: digest, width: info.width, height: info.height,
            quality: got.quality || 'original', reason: got.reason || '', source: got.source || '', saved: new Date().toISOString(), ...(got.meta || {}),
            ...(got.text != null ? { text: got.text } : {}) };
          saved++;
        } catch (e) {
          if (stopped) throw e;
          journal.records[item.key] = { ...(rec || {}), status: 'error', error: e.message, ...(item.meta || {}) };
          errors++;
          if (e.fatal) { await checkpoint(); throw e; }
        }
        await checkpoint();
        await sleepStoppable(adapter.delay ?? 700);  // вежливая пауза между запросами к архиву
      }
      summary = `Готово. Сохранено: ${saved}, проверено ранее: ${skipped}, ошибок: ${errors}.` +
        (store.kind === 'folder' ? ` Итог: ${SUMMARY}, журнал: ${JOURNAL}.` : ' Файлы — в «Загрузках».');
    } catch (e) {
      summary = (stopped ? 'Остановлено пользователем.' : 'Остановлено: ' + e.message) + ` Сохранено за запуск: ${saved}. Продолжить можно в той же папке.`;
      if (!stopped && !e.fatal) console.error(e);
    } finally {
      try { await checkpoint(); } catch (e) { /* итог в строке состояния */ }
      if (store.kind === 'downloads') { try { await store.write(JOURNAL, JSON.stringify(journal, null, 2)); await store.write(SUMMARY, summaryText(journal)); } catch (e) {} }
      panel.dataset.running = 'false'; status(summary);
    }
  };
}
