/* Legacy Real front-end. No framework, no build step: served as-is by app.py.
   Everything from the server (scraped data!) is inserted as text, never as HTML, and only http(s) links become links. */
'use strict';

// ---------------------------------------------------------------------------------------------- helpers
const ICONS = {
  home: '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
  research: '<circle cx="10" cy="7" r="4"/><path d="M10.3 15H7a4 4 0 0 0-4 4v2"/><circle cx="17" cy="17" r="3"/><path d="m21 21-1.9-1.9"/>',
  chat: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  audit: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="m9 15 2 2 4-4"/>',
  activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  reports: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/>',
  settings: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
  more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
  star: '<path d="m12 2 3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z"/>',
  phone: '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.8 19.8 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.12 4.18 2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z"/>',
  mail: '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 6L2 7"/>',
  globe: '<circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
  trend: '<path d="m22 7-8.5 8.5-5-5L2 17"/><path d="M16 7h6v6"/>',
  pin: '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z"/><circle cx="12" cy="10" r="3"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
  key: '<circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6M15.5 7.5l3 3L22 7l-3-3"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  zap: '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
  send: '<path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
  back: '<path d="M19 12H5M12 19l-7-7 7-7"/>',
  flame: '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.07-2.14-.22-4.05 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.15.43-2.29 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>',
  building: '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M9 22v-4h6v4M8 6h.01M16 6h.01M12 6h.01M12 10h.01M12 14h.01M16 10h.01M16 14h.01M8 10h.01M8 14h.01"/>',
  alert: '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><path d="M12 9v4M12 17h.01"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5L5 21"/>',
  plug: '<path d="M12 22v-5M9 8V2M15 8V2M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8z"/>',
};
function icon(name) {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('class', 'i'); s.setAttribute('aria-hidden', 'true');
  s.innerHTML = ICONS[name] || ''; return s;                     // icon paths are our own constants, not data
}
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.className = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid instanceof Node ? kid : String(kid));
  return el;
}
const safeUrl = u => /^https?:\/\//i.test(u || '') ? u : null;
const isEmail = e => /^[^\s@<>"']+@[^\s@<>"']+\.[a-z]{2,}$/i.test(e || '');
const tier = s => ((s || '').split(':')[0] || 'UNKNOWN').trim();
const esc = encodeURIComponent;

async function api(path, body) {
  const r = await fetch(path, body !== undefined ? {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)} : {});
  if (r.status === 401) { state.me = null; renderAuth(); throw new Error('Please sign in'); }
  const data = (r.headers.get('Content-Type') || '').includes('json') ? await r.json() : await r.text();
  if (!r.ok) throw new Error(data.error || 'Something went wrong');
  return data;
}
function toast(msg, bad) {
  const t = h('div', {class: 'toast' + (bad ? ' bad' : '')}, msg);
  document.getElementById('toasts').append(t); setTimeout(() => t.remove(), 4200);
}
function field(label, input, help) { return h('div', {class: 'field'}, h('label', {}, label), input, help ? h('div', {class: 'help'}, help) : null); }
function input(name, attrs = {}) { return h('input', {name, ...attrs}); }
function empty(ic, title, text, action) {
  return h('div', {class: 'empty'}, h('div', {class: 'icon-box'}, icon(ic)), h('h3', {}, title), h('p', {}, text),
    action ? h('div', {style: 'margin-top:14px'}, action) : null);
}
function skeleton(n = 3) { return h('div', {class: 'stack'}, ...Array.from({length: n}, () => h('div', {class: 'skeleton'}))); }
function formData(form) {
  const d = {};
  for (const el of form.querySelectorAll('input,textarea,select')) if (el.name) d[el.name] = el.type === 'checkbox' ? el.checked : el.value;
  return d;
}
function sheet(title, subtitle, body, actions) {
  const close = () => { ov.remove(); document.removeEventListener('keydown', onKey); };
  const onKey = e => { if (e.key === 'Escape') close(); };
  const ov = h('div', {class: 'overlay', onclick: e => { if (e.target === ov) close(); }},
    h('div', {class: 'sheet', role: 'dialog', 'aria-modal': 'true', 'aria-label': title},
      h('div', {class: 'sheet-head'},
        h('div', {style: 'min-width:0'}, h('h2', {}, title), subtitle ? h('div', {class: 'small muted', style: 'margin-top:4px'}, subtitle) : null),
        h('div', {class: 'row'}, actions || null, h('button', {class: 'btn ghost', 'aria-label': 'Close', onclick: close}, icon('x')))),
      h('div', {class: 'sheet-body'}, body)));
  document.addEventListener('keydown', onKey); document.body.append(ov); return close;
}

// ---------------------------------------------------------------------------------------------- app shell
const state = {me: null, running: null};
const NAV = [
  ['dashboard', 'Dashboard', 'home'], ['find', 'Find leads', 'search'], ['leads', 'Leads', 'users'],
  ['research', 'Research', 'research'], ['chat', 'Prospect chat', 'chat'], ['audit', 'Website audit', 'audit'],
  ['sent', 'Email tracking', 'mail'], ['activity', 'Activity', 'activity'], ['reports', 'Reports', 'reports'], ['settings', 'Settings', 'settings'],
];
const BOTTOM = [['dashboard', 'Home', 'home'], ['leads', 'Leads', 'users'], ['research', 'Research', 'research'], ['chat', 'Chat', 'chat'], ['more', 'More', 'more']];
let content, jobChip, jobChipTop;

function renderShell() {
  const root = document.getElementById('root'); root.innerHTML = '';
  const side = h('aside', {class: 'side'},
    h('div', {class: 'logo'}, h('img', {src: '/icon.svg', alt: ''}), 'Legacy Real'),
    h('nav', {class: 'navlist', 'aria-label': 'Main'}, NAV.map(([id, label, ic]) => h('a', {href: '#/' + id, 'data-nav': id}, icon(ic), label))),
    h('div', {class: 'side-foot'}, jobChip = h('div', {style: 'margin-bottom:10px'}),
      h('div', {class: 'who'}, h('div', {class: 'avatar'}, (state.me || '?')[0].toUpperCase()), h('div', {}, state.me || ''))));
  content = h('main', {id: 'main'});
  const top = h('div', {class: 'topbar'}, h('img', {src: '/icon.svg', alt: ''}), 'Legacy Real', jobChipTop = h('div', {class: 'job'}));
  const bottom = h('nav', {class: 'bottom', 'aria-label': 'Main'}, BOTTOM.map(([id, label, ic]) => h('a', {href: '#/' + id, 'data-nav': id}, icon(ic), label)));
  root.append(h('div', {class: 'shell'}, side, h('div', {class: 'content'}, top, content)), bottom);
  updateJobChip();
}
function setActive(id) {
  const more = !BOTTOM.some(([b]) => b === id);  // pages only in the sidebar light up "More" on the phone bar
  for (const a of document.querySelectorAll('[data-nav]')) {
    const on = a.dataset.nav === id || (more && a.dataset.nav === 'more' && a.closest('.bottom'));
    if (on) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
  }
}
function page(title, sub, actions) {
  content.innerHTML = '';
  const wrap = h('div', {class: 'page'}, h('div', {class: 'page-head'}, h('div', {}, h('h1', {}, title), sub ? h('p', {}, sub) : null), actions || null));
  content.append(wrap); window.scrollTo(0, 0); return wrap;
}
function updateJobChip() {
  const chip = () => state.running ? h('a', {href: '#/activity', class: 'pill running pulse'}, h('span', {class: 'dot'}), 'Job running') : '';
  if (jobChip) { jobChip.innerHTML = ''; jobChip.append(chip()); }
  if (jobChipTop) { jobChipTop.innerHTML = ''; jobChipTop.append(chip()); }
}

// ---------------------------------------------------------------------------------------------- router
const ROUTES = {dashboard, find, leads, research, chat, audit, sent, activity, reports, settings, more};
function route() {
  if (!state.me) return;
  const [, name = 'dashboard', ...rest] = location.hash.split('/');
  const [id, query] = (name || 'dashboard').split('?');
  const params = new URLSearchParams(query || '');
  const fn = ROUTES[id] || dashboard; setActive(ROUTES[id] ? id : 'dashboard');
  fn(rest.join('/'), params).catch(e => { if (e.message !== 'Please sign in') toast(e.message, true); });
}
window.addEventListener('hashchange', route);
const go = hash => { if (location.hash === hash) route(); else location.hash = hash; };

