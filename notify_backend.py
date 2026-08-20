"""Notification desktop native, par OS, avec ouverture du lien au clic
quand la plateforme le permet.

Pourquoi pas plyer pour tout : son API commune n'expose ni le nom d'appli
affiche (Windows retombe sur l'identite du process appelant, "Python")
ni de callback au clic. Windows et Mac ont chacun une lib dediee qui fait
correctement les deux ; Linux reste sur plyer (notification simple, sans
clic) faute de pouvoir tester une boucle dbus/GLib depuis cette machine.
"""
import platform


def notify(title: str, message: str, url: str = "", app_name: str = "watch2notif") -> None:
    system = platform.system()
    if system == "Windows":
        _notify_windows(title, message, url, app_name)
    elif system == "Darwin":
        _notify_mac(title, message, url)
    else:
        _notify_linux(title, message, app_name)


def _notify_windows(title: str, message: str, url: str, app_name: str) -> None:
    from win11toast import notify as win_notify

    win_notify(title, message, on_click=url or None, app_id=app_name, duration="long")


def _notify_mac(title: str, message: str, url: str) -> None:
    import pync

    kwargs = {"title": title}
    if url:
        kwargs["open"] = url
    pync.notify(message, **kwargs)


def _notify_linux(title: str, message: str, app_name: str) -> None:
    from plyer import notification

    notification.notify(title=title, message=message, app_name=app_name, timeout=10)
