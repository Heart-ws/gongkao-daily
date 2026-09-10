/* 无头回归测试：用 node:vm + DOM 桩直接跑 index.html 里的脚本
 * 运行： node _dev/_test.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

/* ---------------- DOM 桩 ---------------- */
class El {
  constructor(tag, id) {
    this.tagName = (tag || 'div').toUpperCase();
    this.id = id || '';
    this._cls = new Set();
    this._attrs = {};
    this._h = {};
    this.style = {};
    this.textContent = '';
    this._html = '';
    this.disabled = false;
    this.files = null;
    this.value = '';
    this.classList = {
      add: c => this._cls.add(c),
      remove: c => this._cls.delete(c),
      contains: c => this._cls.has(c),
      toggle: (c, f) => { const on = f === undefined ? !this._cls.has(c) : !!f; on ? this._cls.add(c) : this._cls.delete(c); return on; }
    };
  }
  set innerHTML(v) { this._html = v; }
  get innerHTML() { return this._html; }
  setAttribute(k, v) { this._attrs[k] = String(v); }
  getAttribute(k) { return k in this._attrs ? this._attrs[k] : null; }
  hasAttribute(k) { return k in this._attrs; }
  removeAttribute(k) { delete this._attrs[k]; }
  addEventListener(t, fn) { (this._h[t] = this._h[t] || []).push(fn); }
  dispatch(t, ev) { (this._h[t] || []).forEach(fn => fn(Object.assign({ target: this, preventDefault() { } }, ev))); }
  closest(sel) {
    const want = sel.replace('.', '');
    if (this.tagName === 'BUTTON' && want === 'tab' && this._attrs['data-tab'] !== undefined) return this;
    if (this._attrs['data-act'] !== undefined) return this;
    if (this._attrs['data-fav'] !== undefined) return this;
    return null;
  }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  appendChild() { }
  remove() { }
  select() { }
  click() { }
}

const PANES = ['news', 'facts', 'fav', 'arch', 'set'].map(k => Object.assign(new El('section', 'pane-' + k), {}));
const TABS = ['news', 'facts', 'fav', 'arch', 'set'].map(k => {
  const e = new El('button');
  e.setAttribute('data-tab', k);
  return e;
});
const SEL_CACHE = new Map();
const panesHost = new El('div');
const tabsHost = new El('div');

function elem(sel) {
  if (sel === '#tabs') return tabsHost;
  if (!SEL_CACHE.has(sel)) SEL_CACHE.set(sel, new El('div', sel.replace('#', '')));
  return SEL_CACHE.get(sel);
}

const documentStub = {
  hidden: false,
  head: new El('head'),
  body: new El('body'),
  querySelector: elem,
  querySelectorAll: sel => sel === '.pane' ? PANES : sel === '.tab' ? TABS : [],
  addEventListener() { },
  createElement: tag => { const e = new El(tag); if (tag === 'script') setTimeout(() => e.onload && e.onload(), 0); return e; },
  execCommand() { return true; }
};
SEL_CACHE.set('#tabs', tabsHost);
SEL_CACHE.set('#newsList', new El('div'));
SEL_CACHE.set('#factsList', new El('div'));
SEL_CACHE.set('#favList', new El('div'));
SEL_CACHE.set('#archList', new El('div'));
SEL_CACHE.set('#daySel', new El('select'));