// ---------------------------------------------------------------------------------------------- pages
async function dashboard() {
  const p = page('Dashboard', `Welcome back, ${state.me}.`, h('a', {class: 'btn', href: '#/find'}, icon('search'), 'Find leads'));
  p.append(skeleton(2));
  const d = await api('/api/dashboard'); p.lastChild.remove();
  const missing = Object.entries(d.connected).filter(([, v]) => !v).map(([k]) => k);
  if (d.running) p.append(h('a', {class: 'banner info', href: '#/activity'}, h('span', {class: 'spin'}), 'A job is running — tap to watch it live.'));
  if (['gemini', 'apify', 'salesbrain'].some(k => missing.includes(k)))
    p.append(h('a', {class: 'banner', href: '#/settings'}, icon('plug'), 'Connect your Gemini, Apify and Sales Brain keys to unlock every feature.'));
  const apify = d.connected.apify ? await api('/api/status').then(s => s.apify).catch(() => null) : null;
  const stat = (ic, label, value, hint, meter) => h('div', {class: 'card stat'}, h('div', {class: 'label'}, icon(ic), label),
    h('div', {class: 'value'}, value), hint ? h('div', {class: 'hint'}, hint) : null,
    meter != null ? h('div', {class: 'meter'}, h('span', {style: `width:${Math.min(100, meter)}%`})) : null);
  p.append(h('div', {class: 'grid g5'},
    stat('users', 'Leads found', d.leads, 'across your recent runs'),
    stat('star', 'Excellent prospects', d.scores.EXCELLENT, `${d.scores.OKAY} okay · ${d.scores.POOR} poor`),
    stat('research', 'People researched', d.people),
    stat('chat', 'Active chats', d.chats),
    apify ? stat('zap', 'Apify credit', `$${apify.used}`, `of $${apify.limit} this month`, apify.used / apify.limit * 100)
          : stat('zap', 'Apify credit', '—', 'not connected')));
  const action = (href, ic, title, text) => h('a', {class: 'card row', href, style: 'color:inherit'}, h('div', {class: 'icon-box'}, icon(ic)),
    h('div', {}, h('h3', {}, title), h('p', {class: 'small muted'}, text)));
  p.append(h('h2', {style: 'margin:26px 0 12px'}, 'Start something'), h('div', {class: 'grid g3'},
    action('#/find', 'flame', 'Find leads in hot areas', 'Hot ZIPs → busy agents → audit → score'),
    action('#/research', 'research', 'Research a LinkedIn connection', 'Name + city → facts → your first two messages'),
    action('#/audit', 'audit', 'Audit a website', 'See what Google and AI actually read')));
  const top = h('div', {class: 'card'}, h('div', {class: 'card-head'}, h('h2', {}, 'Top prospects'), h('a', {href: '#/leads'}, 'All leads')));
  if (!d.excellent.length) top.append(h('p', {class: 'muted small'}, 'No EXCELLENT prospects yet — run a hunt.'));
  for (const x of d.excellent) top.append(h('div', {class: 'item', onclick: () => go(`#/leads?file=${esc(x.file)}&q=${esc(x.name)}`)},
    h('div', {class: 'icon-box'}, icon('star')), h('div', {class: 'grow'}, h('div', {class: 'title'}, x.name), h('div', {class: 'sub'}, x.why))));
  const recent = h('div', {class: 'card'}, h('div', {class: 'card-head'}, h('h2', {}, 'Recent activity'), h('a', {href: '#/activity'}, 'All activity')));
  if (!d.recent_jobs.length) recent.append(h('p', {class: 'muted small'}, 'Nothing run yet.'));
  for (const j of d.recent_jobs) recent.append(jobItem(j));
  p.append(h('div', {class: 'grid g2', style: 'margin-top:14px'}, top, recent));
  const sets = await api('/api/results');
  if (sets.length) {
    const rows = (await api('/api/results/' + esc(sets[0].file))).map(r => ({...r, _file: sets[0].file}));
    p.append(h('div', {class: 'card', style: 'margin-top:14px'},
      h('div', {class: 'card-head'}, h('h2', {}, `Contacts · ${sets[0].label} · ${rows.length}`),
        h('div', {class: 'row'}, h('a', {class: 'btn secondary sm', href: `/api/results/${esc(sets[0].file)}?download=1`}, icon('download'), 'CSV'),
          h('a', {href: `#/leads?file=${esc(sets[0].file)}`}, 'All leads'))),
      contactTable(rows)));
  }
}
const SOCIALS = [['Linkedin', 'LinkedIn'], ['Instagram', 'Instagram'], ['Facebook', 'Facebook'], ['Tiktok', 'TikTok'], ['Youtube', 'YouTube'], ['X', 'X']];
// big brokerage pages list every agent's email: the ones with this agent's name in them go first
function rankEmails(r) {
  const words = (r['Business Name'] || '').toLowerCase().match(/[a-z]{3,}/g) || [];
  const emails = (r['Emails'] || '').split(';').map(x => x.trim()).filter(isEmail);
  return emails.map((e, i) => [words.some(w => e.toLowerCase().split('@')[0].includes(w)) ? 0 : 1, i, e]).sort((a, b) => a[0] - b[0] || a[1] - b[1]).map(x => x[2]);
}
function contactTable(rows) {  // spreadsheet view: who, how to reach them, where they are online
  const a = (href, text) => h('a', {href, target: '_blank', rel: 'noopener noreferrer', onclick: e => e.stopPropagation()}, text);
  const cell = (...kids) => h('td', {}, ...kids);
  const body = rows.map(r => {
    const emails = rankEmails(r), more = emails.length - 2;
    const phone = r['Main Office Phone'] || '';
    const socials = SOCIALS.filter(([k]) => safeUrl(r[k]));
    const site = safeUrl(r['Website URL']);
    return h('tr', {onclick: () => leadSheet(r)},
      cell(h('span', {class: 'pill ' + tier(r['Prospect Score'])}, tier(r['Prospect Score']))),
      cell(h('b', {}, r['Business Name'] || '—'), h('div', {class: 'tiny muted'}, [r['Brokerage'], r['Address']].filter(Boolean).join(' · '))),
      cell(phone ? h('a', {href: 'tel:' + phone.replace(/[^\d+]/g, ''), onclick: e => e.stopPropagation()}, phone) : '—'),
      cell(...(emails.length ? emails.slice(0, 2).flatMap((e, i) => [i ? h('br') : null, h('a', {href: 'mailto:' + e, onclick: ev => ev.stopPropagation()}, e)]) : ['—']),
        more > 0 ? h('div', {class: 'tiny muted'}, `+${more} more (tap row)`) : null),
      cell(site ? a(site, site.replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '').slice(0, 40)) : '—'),
      cell(...(socials.length ? socials.flatMap(([k, label], i) => [i ? ' · ' : '', a(r[k], label)]) : ['—'])),
      cell(r['Sales (12 mo)'] || '—'));
  });
  return h('div', {class: 'table-wrap'}, h('table', {class: 'sheet-table'},
    h('thead', {}, h('tr', {}, ...['Score', 'Name', 'Phone', 'Email', 'Website', 'Social', 'Sales/yr'].map(t => h('th', {}, t)))),
    h('tbody', {}, ...body)));
}

