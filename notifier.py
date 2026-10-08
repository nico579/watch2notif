"""Poll the sources enabled in config.json (RSS/Atom feeds, GitHub issues,
see providers/) and fire a desktop notification for anything new.
Cross-platform (Windows/Linux/Mac). Runs the polling in a background
thread, serves the settings/history GUI on local HTTP (browser), and
shows a system tray icon on the main thread.

Meme architecture que lidar2map (serveweb + gui/ + pystray), plus de
Qt/PySide6 dans watch2notif. L'icone et son menu viennent de
nico579_commons.tray, le meme menu dans les quatre applications (Ouvrir,
Mettre a jour, Redemarrer, Arreter, Creer un raccourci) ; pause,
historique et aide sont dans la page. --settings (bas de ce fichier)
ouvre le navigateur sur l'instance en cours (ou en demarre une si aucune
ne tourne) ; --no-tray sert aux tests et aux environnements sans zone de
notification.
"""
import calendar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from nico579_commons import atomique, demarrage, environnement, langue, maj, maj_install, raccourci, relance, serveweb
from nico579_commons import tray as apptray

import autostart_manager
import filtre_ia
import data_paths
import i18n
import notification_history
import notify_backend
import self_update
import single_instance
import update_check
from providers import DEFAULT_KIND, PROVIDERS

CONFIG_FILE = data_paths.DATA_DIR / "config.json"
STATE_DIR = data_paths.DATA_DIR / "state"
STATE_SCHEMA_VERSION = 2
# Dernière release publiée, interrogée par un fil de fond (une fois par heure) :
# le cycle de poll et le menu lisent la dernière réponse sans attendre le réseau.
# Gardée dans le dossier de données : un redémarrage ne repose pas la question tant que
# la réponse a moins d'une heure.
VERIFICATEUR = maj.Verificateur(update_check.DEPOT, update_check.VERSION,
                                cache=data_paths.DATA_DIR / "maj.json")
# Un flux peut publier une entree avec quelques minutes de retard ou plusieurs
# entrees a la meme seconde. On ne classe silencieusement comme "remontee
# ancienne" qu'une entree clairement anterieure au repere persiste.
BACKFILL_GRACE_SECONDS = 5 * 60
MAX_FUTURE_TIMESTAMP_SECONDS = 24 * 3600

# Port fixe (pas de recherche de plage comme lidar2map) : single_instance.py
# interdit deja tout doublon, jamais deux serveurs a demarrer en parallele.
# 8765=blink2video, 8766=lidar2map (voir leurs --port par defaut) : suite
# logique, pas de collision si les trois tournent en meme temps sur la
# meme machine.
PORT = 8767
BIND = "127.0.0.1"

# A l'inverse de data_paths.DATA_DIR : les assets embarques (watch2notif.spec,
# datas=) vivent dans sys._MEIPASS une fois fige (le dossier _internal/ en
# mode dossier), pas a cote de l'executable ni dans le dossier de donnees.
RESOURCE_DIR = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
# Icones rangees comme celles de blink2video, lidar2map et gpxsolar :
# assets/watch2notif.png pour l'executable (watch2notif.spec, icon=),
# assets/watch2notif.ico pour la zone de notification et l'onglet.
ICON_FILE = RESOURCE_DIR / "assets" / "watch2notif.ico"
GUI_DIR = RESOURCE_DIR / "gui"


class _TimestampedLog:
    """Prefixe chaque ligne ecrite d'un horodatage ISO, sans toucher aux
    print() eux-memes : sans ca, une ligne du log ne peut se situer dans
    le temps qu'en la recoupant avec un contexte externe (constate en
    reel en debuggant le mecanisme de mise a jour, ou l'ordre des lignes
    ne suffisait pas)."""

    def __init__(self, stream):
        self._stream = stream
        self._at_line_start = True

    def write(self, data: str) -> None:
        for chunk in data.splitlines(keepends=True):
            if self._at_line_start and chunk.strip():
                self._stream.write(datetime.now().isoformat(timespec="seconds") + " ")
            self._stream.write(chunk)
            self._at_line_start = chunk.endswith("\n")

    def flush(self) -> None:
        self._stream.flush()


