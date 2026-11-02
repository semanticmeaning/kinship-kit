// @kin-adapter yandex-archive-favorites
// @title Яндекс Архивы — избранное (yandex.ru/archive)
// @site https://yandex.ru/archive/favorites
// @version 3
// @start Шаг 0: в Яндекс Архивах найдите по фамилии похожие записи и добавьте нужные листы в «Избранное» (сердечко). Затем войдите в Яндекс и откройте https://yandex.ru/archive/favorites
// @based-on export-favorites.js v2 (автор набора)
kinDownloader({
  id: 'yandex-archive-favorites', version: 3, title: 'Яндекс Архивы — избранное',
  note: 'Скачает оригиналы листов из вашего «Избранного» и сохранит расшифровки и полные реквизиты в итоговый TXT.',
  delay: 900,
  check() { return location.origin !== 'https://yandex.ru' || !location.pathname.startsWith('/archive/') ? 'Запустите на https://yandex.ru/archive/favorites (войдите в Яндекс).' : ''; },
  allow(u) { return u.origin === 'https://yandex.ru' && u.pathname.startsWith('/archive/'); },
  props(html, ctx) {
    const raw = new DOMParser().parseFromString(html, 'text/html').getElementById('__NEXT_DATA__')?.textContent;
    if (!raw) throw ctx.fatal('Страница без данных карточки: проверьте вход в Яндекс и отсутствие проверки браузера.');
    const p = JSON.parse(raw).props?.pageProps;
    if (!p) throw ctx.fatal('Неизвестный формат страницы Яндекс Архивов — пришлите страницу агенту для обновления адаптера.');
    return p;
  },
  async *items(ctx) {
    const queue = [], seen = new Set(); let total = 1;
    for (let page = 1; page <= total; page++) {
      ctx.status(`Собираю избранное: страница ${page}${page > 1 ? ' из ' + total : ''}`);
      const p = this.props(await ctx.request('/archive/favorites' + (page === 1 ? '' : '?pageNum=' + page), {}, 'text'), ctx);
      if (!Array.isArray(p.catalogItems) || !Number.isInteger(p.totalPages)) throw ctx.fatal('Неизвестный формат избранного.');
      if (page === 1) total = Math.min(p.totalPages, 1000);
      for (const it of p.catalogItems) {
        if (it.type !== 'Sheet' || !it.parentId || !Number.isInteger(it.sheetPageNumber)) continue;  // карточки без листа — пропуск
        if (!seen.has(it.id)) { seen.add(it.id); queue.push({ key: it.id, id: it.id, parentId: it.parentId, scan: it.sheetPageNumber, title: it.name || it.id }); }
      }
    }
    for (const item of queue) yield item;
  },
  async fetch(item, ctx) {
    const url = '/archive/catalog/' + item.parentId + '/' + item.scan;
    const p = this.props(await ctx.request(url, {}, 'text'), ctx), n = p.currentNode;
    if (n?.id !== item.id || Number(p.docNumber) !== item.scan) throw Error('Номер/идентификатор скана не совпал — фото и текст не сохранены вместе.');
    const crumbs = (p.breadcrumbs || []).map(b => ({ type: b.type, name: b.name || '', code: b.code ?? '', dateFrom: b.dateFrom || '', dateTo: b.dateTo || '' }));
    const get = t => crumbs.find(b => b.type === t);
    if (!Array.isArray(n.textBlocks)) throw Error('Неизвестный формат расшифровки.');
    const w = Number(n.originalImageSize?.width), h = Number(n.originalImageSize?.height);
    if (!w || !h) throw Error('Не указан размер оригинала.');
    const grant = await ctx.request('/archive/api/image-grant', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nodeId: n.id, type: 'original' }) }, 'json');
    if (!grant.url || !grant.token) throw Error('Сайт не выдал разрешение на оригинал.');
    const blob = await ctx.request(grant.url, { headers: { 'X-Archive-Image-Token': grant.token } });
    const file = get('File'), dates = [file?.dateFrom, file?.dateTo].filter(Boolean).join(' — ');
    this.crumbs = crumbs;
    return { blob, source: location.origin + url, expect: { width: w, height: h },
      text: n.textBlocks.map(b => String(b.text ?? '')).join('\n'),
      meta: { title: file?.name || n.name || item.title, archive: get('Archive')?.name || '',
        reference: [get('Archive')?.name, 'ф. ' + (get('Fund')?.code || '?'), 'оп. ' + (get('Inventory')?.code || '?'),
                    'д. ' + (file?.code || '?'), 'скан ' + item.scan].join(', '),
        fund: get('Fund')?.code || '', inventory: get('Inventory')?.code || '', file: file?.code || '', sheet: String(item.scan),
        date: dates, page: location.origin + url } };
  },
  fileName(item) {
    const g = t => (this.crumbs || []).find(b => b.type === t);
    return [g('Archive')?.name, 'ф' + (g('Fund')?.code || ''), 'оп' + (g('Inventory')?.code || ''), 'д' + (g('File')?.code || ''),
            'скан' + String(item.scan).padStart(4, '0')].filter(Boolean).join('_').slice(0, 140) + '_' + item.id.slice(0, 8);
  },
});
