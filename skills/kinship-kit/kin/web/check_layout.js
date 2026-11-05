// Проверка раскладки сайта-схемы на свежих данных (kinship-kit: запускается kin site build, если есть node; тесты и CI).
// node check_layout.js <страница набора kin/web/index.html> <site>/tree.json
// Скрипт страницы выполняется в node с правами пользователя: передавать только страницу из набора, не из дела (theme/).
// Прогоняет код страницы в node: три режима показа × (обычный вид, каждый фильтр семьи), случайные раскрытия родни.
// Ищет пустые координаты (NaN — схема схлопывается в угол), наложения карточек, ошибки скрипта.
// Пишет «проверка раскладки: ок» или строки «предупреждение: …»; код выхода 1 при проблемах.
'use strict';
const fs = require('fs');
const [htmlPath, jsonPath] = process.argv.slice(2);
const warn = [];
let api;
try {
  const html = fs.readFileSync(htmlPath, 'utf8');
  const js = html.split('<script>')[1].split('</script>')[0].replace("'use strict';", '');
  const data = JSON.parse(fs.readFileSync(jsonPath, 'utf8'));
  const el = () => ({ style: { setProperty() {} }, classList: { toggle() {}, add() {} }, setAttribute() {}, addEventListener() {}, insertAdjacentHTML() {}, querySelectorAll: () => [], dataset: {} });
  const stub = `const document={getElementById:${el},body:{insertAdjacentHTML(){},classList:{toggle(){}}},addEventListener(){},createElement:${el}};
const window={addEventListener(){}};const localStorage={getItem:()=>null,setItem(){}};const location={hash:''};
const matchMedia=()=>({matches:true});const innerWidth=1400,innerHeight=900;const requestAnimationFrame=()=>{};const performance={now:()=>0};
const fetch=()=>({then:()=>({then:()=>({catch(){}})})});`;
  api = new Function('DATA', stub + js + `
D = DATA; P = new Map(D.persons.map(p => [p.id, p])); E = D.edges;
nb = new Map(D.persons.map(p => [p.id, []])); for (const e of E) { nb.get(e.a)?.push(e); nb.get(e.b)?.push(e); }
LN = new Map(D.lines.map(l => [l.id, l])); CL = new Map(D.claims.map(c => [c.id, c]));
const gs = D.persons.map(p => p.gen); minGen = Math.min(...gs); maxGen = Math.max(...gs);
return { S, P, layout, applyFamFilter, allowed, families: D.families || [], vis: () => { VIS = computeVisible(); linkForced(); return VIS; } };`)(data);
} catch (e) {
  console.log(`предупреждение: проверка раскладки не запустилась — ${e.message}`);
  process.exit(1);
}

function check(label) {
  let vis, L;
  try { vis = api.vis(); L = api.layout(vis); } catch (e) { warn.push(`${label}: ошибка скрипта — ${e.message}`); return; }
  const extra = [...vis].filter(id => !api.allowed(api.P.get(id)));
  if (extra.length) warn.push(`${label}: показаны люди, не разрешённые режимом — ${extra.slice(0, 5).join(', ')}`);
  const nan = [...L.pos].filter(([, q]) => !Number.isFinite(q.x) || !Number.isFinite(q.y)).map(([id]) => id);
  if (nan.length) warn.push(`${label}: пустые координаты у ${nan.length} из ${L.pos.size} (схема схлопнется), первые: ${nan.slice(0, 5).join(', ')}`);
  const rows = new Map();
  for (const id of vis) { const g = api.P.get(id).gen; if (!rows.has(g)) rows.set(g, []); rows.get(g).push(id); }
  const ovl = [];
  for (const r of rows.values()) {
    r.sort((a, b) => L.pos.get(a).x - L.pos.get(b).x);
    for (let i = 1; i < r.length; i++) if (L.pos.get(r[i]).x - L.pos.get(r[i - 1]).x < 195.5) ovl.push(`${r[i - 1]}/${r[i]}`);
  }
  if (ovl.length && !nan.length) warn.push(`${label}: наложения карточек — ${ovl.slice(0, 5).join(', ')}`);
}

const S = api.S;
// каждый режим показа (кнопка «Гипотезы поиска»): обычный вид и все фильтры семей
for (const [mode, name] of [['conf', 'только подтверждённые'], ['hyp', 'гипотезы поиска'], ['rej', 'с отброшенным']]) {
  S.mode = mode; S.showRej = mode === 'rej'; S.forced = new Set(); S.expanded = new Set();
  check(`${name}: обычный вид`);
  S.famMode = true;
  for (const f of api.families) { api.applyFamFilter(f.key); check(`${name}: фильтр «${f.name}»`); }
  api.applyFamFilter(null); S.famMode = false;
}
S.mode = 'hyp'; S.showRej = false;
// случайные раскрытия родни (детерминированно — одинаковый результат при одинаковых данных)
let seed = 1;
const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
const ids = [...api.P.keys()];
for (let t = 0; t < 60; t++) {
  S.expanded = new Set(); S.forced = new Set();
  for (let k = 0; k < 1 + t % 30; k++) S.expanded.add(ids[Math.floor(rnd() * ids.length)]);
  check(`раскрытия №${t + 1}`);
}
if (process.argv[4] === '--modes') {  // для тестов набора: кто виден в каждом режиме
  const out = {};
  for (const m of ['conf', 'hyp', 'rej']) { S.mode = m; S.showRej = m === 'rej'; S.forced = new Set(); S.expanded = new Set(); out[m] = [...api.vis()]; }
  console.log(JSON.stringify(out));
  process.exit(warn.length ? 1 : 0);
}
if (!warn.length) { console.log('проверка раскладки: ок'); process.exit(0); }
for (const w of warn.slice(0, 10)) console.log(`предупреждение: ${w}`);
if (warn.length > 10) console.log(`предупреждение: и ещё ${warn.length - 10}`);
process.exit(1);
