"""Version de watch2notif et depot de ses releases.

La recherche d'une nouvelle version stable est nico579_commons.maj
(Verificateur), la meme pour les quatre applications : notifier.py en
tient un (VERIFICATEUR), interroge GitHub une fois par heure par un fil de
fond, et porte avec la version les metadonnees minimales des fichiers de la
release. Elles sont revalidees par self_update.py au moment ou l'utilisateur
accepte l'installation ; aucune URL arbitraire n'est executee telle quelle.

Ce fichier ne garde que ce que lisent aussi le spec PyInstaller et la CI
(update_check.VERSION, verifie contre l'etiquette de la release).
"""

VERSION = "0.10.2"
DEPOT = "nico579/watch2notif"
