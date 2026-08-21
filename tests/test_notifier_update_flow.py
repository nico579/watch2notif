import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import notifier  # noqa: E402


class TrayUpdateFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.config_patch = mock.patch.object(notifier, "load_config", return_value={"lang": "en"})
        self.install_patch = mock.patch.object(
            notifier.self_update,
            "can_install_automatically",
            return_value=(True, ""),
        )
        self.native_window_patch = mock.patch.object(
            notifier,
            "_show_windows_window",
            return_value=True,
        )
        self.config_patch.start()
        self.install_patch.start()
        self.native_window_show = self.native_window_patch.start()
        self.signals = notifier.UpdateSignals()
        self.tray = notifier.TrayApp("en", notifier.threading.Event(), self.signals)

    def tearDown(self):
        for dialog_name in ("update_dialog", "progress_dialog", "error_dialog"):
            dialog = getattr(self.tray, dialog_name, None)
            if dialog is not None:
                dialog.done(0)
                dialog.deleteLater()
        self.tray.tray.hide()
        self.tray.deleteLater()
        self.app.processEvents()
        self.native_window_patch.stop()
        self.install_patch.stop()
        self.config_patch.stop()

    @staticmethod
    def info(version):
        return {"version": version, "page": f"https://example.test/v{version}", "assets": []}

    def test_english_prompt_uses_custom_buttons_and_accepts_snapshot(self):
        with mock.patch.object(self.tray, "_start_update") as start:
            self.tray._on_update_available(self.info("9.0.0"))
            dialog = self.tray.update_dialog
            self.assertIsNotNone(dialog)
            self.assertIn("Version 9.0.0", dialog.text())
            buttons = {button.text(): button for button in dialog.buttons()}
            self.assertIn("Download and install", buttons)
            self.assertIn("Later", buttons)
            buttons["Download and install"].click()
            self.app.processEvents()
            start.assert_called_once()
            self.assertEqual(start.call_args.args[0]["version"], "9.0.0")

    def test_new_version_while_prompt_is_open_is_asked_separately(self):
        with mock.patch.object(self.tray, "_start_update") as start:
            self.tray._on_update_available(self.info("2.0.0"))
            old_dialog = self.tray.update_dialog
            self.tray._on_update_available(self.info("3.0.0"))
            self.assertNotIn("3.0.0", self.tray.prompted_versions)
            old_accept = next(button for button in old_dialog.buttons() if button.text() == "Download and install")
            old_accept.click()
            self.app.processEvents()

            start.assert_not_called()
            self.assertIsNotNone(self.tray.update_dialog)
            self.assertIn("Version 3.0.0", self.tray.update_dialog.text())
            self.assertIn("3.0.0", self.tray.prompted_versions)

    def test_internal_french_error_detail_is_not_shown_in_english(self):
        self.tray.update_info = self.info("9.0.0")
        self.tray._on_update_failed({"code": "missing_asset", "detail": "la release est invalide"})
        self.assertIn("No valid update bundle", self.tray.error_dialog.text())
        self.assertNotIn("la release est invalide", self.tray.error_dialog.text())

    def test_source_mode_fallback_is_french_when_configured(self):
        notifier.load_config.return_value = {"lang": "fr"}
        notifier.self_update.can_install_automatically.return_value = (False, "source_mode")
        self.tray._on_update_available(self.info("9.0.0"))
        buttons = {button.text() for button in self.tray.update_dialog.buttons()}
        self.assertIn("Ouvrir la page de la release", buttons)
        self.assertIn("Plus tard", buttons)

    def test_settings_action_survives_refreshes_and_restores_window(self):
        action = self.tray.settings_action
        action.trigger()
        self.app.processEvents()
        window = self.tray.settings_window
        self.assertIsNotNone(window)
        self.assertTrue(window.isVisible())

        window.close()
        self.app.processEvents()
        self.tray.update_info = self.info("9.0.0")
        self.tray._rebuild_menu()
        self.tray.update_info = None
        self.tray._rebuild_menu()

        self.assertIs(self.tray.settings_action, action)
        self.assertIn(action, self.tray.menu.actions())
        action.trigger()
        self.app.processEvents()
        self.assertTrue(window.isVisible())

        window.showMinimized()
        self.app.processEvents()
        action.trigger()
        self.app.processEvents()
        self.assertFalse(window.isMinimized())
        self.assertTrue(self.native_window_show.called)
        window.close()


if __name__ == "__main__":
    unittest.main()