function jobForm(kind, fields, button, note) {
  const form = h('form', {class: 'card', onsubmit: async e => {
    e.preventDefault(); const btn = form.querySelector('button[type=submit]'); btn.disabled = true;
    try { const job = await api('/api/jobs/' + kind, formData(form)); toast('Started — watch it live in Activity'); state.running = job.id; updateJobChip(); go('#/activity/' + job.id); }
    catch (err) { toast(err.message, true); btn.disabled = false; }
  }}, h('div', {class: 'grid g2'}, fields), h('div', {class: 'form-actions'}, h('button', {class: 'btn', type: 'submit'}, icon('zap'), button),
    note ? h('span', {class: 'small muted'}, note) : null));
  return form;
}
async function find(_, params) {
  const p = page('Find leads', 'Pick where to look. Every run audits each business and scores it as a prospect.');
  const modes = [['hunt', 'Hot areas'], ['zips', 'ZIP codes'], ['zillow', 'Zillow city']];
  let mode = params.get('mode') || 'hunt';
  const seg = h('div', {class: 'seg', role: 'group'}), holder = h('div', {style: 'margin-top:16px'});
  const draw = () => {
    seg.innerHTML = ''; holder.innerHTML = '';
    for (const [id, label] of modes) seg.append(h('button', {type: 'button', 'aria-pressed': String(id === mode), onclick: () => { mode = id; draw(); }}, label));
    if (mode === 'hunt') holder.append(jobForm('hunt', [
      field('Hot areas to search', input('top', {type: 'number', value: 3, min: 1, max: 50}), 'From Realtor.com\'s 2026 Hottest ZIP list, best first'),
      field('Minimum median home price', input('min_price', {type: 'number', value: 400000, step: 50000}), 'Higher prices = agents who can afford you'),
      field('Minimum sales (last 12 months)', input('min_sales', {type: 'number', value: 20})),
      field('Minimum reviews', input('min_reviews', {type: 'number', value: 20})),
      field('Max agents per area', input('per_city', {type: 'number', value: 15})),
      h('label', {class: 'checkbox', style: 'align-self:end'}, input('teams', {type: 'checkbox'}), 'Team leaders only'),
    ], 'Start hunt', 'Uses Apify (~$0.003 per agent) + Gemini'), hotZips());
    if (mode === 'zips') holder.append(jobForm('zips', [
      field('ZIP codes', input('zips', {placeholder: '01960 07042', required: true}), 'Up to 10, separated by spaces or commas'),
    ], 'Search Google Maps', 'Top 20 agencies per ZIP · chains skipped'));
    if (mode === 'zillow') holder.append(jobForm('zillow', [
      field('City', input('city', {placeholder: 'Peabody, MA', required: true}), 'City, two-letter state'),
      field('Minimum reviews', input('min_reviews', {type: 'number', value: 10})),
      field('Minimum sales (last 12 months)', input('min_sales', {type: 'number', value: 10})),
      field('Max agents', input('max', {type: 'number', value: 25})),
    ], 'Pull agents', 'Uses Apify (~$0.003 per agent)'));
  };
  p.append(seg, holder); draw();
}
function hotZips() {
  const card = h('div', {class: 'card'}, h('div', {class: 'card-head'}, h('h2', {}, 'Hot ZIP list · Realtor.com 2026'), h('span', {class: 'small muted'}, 'Released Aug 10, 2026')));
  const list = h('div', {class: 'list'}); card.append(list);
  api('/api/hot-zips').then(z => z.slice(0, 20).forEach((r, i) => list.append(h('div', {class: 'item', style: 'cursor:default'},
    h('div', {class: 'icon-box'}, String(i + 1)), h('div', {class: 'grow'}, h('div', {class: 'title'}, `${r.city}, ${r.state}`), h('div', {class: 'sub'}, `ZIP ${r.zip}`)),
    h('span', {class: 'pill'}, '$' + r.price.toLocaleString())))));
  return card;
}

async function research(_, params) {
  const p = page('Research a person', 'For a LinkedIn connection: we find them on Google, Maps and Zillow, check every website, and write your first two messages with your Sales Brain.');
  p.append(jobForm('person', [
    field('Full name *', input('name', {required: true, placeholder: 'Veores Dean', value: params.get('name') || ''})),
    field('City *', input('city', {required: true, placeholder: 'St. Louis, MO', value: params.get('city') || ''}), 'City, two-letter state'),
    field('Brokerage', input('brokerage', {value: params.get('brokerage') || ''}), 'Optional — we find it if you leave it empty'),
    field('Websites', input('sites', {placeholder: 'site.com other.com', value: params.get('sites') || ''}), 'Optional, space separated'),
    field('Phone (from LinkedIn)', input('phone')), field('Address (from LinkedIn)', input('address')),
    h('div', {class: 'field', style: 'grid-column:1/-1'}, h('label', {}, 'What their LinkedIn says'),
      h('textarea', {name: 'notes', placeholder: 'Headline, brand, numbers, specialties…'})),
  ], 'Research', 'About 1–3 minutes'));
  const people = await api('/api/people');
  const card = h('div', {class: 'card'}, h('h2', {style: 'margin-bottom:8px'}, 'Researched'));
  if (!people.length) card.append(h('p', {class: 'small muted'}, 'Nobody yet.'));
  for (const x of people) card.append(h('div', {class: 'item', onclick: () => go('#/chat/' + x.slug)},
    h('div', {class: 'avatar'}, x.name[0]), h('div', {class: 'grow'}, h('div', {class: 'title'}, x.name), h('div', {class: 'sub'}, x.turns ? `${x.turns} messages · ${x.last}` : 'Chat not started')),
    h('span', {class: 'btn secondary sm'}, x.turns ? 'Open chat' : 'Start chat')));
  p.append(card);
}

async function audit() {
  const p = page('Website audit', 'Grades a page the way Google and AI crawlers read it. Every run is saved with a date — your before/after proof.');
  p.append(jobForm('audit', [
    field('Website *', input('url', {required: true, placeholder: 'https://…'})),
    field('Business name', input('name'), 'Adds AI review, AI visibility and a pitch'),
    field('Google Maps address', input('address'), 'For the address-match check'),
    field('Google Maps phone', input('phone')),
  ], 'Run audit'));
  const files = (await api('/api/reports')).filter(f => /^[a-z0-9]/.test(f));  // audits are named after the site; people reports start with a Capital
  const card = h('div', {class: 'card'}, h('h2', {style: 'margin-bottom:8px'}, 'Past audits'));
  if (!files.length) card.append(h('p', {class: 'small muted'}, 'No audits yet.'));
  for (const f of files) card.append(reportItem(f));
  p.append(card);
}

