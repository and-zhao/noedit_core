/* NoEdit Core —— 轻量 UI 逻辑
 *
 * 与后端只通过两个 HTTP 接口打交道：
 *   POST /api/call   {method, args}  → {ok, result} | {ok:false, message}
 *   GET  /canvas?page=N             → 当前页的静态渲染页（导出用的同一份渲染器）
 *
 * 编辑策略：每次改动调一次对应的 noedit_core.api 方法（后端即时落盘），随后刷新预览。
 * 预览是独立 iframe，里面注入的脚本把被点元素的 data-id postMessage 回来做选中。
 *
 * 多语言：文案数据在 i18n.js（window.AC_I18N），本文件只负责取用与套用。
 */
'use strict';

// ---------------------------------------------------------------- 基础工具
const $ = (sel) => document.querySelector(sel);
const byId = (id) => document.getElementById(id);
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

// ---------------------------------------------------------------- 多语言
const I18N = window.AC_I18N;
let LANG = I18N.defaultLang;

/** 取文案；缺 key 时回落到默认语言，再缺就原样返回 key。{name} 占位符由 params 替换。 */
function t(key, params) {
  const table = I18N.dict[LANG] || {};
  const base = I18N.dict[I18N.defaultLang] || {};
  let s = table[key] !== undefined ? table[key] : base[key];
  if (s === undefined) return key;
  if (params) s = s.replace(/\{(\w+)\}/g, (m, k) => (params[k] === undefined ? m : String(params[k])));
  return s;
}

/** 缺 key 时用 fallback（服务端返回中文标签等场景）。 */
function tOr(key, fallback, params) {
  const table = I18N.dict[LANG] || {};
  return table[key] !== undefined ? t(key, params) : fallback;
}

function setLang(code, persist) {
  LANG = I18N.dict[code] ? code : I18N.defaultLang;
  if (persist !== false) { try { localStorage.setItem(I18N.storageKey, LANG); } catch (e) { /* 忽略 */ } }
  document.documentElement.lang = LANG;
  applyI18n();
}

/** 静态文案走 data-i18n*，动态文案交给各自的 render 函数。 */
function applyI18n() {
  document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.getAttribute('data-i18n')); });
  document.querySelectorAll('[data-i18n-title]').forEach((el) => { el.title = t(el.getAttribute('data-i18n-title')); });
  document.querySelectorAll('[data-i18n-ph]').forEach((el) => { el.placeholder = t(el.getAttribute('data-i18n-ph')); });
  // 输入框的「默认值」只在用户没动过时改写，免得把已填内容冲掉
  document.querySelectorAll('[data-i18n-value]').forEach((el) => {
    if (!el.dataset.touched) el.value = t(el.getAttribute('data-i18n-value'));
  });
  fillLangSelect();
  fillPresetOptions();
  if (S.types.length) fillTypeOptions();
  relocalizePages();      // 原地改文案，避免重载整列缩略图
  renderElements();
  renderProps();
  renderRecent();
  updateStageFoot();
}

function buildLangSelect() {
  const sel = byId('lang-select');
  sel.innerHTML = '';
  I18N.langs.forEach((l) => {
    const opt = document.createElement('option');
    opt.value = l.code;
    opt.textContent = l.label;      // 语言名用其本名，不翻译
    sel.appendChild(opt);
  });
}
function fillLangSelect() { byId('lang-select').value = LANG; }

/** 新建工程的下拉：value 是后端 preset 名，展示文案交给 i18n。 */
function fillPresetOptions() {
  const sel = byId('new-preset');
  if (!sel) return;
  const cur = sel.value;
  sel.innerHTML = '';
  PRESETS.forEach(([v, key]) => {
    const opt = document.createElement('option');
    opt.value = v;
    opt.textContent = t(key);
    sel.appendChild(opt);
  });
  if (cur) sel.value = cur;
}

/** 元素类型下拉：文案用本地化标签，附上语言无关的 type 便于对照。 */
function fillTypeOptions() {
  const sel = byId('add-type');
  if (!sel) return;
  const cur = sel.value;
  sel.innerHTML = '';
  S.types.forEach((ty) => {
    const opt = document.createElement('option');
    opt.value = ty.type;
    const label = tOr('eltype.' + ty.type, ty.label);
    opt.textContent = ty.label === ty.type ? label : label + ' · ' + ty.type;
    sel.appendChild(opt);
  });
  if (cur) sel.value = cur;
}

/** 语言切换时原地更新页面列表的文案与 title（不重载缩略图 iframe）。 */
function relocalizePages() {
  const items = byId('page-list').querySelectorAll(':scope > li');
  items.forEach((li, i) => {
    const p = S.pages[i];
    if (!p) return;
    const main = li.querySelector('.li-main');
    if (main) { main.textContent = p.name || t('page.default', { n: i + 1 }); main.title = t('page.rename.title'); }
    const tag = li.querySelector('.li-tag');
    if (tag) tag.textContent = t('page.count', { n: (p.elements || []).length });
    const x = li.querySelector('.li-x');
    if (x) x.title = t('page.delete.title');
    const f = S.thumbs[i];
    if (f) f.title = t('page.preview.title', { n: i + 1 });
  });
}

async function call(method, ...args) {
  const resp = await fetch('/api/call', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ method, args }),
  });
  let data;
  try {
    data = await resp.json();
  } catch (e) {
    throw new Error(t('err.backend', { s: resp.status }));
  }
  if (!data.ok) throw new Error(data.message || t('err.op'));
  return data.result;
}

function toast(msg, kind) {
  const box = byId('toasts');
  const item = document.createElement('div');
  item.className = 'toast' + (kind ? ' ' + kind : '');
  item.textContent = msg;
  box.appendChild(item);
  setTimeout(() => item.remove(), kind === 'err' ? 5200 : 3200);
}

const PRESETS = [
  ['ppt-16:9', 'preset.ppt169'],
  ['ppt-4:3', 'preset.ppt43'],
  ['slide-widescreen', 'preset.wide169'],
  ['a4-portrait', 'preset.a4p'],
  ['a4-landscape', 'preset.a4l'],
  ['b5-portrait', 'preset.b5p'],
];

// ---------------------------------------------------------------- 状态
const S = {
  project: null,
  name: '',
  defaultDir: '',    // 「默认目录」：新建的父目录、目录树起点、导出落点都以此为准
  defaultDirSet: false,   // 用户是否显式设过默认目录（没设过时导出仍写工程内的 export/）
  canvas: { width: 1280, height: 720 },
  pages: [],
  pageIndex: 0,
  selectedId: '',
  types: [],
  assetBase: '',
  scale: 1,
  thumbs: [],        // 每页缩略图 iframe（与 pages 同下标）
};

