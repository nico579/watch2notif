// Page de reglages/historique de watch2notif, servie sur HTTP local par
// notifier.py (_serve_web.py). Remplace le panneau Qt (settings.py) et la
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
  updateInstall: () => _post('/api/update-install', {}),
};

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
  document.querySelectorAll('[data-i18n]').forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll('#lang-toggle button').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.lang === lang);
  });
  renderFeedKindOptions();
  renderUpdateBanner(lastUpdateState);
}

// --- etat courant (charge une fois, modifie localement, sauvegarde explicite) ---

let providers = {};
let defaultKind = 'rss';
let lastUpdateState = null;
let feedKeySeq = 0;

// --- table des sources ----------------------------------------------------

function renderFeedKindOptions() {
  document.querySelectorAll('select.feed-kind').forEach((select) => {
    const current = select.value;
    select.innerHTML = '';
    for (const [kind, info] of Object.entries(providers)) {
      const opt = document.createElement('option');
      opt.value = kind;
      opt.textContent = info.label;
      select.appendChild(opt);
    }
    select.value = current;
  });
}

function createFeedRow(feed) {
  feed = feed || { key: '', label: '', url: '', enabled: false, kind: defaultKind, interval_seconds: null };
  const tr = document.createElement('tr');
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

  const tdRemove = document.createElement('td');
  tdRemove.className = 'col-remove';
  const removeBtn = document.createElement('button');
  removeBtn.type = 'button';
  removeBtn.className = 'remove-btn';
  removeBtn.textContent = '×';
  removeBtn.addEventListener('click', () => tr.remove());
  tdRemove.appendChild(removeBtn);

  tr.append(tdActive, tdKind, tdName, tdUrl, tdInterval, tdRemove);

  kindSelect.addEventListener('change', () => {
    if (tr.dataset.intervalAuto !== '0') {
      intervalInput.value = (providers[kindSelect.value] || {}).default_interval_seconds || 60;
    }
  });

  document.getElementById('feeds-body').appendChild(tr);
  kindSelect.value = feed.kind || defaultKind;
  return tr;
}

function renderFeedsTable(feeds) {
  document.getElementById('feeds-body').innerHTML = '';
  feeds.forEach(createFeedRow);
  renderFeedKindOptions();
}

