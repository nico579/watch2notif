// Page de reglages/historique de watch2notif, servie sur HTTP local par
// notifier.py (nico579_commons.serveweb). Remplace le panneau Qt (settings.py) et la
// fenetre d'historique (history_window.py), tous deux retires. Vanilla JS,
// pas de framework - meme choix que lidar2map/blink2video pour ce type de
// page (formulaire + table), aucune bibliotheque a charger.

const api = {
  strings: () => fetch('/api/strings').then(r => r.json()),
  state: () => fetch('/api/state').then(r => r.json()),
  history: () => fetch('/api/history').then(r => r.json()),
  saveConfig: (payload) => _post('/api/save-config', payload),
  setPause: (paused) => _post('/api/set-pause', { paused }),
  clearHistory: () => _post('/api/clear-history', {}),
};

// --- la pause, dans le panneau « Reglages » commun ------------------------------------
// (nico579_commons, /nico579-reglages.js, bouton a cote de FR / EN). Construite ici et
// gardee par reference : le panneau retire ses lignes du document quand il se ferme.
// Le demarrage automatique, lui, est la case du commun (/api/autostart).

const reglagesGeneraux = document.createElement('div');
const pauseLabel = document.createElement('label');
pauseLabel.className = 'checkbox-row';
const pauseCheck = document.createElement('input');
pauseCheck.type = 'checkbox';
pauseCheck.id = 'pause-check';
const pauseText = document.createElement('span');
pauseText.dataset.i18n = 'tray_pause';
pauseLabel.append(pauseCheck, pauseText);
reglagesGeneraux.appendChild(pauseLabel);

// reglages.js (charge apres ce fichier) definit window.nico579Reglages.
window.addEventListener('load', () => {
  if (window.nico579Reglages) window.nico579Reglages.ajouter('', reglagesGeneraux);
});

function _post(route, payload) {
  return fetch(route, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  }).then(r => r.json());
}

// --- i18n ---------------------------------------------------------------

let STRINGS = {};
let lang = 'en';

function t(key, params) {
  const entry = STRINGS[key];
  let text = (entry && (entry[lang] || entry.en)) || key;
  if (params) {
    for (const [name, value] of Object.entries(params)) {
      text = text.replaceAll(`{${name}}`, value);
    }
  }
  return text;
}

function applyLanguage() {
  document.documentElement.lang = lang;
  // Le panneau Reglages retire ses lignes du document a la fermeture : on les traduit aussi.
  [document, reglagesGeneraux].forEach((racine) => {
    racine.querySelectorAll('[data-i18n]').forEach((el) => {
      el.textContent = t(el.dataset.i18n);
    });
    racine.querySelectorAll('[data-i18n-title]').forEach((el) => {
      el.title = t(el.dataset.i18nTitle);
    });
    racine.querySelectorAll('[data-i18n-placeholder]').forEach((el) => {
      el.placeholder = t(el.dataset.i18nPlaceholder);
    });
    racine.querySelectorAll('[data-i18n-href]').forEach((el) => {
      el.href = t(el.dataset.i18nHref);
    });
  });
  renderFeedKindOptions();
  renderServerInfo();
}

// Version et PID du serveur en tete de page, comme blink2video : on voit
// d'un coup d'oeil quelle version repond, et quel processus l'heberge.
let serverInfo = { version: '', pid: '' };

function renderServerInfo() {
  document.getElementById('server-version').textContent = serverInfo.version;
  document.getElementById('server-pid').textContent = t('header_pid', { pid: serverInfo.pid });
}

// --- etat courant (charge une fois, modifie localement, sauvegarde explicite) ---

let providers = {};
let defaultKind = 'rss';
// Rempli par /api/state : faux si ANTHROPIC_API_KEY manque (voir filtre_ia.py).
let cleIaPresente = true;
let feedKeySeq = 0;

// --- table des sources ----------------------------------------------------

function fillKindOptions(select) {
  select.innerHTML = '';
  for (const [kind, info] of Object.entries(providers)) {
    const opt = document.createElement('option');
    opt.value = kind;
    opt.textContent = info.label;
    select.appendChild(opt);
  }
}

function renderFeedKindOptions() {
  document.querySelectorAll('select.feed-kind').forEach((select) => {
    const current = select.value;
    fillKindOptions(select);
    select.value = current;
  });
}