const frame = byId('canvas-frame');

// ---------------------------------------------------------------- 启动
// 注意：init() 在文件末尾才调用 —— 它同步阶段就要用到后面声明的常量（SPLIT / THUMB_W 等）。
async function init() {
  // 语言：本地记住的选择优先，否则默认中文
  let saved = null;
  try { saved = localStorage.getItem(I18N.storageKey); } catch (e) { /* 忽略 */ }
  LANG = I18N.dict[saved] ? saved : I18N.defaultLang;
  document.documentElement.lang = LANG;
  buildLangSelect();
  fillPresetOptions();
  applyI18n();
  bindEvents();
  renderRecent();
  try {
    S.types = await call('element_types');
    fillTypeOptions();
  } catch (e) {
    toast(t('err.types', { msg: e.message }), 'err');
  }
  await loadSettings();
  await refresh();
  startProjectSync();
}

/** 读「默认目录」等设置并填进落地页顶部那一行。 */
async function loadSettings() {
  try {
    const r = await call('get_settings');
    S.defaultDir = (r && r.defaultDir) || '';
    S.defaultDirSet = !!(r && r.custom);
  } catch (e) { S.defaultDir = ''; S.defaultDirSet = false; }
  applyDefaultDir();
}

/** 把 S.defaultDir 反映到界面：顶部输入框 + 新建工程的父目录默认值。 */
function applyDefaultDir() {
  byId('defdir-input').value = S.defaultDir || '';
  if (S.defaultDir && !byId('new-dir').value) byId('new-dir').value = S.defaultDir;
}

function bindEvents() {
  byId('btn-reload').addEventListener('click', () => refresh(true));
  byId('btn-open').addEventListener('click', () => showLanding('open'));
  byId('btn-new').addEventListener('click', () => showLanding('create'));
  byId('btn-close-landing').addEventListener('click', hideLanding);
  byId('landing').addEventListener('click', (e) => { if (e.target === byId('landing')) hideLanding(); });
  byId('landing-tabs').addEventListener('click', (e) => {
    const tab = e.target.closest('.tab');
    if (tab) selectLandingTab(tab.dataset.tab);
  });
  byId('btn-add-page').addEventListener('click', onAddPage);
  byId('btn-add-el').addEventListener('click', onAddElement);
  byId('btn-del-el').addEventListener('click', onDeleteElement);
  byId('btn-prev').addEventListener('click', () => goPage(S.pageIndex - 1));
  byId('btn-next').addEventListener('click', () => goPage(S.pageIndex + 1));
  byId('btn-fit').addEventListener('click', fitStage);
  byId('btn-export').addEventListener('click', (e) => {
    e.stopPropagation();
    byId('export-menu').hidden = !byId('export-menu').hidden;
  });
  byId('export-menu').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-fmt]');
    if (btn) doExport(btn.getAttribute('data-fmt'));
  });
  document.addEventListener('click', () => { byId('export-menu').hidden = true; });
  byId('btn-do-create').addEventListener('click', doCreate);
  byId('btn-defdir-save').addEventListener('click', saveDefaultDir);
  byId('defdir-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); saveDefaultDir(); }
  });
  byId('lang-select').addEventListener('change', (e) => setLang(e.target.value));
  byId('new-name').addEventListener('input', (e) => { e.target.dataset.touched = '1'; });
  window.addEventListener('message', onCanvasMessage);
  frame.addEventListener('load', onFrameReady);

  // 画布周围的留白区域（指针不落在 iframe 上时）也要能翻页
  byId('stage-box').addEventListener('wheel', onStageWheel, { passive: false });

  // Esc 关闭导出菜单；有工程在编辑时也用于退出落地页
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    byId('export-menu').hidden = true;
    if (!byId('landing').hidden) hideLanding();
  });

  initSplitters();

  // 画布区尺寸变化（窗口缩放、栏宽拖拽、侧栏拖高…）→ 重新适配缩放
  const box = byId('stage-box');
  if (window.ResizeObserver) new ResizeObserver(scheduleFit).observe(box);
  window.addEventListener('resize', () => { applySideSplit(); scheduleFit(); });
}

// ---------------------------------------------------------------- 布局拖拽
// 侧栏内「页面 : 元素」用比例记忆（窗口变高时仍按比例自适应）；
// 两侧栏宽用 px 记忆（拖拽语义就是绝对宽度），双击恢复 CSS 默认。
const SPLIT = { sideW: null, propsW: null, sideRatio: 0.5 };
const LS_SPLIT = { w: 'noedit_core.wSide', pw: 'noedit_core.wProps', r: 'noedit_core.sideRatio' };
const SPLIT_MIN = 96;                 // 侧栏两个面板各自的最小高度
const W_MIN = { side: 172, props: 220 };
const W_MAX = { side: 420, props: 520 };

function persistSplit() {
  try {
    if (SPLIT.sideW) localStorage.setItem(LS_SPLIT.w, String(Math.round(SPLIT.sideW)));
    else localStorage.removeItem(LS_SPLIT.w);
    if (SPLIT.propsW) localStorage.setItem(LS_SPLIT.pw, String(Math.round(SPLIT.propsW)));
    else localStorage.removeItem(LS_SPLIT.pw);
    localStorage.setItem(LS_SPLIT.r, String(SPLIT.sideRatio));
  } catch (e) { /* 忽略 */ }
}

function restoreSplit() {
  let w = 0; let pw = 0; let r = 0.5;
  try {
    w = Number(localStorage.getItem(LS_SPLIT.w)) || 0;
    pw = Number(localStorage.getItem(LS_SPLIT.pw)) || 0;
    r = Number(localStorage.getItem(LS_SPLIT.r)) || 0.5;
  } catch (e) { /* 忽略 */ }
  SPLIT.sideRatio = clamp(r, 0.05, 0.95);
  if (w) { SPLIT.sideW = clamp(w, W_MIN.side, W_MAX.side); byId('side').style.width = SPLIT.sideW + 'px'; }
  if (pw) { SPLIT.propsW = clamp(pw, W_MIN.props, W_MAX.props); byId('props-panel').style.width = SPLIT.propsW + 'px'; }
}

/** 把 sideRatio 套到「页面 / 元素」两面板的高度上（弹性由 els-panel 吸收剩余）。 */
function applySideSplit() {
  const side = byId('side');
  const pages = byId('pages-panel');
  if (!side || !pages || side.clientHeight <= 0) return;
  const avail = side.clientHeight - byId('v-split').offsetHeight;
  if (avail <= SPLIT_MIN) return;
  const max = Math.max(SPLIT_MIN, avail - SPLIT_MIN);
  pages.style.flex = '0 0 ' + Math.round(clamp(avail * SPLIT.sideRatio, SPLIT_MIN, max)) + 'px';
}