async function leads(_, params) {
  const sets = await api('/api/results');
  const p = page('Leads', 'Best prospects first. Tap a lead for everything we found.');
  if (!sets.length) { p.append(h('div', {class: 'card'}, empty('users', 'No leads yet', 'Run a hunt, a ZIP search or a Zillow pull to fill this page.', h('a', {class: 'btn', href: '#/find'}, 'Find leads')))); return; }
  const pick = h('select', {'aria-label': 'Result set'}, sets.map(s => h('option', {value: s.file}, `${s.label} · ${s.date} · ${s.rows} leads`)));
  pick.value = params.get('file') || sets[0].file;
  const dl = h('a', {class: 'btn secondary'}, icon('download'), 'CSV');
  const q = h('input', {type: 'search', placeholder: 'Search name, brokerage, email…', value: params.get('q') || ''});
  let filter = 'ALL', view = localStorage.getItem('leadsView') || 'cards'; const chips = h('div', {class: 'chips'}); const grid = h('div', {class: 'leads'}); let rows = [];
  const views = h('div', {class: 'seg', role: 'group'});
  p.append(h('div', {class: 'card', style: 'margin-bottom:16px'}, h('div', {class: 'row wrap'}, h('div', {style: 'flex:1;min-width:220px'}, pick), views, dl),
    h('div', {class: 'row wrap', style: 'margin-top:12px'}, h('div', {class: 'search', style: 'flex:1;min-width:220px'}, icon('search'), q), chips)), grid);
  const draw = () => {
    const counts = {ALL: rows.length}; rows.forEach(r => counts[tier(r['Prospect Score'])] = (counts[tier(r['Prospect Score'])] || 0) + 1);
    chips.innerHTML = '';
    for (const t of ['ALL', 'EXCELLENT', 'OKAY', 'POOR']) if (counts[t] || t === 'ALL')
      chips.append(h('button', {class: 'chip', 'aria-pressed': String(filter === t), onclick: () => { filter = t; draw(); }}, `${t === 'ALL' ? 'All' : t[0] + t.slice(1).toLowerCase()} ${counts[t] || 0}`));
    grid.innerHTML = ''; const term = q.value.toLowerCase();
    const shown = rows.map((r, i) => [r, i]).filter(([r]) => (filter === 'ALL' || tier(r['Prospect Score']) === filter) &&
      (!term || Object.values(r).join(' ').toLowerCase().includes(term)));
    views.innerHTML = '';
    for (const [id, label] of [['cards', 'Cards'], ['table', 'Table']]) views.append(h('button', {type: 'button', 'aria-pressed': String(view === id),
      onclick: () => { view = id; try { localStorage.setItem('leadsView', id); } catch {} draw(); }}, label));
    grid.className = view === 'table' ? '' : 'leads';
    if (!shown.length) grid.append(h('div', {class: 'card'}, empty('search', 'Nothing matches', 'Try another filter or search.')));
    else if (view === 'table') grid.append(h('div', {class: 'card'}, contactTable(shown.map(([r]) => r))));
    else for (const [r, i] of shown) grid.append(leadCard(r, () => leadSheet(r)));
    if (params.get('q') && shown.length === 1) { leadSheet(shown[0][0]); params.delete('q'); }
  };
  const load = async () => {
    grid.innerHTML = ''; grid.append(skeleton(3)); dl.href = `/api/results/${esc(pick.value)}?download=1`;
    rows = (await api('/api/results/' + esc(pick.value))).map(r => ({...r, _file: pick.value})); draw();
  };
  pick.onchange = load; q.oninput = draw; await load();
}
function leadCard(r, open) {
  const t = tier(r['Prospect Score']); const why = (r['Prospect Score'] || '').split(':').slice(1).join(':').trim();
  const fact = (ic, text) => text ? h('span', {}, icon(ic), text) : null;
  return h('div', {class: 'card lead', tabindex: 0, role: 'button', onclick: open, onkeydown: e => { if (e.key === 'Enter') open(); }},
    h('div', {class: 'row between'}, h('div', {class: 'name'}, r['Business Name'] || '(no name)'), h('span', {class: 'pill ' + t}, t)),
    why ? h('div', {class: 'why'}, why) : null,
    h('div', {class: 'facts'}, fact('building', r['Brokerage']), fact('trend', r['Sales (12 mo)'] ? r['Sales (12 mo)'] + ' sales/yr' : ''),
      fact('star', r['Zillow Reviews'] ? r['Zillow Reviews'] + ' reviews' : (r['Google Rating'] ? r['Google Rating'] + '★ Google' : '')),
      fact('mail', r['Emails'] ? r['Emails'].split(';')[0] : ''), fact('alert', r['Fails'] && r['Fails'] !== '0' ? r['Fails'] + ' fails' : '')));
}
function leadSheet(r) {
  const t = tier(r['Prospect Score']);
  const link = (u, text) => safeUrl(u) ? h('a', {href: u, target: '_blank', rel: 'noopener noreferrer'}, text || u) : (u || '—');
  const kv = pairs => h('dl', {class: 'kv'}, pairs.filter(([, v]) => v && v !== '0').flatMap(([k, v]) => [h('dt', {}, k), h('dd', {}, v)]));
  const phone = r['Main Office Phone']; const emails = rankEmails(r);
  const socials = ['Instagram', 'Facebook', 'Linkedin', 'Tiktok', 'Youtube', 'X'].filter(k => safeUrl(r[k]));
  const grades = ['Schema', 'Geo Pin', 'Schema Data', 'NAP', 'H1', 'Speed', 'Other Issues'].filter(k => r[k]);
  const body = h('div', {},
    r['Prospect Score'] ? h('div', {class: 'section'}, h('h3', {}, 'Why this score'), h('div', {class: 'quote'}, r['Prospect Score'])) : null,
    h('div', {class: 'section'}, h('h3', {}, 'Contact'), kv([
      ['Phone', phone ? h('a', {href: 'tel:' + phone.replace(/[^\d+]/g, '')}, phone) : ''],
      ['Email', emails.length ? h('span', {}, ...emails.flatMap((e, i) => [i ? ', ' : '', h('a', {href: 'mailto:' + e}, e)])) : ''],
      ['Website', r['Website URL'] ? link(r['Website URL']) : ''],
      ['Social', socials.length ? h('span', {}, ...socials.flatMap((s, i) => [i ? ' · ' : '', link(r[s], s)])) : ''],
      ['Address', r['Address']]])),
    h('div', {class: 'section'}, h('h3', {}, 'Business'), kv([['Brokerage', r['Brokerage']], ['Sales (12 mo)', r['Sales (12 mo)']], ['Total sales', r['Total Sales']],
      ['Avg price', r['Avg Price']], ['Est. volume', r['Est. Volume (12 mo)']], ['Active listings', r['Active Listings']], ['Reviews', r['Zillow Reviews'] || r['Google Reviews']],
      ['Expansion', r['Expansion']], ['Team', r['Team'] ? `${r['Team']} (${r['Team Size']})` : ''], ['Pays Zillow ads', r['Zillow Premier (pays Zillow)']],
      ['Specialties', r['Zillow Specialties']], ['Languages', r['Languages']], ['Zillow', r['Zillow Profile'] ? link(r['Zillow Profile'], 'Profile') : '']])),
    grades.length ? h('div', {class: 'section'}, h('h3', {}, 'Website check'), ...grades.map(k => {
      const g = r[k]; const st = (g.match(/^(PASS|PARTIAL|FAIL|CHECK)/) || [])[1];
      return h('div', {class: 'grade'}, h('div', {class: 't'}, k), h('div', {style: 'flex:1'}, st ? h('span', {class: 'pill ' + st, style: 'margin-right:6px'}, st) : null, g.replace(/^(PASS|PARTIAL|FAIL|CHECK):\s*/, '')));
    })) : null,
    r['AI Review'] ? h('div', {class: 'section'}, h('h3', {}, 'AI review of the page source'), h('div', {class: 'quote'}, r['AI Review'])) : null,
    r['AI Visibility'] ? h('div', {class: 'section'}, h('h3', {}, 'AI visibility'), h('div', {class: 'quote'}, r['AI Visibility'])) : null,
    r['Test in ChatGPT'] ? h('div', {class: 'section'}, h('h3', {}, 'Ask these in ChatGPT yourself'), h('div', {class: 'quote'}, r['Test in ChatGPT'])) : null,
    r['Pitch'] ? h('div', {class: 'section'}, h('h3', {}, 'Suggested pitch'), h('div', {class: 'quote'}, r['Pitch']),
      h('button', {class: 'btn secondary sm', style: 'margin-top:8px', onclick: e => navigator.clipboard.writeText(r['Pitch']).then(() => { e.target.textContent = 'Copied'; })}, icon('copy'), 'Copy')) : null);
  const city = (() => { const parts = (r['Address'] || '').split(',').map(s => s.trim()); return parts.length >= 3 ? `${parts[1]}, ${parts[2].split(' ')[0]}` : (r['Address'] || ''); })();
  const researchBtn = h('a', {class: 'btn sm', href: `#/research?name=${esc(r['Business Name'] || '')}&city=${esc(city)}&brokerage=${esc(r['Brokerage'] || '')}&sites=${esc(safeUrl(r['Website URL']) || '')}`,
    onclick: () => document.querySelector('.overlay')?.remove()}, icon('research'), 'Research');
  const mailBtn = emails.length && r._file ? h('button', {class: 'btn sm', onclick: () => emailSheet({emails, lead: r['Business Name'],
    draft: async () => waitTask((await api('/api/email/draft', {file: r._file, name: r['Business Name']})).task)})}, icon('mail'), 'Write email') : null;
  sheet(r['Business Name'] || 'Lead', h('span', {class: 'pill ' + t}, t), body, h('div', {class: 'row'}, mailBtn, researchBtn));
}

