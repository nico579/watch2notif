# watch2notif Android

Application native Java, Android 8.0 ou plus récent (`minSdk 26`, cible Android 16).
Elle fonctionne directement sur le téléphone, sans serveur permanent ni Python.
Les données restent dans le stockage privé de l’application.

## Installation et construction sur GitHub

Télécharger **watch2notif-android.apk** dans la
[dernière release GitHub](https://github.com/nico579/watch2notif/releases/latest),
ouvrir le fichier sur le téléphone et autoriser son installation. L’APK de
release porte une signature stable ; les versions suivantes conservent les
réglages lors de leur installation. Une ancienne version debug utilise une
autre signature et doit être désinstallée avant de passer au canal de release.
L’AAB est également publié pour la distribution via une boutique Android.

Tous les fichiers publiés sont construits par **GitHub Actions**, avec le SDK
Android du runner. Aucun binaire compilé localement n’est téléversé. Les
pull requests et les changements de `master` exécutent les tests unitaires,
Robolectric et Android Lint. Les rapports et les captures des écrans sont
disponibles dans les artefacts de ces exécutions.

Une étiquette `v*` déclenche la construction des bundles Windows, Linux, macOS,
de l’APK et de l’AAB. La publication attend la réussite des tests et de chaque
construction. Le workflow **Release** peut aussi être relancé depuis l’onglet
Actions en indiquant l’étiquette existante.

Le numéro de version est lu dans `../update_check.py` et vérifié contre
l’étiquette de release. Le wrapper Gradle est livré avec une somme SHA-256
de sa distribution.

## Installer les mises à jour depuis l’application

Dans **Réglages → Mises à jour de l’application**, rechercher une version,
la télécharger, puis appuyer sur **Installer la mise à jour**. L’application
consulte également les releases à son ouverture, avec un cache en mémoire de
six heures. Le premier lancement de l’installateur peut ouvrir l’autorisation
Android d’installer des applications depuis watch2notif ; revenir ensuite et
appuyer de nouveau sur Installer. Android demande la confirmation finale.
Une annulation conserve le téléchargement vérifié pour réessayer.

Seules les releases stables du dépôt `nico579/watch2notif` sont proposées.
Les requêtes HTTPS et leurs redirections sont limitées aux domaines GitHub
officiels, sans utiliser les tokens des providers. La taille et le SHA-256 de
l’APK sont vérifiés (digest de la release ou `SHA256SUMS.txt`), puis son package,
sa version et sa signature sont comparés à l’application installée. L’APK est
vérifié de nouveau avant d’être remis à l’installateur. Il reste dans le cache
privé ; le FileProvider n’expose que le dossier de mises à jour et donne un accès
en lecture au fichier choisi. La progression survit aux rotations d’écran.
Les sources et clés chiffrées sont conservées lors d’une installation de même
signature. Les opérations de mise à jour utilisent un thread distinct des
vérifications des providers et de la réception du QR.

## Tester les accès après un import

**Réglages → Identifiants des API → Tester les accès** utilise les clés
enregistrées et interroge réellement chaque source activée avec son provider.
Les sources désactivées sont ignorées. Le bilan reste visible et survit à une
rotation : accès réussi, clé manquante, HTTP 401 (authentification), HTTP 403
(droits, activation de l’API ou quota), HTTP 429 (limite du service), erreur
de réponse ou de réseau. Trois requêtes au maximum s’exécutent en parallèle ;
le test s’arrête au bout de deux minutes et signale les vérifications restantes.
Il ne modifie pas les identifiants vus, notifications en attente ou historiques.

Une clé Claude configurée, ou une source avec filtre IA, déclenche un unique
appel au même modèle utilisé pour filtrer les nouveautés. L’appel contient un
court message de diagnostic, sans texte des sources, et est facturé par
l’API Anthropic. Une clé absente alors qu’un filtre est actif est un échec ;
Claude sans clé ni filtre configuré est ignoré. Un accès aux sources réussi
ne valide pas à lui seul la clé Claude. Le succès prouve l’accès au moment du
test ; les clés, droits, quotas et réseaux peuvent changer ensuite.

Le bilan de **Vérifier maintenant** distingue aussi les réussites et les échecs.
Chaque carte de source affiche son dernier accès réussi ou son erreur actuelle.

## Recevoir la configuration du PC par QR

1. Installer le bundle desktop de la même release GitHub et
   démarrer watch2notif sur le PC. Les clés sont celles des
   variables `GITHUB_TOKEN`, `YOUTUBE_API_KEY` et `ANTHROPIC_API_KEY` du processus.
2. Connecter PC et téléphone au même réseau local ; le PC peut être en Ethernet
   et le téléphone en Wi-Fi. Dans les réglages PC, cliquer **Envoyer vers le téléphone**.
3. Sur Android : **Réglages → Scanner le QR du PC**. Autoriser la caméra,
   scanner le QR, puis confirmer l’import des sources et des clés. La réception
   affiche une progression immédiatement, même si une vérification des sources
   est en cours, et se termine sous 30 secondes ou affiche une erreur persistante.

Une rotation de l’écran conserve la réception et sa confirmation. Le QR et les
clés reçues restent uniquement en mémoire jusqu’à la confirmation ou l’annulation ;
ils ne sont pas ajoutés à l’état sauvegardé de l’écran. Après un redémarrage du
processus Android, générer un nouveau QR. Une confirmation d’import réussi reste
affichée jusqu’à son acquittement.

Le QR contient une adresse IPv4 privée et un port temporaire, un code aléatoire
à usage unique et une clé AES de 256 bits. Il expire au bout de **120 secondes**.
Le serveur PC ne démarre qu’à la demande et écoute uniquement sur l’interface
LAN choisie. Android demande une seule fois `/v1/config` par POST ; le code ne
figure pas dans l’URL. Le PC renvoie du JSON **chiffré et authentifié avec
AES-256-GCM**, consomme le code avant d’envoyer la réponse, puis ferme le port.
La clé de déchiffrement n’est jamais envoyée sur le réseau : elle vient du QR.
Fermer la fenêtre ou laisser expirer le QR ferme aussi l’accès. Les requêtes
ne sont pas journalisées et aucun fichier de transfert n’est créé.

Les sources, leurs intervalles, leurs activations, les consignes `filtre_ia`
et les trois clés API sont transférés. L’historique et les états « déjà vu »
restent propres à chaque appareil. Les anciennes sources Android sont remplacées
et une nouvelle première vérification établit leur référence sans notifications.
Une clé absente sur le PC conserve la clé déjà configurée sur Android.
L’import des sources et des identifiants chiffrés est enregistré atomiquement.

Le QR donne accès aux réglages et aux clés : ne pas le diffuser. Vérifier
l’interface choisie dans la fenêtre PC et utiliser le réseau du téléphone.
Un réseau invité avec isolation des clients, un VPN bloquant le réseau local
ou le pare-feu peut empêcher la connexion. Sur Windows, **Autoriser le transfert
local** demande le consentement administrateur pour une règle TCP limitée au
seul exécutable watch2notif, à l’adresse PC choisie et au sous-réseau local
(profils Privé/Public). La règle reste enregistrée ; le serveur reste temporaire,
fermé après usage, annulation ou 120 secondes. Le consentement permet de remplacer
les blocages TCP généraux du seul exécutable sur le profil Public par cette
permission limitée. Les blocages UDP, Privé, Domaine, gérés ou plus spécifiques
restent en place et peuvent empêcher le transfert. Le profil réseau n’est pas modifié.
La demande UAC utilise directement Windows et ne lance pas de console PowerShell.
L’ancien QR est fermé pendant l’autorisation ; le PC en génère un nouveau après
vérification de la règle. La cause d’un échec reste affichée au-dessus du QR.
Le PC conserve également des compteurs bornés de connexions et de requêtes et
un résultat fixe en mémoire, sans enregistrer de corps de requête, de clé,
de code ou d’adresse de client. Ils distinguent l’absence de connexion locale
d’une requête rejetée ou d’une réponse chiffrée interrompue.
Android utilise le Wi-Fi/Ethernet pour cette seule requête, sans proxy ni
changement du routage des autres connexions. L’erreur distingue délai dépassé,
connexion refusée, statut HTTP et QR expiré. Générer et scanner un nouveau QR
après correction. Aucun port Internet ou service cloud n’est nécessaire.
Les réseaux IPv4 privés sont pris en charge (10/8, 172.16/12, 192.168/16).

## Surveillance et notifications

Les providers gardent les mêmes identifiants `kind` que sur PC. Chaque type
dispose de sa classe Java, derrière une interface commune et un registre qui
alimente également le sélecteur de sources, leurs libellés, la validation et
leurs intervalles par défaut. Les besoins de clés sont propres au provider ;
le moteur de surveillance, le filtre Claude et les notifications sont communs.
Ajouter un provider consiste à implémenter ce contrat et à l’enregistrer,
sans ajouter de branchement dans le moteur ou l’écran. La compatibilité du
transfert PC/Android demande le même identifiant et une implémentation sur
chaque plateforme.

- RSS 2.0, RSS 1.0/RDF et Atom ; issues GitHub, discussions et leurs réponses,
  Sponsors (utilisateur ou organisation), commentaires YouTube et réponses
  visibles dans le résultat de l’API.
- Sources modifiables, activables et supprimables, chacune avec son intervalle.
- Première vérification silencieuse ; mémorisation persistante des identifiants,
  des notifications en attente et d’un repère temporel pour absorber les anciennes
  entrées qui réapparaissent. Les 4000 identifiants les plus récents sont conservés
  par source ; un flux sans dates qui republie davantage d’anciens identifiants
  peut donc entraîner des notifications répétées.
- Notifications natives cliquables et historique des 200 dernières notifications.
- Réglages et notifications en français ou anglais, selon l’appareil ou au choix.

**Automatique** : WorkManager planifie une vérification toutes les 15 minutes,
en respectant les intervalles plus longs. Les tâches persistent après redémarrage ;
Android peut les retarder selon la batterie et la connectivité. Un arrêt forcé
de l’application suspend les tâches jusqu’à sa prochaine ouverture.

**Mode rapide** : un service démarré explicitement depuis l’écran utilise les
intervalles des sources, avec une notification permanente et un verrou partiel
qui maintient le processeur disponible écran éteint. Cette session consomme
davantage de batterie. Le verrou est libéré immédiatement à l’arrêt, à la pause,
si toutes les sources sont désactivées, en cas d’erreur et au timeout Android.
Un bail de dix minutes, renouvelé par la boucle saine, évite qu’une boucle
bloquée maintienne indéfiniment le processeur éveillé.

Dans **Réglages → Surveillance en arrière-plan**, le bouton **Autoriser la
surveillance en arrière-plan** ouvre la confirmation Android d’exemption
d’optimisation de batterie. Cette autorisation reste un choix de l’utilisateur ;
sans elle, Doze peut ignorer le verrou et suspendre le réseau. Son état est
affiché dans les sources et les réglages, avec le dernier cycle terminé et le
bilan des derniers accès. Ces compteurs sont locaux, sans URL, identifiants ni
clés ; ils ne figurent pas dans les exports de configuration.

Le service est `START_STICKY` : Android peut recréer une session déjà demandée
après avoir tué son processus, sans réamorcer les sources ni dupliquer les
notifications. Le souhait de surveillance rapide est conservé sur cet appareil.
La pause, la désactivation de toutes les sources et l’action Arrêter le mode
rapide l’effacent. Après un redémarrage du téléphone, le mode automatique
persiste et le mode rapide reprend à la réouverture de l’application ; aucun
service `dataSync` n’est lancé depuis un worker ou un récepteur de démarrage.

Android 15+ limite les services `dataSync` à six heures en arrière-plan sur
24 heures. Le retour de l’application au premier plan réinitialise ce quota.
À expiration, le verrou est libéré, une notification et un état explicite
signalent l’interruption, et les tâches automatiques restent planifiées. Le
mode rapide attend un nouveau démarrage depuis Sources ; il ne contourne pas
le quota. Les restrictions du fabricant, l’économie de batterie et les pertes
de connexion peuvent encore retarder la surveillance. Un arrêt forcé suspend
les deux modes jusqu’à la réouverture.

Références Android : [Doze et exemption de batterie](https://developer.android.com/training/monitoring-device-state/doze-standby),
[reprise d’un service sticky](https://developer.android.com/reference/android/app/Service#START_STICKY),
[limite des services au premier plan](https://developer.android.com/develop/background-work/services/fgs/timeout).

**Vérifier maintenant** effectue une vérification manuelle des sources actives,
y compris pendant une pause. Les notifications bloquées restent en attente,
y compris si elles disparaissent ensuite de la fenêtre du fournisseur.

Les fenêtres des API sont bornées : 30 issues ouvertes, les 100 derniers
commentaires d’une discussion et les 100 dernières réponses par commentaire,
100 sponsors, 100 fils YouTube et leurs réponses incluses. L’application ne
reconstruit pas l’historique complet d’une source très active.

## Claude et stockage des clés

Dans chaque source, **Filtre IA** accepte une consigne en langage courant.
Une consigne vide désactive le filtre. Claude Haiku reçoit le titre, l’auteur
et jusqu’à 4000 caractères du message pour juger sa pertinence. Les entrées
écartées sont mémorisées sans notification ; la raison d’un verdict positif
apparaît dans la notification. Sans clé Claude, en cas d’erreur API ou de
réponse invalide, l’application notifie quand même avec un avertissement.
L’API Anthropic est facturée séparément de l’abonnement Claude.

Les verdicts positifs sont conservés pendant la reprise d’une notification
en échec pour éviter de payer de nouveau le même tri. Quand les notifications
sont désactivées, les entrées restent en attente sans appel payant à Claude.
Modifier une consigne conserve les identifiants déjà vus ; changer l’adresse
ou le type d’une source établit une nouvelle référence.

Les clés GitHub, YouTube et Anthropic peuvent aussi être saisies dans les
réglages. Elles sont chiffrées avec AES-GCM et une clé Android Keystore propre
à l’appareil. Les sauvegardes Android et les exports ordinaires les excluent.
Désinstaller l’application supprime les réglages ; réinstaller l’APK avec la
même signature les conserve.

## Import/export JSON des sources

En complément du QR, les deux interfaces proposent **Importer/Exporter un JSON**.
Le fichier contient les sources et les consignes Claude, sans clés API ni
historique. Il peut toutefois contenir des tokens privés dans les URLs RSS.
Le sélecteur Android permet de transférer le fichier via stockage local, USB,
messagerie ou un fournisseur de documents. L’import PC prépare la table : cliquer
sur **Sauvegarder** pour l’appliquer. L’import Android demande confirmation avant
de remplacer les sources. Jusqu’à 50 sources sont prises en charge.

## Signature de distribution

La signature de release est fournie au runner par les secrets du dépôt GitHub :

```text
ANDROID_KEYSTORE_BASE64
ANDROID_KEYSTORE_PASSWORD
ANDROID_KEY_ALIAS
ANDROID_KEY_PASSWORD
```

La clé privée et les mots de passe ne sont jamais committés ni publiés parmi
les artefacts. Le workflow refuse de publier si les secrets manquent et vérifie
la signature des fichiers produits. Toutes les mises à jour doivent conserver
cette même clé. Le workflow transmet à Gradle les variables :

```text
WATCH2NOTIF_KEYSTORE       chemin vers le .jks
WATCH2NOTIF_STORE_PASSWORD mot de passe du magasin
WATCH2NOTIF_KEY_ALIAS      alias (watch2notif par défaut)
WATCH2NOTIF_KEY_PASSWORD   mot de passe de la clé
```

L’APK debug présent dans les artefacts de CI sert aux essais. Il ne fait pas
partie du canal de mise à jour public ; la clé debug d’un runner peut différer
de celle d’un autre runner.

## Vérifications

Les tests couvrent les parseurs et formes de source, l’amorçage silencieux,
le rattrapage ancien, la reprise après échec, les changements de source pendant
une requête, le filtre Claude, l’import et le chiffrement. Un vecteur à clés
fictives partagé avec les tests Python vérifie que le déchiffrement Android
lit exactement les données AES-GCM produites côté PC.

Les tests du smoke test couvrent les cinq providers et Claude, les clés
manquantes, les refus d’accès, les délais, les sources désactivées et la
conservation des états. Les tests de mise à jour couvrent les versions stables,
les redirections HTTPS, empreintes, tailles, signatures, annulations et la
vérification avant installation. Les appels réseau utilisent des réponses
fictives en CI ; le bouton Tester les accès permet de valider les vrais
identifiants sur le téléphone sans les publier dans les tests GitHub.

Les tests de surveillance couvrent la reprise sticky, l’intention persistante,
les arrêts volontaires, la pause, les sources désactivées, les erreurs de boucle,
le quota et la libération du verrou sur Android 8 et 14. Un smoke supplémentaire
sur émulateurs Android 11 et 15 teste le vrai service, une notification RSS en
veille profonde écran éteint, la mort de son processus et sa reprise sans
doublons, l’arrêt volontaire et le maintien des tâches automatiques. Android 15
exerce aussi son vrai timeout avec un quota temporairement raccourci. Le flux
est un serveur HTTP local à données fictives ; aucune clé réelle n’est utilisée.
Ce smoke ne peut s’exécuter que sur un émulateur GitHub, et la publication d’une
release dépend de sa réussite.

Les tests PC exercent également le vrai serveur HTTP : mauvais code, expiration,
usage unique concurrent, fermeture du port et altération du ciphertext. Les
tests Robolectric vérifient également la réception pendant une surveillance lente,
la rotation, le retour d’erreur après une pause de l’activité, l’annulation et
le délai global. Les appels Windows natifs sont simulés en CI, sans demande UAC
ni modification du pare-feu du runner. Les tests Robolectric rendent les écrans FR dans les artefacts GitHub pour contrôle
visuel. Les tests et Lint sont aussi exécutés sur la variante release avant
publication. Le scan caméra, les notifications sur appareil physique et les politiques
de batterie des fabricants restent à essayer sur un téléphone réel.