/** 通用拖拽：Pointer Events + setPointerCapture，onDown 返回起始快照，onMove/onUp 拿它算增量。
 *  这里刻意不调 preventDefault()——它会连带吃掉兼容鼠标事件，双击复位就失效了；
 *  滚动与选中由 CSS 的 touch-action / user-select 负责。 */
function dragify(handle, onDown, onMove, onUp) {
  handle.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    const start = onDown(e);
    handle.setPointerCapture(e.pointerId);
    handle.classList.add('dragging');
    document.body.style.userSelect = 'none';
    const move = (ev) => onMove(ev, start);
    const up = (ev) => {
      handle.removeEventListener('pointermove', move);
      handle.removeEventListener('pointerup', up);
      handle.removeEventListener('pointercancel', up);
      handle.classList.remove('dragging');
      document.body.style.userSelect = '';
      if (handle.hasPointerCapture(ev.pointerId)) handle.releasePointerCapture(ev.pointerId);
      if (onUp) onUp(ev, start);
    };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', up);
    handle.addEventListener('pointercancel', up);
  });
}

function initSplitters() {
  const side = byId('side');
  const props = byId('props-panel');
  const vSplit = byId('v-split');
  const left = byId('split-left');
  const right = byId('split-right');

  // 左栏：向右拖变宽
  dragify(left,
    (e) => ({ x: e.clientX, w: side.getBoundingClientRect().width }),
    (e, s) => {
      SPLIT.sideW = clamp(s.w + (e.clientX - s.x), W_MIN.side, W_MAX.side);
      side.style.width = SPLIT.sideW + 'px';
      scheduleFit();
    },
    persistSplit);

  // 右栏：向右拖变窄（面板在右侧）
  dragify(right,
    (e) => ({ x: e.clientX, w: props.getBoundingClientRect().width }),
    (e, s) => {
      SPLIT.propsW = clamp(s.w - (e.clientX - s.x), W_MIN.props, W_MAX.props);
      props.style.width = SPLIT.propsW + 'px';
      scheduleFit();
    },
    persistSplit);

  // 侧栏内：上下拖调节「页面 : 元素」高度比
  dragify(vSplit,
    (e) => ({ y: e.clientY, ratio: SPLIT.sideRatio, avail: side.clientHeight - vSplit.offsetHeight }),
    (e, s) => {
      if (s.avail > 0) SPLIT.sideRatio = clamp(s.ratio + (e.clientY - s.y) / s.avail, 0.05, 0.95);
      applySideSplit();
    },
    persistSplit);

  // 双击拖拽条恢复默认
  vSplit.addEventListener('dblclick', () => { SPLIT.sideRatio = 0.5; applySideSplit(); persistSplit(); });
  left.addEventListener('dblclick', () => { SPLIT.sideW = null; side.style.width = ''; persistSplit(); applySideSplit(); scheduleFit(); });
  right.addEventListener('dblclick', () => { SPLIT.propsW = null; props.style.width = ''; persistSplit(); scheduleFit(); });

  restoreSplit();
}

// ---------------------------------------------------------------- 状态同步
async function refresh(showToast) {
  let st;
  try {
    st = await call('state');
  } catch (e) {
    toast(t('err.state', { msg: e.message }), 'err');
    return;
  }
  applyState(st);
  if (showToast) toast(t('ok.reloaded'), 'ok');
}

// 外部（agent 调 /api/ui/open）切换工程后，本页自动跟随，不用手动刷新。
let _syncTimer = null;
function startProjectSync() {
  if (_syncTimer) clearInterval(_syncTimer);
  _syncTimer = setInterval(syncProject, 2000);
}
async function syncProject() {
  let cur;
  try {
    const resp = await fetch('/api/ui/current');
    const data = await resp.json();
    if (!data.ok) return;
    cur = data.result || {};
  } catch (e) { return; }  // 服务不可达就静默跳过，下次再试
  const serverProject = cur.project || null;
  if (serverProject === (S.project || null)) return;
  await refresh();
  if (serverProject) toast(t('sync.switched', { name: cur.name || serverProject }), 'ok');
}

function applyState(st) {
  if (!st || !st.project) {
    S.project = null;
    S.thumbs = [];
    byId('layout').hidden = true;
    showLanding();
    return;
  }
  S.project = st.project;
  S.name = st.name || '';
  S.canvas = st.canvas || { width: 1280, height: 720 };
  S.pages = st.pages || [];
  S.assetBase = st.assetBase || '';
  if (S.pageIndex >= S.pages.length) S.pageIndex = Math.max(0, S.pages.length - 1);
  byId('landing').hidden = true;
  byId('layout').hidden = false;
  byId('proj-name').textContent = S.name || S.project;
  byId('proj-path').textContent = S.project;
  byId('proj-path').title = S.project;
  renderPages();
  renderElements();
  renderProps();
  reloadCanvas();
  applySideSplit();
  scheduleFit();
}

function currentPage() { return S.pages[S.pageIndex] || null; }

function currentElement() {
  const page = currentPage();
  if (!page) return null;
  return (page.elements || []).find((e) => e.id === S.selectedId) || null;
}

// ---------------------------------------------------------------- 页面列表
/** 缩略图宽度（px）。高度按画布比例算，保证不变形。 */
const THUMB_W = 92;

function thumbUrl(i) { return `/canvas?page=${i}&t=${Date.now()}`; }

/** 造一个「整幅画布按比例缩小」的缩略图，内容是 /canvas 的静态渲染（与导出同源）。 */
function makeThumb(i) {
  const cw = S.canvas.width || 1280;
  const ch = S.canvas.height || 720;
  const wrap = document.createElement('div');
  wrap.className = 'thumb';
  wrap.style.width = THUMB_W + 'px';
  wrap.style.height = Math.round(THUMB_W * ch / cw) + 'px';
  const f = document.createElement('iframe');
  f.className = 'thumb-frame';
  f.tabIndex = -1;
  f.setAttribute('scrolling', 'no');
  f.title = t('page.preview.title', { n: i + 1 });
  f.style.width = cw + 'px';
  f.style.height = ch + 'px';
  f.style.transform = `scale(${THUMB_W / cw})`;
  wrap.appendChild(f);
  return { wrap, frame: f };
}

/** 只刷新某页的缩略图；编辑当前页后调用，避免整列重载。 */
function reloadThumb(i) {
  const f = S.thumbs[i];
  if (f) f.src = thumbUrl(i);
}