let chatTimer = null;
async function chat(slug) {
  const p = page('Prospect chat', 'Paste what they reply. You get what it means and your next message, from your Sales Brain.',
    h('button', {class: 'btn', onclick: newChat}, icon('plus'), 'New chat'));
  const people = await api('/api/people');
  if (!people.length) { p.append(h('div', {class: 'card'}, empty('chat', 'No conversations yet', 'Start one from screenshots of their LinkedIn, Instagram or Facebook page — or research someone.', h('button', {class: 'btn', onclick: newChat}, icon('image'), 'New chat from screenshots')))); return; }
  const wrap = h('div', {class: 'chat' + (slug ? ' open' : '')});
  const list = h('div', {class: 'card people'}, h('h2', {style: 'margin-bottom:6px'}, 'People'));
  for (const x of people) list.append(h('div', {class: 'item', style: slug === x.slug ? 'background:var(--surface-2);border-radius:10px' : '', onclick: () => go('#/chat/' + x.slug)},
    h('div', {class: 'avatar'}, x.name[0]), h('div', {class: 'grow'}, h('div', {class: 'title'}, x.name), h('div', {class: 'sub'}, x.turns ? `${x.turns} messages` : 'Not started'))));
  const thread = h('div', {class: 'thread'}); wrap.append(list, thread); p.append(wrap);
  if (!slug) { thread.append(h('div', {class: 'card'}, empty('chat', 'Pick a person', 'Choose someone on the left to open the conversation.'))); return; }
  thread.append(skeleton(2));
  const d = await api('/api/chat/' + slug); thread.innerHTML = '';
  const header = h('div', {class: 'card row between', style: 'margin-bottom:12px'},
    h('div', {class: 'row'}, h('a', {href: '#/chat', class: 'btn ghost', 'aria-label': 'Back'}, icon('back')), h('div', {class: 'avatar'}, d.name[0]), h('h2', {}, d.name)),
    h('button', {class: 'btn secondary sm', onclick: () => sheet(d.name, 'Research & first messages', h('pre', {class: 'log'}, d.report))}, icon('reports'), 'Research'));
  const conv = h('div', {class: 'conv card'}); const mine = h('textarea', {placeholder: 'Your message (what you actually sent)'});
  if (!d.turns.length) conv.append(h('p', {class: 'small muted'}, 'Your first message is ready below — send it on LinkedIn, then tap "Log as sent".'));
  for (const t of d.turns) {
    conv.append(h('div', {class: 'bubble ' + (t.role === 'me' ? 'me' : 'them')}, h('div', {class: 'meta'}, `${t.role === 'me' ? 'You' : d.name} · ${t.at || ''}`), t.text,
      (t.images || []).length ? h('div', {class: 'thumbs', style: 'margin-top:8px'}, t.images.map(src => h('a', {class: 'thumb', href: '/api/screens/' + src, target: '_blank'}, h('img', {src: '/api/screens/' + src, alt: 'screenshot'})))) : null,
      t.note ? h('div', {class: 'tiny muted', style: 'margin-top:6px'}, 'Your note to the AI: ' + t.note) : null));
    if (t.coach && t.coach.pending) {
      conv.append(h('div', {class: 'coach row'}, h('span', {class: 'spin'}), 'Reading their reply with your Sales Brain… (30–90s)'));
      clearTimeout(chatTimer); chatTimer = setTimeout(() => { if (location.hash === '#/chat/' + slug) route(); }, 4000);
    } else if (t.coach) {
      const c = t.coach, box = h('div', {class: 'coach'});
      for (const [k, l] of [['said', 'What they said'], ['meaning', 'What it means'], ['next_goal', 'Next goal']]) if (c[k]) box.append(h('div', {class: 'k'}, l), h('div', {}, c[k]));
      if (c.reply) box.append(h('div', {class: 'k'}, 'Suggested reply'), h('div', {class: 'reply'}, c.reply));
      if (c.why) box.append(h('div', {class: 'k'}, 'Why (your Sales Brain)'), h('div', {class: 'small'}, c.why));
      if (c.watch_out) box.append(h('div', {class: 'k'}, "Don't say"), h('div', {class: 'small'}, c.watch_out));
      if ((c.principles || []).length) box.append(h('div', {class: 'k'}, 'Principles pulled'), h('div', {class: 'tiny muted'}, c.principles.join(' · ')));
      box.append(h('div', {class: 'row', style: 'margin-top:10px'},
        h('button', {class: 'btn sm', onclick: () => { mine.value = c.reply; mine.focus(); }}, 'Use this reply'),
        h('button', {class: 'btn secondary sm', onclick: e => navigator.clipboard.writeText(c.reply).then(() => { e.target.textContent = 'Copied'; })}, icon('copy'), 'Copy')));
      conv.append(box);
    }
  }
  if (!d.turns.length) mine.value = d.first_message;
  const theirs = h('textarea', {placeholder: `Paste what ${d.name} replied… (or just add a screenshot)`});
  const note = input('note', {placeholder: 'Optional: tell the AI what you want, e.g. "write a comment on this post" or "they went quiet, re-open it"'});
  const shots = imagePicker();
  const attach = h('button', {class: 'btn secondary', type: 'button', onclick: () => shots.pick.click()}, icon('image'), 'Add screenshot', shots.pick);
  const analyze = h('button', {class: 'btn', onclick: async () => {
    if (!theirs.value.trim() && !shots.files.length) return toast('Paste their reply or add a screenshot', true);
    analyze.disabled = true; analyze.replaceChildren(h('span', {class: 'spin'}), ' Reading it… (30–90s)');
    try { await api(`/api/chat/${slug}/theirs`, {text: theirs.value, note: note.value, images: await Promise.all(shots.files.map(shrink))}); route(); }
    catch (e) { toast(e.message, true); analyze.disabled = false; analyze.textContent = 'Break it down'; }
  }}, icon('zap'), 'Break it down');
  theirs.addEventListener('paste', e => shots.add([...(e.clipboardData?.files || [])]));
  const log = h('button', {class: 'btn secondary', onclick: async () => {
    if (!mine.value.trim()) return; await api(`/api/chat/${slug}/mine`, {text: mine.value}); toast('Logged'); route();
  }}, icon('send'), d.turns.length ? 'Log my message' : 'Log as sent');
  const byEmail = h('button', {class: 'btn secondary', onclick: () => emailSheet({to: d.email || '', body: mine.value, slug, lead: d.name, onSent: route})}, icon('mail'), 'Send by email');
  thread.append(header, conv, h('div', {class: 'composer'}, h('div', {class: 'card'},
    field('Their reply', theirs), shots.thumbs, h('div', {style: 'margin-top:10px'}, field('Note to the AI', note)),
    h('div', {class: 'form-actions', style: 'margin-top:10px'}, analyze, attach),
    h('div', {class: 'divider'}), field('Your message', mine), h('div', {class: 'form-actions', style: 'margin-top:10px'}, log, byEmail),
    d.email ? h('p', {class: 'tiny muted', style: 'margin-top:6px'}, 'Email: ' + d.email) : null)));
}