function createFeedRow(feed) {
  feed = feed || { key: '', label: '', url: '', enabled: false, kind: defaultKind, interval_seconds: null, filtre_ia: '' };
  const tr = document.createElement('tr');
  tr.className = 'feed-row';
  tr.dataset.key = feed.key || '';
  // Auto : le champ intervalle suit le defaut du type tant que l'utilisateur
  // ne l'a pas modifie lui-meme (meme logique que interval_auto dans
  // l'ancien settings.py/QSpinBox).
  tr.dataset.intervalAuto = feed.interval_seconds ? '0' : '1';

  const tdActive = document.createElement('td');
  tdActive.className = 'col-active';
  const active = document.createElement('input');
  active.type = 'checkbox';
  active.className = 'feed-active';
  active.checked = !!feed.enabled;
  tdActive.appendChild(active);

  const tdKind = document.createElement('td');
  const kindSelect = document.createElement('select');
  kindSelect.className = 'feed-kind';
  // Les options d'abord : sur une liste encore vide, le navigateur ignore la
  // valeur qu'on lui donne (plus bas), et chaque source s'affichait sans
  // type, puis partait en RSS au premier « Enregistrer ».
  fillKindOptions(kindSelect);
  tdKind.appendChild(kindSelect);

  const tdName = document.createElement('td');
  const nameInput = document.createElement('input');
  nameInput.type = 'text';
  nameInput.className = 'feed-name';
  nameInput.value = feed.label || '';
  tdName.appendChild(nameInput);

  const tdUrl = document.createElement('td');
  const urlInput = document.createElement('input');
  urlInput.type = 'text';
  urlInput.className = 'feed-url';
  urlInput.value = feed.url || '';
  tdUrl.appendChild(urlInput);

  const tdInterval = document.createElement('td');
  const intervalInput = document.createElement('input');
  intervalInput.type = 'number';
  intervalInput.className = 'feed-interval';
  intervalInput.min = '5';
  intervalInput.max = '86400';
  intervalInput.value = feed.interval_seconds || (providers[feed.kind] || {}).default_interval_seconds || 60;
  intervalInput.addEventListener('input', () => { tr.dataset.intervalAuto = '0'; });
  tdInterval.appendChild(intervalInput);

  // Filtre IA (filtre_ia.py) : la consigne s'ecrit dans une ligne a part, sous la
  // source, ouverte par le bouton « Filtre IA » ; elle reste ouverte si elle n'est pas vide.
  const filterRow = document.createElement('tr');
  filterRow.className = 'feed-filter-row';
  const filterCell = document.createElement('td');
  filterCell.colSpan = 6;
  const filterInput = document.createElement('textarea');
  filterInput.className = 'feed-filter';
  filterInput.rows = 3;
  filterInput.dataset.i18nPlaceholder = 'filter_placeholder';
  filterInput.placeholder = t('filter_placeholder');
  filterInput.value = feed.filtre_ia || '';
  filterCell.appendChild(filterInput);
  // Sans cle, une consigne ne trie rien : le dire ici, la ou on l'ecrit, plutot qu'a la
  // premiere notification non triee.
  if (!cleIaPresente) {
    const keyNote = document.createElement('p');
    keyNote.className = 'note filter-key-note';
    const keyText = document.createElement('span');
    keyText.dataset.i18n = 'filter_key_missing';
    keyText.textContent = t('filter_key_missing');
    const keyLink = document.createElement('a');
    keyLink.target = '_blank';
    keyLink.rel = 'noopener';
    keyLink.textContent = 'README';
    keyLink.href = t('filter_key_url');
    keyLink.dataset.i18nHref = 'filter_key_url';
    keyNote.append(keyText, ' ', keyLink);
    filterCell.appendChild(keyNote);
  }
  filterRow.appendChild(filterCell);
  filterRow.hidden = !filterInput.value;
  tr.filterInput = filterInput;
  tr.filterRow = filterRow;

  const tdRemove = document.createElement('td');
  tdRemove.className = 'col-remove';
  const filterBtn = document.createElement('button');
  filterBtn.type = 'button';
  filterBtn.className = 'filter-btn';
  filterBtn.dataset.i18n = 'filter_button';
  filterBtn.dataset.i18nTitle = 'filter_button_title';
  filterBtn.textContent = t('filter_button');
  filterBtn.title = t('filter_button_title');
  const majFilterBtn = () => filterBtn.classList.toggle('active', !!filterInput.value.trim());
  majFilterBtn();
  filterInput.addEventListener('input', majFilterBtn);
  filterBtn.addEventListener('click', () => {
    filterRow.hidden = !filterRow.hidden;
    if (!filterRow.hidden) filterInput.focus();
  });
  const removeBtn = document.createElement('button');
  removeBtn.type = 'button';
  removeBtn.className = 'remove-btn';
  removeBtn.textContent = '×';
  removeBtn.addEventListener('click', () => { tr.remove(); filterRow.remove(); });
  tdRemove.append(filterBtn, removeBtn);

  tr.append(tdActive, tdKind, tdName, tdUrl, tdInterval, tdRemove);

  kindSelect.addEventListener('change', () => {
    if (tr.dataset.intervalAuto !== '0') {
      intervalInput.value = (providers[kindSelect.value] || {}).default_interval_seconds || 60;
    }
  });

  document.getElementById('feeds-body').append(tr, filterRow);
  kindSelect.value = feed.kind || defaultKind;
  return tr;
}

function renderFeedsTable(feeds) {
  document.getElementById('feeds-body').innerHTML = '';
  feeds.forEach(createFeedRow);
  renderFeedKindOptions();
}