function renderPages() {
  const list = byId('page-list');
  list.innerHTML = '';
  S.thumbs = [];
  S.pages.forEach((p, i) => {
    const li = document.createElement('li');
    if (i === S.pageIndex) li.classList.add('active');

    const { wrap, frame } = makeThumb(i);
    S.thumbs[i] = frame;
    li.appendChild(wrap);

    const meta = document.createElement('div');
    meta.className = 'page-meta';
    const no = document.createElement('span');
    no.className = 'page-no';
    no.textContent = 'P' + String(i + 1).padStart(2, '0');
    const main = document.createElement('span');
    main.className = 'li-main';
    main.textContent = p.name || t('page.default', { n: i + 1 });
    main.title = t('page.rename.title');
    main.addEventListener('dblclick', (e) => { e.stopPropagation(); renamePage(i, p.name); });
    const tag = document.createElement('span');
    tag.className = 'li-tag';
    tag.textContent = t('page.count', { n: (p.elements || []).length });
    meta.appendChild(no);
    meta.appendChild(main);
    meta.appendChild(tag);
    li.appendChild(meta);

    if (S.pages.length > 1) {
      const x = document.createElement('button');
      x.className = 'li-x';
      x.textContent = '×';
      x.title = t('page.delete.title');
      x.addEventListener('click', (e) => { e.stopPropagation(); onDeletePage(i); });
      li.appendChild(x);
    }
    li.addEventListener('click', () => goPage(i));
    list.appendChild(li);
    frame.src = thumbUrl(i);
  });
}

function goPage(i) {
  if (i < 0 || i >= S.pages.length) return;
  S.pageIndex = i;
  S.selectedId = '';
  renderPages();
  renderElements();
  renderProps();
  reloadCanvas();
  updateStageFoot();
}

/** 画布区滚轮翻页：向下滚下一页、向上滚上一页；280ms 内只认一次，避免一次手势连翻多页。 */
let _wheelAt = 0;
function onStageWheel(e) {
  if (!S.project || S.pages.length <= 1) return;
  if (Math.abs(e.deltaY) < 1) return;
  e.preventDefault();
  const now = Date.now();
  if (now - _wheelAt < 280) return;
  _wheelAt = now;
  goPage(S.pageIndex + (e.deltaY > 0 ? 1 : -1));
}

async function onAddPage() {
  try {
    await call('add_page', S.project, -1, '');
    await refresh();
    goPage(S.pages.length - 1);
  } catch (e) { toast(e.message, 'err'); }
}

async function onDeletePage(i) {
  if (S.pages.length <= 1) { toast(t('err.keepOnePage'), 'err'); return; }
  if (!confirm(t('page.delete.confirm', { name: S.pages[i].name }))) return;
  try {
    await call('delete_page', S.project, i);
    if (S.pageIndex >= i) S.pageIndex = Math.max(0, S.pageIndex - 1);
    S.selectedId = '';
    await refresh();
  } catch (e) { toast(e.message, 'err'); }
}

async function renamePage(i, oldName) {
  const name = prompt(t('page.rename.prompt'), oldName || '');
  if (name === null) return;
  try {
    await call('update_page', S.project, { name }, i);
    await refresh();
  } catch (e) { toast(e.message, 'err'); }
}

// ---------------------------------------------------------------- 元素列表
function renderElements() {
  const list = byId('el-list');
  list.innerHTML = '';
  const page = currentPage();
  const els = (page && page.elements) || [];
  if (!els.length) {
    const li = document.createElement('li');
    li.className = 'empty';
    li.textContent = t('els.empty');
    list.appendChild(li);
    return;
  }
  // 画布上 z 越大越靠上；列表按「上层在前」展示更直观
  [...els].reverse().forEach((e) => {
    const li = document.createElement('li');
    if (e.id === S.selectedId) li.classList.add('active');
    const main = document.createElement('span');
    main.className = 'li-main';
    main.textContent = e.name || e.id;
    const tag = document.createElement('span');
    tag.className = 'li-tag';
    tag.textContent = e.type;
    li.appendChild(main);
    li.appendChild(tag);
    li.addEventListener('click', () => select(e.id));
    list.appendChild(li);
  });
}

function select(id) {
  S.selectedId = id || '';
  renderElements();
  renderProps();
  highlightInFrame();
}

function onCanvasMessage(e) {
  // 缩略图 iframe 也加载 /canvas，会发同样的消息；只认主画布那一份。
  if (e.source !== frame.contentWindow) return;
  const m = e.data || {};
  if (m.type === 'ac-select') select(m.id || '');
  else if (m.type === 'ac-ready') highlightInFrame();
}

function highlightInFrame() {
  try {
    frame.contentWindow.postMessage({ type: 'ac-highlight', id: S.selectedId }, '*');
  } catch (err) { /* iframe 尚未就绪，忽略 */ }
}

/** 每次 iframe 加载完成后：同步选中高亮，并把滚轮翻页监听到它自己的窗口上。
 *  画布铺满整个 iframe，指针基本都停在 iframe 上——那里的滚轮事件不会冒泡到父页面，
 *  必须直接挂在 iframe 的 window 上（同源，可直接访问）；文档每次加载都是新的，不会重复叠加。 */
function onFrameReady() {
  highlightInFrame();
  try {
    frame.contentWindow.addEventListener('wheel', onStageWheel, { passive: false });
  } catch (err) { /* iframe 尚未就绪或跨域，忽略 */ }
}

// ---------------------------------------------------------------- 预览
function reloadCanvas() {
  if (!S.project) return;
  frame.src = `/canvas?page=${S.pageIndex}&t=${Date.now()}`;
  updateStageFoot();
}

function updateStageFoot() {
  const page = currentPage();
  byId('page-indicator').textContent = t('page.nav', { a: S.pageIndex + 1, b: S.pages.length });
  const cw = S.canvas.width;
  const ch = S.canvas.height;
  byId('stage-foot').textContent =
    t('stage.foot', { w: cw, h: ch })
    + (page && page.name ? ` · ${page.name}` : '')
    + ` · ${t('stage.zoom', { p: Math.round(S.scale * 100) })}`;
}

/** 缩放适配：ResizeObserver / 拖拽改动都会触发，防抖后再算，避免抖动。 */
let _fitTimer = null;
function scheduleFit() {
  clearTimeout(_fitTimer);
  _fitTimer = setTimeout(fitStage, 80);
}