const sleep = ms => new Promise(r => setTimeout(r, ms));
async function waitTask(id) {  // long AI work runs on the server; poll until it's done
  for (;;) { await sleep(3000); const t = await api('/api/tasks/' + id); if (t.status === 'error') throw new Error(t.error); if (t.status === 'done') return t; }
}
async function shrink(file) {  // phone screenshots are huge: keep text readable, send ~200KB each
  const img = await createImageBitmap(file); const k = Math.min(1, 1200 / img.width, 4000 / img.height);
  const c = h('canvas', {width: Math.round(img.width * k), height: Math.round(img.height * k)});
  c.getContext('2d').drawImage(img, 0, 0, c.width, c.height); return c.toDataURL('image/jpeg', 0.82);
}
function imagePicker() {  // {files, thumbs, pick (hidden input), add(list), clear()}
  const files = []; const thumbs = h('div', {class: 'thumbs'});
  const pick = h('input', {type: 'file', accept: 'image/*', multiple: true, style: 'display:none', onchange: () => { add([...pick.files]); pick.value = ''; }});
  const draw = () => { thumbs.replaceChildren(...files.map((f, i) => h('div', {class: 'thumb'}, h('img', {src: URL.createObjectURL(f), alt: ''}),
    h('button', {type: 'button', 'aria-label': 'Remove', onclick: () => { files.splice(i, 1); draw(); }}, icon('x'))))); };
  const add = list => { for (const f of list) if (f.type.startsWith('image/') && files.length < 8) files.push(f); draw(); };
  return {files, thumbs, pick, add, clear: () => { files.length = 0; draw(); }};
}
function newChat() {
  const {files, thumbs, pick: pickFiles, add} = imagePicker();
  const platform = h('select', {name: 'platform'}, ['LinkedIn', 'Instagram', 'Facebook', 'Other'].map(v => h('option', {value: v}, v)));
  const status = h('div', {class: 'small', style: 'margin-top:10px'});
  const form = h('form', {class: 'stack', onsubmit: async e => {
    e.preventDefault(); if (!files.length) return toast('Add at least one screenshot', true);
    const btn = form.querySelector('button[type=submit]'); btn.disabled = true;
    try {
      status.replaceChildren(h('span', {class: 'spin'}), ' Uploading…');
      const images = await Promise.all(files.map(shrink));
      const {task} = await api('/api/chat/new', {...formData(form), images});
      status.replaceChildren(h('span', {class: 'spin'}), ' Reading their page, asking your Sales Brain, writing your opener… (1–3 min)');
      const t = await waitTask(task); close(); toast('Chat ready'); go('#/chat/' + t.slug);
    } catch (err) { status.textContent = ''; toast(err.message, true); btn.disabled = false; }
  }},
    h('div', {class: 'drop', onclick: () => pickFiles.click(), ondragover: e => e.preventDefault(), ondrop: e => { e.preventDefault(); add([...e.dataTransfer.files]); }},
      icon('image'), h('div', {}, h('b', {}, 'Add screenshots of their page'), h('div', {class: 'tiny muted'}, 'Profile, about, posts — up to 8. Tap to pick, drag in, or paste (Ctrl+V).')), pickFiles),
    thumbs,
    h('div', {class: 'grid g2'}, field('Where', platform), field('Name', input('name', {placeholder: 'We read it from the page'})),
      field('Their email', input('email', {type: 'email', placeholder: 'Optional — if you have it'})), field('Your notes', input('notes', {placeholder: 'Optional'}))),
    h('div', {class: 'form-actions'}, h('button', {class: 'btn', type: 'submit'}, icon('zap'), 'Analyze & write opener')), status);
  const onPaste = e => add([...(e.clipboardData?.files || [])]);
  document.addEventListener('paste', onPaste);
  const close0 = sheet('New chat from screenshots', 'The AI reads their page, your Sales Brain picks the principles, then it writes your first message.', form);
  const close = () => { document.removeEventListener('paste', onPaste); close0(); };
  new MutationObserver((_, obs) => { if (!document.body.contains(form)) { document.removeEventListener('paste', onPaste); obs.disconnect(); } }).observe(document.body, {childList: true});
}
function principlesBox(d) {
  const box = h('div', {class: 'coach', style: 'margin-top:12px'});
  if (!d.brain) return box.append(h('div', {class: 'k'}, 'Sales Brain'), h('div', {class: 'small'}, 'Not reached — this draft was written WITHOUT your principles. Check Settings → Sales Brain.')), box;
  box.append(h('div', {class: 'k'}, 'Sales Brain principles used'));
  for (const u of d.principles_used || []) box.append(h('div', {class: 'small', style: 'margin-top:6px'}, h('b', {}, u.principle || ''), u.how ? ' — ' + u.how : ''));
  if (!(d.principles_used || []).length) box.append(h('div', {class: 'tiny muted'}, 'Pulled: ' + (d.principles || []).join(' · ')));
  return box;
}
function emailSheet({to = '', subject = '', body = '', slug = '', lead = '', emails = [], draft, onSent}) {
  const toIn = emails.length > 1 ? h('select', {}, emails.map(e => h('option', {value: e}, e))) : input('to', {type: 'email', value: to || emails[0] || ''});
  const subj = input('subject', {value: subject, placeholder: 'Subject'}); const text = h('textarea', {rows: 12}, body);
  const extra = h('div'); const status = h('div', {class: 'small', style: 'margin-top:8px'});
  const send = h('button', {class: 'btn', onclick: async () => {
    if (!confirm(`Send this email to ${toIn.value}?`)) return; send.disabled = true;
    try { await api('/api/email/send', {to: toIn.value.trim(), subject: subj.value.trim(), body: text.value, slug, lead}); toast('Sent ✓'); close(); onSent && onSent(); }
    catch (e) { toast(e.message, true); send.disabled = false; }
  }}, icon('send'), 'Send');
  const close = sheet(lead ? `Email ${lead}` : 'Send email', 'Goes from the email you connected in Settings.',
    h('div', {class: 'stack'}, field('To', toIn), field('Subject', subj), field('Message', text), status, extra,
      h('div', {class: 'form-actions'}, send, h('a', {class: 'small', href: '#/settings', onclick: () => close()}, 'Email settings'))));
  if (draft) {
    send.disabled = true; text.disabled = subj.disabled = true;
    status.replaceChildren(h('span', {class: 'spin'}), ' Your Sales Brain + AI are writing it from everything we found… (1–2 min)');
    draft().then(d => { subj.value = d.subject || ''; text.value = d.message || ''; extra.append(principlesBox(d)); status.textContent = ''; })
      .catch(e => { status.textContent = 'Draft failed: ' + e.message; })
      .finally(() => { send.disabled = text.disabled = subj.disabled = false; });
  }
}

function jobItem(j) {
  const label = {hunt: 'Hunt', zips: 'ZIP search', person: 'Research', audit: 'Audit', zillow: 'Zillow'}[j.type] || j.type;
  const detail = Object.entries(j.params || {}).map(([k, v]) => `${k} ${v}`).join(' · ');
  return h('div', {class: 'item', onclick: () => go('#/activity/' + j.id)},
    h('div', {class: 'icon-box'}, icon({hunt: 'flame', zips: 'pin', person: 'research', audit: 'audit', zillow: 'building'}[j.type] || 'activity')),
    h('div', {class: 'grow'}, h('div', {class: 'title'}, `${label} · ${j.started}`), h('div', {class: 'sub'}, detail)),
    h('span', {class: 'pill ' + j.status}, j.status));
}
let logTimer = null;
async function activity(openId) {
  const p = page('Activity', 'Everything you ran. One job at a time; logs update live.');
  const card = h('div', {class: 'card'}); p.append(card);
  const jobs = await api('/api/jobs');
  if (!jobs.length) card.append(empty('activity', 'Nothing yet', 'Jobs you start show up here with a live log.'));
  for (const j of jobs) card.append(jobItem(j));
  if (openId) openJob(openId);
}
function openJob(id) {
  const pre = h('pre', {class: 'log'}, 'Loading…'); const actions = h('div', {class: 'row'});
  const close = sheet('Job log', id, h('div', {}, pre, h('div', {style: 'margin-top:14px'}, actions)));
  const tick = async () => {
    if (!document.body.contains(pre)) { clearInterval(logTimer); return; }
    const j = await api('/api/jobs/' + id); const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 30;
    pre.textContent = j.log || '(starting…)'; if (atBottom) pre.scrollTop = pre.scrollHeight;
    if (j.status !== 'running') {
      clearInterval(logTimer); actions.innerHTML = '';
      actions.append(h('span', {class: 'pill ' + j.status}, j.status));
      if (j.results) actions.append(h('a', {class: 'btn sm', href: `#/leads?file=${esc(j.results)}`, onclick: close}, 'Open leads'));
      if (j.type === 'person') actions.append(h('a', {class: 'btn sm', href: '#/chat', onclick: close}, 'Open chat'));
      if (j.type === 'audit') actions.append(h('a', {class: 'btn secondary sm', href: '#/reports', onclick: close}, 'Reports'));
    } else if (!actions.firstChild) actions.append(h('span', {class: 'pill running pulse'}, h('span', {class: 'dot'}), 'running'),
      h('button', {class: 'btn danger sm', onclick: async e => {
        if (!confirm('Stop this job? Leads found so far are kept if the sheet was already saved.')) return;
        e.currentTarget.disabled = true; try { await api(`/api/jobs/${id}/stop`, {}); toast('Stopping…'); } catch (err) { toast(err.message, true); }
      }}, 'Stop job'));
  };
  clearInterval(logTimer); tick(); logTimer = setInterval(tick, 3000);
}

