*[English](README.md) | **Français***

# watch2notif

Application pour PC et Android qui surveille des sources (flux RSS/Atom, issues
GitHub, commentaires YouTube...) et affiche une notification native et
cliquable quand quelque chose de nouveau apparait. Cross-platform
(Windows/Linux/macOS/Android).

Parti d'un besoin de surveiller son inbox Reddit (via les flux RSS prives
de reddit.com/prefs/feeds), puis generalise : n'importe quel flux
RSS/Atom fonctionne, plus les issues GitHub sur les repos publics (pas
d'auth necessaire), les reponses a une discussion GitHub, et les
commentaires de video YouTube. Ajouter un nouveau type de source =
ajouter un module dans `providers/`, rien d'autre a toucher.

## Captures d'ecran

![Panneau de reglage](screenshots/settings.png)
![Menu du tray](screenshots/systray.png)
![Historique des notifications](screenshots/history.png)

## Fonctionnement

- `notifier.py` : boucle de fond, poll les sources activees dans
  `config.json`, chacune avec son propre intervalle, notification
  desktop cliquable (ouvre le lien de la source) sur chaque nouvelle
  entree. Etat "deja vu" garde par source dans `state/`. `config.json`,
  `state/` et l'historique des notifications vivent dans le dossier de
  donnees standard de l'OS (`%APPDATA%` sous Windows, dossier XDG sous
  Linux, Application Support sous Mac, via `platformdirs`, voir
  `data_paths.py`), jamais a cote de l'executable : une reinstallation ou
  une reconstruction ne doit jamais les effacer. C'est aussi le
  point d'entree unique du binaire construit : une icone de zone de
  notification (`pystray`, par
  [nico579-commons](https://github.com/nico579/nico579-commons)) au meme
  menu que les trois applications soeurs : Ouvrir (la page de
  reglages/historique, dans le navigateur par defaut), Mettre a jour
  quand une version plus recente existe, Redemarrer, Arreter, et Creer un
  raccourci sur le Bureau. La pause, l'historique et le lien d'aide
  GitHub sont dans la page. Verifie la page de
  releases GitHub toutes les 6h et ajoute cette entree de menu + une
  notification desktop unique quand une nouvelle version sort
  (`update_check.py`). Dans l'application empaquetee, la page de reglages
  propose de l'installer, verifie la taille et le SHA-256 de l'asset,
  puis remplace le bundle apres sa fermeture et le redemarre en conservant
  les reglages et l'historique (`self_update.py`). Un checkout source n'est
  jamais modifie automatiquement.
- `providers/` : un module par type de source (`rss.py`,
  `github_issues.py`, `github_discussion.py`, `youtube_comments.py`),
  chacun expose `fetch_entries(source) -> list[Entry]`.
  Ajouter un type de source = ajouter un module ici, rien d'autre ne
  change.
- `gui/` + `nico579_commons.serveweb` : page de reglages/historique (ajouter/retirer
  des sources, choisir leur type, regler leur intervalle de polling
  individuel, activer l'autostart, parcourir les 200 dernieres
  notifications envoyees, double-clic sur une ligne pour rouvrir son
  lien), servie en HTTP local (stdlib `http.server`, aucun framework) et
  ouverte dans le navigateur par defaut du systeme - meme architecture
  que les projets jumeaux lidar2map et blink2video. Bilingue FR/EN,
  bascule en haut a droite. Accessible depuis l'entree Ouvrir du tray, ou
  avec `notifier.py --settings`.
- `notify_backend.py` : backend de notification par OS - `win11toast`
  (Windows, toast WinRT moderne, bon nom d'appli, cliquable), `pync`
  (Mac, via terminal-notifier, cliquable), `plyer` (Linux, pas encore
  cliquable).
- `autostart_manager.py` : active/desactive l'autostart selon l'OS
  (raccourci dans le dossier Demarrage sous Windows, service utilisateur
  systemd sous Linux, launchd sous Mac). Detecte le mode fige
  PyInstaller pour pointer vers le binaire construit plutot que le
  script Python.

## Installation

### Depuis les sources

```bash
pip install -r requirements.txt
python notifier.py   # le premier lancement ouvre la page de reglages dans le navigateur
```

### Binaire autonome

Chaque release fournit des bundles pre-construits (Windows/Linux/Mac) sur
la page [Releases](../../releases), sans Python a installer : un seul
executable, `watch2notif`. Le lancer demarre la surveillance ; la page de
reglages/historique s'ouvre depuis son icone de tray (Ouvrir) ou
avec `watch2notif --settings`.

Lorsqu'une mise a jour compatible est publiee, la page de reglages affiche
un bandeau avant tout telechargement. "Telecharger et installer", ou
Mettre a jour dans le menu du tray, prepare
et valide le nouveau bundle complet ; watch2notif ne se ferme que lorsque
le programme de remplacement externe est pret, puis redemarre sur la
nouvelle version. Si la preparation, le remplacement ou le redemarrage
echoue, l'installation courante est conservee ou restauree. Une
plateforme non prise en charge retombe sur la page de la release.

### Application Android

Télécharger **watch2notif-android.apk** dans la
[dernière release GitHub](https://github.com/nico579/watch2notif/releases/latest),
puis ouvrir le fichier sur le téléphone et autoriser son installation.
L’APK signé et les bundles desktop sont construits et testés sur GitHub Actions,
puis publiés ensemble. L’AAB Android est également disponible pour une boutique.
La signature reste identique entre les releases ; une ancienne installation
debug doit être désinstallée avant de passer à l’APK de release.

L’application native fonctionne directement sur Android 8.0 ou plus récent,
avec les mêmes types de sources, un historique et un filtre Claude facultatif
par source. Autoriser les notifications pour recevoir les alertes. La
surveillance automatique vérifie les sources au minimum toutes les 15 minutes ;
le mode rapide utilise leurs intervalles avec une notification permanente.
Android peut retarder la surveillance selon la batterie et la connectivité.
Voir le [guide Android](android/README.md) pour les réglages et les limites.

### Partager les réglages du PC vers Android

1. Installer les versions PC et Android de la même release, puis connecter
   les deux appareils au même réseau local.
2. Sur le PC, cliquer **Envoyer vers le téléphone** dans l’onglet **Flux**.
3. Sur Android, ouvrir **Réglages → Scanner le QR du PC**, autoriser la caméra,
   scanner le QR et confirmer l’import.

Les sources, leurs intervalles, leur activation, les consignes Claude et les
clés `GITHUB_TOKEN`, `YOUTUBE_API_KEY` et `ANTHROPIC_API_KEY` du processus PC
sont transférés avec un chiffrement authentifié AES-256-GCM. La clé de
déchiffrement vient uniquement du QR. Le code expire après deux minutes,
ne fonctionne qu’une fois et le PC referme le port après usage ou annulation.
Aucun service cloud ni accès entrant permanent n’est nécessaire.

L’import remplace les sources du téléphone et établit une référence initiale
silencieuse. L’historique reste propre à chaque appareil. Les clés Android sont
chiffrées dans le stockage privé de l’application avec Android Keystore.
Ne pas diffuser le QR : il permet d’accéder à la configuration et aux clés.

**Importer/Exporter un JSON** reste disponible sur les deux appareils pour
les sources et les consignes Claude, sans clés API ni historique. Les URLs
RSS privées peuvent toutefois contenir un token : privilégier le QR pour
les transférer. Sur le PC, cliquer **Sauvegarder** après un import JSON.

## Construction et tests sur GitHub

GitHub Actions construit les bundles Windows, Linux et macOS ainsi que l’APK
et l’AAB Android à chaque étiquette `v*`. Les tests Python sur les trois OS,
les tests Android/Robolectric, Android Lint et le lancement de contrôle des
exécutables conditionnent la publication. Aucun binaire construit localement
n’est téléversé dans les releases.

Les pull requests et les changements de `master` exécutent également la CI.
Voir [.github/workflows/ci.yml](.github/workflows/ci.yml),
[android.yml](.github/workflows/android.yml) et
[release.yml](.github/workflows/release.yml).

## Sources

### RSS/Atom (n'importe quel flux)

N'importe quelle URL RSS/Atom valide fonctionne. Pour Reddit
specifiquement : sur `https://www.reddit.com/prefs/feeds/`, chaque flux
(inbox, front page, saved, upvoted...) a un lien RSS/JSON avec un token
prive dans l'URL. Ce token n'expire pas tant que le mot de passe du
compte ne change pas. Ne pas partager ces URLs : elles donnent un acces
en lecture au contenu prive associe.

L'API Data Reddit classique (OAuth, ce qu'utilise `praw`) exige
desormais un cas d'usage de moderation pour enregistrer une nouvelle
application. Ces flux RSS prives restent une fonctionnalite officielle,
sans ce blocage, suffisante pour un usage personnel de lecture.

Les forums batis sur SMF (Simple Machines Forum, un moteur de forum PHP
courant) exposent un flux RSS natif par sujet, sans plugin : ajouter
`?action=.xml;type=rss2;topic=<id>.0` a l'URL `index.php` du forum, ou
`<id>` est l'identifiant numerique du sujet, visible dans l'URL du sujet
lui-meme (`index.php?topic=<id>.<offset>`). Il ne renvoie que les
messages de ce fil, ce qui en fait un watcher "prevenir des nouvelles
reponses a mon post" tout fait.

### Issues GitHub (repos publics)

Entre `owner/repo` comme source. Utilise l'API REST publique de GitHub,
pas d'authentification necessaire pour les repos publics. Limite a 60
requetes/heure par IP sans token, 5000/heure avec un token (variable
d'environnement `GITHUB_TOKEN`). Si le CLI `gh` est deja installe et
connecte, `gh auth token` en affiche un ; sinon, en creer un a la main
sur GitHub.com : menu avatar -> Settings -> Developer settings ->
Personal access tokens -> Tokens (classic) -> Generate new token
(classic). Aucune case a cocher pour un acces lecture seule aux repos
publics, le token doit juste exister pour authentifier la requete et
lever la limite par IP. Prefere un intervalle plus long (quelques
minutes) pour ce type de source, pour rester sous la limite sans token.

### Reponses a une discussion GitHub

Entre `owner/repo#numero` comme source (le numero apres `/discussions/`
dans l'URL). Surveille un fil de discussion precis et signale les
nouveaux commentaires et reponses. Contrairement aux issues, les
Discussions n'ont aucune API REST : ceci passe par l'API GraphQL de
GitHub, qui refuse les requetes anonymes meme sur un repo public. La
variable d'environnement `GITHUB_TOKEN` est donc obligatoire, pas juste
un bonus de limite de debit (meme variable que pour les issues GitHub,
voir plus haut pour l'obtenir).

### GitHub Sponsors

Entre ton identifiant GitHub (ou celui d'une organisation) comme source.
GitHub n'envoie aucune notification quand quelqu'un devient nouveau sponsor
([confirme ici](https://github.com/orgs/community/discussions/41675)) :
consulter le tableau de bord Sponsors a la main reste sinon le seul moyen
de le savoir. Passe par l'API GraphQL comme les reponses de discussion
GitHub, donc `GITHUB_TOKEN` est requis la aussi, mais avec en plus le scope
`read:user` par-dessus les scopes habituels : ce scope est ce qui expose un
identifiant stable pour un sponsor reste anonyme (son profil est cache,
mais le parrainage lui-meme garde un identifiant distinct, donc un
deuxieme sponsor anonyme n'est jamais confondu avec le premier). Un
evenement rare compare a une reponse de discussion, d'ou un intervalle par
defaut plus long.

### Commentaires YouTube

Entre une URL de video (n'importe quel format courant) ou un ID brut
comme source. Surveille une video et signale les nouveaux commentaires
de premier niveau et leurs reponses visibles. YouTube expose un flux
Atom pour les nouvelles videos d'une chaine, mais aucun pour les
commentaires d'une video : ceci passe par l'API YouTube Data v3. Necessite
une cle API gratuite : Google Cloud Console -> APIs & Services -> activer
"YouTube Data API v3" -> Credentials -> Create API key, puis definir la
variable d'environnement `YOUTUBE_API_KEY`. Cout de quota : 2 unites par
sondage (quota gratuit de 10000/jour), donc l'intervalle par defaut est
une question de courtoisie, pas de necessite de quota.

## Filtre IA (facultatif)

Certaines sources sont trop larges pour etre utiles telles quelles. Une
recherche Reddit sur "local storage" dans un subreddit de cameras remonte
les personnes a qui votre outil rendrait service, mais aussi des plaintes
de facturation et des photos de cameras neuves. Les mots seuls ne font pas
la difference ; la lecture du message, si.

Chaque source a un bouton **Filtre IA**. Il ouvre une zone de texte ou
l'on decrit, en langage courant, les entrees qui meritent une
notification, par exemple : "Les questions de personnes qui veulent
garder ou telecharger leurs clips Blink sans abonnement. Pas les plaintes
de facturation, pas les problemes de detection de mouvement." Avant de
notifier une nouvelle entree, watch2notif envoie son titre et son texte a
Claude Haiku avec cette consigne, et ne notifie que celles qu'il juge
pertinentes, avec en tete de la notification une phrase qui dit pourquoi.
Les autres sont memorisees comme vues et ne reviennent jamais. Une zone
vide veut dire : pas de filtre.

Il faut une cle d'API Anthropic dans la variable d'environnement
`ANTHROPIC_API_KEY` (console.anthropic.com). L'API se paie a l'usage, a
part de tout abonnement Claude ; trier quelques dizaines de messages par
mois avec Haiku coute quelques centimes. Si la cle manque ou que l'API ne
repond pas, watch2notif notifie quand meme et le dit dans la
notification : une entree n'est jamais perdue en silence.

## Ajouter un type de source

Un provider est un module dans `providers/` qui expose deux choses :

- `LABEL` : nom affiche dans la liste des types de source du panneau de
  reglage.
- `fetch_entries(source) -> list` : prend la chaine de source saisie par
  l'utilisateur (une URL, `owner/repo`...) et renvoie la liste actuelle
  des entrees. Chaque entree doit exposer `.id` et `.get(key, default)`,
  la forme dont `notifier.py` a besoin pour detecter les nouvelles
  entrees et lire `title`, `author`, `link`, `summary`.

`SOURCE_HINT` est optionnel : texte indicatif affiche dans le panneau de
reglage a cote du champ de saisie de la source.

Si les donnees brutes sont deja des objets avec `.id`/`.get()` (comme
les entrees feedparser dans `rss.py`), les renvoyer directement. Sinon,
envelopper chaque element dans `providers.base.Entry(id, title, author,
link, summary)`, comme le fait `github_issues.py` pour l'API JSON de
GitHub.

Enregistrer ensuite le module dans le dict `PROVIDERS` de
`providers/__init__.py` (cle = type interne, valeur = le module). Rien
d'autre ne change : `notifier.py` et la page de reglages (`gui/`)
recuperent tout provider enregistre via `PROVIDERS`, sans branchement
specifique par provider.

Android conserve ce principe avec une interface Java commune, une classe par
provider et un registre dans [ProviderRegistry.java](android/app/src/main/java/io/github/nico579/watch2notif/ProviderRegistry.java).
Le registre fournit les types disponibles, les libellés, les indications de
saisie et les intervalles ; le moteur de surveillance et l’interface restent
communs. Chaque provider valide sa source et gère ses propres besoins de clés.
Pour ajouter un type sur les deux plateformes, fournir les implémentations
Python et Java avec le même identifiant `kind`, puis ajouter sa compatibilité
au format de transfert. Android exécute son implémentation native.

## Alternatives existantes

Des lecteurs RSS generalistes (RSS Guard, QuiteRSS...) font deja du
polling de flux avec notifications desktop, mais ne couvrent pas les
sources non-RSS comme l'API issues de GitHub. `watch2notif` reste
minimaliste (pas de lecteur d'articles) et integre l'autostart, les
notifications cliquables, et un petit systeme de providers pour ajouter
des types de sources.

## Licence

GPLv3, voir `LICENSE`.