function fitStage() {
  if (!S.project) return;
  const box = byId('stage-box');
  const cs = getComputedStyle(box);
  const padX = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight);
  const padY = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
  const availW = box.clientWidth - padX;
  const availH = box.clientHeight - padY;
  const cw = S.canvas.width;
  const ch = S.canvas.height;
  let k = Math.min(availW / cw, availH / ch);
  if (!isFinite(k) || k <= 0) k = 1;
  const wrap = byId('stage-frame');
  // 缩放没变就别反复写样式（写样式又会触发 ResizeObserver，造成回环）
  if (wrap.style.width && Math.abs(k - S.scale) < 1e-3) { updateStageFoot(); return; }
  S.scale = k;
  wrap.style.width = cw * k + 'px';
  wrap.style.height = ch * k + 'px';
  frame.style.width = cw + 'px';
  frame.style.height = ch + 'px';
  frame.style.transform = `scale(${k})`;
  updateStageFoot();
}

// ---------------------------------------------------------------- 属性面板
function renderProps() {
  const body = byId('props-body');
  body.innerHTML = '';
  const el = currentElement();
  byId('btn-del-el').hidden = !el;
  byId('props-title').textContent = el
    ? t('props.head', { name: el.name || el.id, type: el.type })
    : t('props.title');
  if (!el) {
    body.innerHTML = '<p class="muted">' + t('props.empty') + '</p>';
    return;
  }

  // --- 基本 ---
  const basic = group(body, t('props.basic'));
  row(basic, t('props.name'), textInput(el.name || '', (v) => commit({ name: v })));
  const xy = pairRow(basic, t('props.pos'), 'x', 'y');
  rowInto(xy.x, numInput(el.x, (v) => commit({ x: v })));
  rowInto(xy.y, numInput(el.y, (v) => commit({ y: v })));
  const wh = pairRow(basic, t('props.size'), 'w', 'h');
  rowInto(wh.w, numInput(el.w, (v) => commit({ w: v })));
  rowInto(wh.h, numInput(el.h, (v) => commit({ h: v })));
  const zr = pairRow(basic, t('props.z'), 'z', 'rotate');
  rowInto(zr.z, numInput(el.z, (v) => commit({ z: v })));
  rowInto(zr.rotate, numInput(el.rotate || 0, (v) => commit({ rotate: v })));
  const opv = pairRow(basic, t('props.look'), 'opacity', 'visible');
  rowInto(opv.opacity, numInput(el.opacity === undefined ? 1 : el.opacity, (v) => commit({ opacity: v }), { step: 0.05, min: 0, max: 1 }));
  const vis = document.createElement('input');
  vis.type = 'checkbox';
  vis.checked = el.visible !== false;
  vis.addEventListener('change', () => commit({ visible: vis.checked }));
  opv.visible.appendChild(vis);

  // --- 样式 style.* ---
  const styleBox = group(body, t('props.styleGroup'));
  const styleKeys = Object.keys(el.style || {});
  if (!styleKeys.length) note(styleBox, t('props.noStyle'));
  styleKeys.forEach((k) => {
    row(styleBox, k, scalarInput(el.style[k], (v) => commit({ ['style.' + k]: v }), k));
  });

  // --- 属性 props.* ---
  const propsBox = group(body, t('props.propsGroup'));
  const props = el.props || {};
  const propsKeys = Object.keys(props);
  if (!propsKeys.length) note(propsBox, t('props.noProps'));
  propsKeys.forEach((k) => {
    if (k === 'src' && (el.type === 'image' || el.type === 'video')) {
      const ctl = row(propsBox, k, textInput(props[k] || '', (v) => commit({ ['props.' + k]: v })));
      const btn = document.createElement('button');
      btn.className = 'mini';
      btn.textContent = t('props.upload');
      btn.title = t('props.upload.title');
      btn.style.width = 'auto';
      btn.style.padding = '0 8px';
      btn.addEventListener('click', () => uploadInto(el, k));
      ctl.appendChild(btn);
      return;
    }
    row(propsBox, k, scalarInput(props[k], (v) => commit({ ['props.' + k]: v }), k));
  });

  // --- 原始 JSON ---
  const raw = group(body, t('props.rawGroup'));
  raw.appendChild(jsonEditor('props', props));
  raw.appendChild(jsonEditor('style', el.style || {}));
}

function group(parent, title) {
  const box = document.createElement('div');
  box.className = 'group';
  const h = document.createElement('div');
  h.className = 'group-title';
  h.textContent = title;
  box.appendChild(h);
  parent.appendChild(box);
  return box;
}

function note(parent, text) {
  const p = document.createElement('div');
  p.className = 'inline-note';
  p.textContent = text;
  parent.appendChild(p);
}

/** 一行：标签 + 控件；返回放控件的容器。 */
function row(parent, label, control) {
  const wrap = document.createElement('div');
  wrap.className = 'field-row';
  const lb = document.createElement('label');
  lb.textContent = label;
  lb.title = label;
  const ctl = document.createElement('div');
  ctl.className = 'ctl';
  if (control) ctl.appendChild(control);
  wrap.appendChild(lb);
  wrap.appendChild(ctl);
  parent.appendChild(wrap);
  return ctl;
}

/** 两列一行：返回按 key 索引的控件容器（key 与语言无关，如 'x'/'y'/'w'/'h'）。 */
function pairRow(parent, label, leftKey, rightKey) {
  const wrap = document.createElement('div');
  wrap.className = 'field-row';
  const lb = document.createElement('label');
  lb.textContent = label;
  lb.title = label;
  const ctl = document.createElement('div');
  ctl.className = 'ctl row-2';
  const l = document.createElement('div');
  const r = document.createElement('div');
  ctl.appendChild(l);
  ctl.appendChild(r);
  wrap.appendChild(lb);
  wrap.appendChild(ctl);
  parent.appendChild(wrap);
  return { [leftKey]: l, [rightKey]: r };
}

function rowInto(container, control) { container.appendChild(control); }

function textInput(value, onCommit) {
  const input = document.createElement('input');
  input.type = 'text';
  input.value = value == null ? '' : value;
  let timer = null;
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => onCommit(input.value), 500);
  });
  input.addEventListener('change', () => { clearTimeout(timer); onCommit(input.value); });
  return input;
}

function numInput(value, onCommit, opts) {
  const input = document.createElement('input');
  input.type = 'number';
  input.value = value == null ? '' : value;
  if (opts) {
    if (opts.step != null) input.step = opts.step;
    if (opts.min != null) input.min = opts.min;
    if (opts.max != null) input.max = opts.max;
  }
  input.addEventListener('change', () => {
    const raw = input.value.trim();
    onCommit(raw === '' ? '' : Number(raw));
  });
  return input;
}