function reportItem(f) {
  return h('div', {class: 'item', onclick: async () => sheet(f.replace(/\.txt$/, ''), null, h('pre', {class: 'log'}, await api('/api/reports/' + esc(f))))},
    h('div', {class: 'icon-box'}, icon('reports')), h('div', {class: 'grow'}, h('div', {class: 'title'}, f.replace(/-\d{4}-\d{2}-\d{2}-\d{4}\.txt$/, '').replace(/-/g, ' ')),
      h('div', {class: 'sub'}, (f.match(/(\d{4}-\d{2}-\d{2})-(\d{2})(\d{2})/) || []).slice(1).join(' ').replace(/ (\d{2}) (\d{2})$/, ' $1:$2'))));
}
async function reports() {
  const p = page('Reports', 'Research on people and website audits, dated.');
  const files = await api('/api/reports'); const q = h('input', {type: 'search', placeholder: 'Search reports…'}); const list = h('div', {class: 'list'});
  p.append(h('div', {class: 'card'}, h('div', {class: 'search', style: 'margin-bottom:10px'}, icon('search'), q), list));
  const draw = () => { list.innerHTML = ''; const shown = files.filter(f => f.toLowerCase().includes(q.value.toLowerCase()));
    if (!shown.length) list.append(empty('reports', 'No reports', 'Research a person or audit a website.')); shown.forEach(f => list.append(reportItem(f))); };
  q.oninput = draw; draw();
}

async function settings(_, params) {
  if (params && params.get('gmail')) { toast(params.get('gmail') === 'ok' ? 'Gmail connected ✓' : 'Gmail connection failed — try Connect again', params.get('gmail') !== 'ok'); history.replaceState(null, '', '#/settings'); }
  const p = page('Settings', 'Connect the services the app uses. Keys are stored only on your server.');
  const [items, ai] = await Promise.all([api('/api/settings'), api('/api/ai')]);
  p.append(h('h2', {style: 'margin:4px 0 12px'}, 'AI engine'), aiEngine(ai), h('h2', {style: 'margin:28px 0 12px'}, 'Integrations'));
  const grid = h('div', {class: 'grid g2'}); p.append(grid);
  for (const it of items) {
    const live = it.oauth ? !!it.account : it.connected;
    const status = h('span', {class: 'pill ' + (live ? 'on' : 'off')}, it.oauth ? (it.account ? 'Connected' : it.connected ? 'Ready — click Connect Gmail' : 'Not connected') : (it.connected ? 'Connected' : 'Not connected'));
    const connectBtn = it.oauth ? h('button', {class: 'btn sm', disabled: !it.connected, onclick: async () => {
      try { location.href = (await api('/api/gmail/connect')).url; } catch (e) { toast(e.message, true); }
    }}, icon('mail'), it.account ? 'Reconnect Gmail' : 'Connect Gmail') : null;
    const secret = f => /KEY|TOKEN|SECRET|PASS/.test(f);
    const inputs = it.fields.map(f => input(f, {type: secret(f) ? 'password' : 'text', autocomplete: 'off', 'aria-label': f,
      placeholder: it.values[f] || {SMTP_USER: 'you@gmail.com', SMTP_PASS: 'App password', SMTP_FROM_NAME: 'Your name (signs emails)', SMTP_HOST: 'Optional: smtp.yourhost.com'}[f] || 'Paste key'}));
    const result = h('div', {class: 'small', style: 'margin-top:8px'});
    const save = h('button', {class: 'btn sm', onclick: async () => {
      const values = Object.fromEntries(inputs.map(i => [i.name, i.value.trim()]));
      if (!Object.values(values).some(Boolean)) return toast('Paste a key first', true);
      save.disabled = true; try { await api(`/api/settings/${it.id}`, values); toast(`${it.name} saved`); settings(); } catch (e) { toast(e.message, true); save.disabled = false; }
    }}, icon('key'), it.connected ? 'Replace' : 'Connect');
    const test = h('button', {class: 'btn secondary sm', disabled: !it.connected, onclick: async () => {
      test.disabled = true; result.replaceChildren(h('span', {class: 'spin'}), ' Testing…');
      const r = await api(`/api/settings/${it.id}/test`, {}); result.replaceChildren(h('span', {class: 'pill ' + (r.ok ? 'on' : 'off')}, r.ok ? 'Working' : 'Problem'), ' ', r.message); test.disabled = false;
    }}, icon('check'), 'Test');
    const remove = h('button', {class: 'btn danger sm', disabled: !it.connected, onclick: async () => {
      if (!confirm(`Remove the ${it.name} key from the server?`)) return; await api(`/api/settings/${it.id}/remove`, {}); toast(`${it.name} removed`); settings();
    }}, 'Remove');
    grid.append(h('div', {class: 'card'},
      h('div', {class: 'card-head'}, h('div', {class: 'row'}, h('div', {class: 'icon-box'}, icon('plug')), h('h2', {}, it.name)), status),
      h('p', {class: 'small muted'}, it.powers), it.account ? h('p', {class: 'small', style: 'margin-top:6px'}, 'Sending as ', h('b', {}, it.account)) : null,
      h('p', {class: 'tiny muted', style: 'margin:6px 0 12px'}, 'Get it: ' + it.get),
      h('div', {class: 'stack'}, ...inputs), h('div', {class: 'form-actions', style: 'margin-top:12px'}, connectBtn, save, test, remove), result));
  }
  const cur = input('current', {type: 'password', autocomplete: 'current-password'}), nw = input('new', {type: 'password', autocomplete: 'new-password'});
  p.append(h('h2', {style: 'margin:28px 0 12px'}, 'Account'), h('div', {class: 'grid g2'},
    h('form', {class: 'card', onsubmit: async e => { e.preventDefault(); try { await api('/api/password', {current: cur.value, new: nw.value}); toast('Password changed'); cur.value = nw.value = ''; } catch (err) { toast(err.message, true); } }},
      h('h2', {style: 'margin-bottom:12px'}, 'Change password'), h('div', {class: 'stack'}, field('Current password', cur), field('New password', nw, 'At least 10 characters')),
      h('div', {class: 'form-actions'}, h('button', {class: 'btn', type: 'submit'}, 'Update password'))),
    h('div', {class: 'card'}, h('h2', {style: 'margin-bottom:8px'}, `Signed in as ${state.me}`),
      h('p', {class: 'small muted'}, 'Signing out ends every session of this account.'),
      h('div', {class: 'form-actions'}, h('button', {class: 'btn secondary', onclick: async () => { await api('/api/logout', {}); state.me = null; renderAuth(); }}, icon('logout'), 'Sign out')))));
}

function aiEngine(ai) {
  const save = async body => { try { await api('/api/ai', body); toast('AI engine saved'); settings(); } catch (e) { toast(e.message, true); } };
  const seg = h('div', {class: 'seg', role: 'group'},
    ...[['gemini', 'Gemini (API key)'], ['claude', 'Claude (your subscription)']].map(([id, label]) =>
      h('button', {type: 'button', 'aria-pressed': String(ai.provider === id), onclick: () => save({provider: id, model: ai.model})}, label)));
  const model = h('select', {'aria-label': 'Claude model', onchange: () => save({provider: 'claude', model: model.value})},
    ai.models.map(v => h('option', {value: v, selected: v === ai.model}, v ? v[0].toUpperCase() + v.slice(1) : 'Default for my plan')));
  const result = h('div', {class: 'small', style: 'margin-top:8px'});
  const test = h('button', {class: 'btn secondary sm', onclick: async () => {
    test.disabled = true; result.replaceChildren(h('span', {class: 'spin'}), ' Asking…');
    const r = await api('/api/ai/test', {}).catch(e => ({ok: false, message: e.message}));
    result.replaceChildren(h('span', {class: 'pill ' + (r.ok ? 'on' : 'off')}, r.ok ? 'Working' : 'Problem'), ' ', r.message); test.disabled = false;
  }}, icon('check'), 'Test');
  const claude = ai.provider === 'claude';
  return h('div', {class: 'card'},
    h('p', {class: 'small muted', style: 'margin-bottom:12px'}, 'Does the AI Review, AI Visibility, messages and chat coaching. Switch any time — the next job uses it.'),
    seg,
    claude ? h('div', {class: 'stack', style: 'margin-top:12px'}, field('Model', model),
      h('p', {class: 'tiny muted'}, ai.claude_installed ? 'Runs through Claude Code logged in on your server with your Claude plan — no API key. Uses your plan’s usage limits; a big hunt makes many calls.' : 'Claude Code is not installed on the server.'))
      : h('p', {class: 'tiny muted', style: 'margin-top:12px'}, ai.gemini_connected ? 'Uses your Gemini key below.' : 'Connect a Gemini key below first.'),
    h('div', {class: 'form-actions', style: 'margin-top:12px'}, test), result);
}

