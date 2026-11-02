// @kin-adapter dvinaland
// @title Архив Архангельской области (archives.dvinaland.ru)
// @site https://archives.dvinaland.ru
// @version 2
// @start Войдите на сайт, откройте дело (адрес вида https://archives.dvinaland.ru/archiveN/unit/NNN) и дождитесь, пока в просмотрщике загрузится скан.
// @based-on download-scans.js v1 (автор набора)
kinDownloader({
  id: 'dvinaland', version: 2, title: 'Архив Архангельской области',
  note: 'Скачает сканы дела без изменения размера в диапазоне номеров. Номер — позиция в списке сканов, не номер листа.',
  check() {
    if (location.origin !== 'https://archives.dvinaland.ru' || !/^\/archive\d+\/unit\/\d+\/?$/.test(location.pathname))
      return 'Запустите на странице дела archives.dvinaland.ru (…/archiveN/unit/NNN).';
    if (!document.getElementById('page-select')?.options?.length || !document.querySelector('#viewer img[src*="/image/"]'))
      return 'Откройте скан и дождитесь загрузки изображения, затем вставьте скрипт снова.';
    return '';
  },
  _state() {
    const casePath = location.pathname.replace(/\/$/, '');
    const img = document.querySelector('#viewer img[src*="/image/"]');
    const template = new URL(img.src, location.href);
    if (template.origin !== location.origin || template.pathname !== casePath.replace('/unit/', '/image/'))
      throw Error('Изображение не соответствует открытому делу. Дождитесь загрузки скана.');
    const names = Array.from(document.getElementById('page-select').options, o => o.textContent.trim());
    const title = (document.querySelector('h1')?.textContent || document.title || '').replace(/\s+/g, ' ').trim();
    return { casePath, template, names, caseId: casePath.split('/').pop(), title };
  },
  fields() {
    const s = this._state(), cur = Number(location.hash.slice(1)) || document.getElementById('page-select').selectedIndex + 1;
    return [{ id: 'from', label: 'С номера', type: 'number', value: cur, min: 1, max: s.names.length },
            { id: 'to', label: 'по', type: 'number', value: s.names.length, min: 1, max: s.names.length }];
  },
  validate(o) {
    const total = this._state().names.length, from = Number(o.from), to = Number(o.to);
    return Number.isInteger(from) && Number.isInteger(to) && from >= 1 && to <= total && from <= to ? '' : `Укажите диапазон от 1 до ${total}.`;
  },
  allow(u) { return u.origin === 'https://archives.dvinaland.ru'; },
  async *items(ctx) {
    const s = this._state();
    this.s = s;
    for (let n = Number(ctx.options.from); n <= Number(ctx.options.to); n++) {
      if (location.pathname.replace(/\/$/, '') !== s.casePath) throw ctx.fatal('Вы перешли в другое дело. Запустите скрипт заново на нужной странице.');
      yield { key: s.casePath + '#' + n, n, title: s.names[n - 1] || 'скан ' + n };
    }
  },
  async fetch(item, ctx) {
    const url = new URL(this.s.template.href); url.searchParams.set('n', String(item.n));
    const blob = await ctx.request(url.href, {}, 'blob', u => u.origin === location.origin && u.pathname === this.s.template.pathname);
    return { blob, source: url.href, meta: { title: (this.s.title ? this.s.title + ' — ' : '') + item.title,
      archive: 'Государственный архив Архангельской области', reference: this.s.title || ('дело ' + this.s.caseId),
      sheet: item.title, page: location.origin + this.s.casePath + '#' + item.n } };
  },
  fileName(item) { return String(item.n).padStart(4, '0') + '_' + item.title.slice(0, 120) + '_' + this.s.caseId; },
});