/** 按值类型给出合适的控件：bool→勾选，数字→数字框，颜色串→色板+文本，对象/数组→JSON 文本域。 */
function scalarInput(value, onCommit, key) {
  if (typeof value === 'boolean') {
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = value;
    cb.addEventListener('change', () => onCommit(cb.checked));
    return cb;
  }
  if (typeof value === 'number') return numInput(value, onCommit);
  if (value && typeof value === 'object') {
    const ta = document.createElement('textarea');
    ta.value = JSON.stringify(value, null, 2);
    ta.addEventListener('change', () => {
      try { onCommit(JSON.parse(ta.value)); }
      catch (e) { toast(t('err.json', { msg: e.message }), 'err'); }
    });
    return ta;
  }
  const text = value == null ? '' : String(value);
  const isCode = key === 'code' || key === 'text';
  const looksColor = /color|fill|stroke|bg|background/i.test(key) && /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(text.trim());
  if (isCode) {
    const ta = document.createElement('textarea');
    if (key === 'code') ta.style.minHeight = '180px';
    ta.value = text;
    let timer = null;
    ta.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => onCommit(ta.value), 500); });
    ta.addEventListener('change', () => { clearTimeout(timer); onCommit(ta.value); });
    return ta;
  }
  if (looksColor) {
    const box = document.createElement('div');
    box.style.cssText = 'display:flex;gap:6px;align-items:center;width:100%';
    const color = document.createElement('input');
    color.type = 'color';
    color.value = text.trim();
    const txt = document.createElement('input');
    txt.type = 'text';
    txt.value = text;
    color.addEventListener('input', () => { txt.value = color.value; commitDebounced(onCommit, color.value); });
    txt.addEventListener('change', () => { color.value = txt.value; onCommit(txt.value); });
    box.appendChild(color);
    box.appendChild(txt);
    return box;
  }
  return textInput(text, onCommit);
}

const _deb = new Map();
function commitDebounced(fn, value) {
  const k = fn;
  clearTimeout(_deb.get(k));
  _deb.set(k, setTimeout(() => fn(value), 220));
}

function jsonEditor(label, obj) {
  const wrap = document.createElement('div');
  wrap.className = 'field-row';
  const lb = document.createElement('label');
  lb.textContent = label;
  const ctl = document.createElement('div');
  ctl.className = 'ctl';
  ctl.style.flexDirection = 'column';
  ctl.style.alignItems = 'stretch';
  const ta = document.createElement('textarea');
  ta.value = JSON.stringify(obj, null, 2);
  const btn = document.createElement('button');
  btn.className = 'mini';
  btn.textContent = t('props.apply');
  btn.style.cssText = 'width:auto;padding:0 10px;align-self:flex-end';
  btn.addEventListener('click', () => {
    try { commit({ [label]: JSON.parse(ta.value) }, true); }
    catch (e) { toast(t('err.json', { msg: e.message }), 'err'); }
  });
  ctl.appendChild(ta);
  ctl.appendChild(btn);
  wrap.appendChild(lb);
  wrap.appendChild(ctl);
  return wrap;
}

// ---------------------------------------------------------------- 编辑提交
/**
 * 提交一处改动。patch 的键是点号路径（如 {x:100} / {'props.text':'新'}）。
 * rebuild=false：不重建属性面板，只刷新预览（打字时不打断输入焦点）。
 * rebuild=true ：前后端对齐一次（整段覆盖、需要回读归一的场景）。
 */
function commit(patch, rebuild) {
  const el = currentElement();
  if (!el) return;
  call('update', S.project, patch, el.id, null, S.pageIndex)
    .then(() => {
      // 同步本地对象，让元素列表名称等即时反映
      Object.keys(patch).forEach((path) => setLocal(el, path, patch[path]));
      if (rebuild) refresh();
      else { renderElements(); reloadCanvas(); reloadThumb(S.pageIndex); }
    })
    .catch((e) => toast(e.message, 'err'));
}

function setLocal(el, path, value) {
  const parts = String(path).split('.').filter(Boolean);
  let cursor = el;
  for (let i = 0; i < parts.length - 1; i++) {
    if (typeof cursor[parts[i]] !== 'object' || cursor[parts[i]] === null) cursor[parts[i]] = {};
    cursor = cursor[parts[i]];
  }
  cursor[parts[parts.length - 1]] = value;
}

async function onAddElement() {
  const type = byId('add-type').value;
  if (!type) return;
  const before = new Set(((currentPage() || {}).elements || []).map((e) => e.id));
  try {
    await call('insert', S.project, { type }, S.pageIndex);
    await refresh();
    const page = currentPage();
    const added = ((page && page.elements) || []).find((e) => !before.has(e.id));
    if (added) select(added.id);
  } catch (e) { toast(e.message, 'err'); }
}

async function onDeleteElement() {
  const el = currentElement();
  if (!el) return;
  if (!confirm(t('el.delete.confirm', { name: el.name || el.id }))) return;
  try {
    await call('delete', S.project, el.id, null, S.pageIndex);
    S.selectedId = '';
    await refresh();
  } catch (e) { toast(e.message, 'err'); }
}

async function uploadInto(el, key) {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = el.type === 'video' ? 'video/*' : 'image/*';
  input.addEventListener('change', async () => {
    const file = input.files && input.files[0];
    if (!file) return;
    try {
      const dataUrl = await readAsDataURL(file);
      const rec = await call('upload_asset', file.name, dataUrl);
      await call('update', S.project, { ['props.' + key]: rec.asset.relPath }, el.id, null, S.pageIndex);
      await refresh();
      toast(t('ok.uploaded', { path: rec.asset.relPath }), 'ok');
    } catch (e) { toast(t('err.upload', { msg: e.message }), 'err'); }
  });
  input.click();
}

function readAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error(t('err.readFile')));
    reader.readAsDataURL(file);
  });
}

// ---------------------------------------------------------------- 落地页
/** 目录浏览的当前选中位置（由文件夹树维护，供「打开此工程」与原生对话框定位用）。 */
const BROWSE = { path: '', isProject: false, projectName: '' };

/** 「打开工程」里的文件夹树：节点表（按 treeKey 索引）+ 根节点列表 + 选中项。 */
const TREE = { roots: [], nodes: new Map(), sel: '' };

const ICON_FOLDER = '<svg viewBox="0 0 24 24" class="tico-svg"><path d="M3 6.4A1.6 1.6 0 0 1 4.6 4.8h4.1l2.1 2.3h8.6A1.6 1.6 0 0 1 21 8.7v8.7a1.6 1.6 0 0 1-1.6 1.6H4.6A1.6 1.6 0 0 1 3 17.4z"/></svg>';
const ICON_PROJECT = '<svg viewBox="0 0 24 24" class="tico-svg"><rect x="3.6" y="4.6" width="16.8" height="14.8" rx="2.2"/><path d="M3.6 9.2h16.8"/><path d="M8 4.6V9.2"/></svg>';