function collectFeedsFromTable() {
  return Array.from(document.querySelectorAll('#feeds-body tr.feed-row')).map((tr) => ({
    key: tr.dataset.key || '',
    label: tr.querySelector('.feed-name').value.trim(),
    url: tr.querySelector('.feed-url').value.trim(),
    enabled: tr.querySelector('.feed-active').checked,
    kind: tr.querySelector('.feed-kind').value,
    interval_seconds: parseInt(tr.querySelector('.feed-interval').value, 10) || null,
    filtre_ia: tr.filterInput.value.trim(),
  }));
}

// --- historique -------------------------------------------------------

function renderHistory(entries) {
  const body = document.getElementById('history-body');
  body.innerHTML = '';
  for (const entry of entries) {
    const tr = document.createElement('tr');
    const date = entry.timestamp ? new Date(entry.timestamp * 1000).toLocaleString(lang) : '';
    const tdDate = document.createElement('td');
    tdDate.textContent = date;
    const tdSource = document.createElement('td');
    tdSource.textContent = entry.feed_label || '';
    const tdTitle = document.createElement('td');
    // entry.link vient tel quel du flux RSS/API de la source (rss.py
    // renvoie le champ <link> brut) : un flux malveillant ou compromis
    // pourrait y mettre "javascript:..." plutot qu'une vraie URL. Le
    // schema est verifie avant d'en faire un lien cliquable dans une page
    // qui a acces complet a l'API (trouve en audit).
    if (entry.link && /^https?:\/\//i.test(entry.link)) {
      const a = document.createElement('a');
      a.href = entry.link;
      a.target = '_blank';
      a.rel = 'noopener';
      a.textContent = entry.title || '';
      tdTitle.appendChild(a);
    } else {
      tdTitle.textContent = entry.title || '';
    }
    tr.append(tdDate, tdSource, tdTitle);
    body.appendChild(tr);
  }
}

// --- sauvegarde ---------------------------------------------------------

async function saveConfig() {
  const status = document.getElementById('save-status');
  status.textContent = '';
  status.classList.remove('error');
  const payload = {
    lang,
    feeds: collectFeedsFromTable(),
  };
  const result = await api.saveConfig(payload);
  // Reaffecte les clefs generees cote serveur (nouvelles lignes) : sans ca,
  // un 2e Sauvegarder sans recharger la page regenererait un nouveau slug a
  // chaque fois pour ces lignes (meme piege que checkbox._feed_key en Qt).
  const rows = Array.from(document.querySelectorAll('#feeds-body tr.feed-row'));
  result.feeds.forEach((feed, index) => {
    if (rows[index]) rows[index].dataset.key = feed.key;
  });
  status.textContent = t('ok_msg');
}

// --- rafraichissement periodique (la pause, jamais la
// table de sources) ; le bandeau de mise a jour est celui du commun
// (/nico579-maj.js), qui se recharge seul apres le redemarrage ---

async function refreshState() {
  try {
    const state = await api.state();
    pauseCheck.checked = state.paused;
  } catch (exc) {
    // Serveur momentanement injoignable (redemarrage) : on reessaie au tick suivant.
  }
}

function scheduleRefresh() {
  // setTimeout recursif, pas setInterval : un tick lent ne doit pas se
  // chevaucher avec le suivant.
  setTimeout(() => { refreshState().then(scheduleRefresh); }, 4000);
}
scheduleRefresh();

// --- cablage des controles statiques -------------------------------------

// Le choix FR / EN est celui du commun (/nico579-langue.js, route /api/langue) : il dessine les
// boutons, garde le choix et annonce chaque changement ; la page applique ses textes.
document.addEventListener('nico579-langue', (event) => {
  lang = event.detail.code;
  if (Object.keys(STRINGS).length) applyLanguage();   // sinon init() s'en charge, textes chargés
});

document.querySelectorAll('.tab-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach((b) => b.classList.toggle('active', b === btn));
    document.querySelectorAll('.tab-panel').forEach((panel) => {
      panel.hidden = panel.id !== `tab-${btn.dataset.tab}`;
    });
    if (btn.dataset.tab === 'history') {
      api.history().then((data) => renderHistory(data.entries));
    }
  });
});

document.getElementById('add-feed-btn').addEventListener('click', () => createFeedRow());
document.getElementById('save-btn').addEventListener('click', saveConfig);
pauseCheck.addEventListener('change', (event) => {
  api.setPause(event.target.checked);
});
document.getElementById('history-clear-btn').addEventListener('click', async () => {
  await api.clearHistory();
  const data = await api.history();
  renderHistory(data.entries);
});

// --- chargement initial ---------------------------------------------------

(async function init() {
  STRINGS = await api.strings();
  const state = await api.state();
  lang = (window.nico579Langue && window.nico579Langue.code()) || state.config.lang || 'en';
  providers = state.providers;
  defaultKind = state.default_kind;
  cleIaPresente = state.cle_ia_presente !== false;
  serverInfo = { version: state.version, pid: state.pid };

  pauseCheck.checked = state.paused;
  renderFeedsTable(state.config.feeds || []);
  applyLanguage();

  document.title = `watch2notif v${state.version}`;
})();