function collectFeedsFromTable() {
  return Array.from(document.querySelectorAll('#feeds-body tr')).map((tr) => ({
    key: tr.dataset.key || '',
    label: tr.querySelector('.feed-name').value.trim(),
    url: tr.querySelector('.feed-url').value.trim(),
    enabled: tr.querySelector('.feed-active').checked,
    kind: tr.querySelector('.feed-kind').value,
    interval_seconds: parseInt(tr.querySelector('.feed-interval').value, 10) || null,
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
    if (entry.link) {
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

// --- bandeau de mise a jour ---------------------------------------------

const UPDATE_ERROR_KEYS = {
  download_failed: 'update_error_download',
  integrity_failed: 'update_error_integrity',
  unsafe_archive: 'update_error_integrity',
  invalid_payload: 'update_error_integrity',
  unsupported_target: 'update_error_compatibility',
  missing_asset: 'update_error_compatibility',
  invalid_asset: 'update_error_compatibility',
  source_mode: 'update_error_compatibility',
  helper_failed: 'update_error_installer',
  unsafe_install: 'update_error_installer',
};

function renderUpdateBanner(update) {
  lastUpdateState = update;
  const banner = document.getElementById('update-banner');
  const text = document.getElementById('update-text');
  const installBtn = document.getElementById('update-install-btn');
  const releaseLink = document.getElementById('update-release-link');

  if (!update || !update.info) {
    banner.hidden = true;
    return;
  }
  banner.hidden = false;
  const version = update.info.version;

  if (update.status === 'preparing') {
    text.textContent = t('tray_update_downloading', { version });
    text.classList.remove('error-text');
    installBtn.hidden = true;
    releaseLink.hidden = true;
    return;
  }

  if (update.status === 'failed' && update.error) {
    const key = UPDATE_ERROR_KEYS[update.error.code] || 'update_error_generic';
    text.textContent = t('update_error_body', { error: t(key) });
    text.classList.add('error-text');
  } else {
    text.textContent = t('tray_update_available', { version });
    text.classList.remove('error-text');
  }

  if (update.can_install_automatically) {
    installBtn.hidden = false;
    installBtn.disabled = false;
    installBtn.textContent = update.status === 'failed'
      ? t('tray_update_retry', { version })
      : t('update_install_button');
    releaseLink.hidden = true;
  } else {
    installBtn.hidden = true;
    releaseLink.hidden = false;
    releaseLink.href = update.info.page || '#';
    releaseLink.textContent = t('update_open_release_button');
  }
}

// --- sauvegarde ---------------------------------------------------------

async function saveConfig() {
  const status = document.getElementById('save-status');
  status.textContent = '';
  status.classList.remove('error');
  const payload = {
    lang,
    autostart_enabled: document.getElementById('autostart-check').checked,
    feeds: collectFeedsFromTable(),
  };
  const result = await api.saveConfig(payload);
  if (result.error) {
    status.textContent = t('autostart_error_msg', { error: result.error });
    status.classList.add('error');
    return;
  }
  // Reaffecte les clefs generees cote serveur (nouvelles lignes) : sans ca,
  // un 2e Sauvegarder sans recharger la page regenererait un nouveau slug a
  // chaque fois pour ces lignes (meme piege que checkbox._feed_key en Qt).
  const rows = Array.from(document.querySelectorAll('#feeds-body tr'));
  result.feeds.forEach((feed, index) => {
    if (rows[index]) rows[index].dataset.key = feed.key;
  });
  status.textContent = t('ok_msg');
}

// --- rafraichissement periodique (pause/maj, jamais la table de sources) ---

let reconnecting = false;

async function refreshState() {
  const wasReconnecting = reconnecting;
  try {
    const state = await api.state();
    if (wasReconnecting) {
      // Le nouveau process (relance par le helper de mise a jour) repond a
      // nouveau : on repart d'une page neuve plutot que de tenter de
      // reconcilier tout l'etat en memoire avec la version fraichement
      // installee.
      location.reload();
      return;
    }
    document.getElementById('pause-check').checked = state.paused;
    document.getElementById('autostart-check').checked = state.autostart_enabled;
    renderUpdateBanner(state.update);
  } catch (exc) {
    // Le serveur s'arrete pendant l'etape finale d'une mise a jour (le
    // helper externe prend le relais) : meme modele que blink2video
    // (bouton "Mettre a jour" de la page web), qui attend simplement le
    // retour du serveur plutot que de suivre une progression detaillee.
    if (lastUpdateState && lastUpdateState.status === 'preparing') {
      reconnecting = true;
      document.getElementById('update-text').textContent = t('update_progress_body', {
        version: lastUpdateState.info.version,
      });
    }
  }
}

document.getElementById('update-install-btn').addEventListener('click', async () => {
  document.getElementById('update-install-btn').disabled = true;
  await api.updateInstall();
  refreshState();
});

function scheduleRefresh() {
  // setTimeout recursif, pas setInterval : le delai doit refleter l'etat
  // COURANT de reconnecting a chaque tick (setInterval figerait le premier
  // delai pour toujours, jamais reevalue).
  setTimeout(() => { refreshState().then(scheduleRefresh); }, reconnecting ? 2000 : 4000);
}
scheduleRefresh();

// --- cablage des controles statiques -------------------------------------

document.getElementById('lang-toggle').addEventListener('click', (event) => {
  const btn = event.target.closest('button[data-lang]');
  if (!btn) return;
  lang = btn.dataset.lang;
  applyLanguage();
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
document.getElementById('pause-check').addEventListener('change', (event) => {
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
  lang = state.config.lang || 'en';
  providers = state.providers;
  defaultKind = state.default_kind;

  document.getElementById('autostart-check').checked = state.autostart_enabled;
  document.getElementById('pause-check').checked = state.paused;
  renderFeedsTable(state.config.feeds || []);
  applyLanguage();
  renderUpdateBanner(state.update);

  document.title = `watch2notif v${state.version}`;
})();