/** 路径归一成树的节点键：分隔符归一到 \，去掉末尾多余的 \（盘符根除外）。 */
function treeKey(path) {
  const s = String(path || '').replace(/\//g, '\\');
  if (/^[A-Za-z]:\\?$/.test(s)) return s.slice(0, 2) + '\\';
  return s.replace(/\\+$/, '') || s;
}

/** 取路径最后一段当显示名；盘符根显示成 D:\。 */
function treeName(path) {
  const s = treeKey(path);
  if (/^[A-Za-z]:\\$/.test(s) || s === '/') return s;
  const parts = s.split(/[\\/]/);
  return parts[parts.length - 1] || s;
}

/** 取（或创建）一个树节点，并用后端返回的 seed 补全信息。 */
function treeNode(path, seed) {
  const k = treeKey(path);
  let n = TREE.nodes.get(k);
  if (!n) {
    n = {
      key: k, path, name: treeName(path), depth: 0, parent: '',
      isProject: false, projectName: '', pages: 0,
      children: [], loaded: false, expanded: false,
    };
    TREE.nodes.set(k, n);
  }
  if (seed) {
    if (seed.name) n.name = seed.name;
    if (seed.isProject !== undefined) n.isProject = !!seed.isProject;
    if (seed.projectName) n.projectName = seed.projectName;
    if (seed.pages) n.pages = seed.pages;
  }
  return n;
}

/** 懒加载某节点的子目录（每个节点只拉一次）。 */
async function treeLoad(n) {
  if (n.loaded) return;
  const r = await call('browse_dir', n.path);
  n.children = r.entries.map((e) => {
    const child = treeNode(e.path, e);
    child.parent = n.key;
    child.depth = n.depth + 1;
    return child.key;
  });
  n.loaded = true;
  n.isProject = r.isProject;
  n.projectName = r.projectName || n.projectName;
}

/** 展开 / 收起一个节点（没加载过就先加载）。 */
async function treeToggle(n) {
  byId('landing-err').textContent = '';
  try {
    if (!n.loaded) { await treeLoad(n); n.expanded = true; }
    else { n.expanded = !n.expanded; }
    renderTree();
  } catch (e) { byId('landing-err').textContent = e.message; }
}

/** 选中一个文件夹：同步路径框与「打开此工程」入口。 */
function treeSelect(n) {
  TREE.sel = n.key;
  BROWSE.path = n.path;
  BROWSE.isProject = n.isProject;
  BROWSE.projectName = n.projectName;
  byId('defdir-input').value = n.path;   // 顶部那行兼作「当前目录」：选中哪个就显示哪个
  syncBrowseHere();
}

/** 打开落地页；tab 为 'create' | 'open'，省略则保持当前标签。 */
function showLanding(tab) {
  byId('landing').hidden = false;
  byId('landing-err').textContent = '';
  // 没有工程可回时不能关闭，否则会停在空白界面
  byId('btn-close-landing').hidden = !S.project;
  const active = document.querySelector('#landing-tabs .tab.active');
  selectLandingTab(tab || (active && active.dataset.tab) || 'create');
  applyDefaultDir();
}

function selectLandingTab(tab) {
  document.querySelectorAll('#landing-tabs .tab').forEach((b) => {
    b.classList.toggle('active', b.dataset.tab === tab);
  });
  document.querySelectorAll('#landing .tab-pane').forEach((p) => { p.hidden = p.dataset.pane !== tab; });
  // 切到「打开工程」时拉取/刷新目录树；首次为空 → 自动展开并定位到默认目录
  if (tab === 'open') openTree();
}

/** 点遮罩 / 点关闭 / 按 Esc 返回编辑界面；当前没有工程时忽略。 */
function hideLanding() {
  if (!S.project) return;
  byId('landing').hidden = true;
}

async function doCreate() {
  const name = byId('new-name').value.trim() || t('landing.newName');
  const dir = byId('new-dir').value.trim();
  const preset = byId('new-preset').value;
  if (!dir) { byId('landing-err').textContent = t('err.needDir'); return; }
  try {
    const st = await call('create_project', name, dir, preset, 'ppt');
    rememberRecent(st.project);
    applyState(st);
  } catch (e) { byId('landing-err').textContent = e.message; }
}

/** 「设为默认」：把顶部那行里的目录存成默认目录，新建 / 导出 / 打开都改从它起步。 */
async function saveDefaultDir() {
  const path = byId('defdir-input').value.trim();
  if (!path) return;
  byId('landing-err').textContent = '';
  const prev = S.defaultDir;
  try {
    const r = await call('set_default_dir', path);
    S.defaultDir = r.defaultDir;
    S.defaultDirSet = true;
    byId('defdir-input').value = S.defaultDir;
    const nd = byId('new-dir');
    if (!nd.value || nd.value === prev) nd.value = S.defaultDir;
    // 目录树起点跟着新默认目录走：清掉缓存后重新定位
    BROWSE.path = S.defaultDir;
    TREE.roots = []; TREE.nodes.clear(); TREE.sel = '';
    const openTab = document.querySelector('#landing-tabs .tab[data-tab="open"]');
    if (openTab && openTab.classList.contains('active')) await openTree();
    toast(t('landing.defdirSet', { path: S.defaultDir }), 'ok');
  } catch (e) { byId('landing-err').textContent = e.message; }
}

/** 「打开此工程」入口：当前选中的目录本身是工程时出现。 */
function syncBrowseHere() {
  const here = byId('btn-browse-here');
  if (BROWSE.isProject) {
    here.hidden = false;
    here.textContent = t('landing.openHere', { name: BROWSE.projectName || BROWSE.path });
    here.onclick = () => openProject(BROWSE.path);
  } else {
    here.hidden = true;
    here.onclick = null;
  }
}

/** 打开「打开工程」标签：拉根节点，并展开定位到默认 / 上次的目录。 */
async function openTree() {
  byId('landing-err').textContent = '';
  try {
    if (!TREE.roots.length) {
      const r = await call('browse_roots');
      TREE.roots = r.roots;
      r.roots.forEach((x) => { treeNode(x.path, { name: x.name }).depth = 0; });
      if (!BROWSE.path) BROWSE.path = r.defaultDir || '';
    }
    const target = BROWSE.path || (TREE.roots[0] && TREE.roots[0].path) || '';
    if (target) await expandTo(target);
    renderTree();
  } catch (e) { byId('landing-err').textContent = e.message; }
}

/** 逐级展开到目标目录：先顺着后端给的 parent 收集祖先链，再从根往下加载展开。 */
async function expandTo(target) {
  const chain = [];
  let cur = treeKey(target);
  for (let i = 0; i < 64; i++) {
    chain.unshift(cur);
    const r = await call('browse_dir', cur);
    const node = treeNode(cur, {});
    node.isProject = r.isProject;
    node.projectName = r.projectName || node.projectName;
    if (treeKey(r.parent) === cur) break;   // 已到盘符根
    cur = treeKey(r.parent);
  }
  for (let i = 0; i < chain.length; i++) {
    const node = TREE.nodes.get(chain[i]);
    if (!node) continue;
    node.depth = i;
    if (i < chain.length - 1) { await treeLoad(node); node.expanded = true; }
  }
  const last = TREE.nodes.get(chain[chain.length - 1]);
  if (last) {
    await treeLoad(last);   // 末级也展开：直接看到它下面的工程
    last.expanded = true;
    treeSelect(last);
  }
}

/** 按节点表递归渲染整棵树。 */
function renderTree() {
  const ul = byId('browse-tree');
  ul.innerHTML = '';

  const appendNode = (container, key) => {
    const n = TREE.nodes.get(key);
    if (!n) return;
    const li = document.createElement('li');
    li.className = 'tnode';

    const row = document.createElement('div');
    row.className = 'trow' + (key === TREE.sel ? ' sel' : '') + (n.isProject ? ' is-project' : '');
    row.style.paddingLeft = (4 + n.depth * 15) + 'px';
    row.title = n.path;

    const tw = document.createElement('button');
    tw.type = 'button';
    tw.className = 'ttw' + (n.expanded ? ' open' : '')
      + (n.loaded && !n.children.length ? ' leaf' : '');
    tw.textContent = '▸';
    tw.tabIndex = -1;
    tw.addEventListener('click', (ev) => { ev.stopPropagation(); treeToggle(n); });

    const ico = document.createElement('span');
    ico.className = 'tico';
    ico.innerHTML = n.isProject ? ICON_PROJECT : ICON_FOLDER;

    const main = document.createElement('span');
    main.className = 'tmain';
    main.textContent = n.isProject ? (n.projectName || n.name) : n.name;

    const tag = document.createElement('span');
    tag.className = 'ttag';
    tag.textContent = n.isProject
      ? (n.pages ? t('landing.pages', { n: n.pages }) : t('landing.project'))
      : '';

    row.append(tw, ico, main, tag);
    row.addEventListener('click', () => {
      if (n.isProject) { openProject(n.path); return; }   // 点工程 → 直接打开（不重启服务）
      treeSelect(n);                                      // 点目录 → 选中
      if (!n.expanded) treeToggle(n);                     // 顺带展开，像资源管理器
      else renderTree();
    });
    li.appendChild(row);

    if (n.expanded && n.loaded) {
      const sub = document.createElement('ul');
      sub.className = 'tkids';
      n.children.forEach((c) => appendNode(sub, c));
      li.appendChild(sub);
    }
    container.appendChild(li);
  };

  TREE.roots.forEach((r) => appendNode(ul, treeKey(r.path)));

  // 展开链可能很长，把当前选中的那一行滚到树的中间（只动树的滚动，不动整页）
  const sel = ul.querySelector('.trow.sel');
  if (sel) {
    const a = sel.getBoundingClientRect();
    const b = ul.getBoundingClientRect();
    ul.scrollTop += (a.top - b.top) - (b.height - a.height) / 2;
  }
}

async function openProject(path) {
  try {
    const st = await call('open_project', path);
    rememberRecent(st.project);
    applyState(st);
    toast(t('landing.opened', { name: st.name || path }), 'ok');
  } catch (e) { byId('landing-err').textContent = e.message; }
}

function rememberRecent(path) {
  if (!path) return;
  let list = [];
  try { list = JSON.parse(localStorage.getItem('noedit_core.recent') || '[]'); } catch (e) { list = []; }
  list = [path, ...list.filter((p) => p !== path)].slice(0, 8);
  localStorage.setItem('noedit_core.recent', JSON.stringify(list));
  renderRecent();
}

function renderRecent() {
  const ul = byId('recent-list');
  ul.innerHTML = '';
  let list = [];
  try { list = JSON.parse(localStorage.getItem('noedit_core.recent') || '[]'); } catch (e) { list = []; }
  if (!list.length) {
    const li = document.createElement('li');
    li.className = 'none';
    li.textContent = t('landing.recentNone');
    ul.appendChild(li);
    return;
  }
  list.forEach((path) => {
    const li = document.createElement('li');
    li.textContent = path;
    li.title = path;
    li.addEventListener('click', () => openProject(path));
    ul.appendChild(li);
  });
}

// ---------------------------------------------------------------- 导出
/** 导出落点：设过默认目录 →「默认目录/工程名」；没设过 → 交回后端写工程内的 export/。
 *  算出来正好是工程目录本身时（默认目录 = 工程们的父目录）加个后缀，免得覆盖工程文件。 */
function exportDir() {
  if (!S.defaultDirSet) return '';
  const base = (S.defaultDir || '').replace(/[\\/]+$/, '');
  if (!base) return '';
  const name = (S.project || '').replace(/[\\/]+$/, '').split(/[\\/]/).pop() || S.name || 'export';
  const norm = (p) => String(p).replace(/\//g, '\\').replace(/\\+$/, '').toLowerCase();
  const dir = base + '/' + name;
  return norm(dir) === norm(S.project) ? dir + ' ' + t('export.dirSuffix') : dir;
}

async function doExport(fmt) {
  byId('export-menu').hidden = true;
  if (!S.project) return;
  toast(t('export.working', { fmt: fmt.toUpperCase() }));
  try {
    const res = await call('export', S.project, fmt, exportDir());
    if (!res || res.ok === false) {
      toast(t('export.failed', { msg: (res && res.message) || '?' }), 'err');
      return;
    }
    const rel = relFromPath(res.path);
    toast(t('export.done', { path: res.path }), 'ok');
    if (rel) {
      const a = document.createElement('a');
      a.href = S.assetBase + rel;
      a.target = '_blank';
      a.textContent = t('export.open', { rel });
      const box = byId('toasts');
      const item = document.createElement('div');
      item.className = 'toast';
      item.appendChild(a);
      box.appendChild(item);
      setTimeout(() => item.remove(), 8000);
    }
  } catch (e) { toast(t('export.failed', { msg: e.message }), 'err'); }
}

function relFromPath(abs) {
  if (!abs || !S.project) return '';
  const norm = String(abs).replace(/\\/g, '/');
  const root = String(S.project).replace(/\\/g, '/').replace(/\/+$/, '');
  if (norm.toLowerCase().startsWith(root.toLowerCase() + '/')) return norm.slice(root.length + 1);
  return '';
}

// 全部常量与函数就绪后再启动
init();