def doit_journaliser(stdout, fige: bool, auto_test: bool) -> bool:
    """Vrai si les print() doivent aller au journal plutot qu'a la sortie standard.

    En executable "windowed" (console=False, cf watch2notif.spec), Windows ne
    donne pas de console au process. Lance par le raccourci du demarrage,
    sys.stdout vaut None. Mais relance par « Redemarrer », il recoit un tube
    dont l'ancien process etait le seul lecteur : sys.stdout existe, et le
    premier print() leve « OSError: [Errno 22] Invalid argument » (constate en
    reel le 2026-10-07). Un executable fige n'a donc jamais de sortie standard
    sur laquelle compter : le journal, dans tous les cas. L'auto-test
    (--self-test-version) garde la sienne, que la CI lit.
    """
    if auto_test:
        return False
    return stdout is None or fige


# Le journal est a cote des donnees, seul moyen de garder une trace d'un
# poller silencieux.
SELF_TEST_REQUESTED = "--self-test-version" in sys.argv[1:]
if doit_journaliser(sys.stdout, getattr(sys, "frozen", False), SELF_TEST_REQUESTED):
    log_file = open(data_paths.DATA_DIR / "watch2notif.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = _TimestampedLog(log_file)
elif sys.stdout is not None:
    sys.stdout.reconfigure(line_buffering=True)


def default_config() -> dict:
    return {"poll_interval_seconds": 60, "feeds": [], "lang": i18n.detect_default_lang()}


def load_config() -> dict:
    # tolerer_corrompu=False : un config.json corrompu leve, comme avant, au
    # lieu d'etre remplace en silence par la config par defaut au prochain
    # enregistrement (il se repare encore a la main).
    config = atomique.lire_json(CONFIG_FILE, None, tolerer_corrompu=False)
    return default_config() if config is None else config


def save_config(config: dict) -> None:
    # Temporaire unique par ecriture (nico579_commons.atomique) : l'ancien
    # config.json.tmp au nom fixe faisait echouer deux enregistrements
    # simultanes (double clic sur Enregistrer, deux onglets).
    atomique.ecrire_json(CONFIG_FILE, config, indent=2)


# Lecture-modification-ecriture de la config par la route save-config : deux
# requetes simultanees relisaient la meme config et la seconde ecrasait la
# premiere.
_config_lock = threading.Lock()


def slugify(label: str, existing_keys: set) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_") or "source"
    candidate = slug
    counter = 2
    while candidate in existing_keys:
        candidate = f"{slug}_{counter}"
        counter += 1
    return candidate


def build_feeds_from_rows(rows: list, known_kinds: dict | None = None) -> list:
    """Meme semantique que l'ancien SettingsWindow.on_save() (Qt) : une
    ligne sans label ni url est ignoree, la clef existante d'une ligne
    (reenvoyee par le client apres un premier save) est reutilisee plutot
    que reglissifiee - sinon une source deja active perdrait son historique
    de dedup (state/<key>.json) a chaque sauvegarde suivante.

    known_kinds (clef -> type, tire de la config actuelle) : un type vide
    ou inconnu ne remplace jamais celui, connu, d'une source existante. De
    la 0.2.0 a la 0.2.4, la page renvoyait un type vide pour chaque source,
    et chacune serait passee en RSS au premier enregistrement."""
    known_kinds = known_kinds or {}
    existing_keys: set = set()
    feeds = []
    for row in rows:
        label = str(row.get("label") or "").strip()
        url_value = str(row.get("url") or "").strip()
        if not label and not url_value:
            continue
        # Une clef explicite deja vue (deux lignes qui se la partagent -
        # frontend buggue, ou payload construit a la main) doit etre
        # re-slugifiee comme si elle etait absente : la laisser passer
        # ferait cohabiter deux sources sur le meme state_file(key), chacune
        # ecrasant le fingerprint de l'autre a chaque cycle, sans jamais
        # notifier ni pour l'une ni pour l'autre (trouve en audit).
        key = str(row.get("key") or "").strip()
        if not key or key in existing_keys:
            key = slugify(label, existing_keys)
        existing_keys.add(key)
        kind = row.get("kind")
        if kind not in PROVIDERS:
            kind = known_kinds.get(key) if known_kinds.get(key) in PROVIDERS else DEFAULT_KIND
        try:
            interval_seconds = int(row.get("interval_seconds"))
        except (TypeError, ValueError):
            interval_seconds = getattr(PROVIDERS[kind], "DEFAULT_INTERVAL_SECONDS", 60)
        feeds.append({
            "key": key,
            "label": label or key,
            "url": url_value,
            "enabled": bool(row.get("enabled")),
            "kind": kind,
            "interval_seconds": interval_seconds,
            # Consigne du filtre IA (filtre_ia.py) ; vide = tout notifier.
            "filtre_ia": str(row.get("filtre_ia") or "").strip(),
        })
    return feeds


def state_file(feed_key: str) -> Path:
    return STATE_DIR / f"{feed_key}.json"


@dataclass
class FeedState:
    seen_ids: set[str] = field(default_factory=set)
    pending_ids: set[str] = field(default_factory=set)
    newest_timestamp: float | None = None
    source_fingerprint: str | None = None
    legacy: bool = False


def _valid_timestamp(value, *, reject_far_future: bool = True) -> float | None:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(timestamp) or timestamp < 0:
        return None
    if reject_far_future and timestamp > time.time() + MAX_FUTURE_TIMESTAMP_SECONDS:
        return None
    return timestamp


def load_feed_state(feed_key: str) -> FeedState:
    # Illisible ou corrompu : leve, comme avant. Un etat vide rendu a tort
    # ferait paraitre toutes les entrees nouvelles, donc tout re-notifier.
    raw = atomique.lire_json(state_file(feed_key), None, tolerer_corrompu=False)
    if raw is None:
        return FeedState()
    if isinstance(raw, list):
        # Migration transparente des versions <= 0.1.1.
        return FeedState(seen_ids={str(value) for value in raw if value}, legacy=True)
    if not isinstance(raw, dict):
        raise ValueError(f"format d'etat invalide pour {feed_key}")
    seen = raw.get("seen_ids") or []
    if not isinstance(seen, list):
        raise ValueError(f"seen_ids invalide pour {feed_key}")
    pending = raw.get("pending_ids") or []
    if not isinstance(pending, list):
        raise ValueError(f"pending_ids invalide pour {feed_key}")
    seen_ids = {str(value) for value in seen if value}
    return FeedState(
        seen_ids=seen_ids,
        pending_ids={str(value) for value in pending if value} - seen_ids,
        # Un recul de l'horloge locale ne doit pas effacer un watermark deja
        # valide. La garde "date trop future" ne concerne que les donnees
        # nouvellement fournies par un flux potentiellement mal forme.
        newest_timestamp=_valid_timestamp(raw.get("newest_timestamp"), reject_far_future=False),
        source_fingerprint=str(raw.get("source_fingerprint") or "") or None,
    )


def save_feed_state(feed_key: str, state: FeedState) -> None:
    _write_json_atomic(
        state_file(feed_key),
        {
            "version": STATE_SCHEMA_VERSION,
            "seen_ids": sorted(state.seen_ids),
            "pending_ids": sorted(state.pending_ids - state.seen_ids),
            "newest_timestamp": state.newest_timestamp,
            # Empreinte seulement : une URL RSS privee ne doit jamais etre
            # recopiee en clair dans les fichiers d'etat.
            "source_fingerprint": state.source_fingerprint,
        },
    )


def load_seen_ids(feed_key: str) -> set[str]:
    """Compatibilite pour les appels/tests existants."""
    return load_feed_state(feed_key).seen_ids


def save_seen_ids(feed_key: str, seen_ids: set[str]) -> None:
    """Compatibilite : conserve le repere temporel s'il existe deja."""
    state = load_feed_state(feed_key) if state_file(feed_key).exists() else FeedState()
    state.seen_ids = set(seen_ids)
    state.pending_ids.difference_update(state.seen_ids)
    state.legacy = False
    save_feed_state(feed_key, state)


def _write_json_atomic(path: Path, data) -> None:
    """Ecrit dans un fichier temporaire puis renomme : un lecteur concurrent
    (poll_loop tournant pendant une sauvegarde de reglages, par exemple) ne
    peut jamais voir un fichier tronque/partiellement ecrit. Temporaire
    unique : cf. nico579_commons.atomique."""
    atomique.ecrire_json(path, data, indent=None)


def fetch_entries(feed: dict):
    provider = PROVIDERS[feed.get("kind", DEFAULT_KIND)]
    return provider.fetch_entries(feed["url"])


def _feed_fingerprint(feed: dict) -> str:
    kind = str(feed.get("kind") or DEFAULT_KIND)
    url = str(feed.get("url") or "")
    return hashlib.sha256(f"{kind}\0{url}".encode("utf-8")).hexdigest()


TITLE_MAX_LEN = 100


def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[: max_len - 3] + "..."


def notify(feed_label: str, entry, raison: str = "") -> None:
    title = entry.get("title", "(sans titre)")
    author = entry.get("author", "?")
    body = (entry.get("summary") or "").strip().replace("\n", " ")
    if len(body) > 150:
        body = body[:150] + "..."
    if raison:
        # Le verdict du filtre IA passe avant le debut du message : c'est lui qui dit
        # pourquoi cette notification merite d'etre lue.
        body = f"{raison} | {body}" if body else raison
    full_title = f"[{feed_label}] {title}"
    link = entry.get("link", "")
    notify_backend.notify(
        title=_truncate(full_title, TITLE_MAX_LEN),
        message=f"{author} - {body}" if body else author,
        url=link,
    )
    notification_history.append(feed_label, title, author, body, link)


def _entry_id(entry) -> str:
    """entry.id peut manquer (RSS 2.0 sans <guid>) : on retombe sur le lien,
    puis sur un hash stable du contenu plutot que de planter/reperdre
    l'entree a chaque cycle. getattr (pas .get) : providers.base.Entry
    garde "id" en attribut direct, pas dans les clefs que .get() lit."""
    id_ = getattr(entry, "id", None)
    if id_:
        return str(id_)
    link = entry.get("link")
    if link:
        return str(link)
    signature = f"{entry.get('title', '')}|{entry.get('summary', '')}"
    return hashlib.sha1(signature.encode("utf-8")).hexdigest()


def _entry_timestamp(entry) -> float | None:
    """Horodatage UTC d'une entree RSS/API, si le provider en expose un."""
    for key in ("published_parsed", "created_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                timestamp = _valid_timestamp(calendar.timegm(tuple(parsed)[:9]))
            except (TypeError, ValueError, OverflowError):
                timestamp = None
            if timestamp is not None:
                return timestamp

    for key in ("published", "created", "created_at", "updated"):
        raw = entry.get(key)
        if not raw:
            continue
        if isinstance(raw, (int, float)):
            timestamp = _valid_timestamp(raw)
            if timestamp is not None:
                return timestamp
            continue
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(str(raw))
            except (TypeError, ValueError, OverflowError):
                continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        timestamp = _valid_timestamp(parsed.timestamp())
        if timestamp is not None:
            return timestamp
    return None


def poll_feed(feed: dict) -> None:
    key, label = feed["key"], feed["label"]
    first_run = not state_file(key).exists()
    state = load_feed_state(key)
    fingerprint = _feed_fingerprint(feed)
    source_changed = bool(
        state.source_fingerprint and state.source_fingerprint != fingerprint
    )
    fingerprint_missing = state.source_fingerprint is None
    if source_changed:
        # La cle UI peut rester identique apres modification URL/provider.
        # L'ancien watermark n'a alors aucune signification pour la nouvelle
        # source : on la re-amorce comme un premier lancement, sans rafale.
        state = FeedState(source_fingerprint=fingerprint)
    else:
        state.source_fingerprint = fingerprint

    entries = fetch_entries(feed)
    records = []
    ids_in_batch = set()
    for entry in entries:
        entry_id = _entry_id(entry)
        if entry_id in ids_in_batch:
            continue
        ids_in_batch.add(entry_id)
        records.append((entry, entry_id, _entry_timestamp(entry)))
    timestamps = [timestamp for _entry, _entry_id_value, timestamp in records if timestamp is not None]
    current_newest = max(timestamps, default=None)

    if first_run or source_changed:
        state.seen_ids.update(entry_id for _entry, entry_id, _timestamp in records)
        state.newest_timestamp = current_newest
        state.legacy = False
        save_feed_state(key, state)
        reason = "source modifiee" if source_changed else "premier lancement"
        print(f"[{label}] {reason}: {len(entries)} item(s) amorces, aucune notif.")
        return

    stored_watermark = state.newest_timestamp
    was_legacy = state.legacy
    baseline = stored_watermark
    if baseline is None and state.legacy:
        known_timestamps = [
            timestamp
            for _entry, entry_id, timestamp in records
            if entry_id in state.seen_ids and timestamp is not None
        ]
        # Le dernier ID connu encore present peut etre tres ancien dans une
        # fenetre glissante. La date d'ecriture du state prouve que le poller
        # etait actif plus recemment : prendre le maximum des deux evite de
        # renotifier tous les elements intermediaires. On borne un mtime futur
        # en cas de correction de l'horloge systeme.
        cutoff_candidates = list(known_timestamps)
        try:
            state_mtime = _valid_timestamp(
                state_file(key).stat().st_mtime,
                reject_far_future=False,
            )
        except OSError:
            state_mtime = None
        if state_mtime is not None:
            cutoff_candidates.append(min(state_mtime, time.time()))
        baseline = max(cutoff_candidates, default=None)

    candidates = []
    backfilled = 0
    state_changed = False
    for entry, entry_id, timestamp in records:
        if entry_id in state.seen_ids:
            if entry_id in state.pending_ids:
                state.pending_ids.discard(entry_id)
                state_changed = True
            continue
        if entry_id in state.pending_ids:
            candidates.append((entry, entry_id, timestamp))
            continue
        is_old_backfill = (
            timestamp is not None
            and baseline is not None
            and timestamp < baseline - BACKFILL_GRACE_SECONDS
        )
        if is_old_backfill:
            state.seen_ids.add(entry_id)
            state.pending_ids.discard(entry_id)
            backfilled += 1
            state_changed = True
        else:
            candidates.append((entry, entry_id, timestamp))

    # Tout candidat devient "en attente" avant l'appel au backend. Ainsi, un
    # crash ou un echec de notification ne le transformera jamais en vieux
    # backfill silencieux lorsque le watermark aura avance entre-temps.
    for _entry, entry_id, _timestamp in candidates:
        if entry_id not in state.pending_ids:
            state.pending_ids.add(entry_id)
            state_changed = True

    state.newest_timestamp = baseline
    state.legacy = False
    if was_legacy or fingerprint_missing or state_changed or baseline != stored_watermark:
        save_feed_state(key, state)

    sent = 0
    filtered = 0
    consigne = str(feed.get("filtre_ia") or "").strip()
    for entry, entry_id, timestamp in reversed(candidates):
        raison = ""
        if consigne:
            try:
                verdict = filtre_ia.juger(consigne, entry)
            except filtre_ia.FiltreIndisponible as exc:
                # Sans verdict, on notifie quand meme en le disant : perdre une
                # entree en silence serait pire qu'une notification de trop.
                raison = f"(filtre IA indisponible : {exc})"
                print(f"[{label}] filtre IA indisponible, notification sans tri : {exc}")
            else:
                if not verdict.pertinent:
                    print(f"[{label}] ecartee par le filtre IA : {entry.get('title', '')!r} ({verdict.raison})")
                    state.seen_ids.add(entry_id)
                    state.pending_ids.discard(entry_id)
                    save_feed_state(key, state)
                    filtered += 1
                    continue
                raison = verdict.raison
        try:
            notify(label, entry, raison) if raison else notify(label, entry)
        except Exception as exc:
            print(f"[{label}] notif ratee pour une entree, on continue: {exc}")
            continue
        # Marquee vue seulement apres succes, et sauvee tout de suite : si une
        # notif suivante plante, celles deja envoyees ne repartent pas au
        # prochain cycle.
        state.seen_ids.add(entry_id)
        state.pending_ids.discard(entry_id)
        save_feed_state(key, state)
        sent += 1

    if current_newest is not None:
        next_watermark = max(
            value for value in (state.newest_timestamp, current_newest) if value is not None
        )
        if next_watermark != state.newest_timestamp:
            state.newest_timestamp = next_watermark
            save_feed_state(key, state)
    if backfilled:
        print(f"[{label}] {backfilled} ancienne(s) entree(s) memorisee(s) sans notification.")
    if sent:
        print(f"[{label}] {sent} nouvelle(s) notif(s) envoyee(s).")
    if filtered:
        print(f"[{label}] {filtered} entree(s) ecartee(s) par le filtre IA.")


class SharedState:
    """Etat partage entre poll_loop (thread de fond), le serveur HTTP (un
    thread par requete) et le tray (thread principal), protege par un
    verrou. Remplace les signaux Qt (UpdateSignals) et les attributs
    d'instance de l'ancien TrayApp : ceux-la ne servaient qu'a traverser
    sans risque la frontiere entre threads, ce que ce verrou fait tout
    aussi bien sans dependre de la boucle d'evenements Qt."""

    def __init__(self, pause_event: threading.Event):
        self._lock = threading.Lock()
        self.pause_event = pause_event
        # L'installation d'une mise à jour est conduite par l'Installateur
        # du commun (nico579_commons.maj_install), créé avec les routes :
        # build_api_routes() le pose ici pour le menu de l'icône.
        self.installateur = None


def poll_loop(state: SharedState) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    print("watch2notif demarre.")

    next_due: dict = {}
    notified_version = None

    while True:
        # Try/except large et non specifique : un config.json corrompu par
        # une ecriture concurrente, ou une panne reseau sur le check de
        # version, ne doivent jamais tuer ce thread daemon. Le tray, lui,
        # continuerait de tourner sans plus rien poller, en ayant l'air
        # normal - constate en revue de code, pas en test.
        try:
            config = load_config()
            lang = config.get("lang") or i18n.detect_default_lang()
            default_interval = config.get("poll_interval_seconds", 60)

            # La pause (menu tray) ne concerne que les sources suivies :
            # elle ne doit pas retarder la veille de sortie d'une nouvelle
            # version de watch2notif lui-meme, un evenement distinct qu'on
            # veut voir meme "en vacances" (trouve en audit : le `continue`
            # precoce sautait aussi le bloc plus bas, jamais rejoue tant que
            # la pause dure, potentiellement des semaines).
            if not state.pause_event.is_set():
                active_feeds = [f for f in config["feeds"] if f["enabled"] and f["url"]]

                if not active_feeds:
                    print("aucune source active dans config.json (ouvre les reglages depuis le tray).")

                now = time.time()
                for feed in active_feeds:
                    key = feed["key"]
                    if now < next_due.get(key, 0):
                        continue
                    interval = feed.get("interval_seconds") or default_interval
                    try:
                        poll_feed(feed)
                    except Exception as exc:
                        print(f"[{feed['label']}] erreur, on reessaie au prochain cycle: {exc}")
                    next_due[key] = now + interval

            info = VERIFICATEUR.disponible()
            if info and info["version"] != notified_version:
                notified_version = info["version"]
                notify_backend.notify(
                    title=i18n.t("update_notif_title", lang),
                    message=i18n.t("update_notif_body", lang, version=info["version"], current=update_check.VERSION),
                    url=info.get("page") or "",
                )
                print(f"nouvelle version disponible: {info['version']}")
        except Exception as exc:
            print(f"erreur dans le cycle de poll, on reessaie au prochain: {exc}")

        time.sleep(5)


def _installateur(stop_event: threading.Event):
    """L'installation automatique d'une version plus récente, conduite en fond
    (nico579_commons.maj_install) : rafraîchir la release, préparer, lancer
    l'assistant externe, lui donner le feu vert, puis lever stop_event, qui
    referme l'icône et rend la main à main() pour laisser l'assistant échanger
    les dossiers."""
    return maj_install.Installateur(
        self_update.APP, update_check.DEPOT, VERIFICATEUR, self_update.install_layout,
        quitter=stop_event.set)


def _tray_disponible() -> bool:
    """Faux si pystray ou son image ne peuvent pas etre charges ici :
    bibliotheque absente, ou aucun backend de zone de notification (Linux
    sans AppIndicator/GTK, session sans affichage). Garde commune aux
    quatre applications, dans nico579_commons.tray."""
    return apptray.disponible()


def _langue_tray() -> str:
    try:
        return load_config().get("lang") or i18n.detect_default_lang()
    except (OSError, json.JSONDecodeError, AttributeError):
        return i18n.detect_default_lang()


def _actions_tray(url: str, state: SharedState, stop_event: threading.Event,
                  arreter_serveur) -> apptray.Actions:
    """Ce que watch2notif donne au menu, le meme dans les quatre
    applications : Ouvrir, Mettre a jour quand une version est connue,
    Redemarrer, Arreter, Creer un raccourci sur le Bureau. Pause,
    historique et aide sont dans la page qu'ouvre Ouvrir."""

    def _version_disponible():
        info = VERIFICATEUR.disponible()
        return info["version"] if info else None

    def _mettre_a_jour() -> None:
        # Installation directe quand elle est possible, meme chemin que le
        # bandeau de la page ; l'icone reste pendant le telechargement, et
        # l'Installateur leve stop_event une fois l'assistant pret. Sinon
        # (sources, dossier non inscriptible...), ou si un telechargement
        # est deja en cours, la page dit ou en est la mise a jour.
        installateur = state.installateur
        if (installateur is not None and installateur.possible()[0]
                and installateur.demarrer()):
            return
        webbrowser.open(url)

    def _redemarrer() -> None:
        # Port et verrou liberes avant la relance : le nouveau process
        # demarre pendant que celui-ci finit de sortir.
        arreter_serveur()
        single_instance.release()
        # Sortie standard explicite : sans elle, un process sans console (cas de
        # l'executable) la remplace par un tube que ce process emporte en sortant.
        relance.relancer(autostart_manager.notifier_command(), nom="watch2notif",
                         cwd=str(autostart_manager.PROJECT_DIR),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _creer_raccourci() -> None:
        # --settings : ouvre la page, que watch2notif tourne deja ou non.
        raccourci.creer("watch2notif", autostart_manager.notifier_command() + ["--settings"],
                        autostart_manager.PROJECT_DIR, icone=ICON_FILE,
                        description="watch2notif", langue=_langue_tray())

    return apptray.Actions(
        ouvrir=lambda: webbrowser.open(url),
        redemarrer=_redemarrer,
        arreter=arreter_serveur,
        version_disponible=_version_disponible,
        mettre_a_jour=_mettre_a_jour,
        mettre_a_jour_referme=False,
        creer_raccourci=_creer_raccourci,
        langue=_langue_tray,
    )


def _construire_tray(url: str, state: SharedState, stop_event: threading.Event,
                     arreter_serveur=lambda: None) -> apptray.Tray:
    """L'icone de zone de notification, par nico579_commons.tray : menu
    reconstruit toutes les 5 s (le backend win32 de pystray garderait
    sinon celui du demarrage), sur le fil principal sous macOS, actions
    d'arret hors de la pompe de messages. stop_event sert d'arret :
    Arreter, Redemarrer, et la fin d'une mise a jour installee (l'Installateur,
    qui n'a pas acces a l'icone) referment l'icone et rendent la main a main()."""
    return apptray.Tray("watch2notif", ICON_FILE,
                        _actions_tray(url, state, stop_event, arreter_serveur),
                        arret=stop_event)


def build_api_routes(pause_event: threading.Event, state: SharedState, stop_event: threading.Event) -> tuple:
    """Construit (api_routes, post_routes) pour serveweb.demarrer().
    Fonction a part de main() : un test peut ainsi monter le vrai serveur
    avec les vraies routes sur un port dedie, sans passer par
    single_instance/la reprise des donnees/le tray - juste l'API HTTP."""

    def _api_strings() -> dict:
        return i18n.STRINGS

    def _api_state() -> dict:
        return {
            "version": update_check.VERSION,
            # Affiches en tete de page, comme blink2video : quelle version
            # repond, et quel processus arreter si besoin.
            "pid": os.getpid(),
            "config": load_config(),
            "providers": {
                kind: {
                    "label": provider.LABEL,
                    "default_interval_seconds": getattr(provider, "DEFAULT_INTERVAL_SECONDS", 60),
                }
                for kind, provider in PROVIDERS.items()
            },
            "default_kind": DEFAULT_KIND,
            "paused": pause_event.is_set(),
        }

    def _api_history() -> dict:
        return {"entries": notification_history.load()}

    def _api_save_config(payload: dict) -> dict:
        with _config_lock:
            config = load_config()
            known_kinds = {feed.get("key"): feed.get("kind")
                           for feed in config.get("feeds") or [] if isinstance(feed, dict)}
            feeds = build_feeds_from_rows(payload.get("feeds") or [], known_kinds)
            config["feeds"] = feeds
            config["lang"] = payload.get("lang") or config.get("lang") or i18n.detect_default_lang()
            save_config(config)

        return {"ok": True, "feeds": feeds}

    def _api_set_pause(payload: dict) -> dict:
        if payload.get("paused"):
            pause_event.set()
        else:
            pause_event.clear()
        return {"ok": True, "paused": pause_event.is_set()}

    def _api_clear_history(_payload: dict) -> dict:
        notification_history.clear()
        return {"ok": True}

    # Le bandeau de mise a jour de la page est celui du commun
    # (nico579_commons.maj_install.routes, maj_banniere.js) : /api/maj et
    # /api/maj-installer.
    state.installateur = _installateur(stop_event)
    routes_maj_get, routes_maj_post = maj_install.routes(state.installateur, _langue_tray)

    # La case « Demarrer automatiquement avec le systeme » est celle du commun
    # (/api/autostart, dessinee par reglages.js dans le panneau Reglages) : plus
    # un champ de ce formulaire, donc enregistrer les flux n'y touche pas.
    routes_demarrage_get, routes_demarrage_post = demarrage.routes(autostart_manager.entree, _langue_tray)

    def _lire_langue():
        try:
            return load_config().get("lang")
        except (OSError, json.JSONDecodeError, AttributeError):
            return None

    def _ecrire_langue(code: str) -> None:
        with _config_lock:
            config = load_config()
            config["lang"] = code
            save_config(config)

    # Le choix FR / EN est celui du commun (/nico579-langue.js) ; le menu de l'icone le relit.
    routes_langue_get, routes_langue_post = langue.routes(_lire_langue, _ecrire_langue)

    api_routes = {"strings": _api_strings, "state": _api_state, "history": _api_history,
                  **routes_maj_get, **routes_demarrage_get, **routes_langue_get}
    post_routes = {
        "save-config": _api_save_config,
        "set-pause": _api_set_pause,
        "clear-history": _api_clear_history,
        **routes_maj_post,
        **routes_demarrage_post,
        **routes_langue_post,
    }
    return api_routes, post_routes


def main() -> None:
    # Avant tout lancement de programme du systeme (xdg-open, systemctl,
    # navigateur) : sous Linux, le binaire leur transmettrait sinon ses
    # propres bibliotheques (issue #23 de blink2video).
    environnement.retablir_environnement_systeme()
    try:
        data_paths.DOSSIERS.preparer_etat(data_paths.INSTALL_DIR)
    except (OSError, TimeoutError) as exc:
        print(f"reprise des donnees d'une ancienne installation reportee ({exc}).")
    url = f"http://127.0.0.1:{PORT}/"

    if not single_instance.acquire(data_paths.DATA_DIR):
        # Autostart + lancement manuel, ou double-clic accidentel : pas
        # d'erreur bruyante pour un poller de fond. --settings explicite
        # reste utile meme dans ce cas : rejoindre les reglages de
        # l'instance deja active plutot que de ne rien faire.
        if "--settings" in sys.argv[1:]:
            webbrowser.open(url)
        else:
            print("une instance de watch2notif tourne deja, arret.")
        return

    # Demarrage automatique d'une version <= 0.2.3 (script .vbs) : meme
    # choix, nouveau mecanisme (raccourci .lnk). Jamais bloquant.
    try:
        if autostart_manager.migrer_ancien_demarrage():
            print("demarrage automatique : script .vbs remplace par un raccourci.")
    except Exception as exc:
        print(f"demarrage automatique : migration impossible ({exc}).")

    first_run = not CONFIG_FILE.exists()
    if first_run:
        save_config(default_config())

    pause_event = threading.Event()
    state = SharedState(pause_event)
    stop_event = threading.Event()
    api_routes, post_routes = build_api_routes(pause_event, state, stop_event)

    try:
        server = serveweb.demarrer(
            bind=BIND, port=PORT, trusted_host="", gui_dir=GUI_DIR,
            api_routes=api_routes, post_routes=post_routes, favicon=ICON_FILE,
        )
    except OSError as exc:
        print(f"impossible d'ecouter sur {BIND}:{PORT}: {exc}")
        return

    print(f"watch2notif web GUI: {url}")
    if first_run or "--settings" in sys.argv[1:]:
        threading.Timer(0.5, webbrowser.open, [url]).start()

    VERIFICATEUR.veiller(stop_event)
    threading.Thread(target=poll_loop, args=(state,), daemon=True).start()

    def _arreter_serveur():
        server.shutdown()
        server.server_close()

    if "--no-tray" in sys.argv[1:]:
        print("--no-tray: Ctrl+C pour arreter.")
        try:
            stop_event.wait()
        except KeyboardInterrupt:
            pass
        _arreter_serveur()
        print("watch2notif arrete.")
        return

    if not _tray_disponible():
        print("zone de notification indisponible ici (pas d'affichage/AppIndicator) - Ctrl+C pour arreter.")
        try:
            stop_event.wait()
        except KeyboardInterrupt:
            pass
        _arreter_serveur()
        print("watch2notif arrete.")
        return

    print("regarde dans la zone de notification pour l'icone watch2notif.")
    # Bloque jusqu'a Arreter, Redemarrer, ou la fin d'une mise a jour.
    _construire_tray(url, state, stop_event, _arreter_serveur).executer()

    _arreter_serveur()
    print("watch2notif arrete.")


if __name__ == "__main__":
    if "--self-test-version" in sys.argv[1:]:
        try:
            expected_version = sys.argv[sys.argv.index("--self-test-version") + 1]
        except (ValueError, IndexError):
            raise SystemExit(2)
        if expected_version != update_check.VERSION or not ICON_FILE.is_file():
            raise SystemExit(3)
        # Les fichiers JavaScript communs (bandeau de mise à jour, bouton Réglages)
        # doivent être dans le bundle : sans eux la page en réclame un qui n'existe pas.
        if serveweb.fichiers_manquants():
            print("auto-test : fichiers communs absents du bundle :",
                  ", ".join(serveweb.fichiers_manquants()))
            raise SystemExit(4)
        raise SystemExit(0)
    try:
        main()
    except KeyboardInterrupt:
        print("\narret demande, bye.")
