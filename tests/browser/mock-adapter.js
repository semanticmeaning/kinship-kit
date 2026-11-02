// @kin-adapter mock-archive
// @title Тестовый архив (имитация для проверки ядра)
// @site http://127.0.0.1
// @version 1
// @start Откройте тестовую страницу.
kinDownloader({
  id: 'mock-archive', version: 1, title: 'Тестовый архив',
  check() { return document.getElementById('scans') ? '' : 'Нет списка сканов'; },
  allow(u) { return u.origin === location.origin; },
  async *items() {
    for (const li of document.querySelectorAll('#scans li')) yield { key: 'scan-' + li.dataset.n, n: li.dataset.n, title: li.textContent };
  },
  async fetch(item, ctx) {
    const blob = await ctx.request('/img/' + item.n + '.png');
    return { blob, source: location.origin + '/img/' + item.n + '.png', expect: { width: 3, height: 2 },
      text: item.n === '2' ? 'Расшифровка: Иван, сын Кузьмы (вымышл.)' : undefined,
      meta: { title: 'Тестовое дело 1 — ' + item.title, archive: 'Тестовый архив (вымышл.)',
              reference: 'ф. 1, оп. 1, д. 1, скан ' + item.n, sheet: 'л. ' + item.n, page: location.href } };
  },
  fileName(item) { return 'scan_' + item.n; },
  delay: 50,
});