function emailStatus(e) {
  const days = (Date.now() - new Date(e.at.replace(' ', 'T'))) / 864e5;
  if (e.bounced) return ['failed', 'Bounced', 'The address doesn’t exist or refused mail — find another email'];
  if (e.replied) return ['done', 'Replied', `Replied ${e.replied}`];
  if ((e.opens || []).length) return ['OKAY', `Opened ×${e.opens.length}`, `Last opened ${e.opens.at(-1).at}` + (days > 3 ? ' · no reply after 3 days — send a follow-up' : '')];
  return ['off', 'Not opened yet', days > 4 ? 'Not opened in 4+ days — may be in spam or ignored; try another channel (LinkedIn/Instagram)' : 'Waiting…'];
}
async function sent() {
  const p = page('Email tracking', 'Who opened your emails, who replied, and what bounced. Refreshes every minute.');
  const d = await api('/api/sent'); const list = [...d.sent].reverse();
  if (d.reconnect) p.append(h('a', {class: 'banner', href: '#/settings'}, icon('mail'), 'Reconnect Gmail in Settings once to turn on reply & bounce tracking.'));
  const n = list.length, opened = list.filter(e => (e.opens || []).length || e.replied).length, replied = list.filter(e => e.replied).length;
  const stat = (label, value, hint) => h('div', {class: 'card stat'}, h('div', {class: 'label'}, label), h('div', {class: 'value'}, value), hint ? h('div', {class: 'hint'}, hint) : null);
  const pct = x => n ? Math.round(x / n * 100) + '%' : '—';
  p.append(h('div', {class: 'grid g3'}, stat('Sent', n), stat('Opened', opened, pct(opened)), stat('Replied', replied, pct(replied))));
  const card = h('div', {class: 'card', style: 'margin-top:14px'});
  if (!n) card.append(empty('mail', 'No emails yet', 'Send one from a lead (Write email) or a chat (Send by email).'));
  for (const e of list) {
    const [cls, label, hint] = emailStatus(e);
    card.append(h('div', {class: 'item', style: 'cursor:' + (e.slug ? 'pointer' : 'default'), onclick: () => e.slug && go('#/chat/' + e.slug)},
      h('div', {class: 'icon-box'}, icon('mail')),
      h('div', {class: 'grow'}, h('div', {class: 'title'}, `${e.lead || e.to} — ${e.subject}`), h('div', {class: 'sub'}, `${e.to} · sent ${e.at}`), h('div', {class: 'tiny muted'}, hint)),
      h('span', {class: 'pill ' + cls}, label)));
  }
  p.append(card, h('p', {class: 'tiny muted', style: 'margin-top:10px'},
    'Opens use an invisible image: Apple Mail can count an open that didn’t happen, and people who block images won’t show as opened. Opening your own copy in Gmail’s Sent folder can also count. Replies and bounces are exact.'));
  clearTimeout(chatTimer); chatTimer = setTimeout(() => { if (location.hash.startsWith('#/sent')) route(); }, 60000);
}

async function more() {
  const p = page('More');
  const card = h('div', {class: 'card'});
  for (const [id, label, ic] of NAV.filter(([id]) => !BOTTOM.some(([b]) => b === id)))
    card.append(h('a', {class: 'item', href: '#/' + id, style: 'color:inherit'}, h('div', {class: 'icon-box'}, icon(ic)), h('div', {class: 'grow title'}, label)));
  p.append(card);
}

// ---------------------------------------------------------------------------------------------- sign in
function renderAuth(needsSetup) {
  const root = document.getElementById('root'); root.innerHTML = '';
  const user = input('username', {autocomplete: 'username', required: true}), pw = input('password', {type: 'password', required: true, autocomplete: needsSetup ? 'new-password' : 'current-password'});
  const code = needsSetup ? input('code', {type: 'password', required: true, autocomplete: 'one-time-code'}) : null;
  const err = h('div', {class: 'small', style: 'color:var(--bad);margin-top:10px', role: 'alert'});
  const form = h('form', {class: 'card', onsubmit: async e => {
    e.preventDefault(); err.textContent = '';
    try { const r = await api(needsSetup ? '/api/setup' : '/api/login', {username: user.value, password: pw.value, code: code && code.value}); state.me = r.user; start(); }
    catch (x) { err.textContent = x.message; }
  }},
    h('h1', {style: 'font-size:22px'}, needsSetup ? 'Create your account' : 'Sign in'),
    h('p', {class: 'muted small', style: 'margin:6px 0 18px'}, needsSetup ? 'First time here. Use the setup code from your server to create your login.' : 'Welcome back.'),
    h('div', {class: 'stack'}, code ? field('Setup code', code, 'The APP_KEY / old access key on your server') : null, field('Username', user), field('Password', pw, needsSetup ? 'At least 10 characters' : null)),
    h('button', {class: 'btn block', type: 'submit', style: 'margin-top:18px'}, needsSetup ? 'Create account' : 'Sign in'), err);
  const feature = (text) => h('li', {}, icon('check'), text);
  root.append(h('div', {class: 'auth'},
    h('div', {class: 'auth-hero'}, h('div', {class: 'logo', style: 'padding:0'}, h('img', {src: '/icon.svg', alt: ''}), 'Legacy Real'),
      h('div', {}, h('h1', {}, 'Find agents who can pay — and show them exactly what they\'re missing.'),
        h('p', {}, 'Hot markets, real production data, website and AI-visibility audits, and messages written with your own sales training.'),
        h('ul', {}, feature('Hunt hot ZIPs for busy, growing agents'), feature('Research any LinkedIn connection in minutes'),
          feature('Proof from Google\'s own tools, not guesses'), feature('Chat coaching from your Sales Brain'))),
      h('div', {class: 'tiny', style: 'color:#9fb0dd'}, 'Private workspace')),
    h('div', {class: 'auth-form'}, form)));
  (needsSetup ? code : user).focus();
}

// ---------------------------------------------------------------------------------------------- boot
let lastRunning = null;
async function pollStatus() {
  if (!state.me) return;
  try {
    const s = await api('/api/status'); state.running = s.running; updateJobChip();
    if (lastRunning && !s.running) toast('Job finished — open Activity to see the results');
    lastRunning = s.running;
  } catch (e) { /* signed out or offline */ }
}
let appTag = null;
async function checkUpdate() {  // the app stays open for days on a phone: offer a refresh when a new version ships
  try {
    const r = await fetch('/app.js', {method: 'HEAD', cache: 'no-store'}); const tag = r.headers.get('etag') || r.headers.get('last-modified');
    if (appTag && tag && tag !== appTag && !document.querySelector('.update-bar'))
      document.body.append(h('button', {class: 'update-bar', onclick: () => location.reload()}, 'New version available — tap to refresh'));
    appTag = appTag || tag;
  } catch (e) { /* offline */ }
}
setInterval(checkUpdate, 60000);
function start() { renderShell(); route(); pollStatus(); checkUpdate(); }
setInterval(pollStatus, 6000);
api('/api/me').then(r => { state.me = r.user; if (r.user) start(); else renderAuth(r.needs_setup); }).catch(() => renderAuth());