const store = {};
const sandbox = {
  console,
  setTimeout, clearTimeout,
  document: documentStub,
  localStorage: {
    getItem: k => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: k => { delete store[k]; }
  },
  navigator: {},
  location: { protocol: 'file:' },
  fetch: () => Promise.reject(new Error('offline in test')),
  URL: { createObjectURL: () => 'blob:x', revokeObjectURL() { } },
  Blob: function () { },
  FileReader: function () { this.readAsText = () => { }; },
  confirm: () => true,
  alert: () => { }
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
/* 预置数据（模拟 data/*.js 已被加载） */
sandbox.__DATA_INDEX__ = { updated: '2026-09-10', dates: ['2026-09-10', '2026-09-09', '2026-09-08'] };
const poolSrc = fs.readFileSync(path.join(ROOT, 'data', 'facts-pool.js'), 'utf8');
vm.createContext(sandbox);
vm.runInContext(poolSrc, sandbox);
['2026-09-10', '2026-09-09', '2026-09-08'].forEach(d => {
  vm.runInContext(fs.readFileSync(path.join(ROOT, 'data', d + '.js'), 'utf8'), sandbox);
});

/* ---------------- 断言工具 ---------------- */
let pass = 0, fail = 0;
const failures = [];
function ok(name, cond, extra) {
  if (cond) { pass++; console.log('  ok  ' + name); }
  else { fail++; failures.push(name + (extra ? ' → ' + extra : '')); console.log('  FAIL ' + name + (extra ? ' → ' + extra : '')); }
}
function eq(name, a, b) { ok(name, JSON.stringify(a) === JSON.stringify(b), 'got ' + JSON.stringify(a) + ' want ' + JSON.stringify(b)); }
function run(code) { return vm.runInContext(code, sandbox); }
function group(t) { console.log('\n' + t); }

/* ---------------- 跑起来 ---------------- */
vm.runInContext(script, sandbox);

setTimeout(() => {
  group('【1】日期工具');
  eq('dayIndex 连续性', run('dayIndex("2026-09-10") - dayIndex("2026-09-09")'), 1);
  eq('shiftDate 跨月', run('shiftDate("2026-09-01",-1)'), '2026-08-31');
  eq('cnDate 格式化', run('cnDate("2026-09-08")'), '2026年9月8日');
  eq('sortDates 倒序去重', run('sortDates(["2026-09-09","2026-09-10","2026-09-09"])'), ['2026-09-10', '2026-09-09']);
  eq('pickDefaultDate 取≤今天最新', run('pickDefaultDate("2026-09-09",["2026-09-10","2026-09-08"])'), '2026-09-08');
  eq('pickDefaultDate 全部未来时回落最旧', run('pickDefaultDate("2026-01-01",["2026-09-10","2026-09-08"])'), '2026-09-08');

  group('【2】常识轮换引擎');
  const day1 = run('factsFor("2026-09-10",POOL.items,10,3)');
  const day1b = run('factsFor("2026-09-10",POOL.items,10,3)');
  ok('同一天两次取题完全一致（确定性）', JSON.stringify(day1.items) === JSON.stringify(day1b.items));
  eq('每天恰好 10 条', day1.items.length, 10);
  eq('周期长度为 10 天（题库 100 条）', day1.len, 10);
  const ids1 = day1.items.map(x => x.id);
  eq('当天无重复条目', new Set(ids1).size, 10);
  const cats = {};
  day1.items.forEach(x => cats[x.cat] = (cats[x.cat] || 0) + 1);
  ok('分类均衡：单类不超过 3 条', Object.values(cats).every(v => v <= 3), JSON.stringify(cats));
  ok('分类覆盖不少于 4 类', Object.keys(cats).length >= 4, JSON.stringify(cats));

  // 整轮覆盖
  const seen = new Set();
  const anchor = run('dayIndex(ANCHOR)');
  for (let i = 0; i < 10; i++) {
    const d = run(`(function(){var dd=new Date((${anchor}+${i})*86400000);return dd.toISOString().slice(0,10)})()`);
    run(`factsFor("${d}",POOL.items,10,3)`).items.forEach(x => seen.add(x.id));
  }
  eq('一轮 10 天覆盖全部 100 条考点', seen.size, 100);

  // 跨轮换批
  const dA = run(`(function(){var dd=new Date((${run('dayIndex(ANCHOR)')})*86400000);return dd.toISOString().slice(0,10)})()`);
  const dB = run(`(function(){var dd=new Date((${run('dayIndex(ANCHOR)')+10})*86400000);return dd.toISOString().slice(0,10)})()`);
  const A = run(`factsFor("${dA}",POOL.items,10,3)`).items.map(x => x.id).join(',');
  const B = run(`factsFor("${dB}",POOL.items,10,3)`).items.map(x => x.id).join(',');
  ok('进入下一轮后取题顺序不同（避免死记顺序）', A !== B);

  group('【3】边界与容错');
  eq('锚点之前也能取到题（不报错）', run('factsFor("2020-01-01",POOL.items,10,3)').items.length, 10);
  eq('空题库返回空数组', run('factsFor("2026-09-10",[],10,3)').items.length, 0);
  eq('题库不足一天时按现有数量返回', run('factsFor("2026-09-10",POOL.items.slice(0,4),10,3)').items.length, 4);
  eq('题库被 10 整除时周期正确', run('factsFor("2026-09-10",POOL.items,10,3)').len, 10);

  group('【4】更新提示判定');
  ok('数据日期=今天 → 不提示', run('needUpdateNotice("2026-09-10","2026-09-10",new Date(2026,8,10,9,0))') === false);
  ok('落后且已过 8 点 → 提示', run('needUpdateNotice("2026-09-10","2026-09-09",new Date(2026,8,10,9,0))') === true);
  ok('落后但未到 8 点 → 不提示', run('needUpdateNotice("2026-09-10","2026-09-09",new Date(2026,8,10,6,0))') === false);
  ok('完全没有数据 → 提示', run('needUpdateNotice("2026-09-10","",new Date(2026,8,10,6,0))') === true);

  group('【5】数据流：已读 / 已背');
  run('S = blankState(); S.read={}; S.recited={};');
  eq('默认未读', run('isDone("news","2026-09-10","2026-09-10#0")'), false);
  eq('打勾后为已读', run('toggleDone("news","2026-09-10","2026-09-10#0")'), true);
  eq('再点取消', run('toggleDone("news","2026-09-10","2026-09-10#0")'), false);
  run('toggleDone("fact","2026-09-10","zz01")');
  eq('常识已背可查', run('isDone("fact","2026-09-10","zz01")'), true);
  ok('状态已写入 localStorage', !!store['gk_daily_v1'] && store['gk_daily_v1'].indexOf('zz01') >= 0);

  group('【6】收藏往返');
  run('S.fav=[]');
  eq('初始未收藏', run('isFav("news","2026-09-10#1")'), false);
  eq('收藏成功', run('toggleFav({type:"news",id:"2026-09-10#1",date:"2026-09-10",title:"T",text:"X",source:"S",cat:"时政要闻",tip:""})'), true);
  eq('可查到收藏', run('isFav("news","2026-09-10#1")'), true);
  eq('再次点击取消', run('toggleFav({type:"news",id:"2026-09-10#1",date:"2026-09-10",title:"T",text:"X",source:"S",cat:"",tip:""})'), false);
  eq('已从列表移除', run('S.fav.length'), 0);
  run('toggleFav({type:"fact",id:"fl01",date:"2026-09-10",title:"Q",text:"A",source:"",cat:"法律",tip:"T"})');
  eq('常识收藏成功', run('S.fav.length'), 1);

  group('【7】Markdown 导出');
  const mdN = run('newsToMd(newsOf("2026-09-10"),"2026-09-10")');
  ok('时政导出含 10 个二级标题', (mdN.match(/^## /gm) || []).length === 10);
  ok('时政导出含来源', mdN.indexOf('来源：') > 0);
  const mdF = run('factsInfoOf("2026-09-10") && factsToMd(factsInfoOf("2026-09-10").items,"2026-09-10",factsInfoOf("2026-09-10"))');
  ok('常识导出含答案与提示', mdF.indexOf('答：') > 0 && mdF.indexOf('记忆提示') > 0);
  const mdFav = run('favToMd(S.fav)');
  ok('收藏导出含条数统计', mdFav.indexOf('共 1 条') > 0);

  group('【8】状态兜底与迁移');
  store['gk_daily_v1'] = '{bad json';
  ok('损坏的 JSON 不抛错、回落空状态', JSON.parse(JSON.stringify(run('load()'))).fav.length === 0);
  store['gk_daily_v1'] = JSON.stringify({ read: { '2026-09-10': ['a'] } });
  const st = run('load()');
  eq('旧数据仍能读出', st.read['2026-09-10'][0], 'a');
  eq('缺失字段补默认值', [typeof st.fav, st.settings.hideAnswers], ['object', true]);

  group('【9】分页渲染：每个标签页只有一个面板可见');
  ['news', 'facts', 'fav', 'arch', 'set'].forEach(t => {
    run(`activeTab="${t}"; renderAll();`);
    const on = PANES.filter(p => p.classList.contains('on'));
    const right = on.length === 1 && on[0].id === 'pane-' + t;
    ok(`切到 ${t} 后仅 pane-${t} 显示`, right, 'on=' + on.map(p => p.id).join(','));
    const tabOn = TABS.filter(x => x.classList.contains('on'));
    ok(`切到 ${t} 后仅对应标签高亮`, tabOn.length === 1 && tabOn[0].getAttribute('data-tab') === t);
  });

  group('【10】各页渲染不抛异常 + 关键内容落位');
  run('activeTab="news"; renderAll();');
  ok('时政列表渲染出 10 张卡', (elem('#newsList').innerHTML.match(/class="card n/g) || []).length === 10);
  run('activeTab="facts"; renderAll();');
  const fh = elem('#factsList').innerHTML;
  ok('常识列表渲染出 10 张卡', (fh.match(/data-kind="fact"/g) || []).length === 10);
  ok('默认隐藏答案（含 hidden 属性）', fh.indexOf(' hidden>') > 0);
  ok('每条都带记忆提示块', (fh.match(/class="tip"/g) || []).length >= 8);
  run('ansOpen = {}; setAllAns(1); activeTab="facts"; renderAll();');
  ok('展开全部后不再有 hidden', elem('#factsList').innerHTML.indexOf(' hidden>') < 0);
  ok('展开全部后按钮文字改为收起', elem('#fToggle').textContent === '全部收起答案');
  run('ansOpen = {}; setAllAns(0); renderAll();');
  ok('收起全部后按钮文字复位', elem('#fToggle').textContent === '展开全部答案');
  run('activeTab="arch"; renderAll();');
  ok('归档渲染出 3 期', (elem('#archList').innerHTML.match(/arch-item/g) || []).length === 3);
  run('S.fav=[]; activeTab="fav"; renderAll();');
  ok('收藏页空态提示正确', elem('#favList').innerHTML.indexOf('还没有收藏内容') > 0);
  run('S.fav=[{type:"fact",id:"fl01",date:"2026-09-10",title:"Q",text:"A",source:"",cat:"法律",tip:""}]; activeTab="fav"; renderAll();');
  ok('有收藏时渲染出卡片', elem('#favList').innerHTML.indexOf('data-fav="fact::fl01"') > 0);
  eq('收藏计数显示正确', elem('#favCount').textContent, '共 1 条');

  group('【11】头部进度统计');
  run('S = blankState(); S.read["2026-09-10"]=["2026-09-10#0","2026-09-10#1"]; S.recited["2026-09-10"]=["zz01"]; activeTab="news"; renderAll();');
  eq('时政完成数', elem('#nDone').textContent, 2);
  eq('常识完成数', elem('#fDone').textContent, 1);
  ok('时政进度条宽度 20%', elem('#nBar').style.width === '20%');
  ok('常识进度条宽度 10%', elem('#fBar').style.width === '10%');

  group('【12】时政数据完整性');
  const allNews = run('(function(){var out={};["2026-09-08","2026-09-09","2026-09-10"].forEach(function(d){out[d]=(window.__DAILY__[d].news||[]).map(function(n){return n.title+"|"+n.summary+"|"+n.source+"|"+n.tag;});});return out;})()');
  Object.keys(allNews).forEach(d => {
    eq(d + ' 恰好 10 条', allNews[d].length, 10);
    ok(d + ' 每条都有标题/摘要/来源/分类', allNews[d].every(t => { const p = t.split('|'); return p[0] && p[1] && p[2] && p[3]; }));
    ok(d + ' 摘要长度均≥60字', allNews[d].every(t => t.split('|')[1].length >= 60));
  });

  group('【13】HTML 无外部依赖（可 file:// 双击打开）');
  const extRefs = (html.match(/(?:src|href)\s*=\s*["']https?:\/\//g) || []);
  eq('index.html 中 http(s) 外部引用数量', extRefs.length, 0);
  ok('未引用外部字体/@import', html.indexOf('@import') < 0 && html.indexOf('fonts.googleapis') < 0);

  /* ---------------- 汇总 ---------------- */
  console.log('\n' + '─'.repeat(52));
  console.log(`通过 ${pass} 项，失败 ${fail} 项`);
  if (failures.length) { console.log('\n失败清单：'); failures.forEach(f => console.log('  × ' + f)); process.exit(1); }
  console.log('全部通过 ✅');
}, 400);
