// @kin-adapter kga-rkursk
// @title Государственный архив Курской области (kga.rkursk.ru, ЕАИС)
// @site https://kga.rkursk.ru
// @version 9
// @start Войдите на сайт (доступ к делу может быть платным — решение пользователя), откройте дело и ПЕРВОЕ нужное фото в просмотрщике.
// @based-on download-gallery.js v8 (автор набора)
kinDownloader({
  id: 'kga-rkursk', version: 9, title: 'Государственный архив Курской области',
  note: 'Скачивает фото, листая просмотрщик кнопкой «Далее» с текущего фото до конца дела. Если большая версия недоступна, сохранит доступную копию с пометкой -preview и причиной в журнале.',
  ready: 'Откройте первое нужное фото в просмотрщике и нажмите «Выбрать папку и начать».',
  P: 'MainPlaceHolder__storageViewerControl_',
  field(name) { return document.getElementById(this.P + 'DeepZoomImageViewer_h_' + name)?.value; },
  check() { return location.origin !== 'https://kga.rkursk.ru' ? 'Запустите на сайте kga.rkursk.ru.' : ''; },
  validate() { return this.field('fileId') ? '' : 'Сначала откройте фото в просмотрщике сайта.'; },
  allow(u) { return u.origin === 'https://kga.rkursk.ru' && !/login|signin|logon/i.test(u.pathname); },
  async goNext(id, name, ctx) {
    const busy = () => !!window.Sys?.WebForms?.PageRequestManager?.getInstance()?.get_isInAsyncPostBack();
    const deadline = Date.now() + 180000; let attempts = 0, idle = null;
    while (!ctx.stopped) {
      const processing = busy();
      if (this.field('fileId') !== id && !processing) return true;
      if (Date.now() > deadline) throw ctx.fatal(`Сайт не перешёл дальше ${name} за 3 минуты. Обновите страницу, откройте это фото и запустите снова в ту же папку.`);
      if (!processing && this.field('fileId') === id) {
        if (idle === null) idle = Date.now();
        if (attempts === 0 || Date.now() - idle >= 15000) {
          const next = document.getElementById(this.P + 'ForwardBtn');
          if (!next || next.disabled || next.getAttribute('disabled') !== null || next.closest('[disabled]')) {
            if (attempts === 0) return false;  // последнее фото
            throw ctx.fatal('Кнопка «Далее» недоступна, но фото не сменилось. Проверьте страницу вручную.');
          }
          if (attempts >= 3) throw ctx.fatal(`Сайт остался на ${name} после 3 попыток перехода.`);
          ctx.status(`После ${name}: переход, попытка ${attempts + 1}/3…`);
          next.click(); attempts++; idle = Date.now();
        }
      } else idle = null;
      await ctx.wait(100);
    }
    return false;
  },
  async *items(ctx) {
    const seen = new Set();
    while (!ctx.stopped) {
      const id = this.field('fileId'), w = Number(this.field('width')), h = Number(this.field('height'));
      if (!id || !w || !h || seen.has(id)) throw ctx.fatal('Не удалось определить новую страницу просмотрщика.');
      if (Number(this.field('pageNumber')) !== 0 || Number(this.field('totalPages')) > 1)
        throw ctx.fatal('Многостраничный файл: нужна отдельная обработка страниц (пришлите страницу агенту).');
      seen.add(id);
      const name = document.getElementById(this.P + 'FilesDropDownList_I')?.value || id;
      yield { key: id + ':0', id, name, title: name, w, h };
      if (!await this.goNext(id, name, ctx)) return;
    }
  },
  async fetch(item, ctx) {
    const title = (document.title || '').replace(/\s+/g, ' ').trim();
    const meta = { title: (title ? title + ' — ' : '') + item.name, archive: 'Государственный архив Курской области',
      reference: title, sheet: item.name, page: location.href.split('#')[0] };
    const direct = '/Pages/ImageFile.ashx?' + new URLSearchParams({ id: item.id, simple: 'true', rotation: '0', searchtext: '' });
    const dataError = async blob => /text\//i.test(blob.type) && /Ошибка получения данных|Запрос не с сайта/.test(await blob.slice(0, 2000).text());
    let blob = await ctx.request(direct);
    if (!(await dataError(blob))) return { blob, source: direct, expect: { width: item.w, height: item.h }, meta };
    const reason = 'Сервер: ошибка получения большой версии';
    const tile = Number(this.field('tileSize'));
    if (!tile || tile < Math.max(item.w, item.h)) throw Error(reason + '; уменьшенная копия недоступна.');
    const max = Math.ceil(Math.log2(Math.max(item.w, item.h)));
    for (let level = max - 1; level >= Math.max(0, max - 4); level--) {
      ctx.status(`${item.name}: большая версия недоступна, пробую уменьшенную (уровень ${level})…`);
      const src = '/Pages/ImageFile.ashx?' + new URLSearchParams({ id: item.id, level: String(level), x: '0', y: '0', tileSize: String(tile),
        tileOverlap: this.field('tileOverlap') || '1', page: this.field('pageNumber') || '0', rotation: '0', searchtext: '' });
      blob = await ctx.request(src);
      if (!(await dataError(blob))) return { blob, source: src, quality: 'preview', reason, meta };
    }
    throw Error('Сервер не отдал ни большую версию, ни уменьшенные копии.');
  },
  fileName(item) { return item.name.replace(/\.[^.]+$/, ''); },
});
