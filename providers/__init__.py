"""Registre des providers (sources de notifications). Chaque provider est
un module qui expose fetch_entries(source) -> list[Entry] et un LABEL pour
l'affichage dans settings.py. Ajouter une source = ajouter un module ici
et une ligne dans PROVIDERS, rien d'autre a toucher dans notifier.py ou
settings.py (meme esprit que les providers lidar de lidar2map)."""
from . import github_issues, rss

PROVIDERS = {
    "rss": rss,
    "github_issues": github_issues,
}

DEFAULT_KIND = "rss"
