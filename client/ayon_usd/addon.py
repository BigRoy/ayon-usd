"""USD Addon for AYON."""
import os

from ayon_core.modules import AYONAddon, ITrayModule
from .utils import is_usd_download_needed
from .version import __version__

USD_ADDON_DIR = os.path.dirname(os.path.abspath(__file__))


class USDAddon(AYONAddon, ITrayModule):
    """Addon to add USD Support to AYON.

    Addon can also skip distribution of binaries from server and can
    use path/arguments defined by server.

    Cares about supplying USD Framework.
    """

    name = "ayon_usd"
    version = __version__
    _download_window = None

    def tray_init(self):
        """Initialize tray module."""
        super(USDAddon, self).tray_init()

    def initialize(self, module_settings):
        """Initialize USD Addon."""
        self.enabled = True
        self._download_window = None

    def tray_start(self):
        """Start tray module.

        Download USD if needed.
        """
        super(USDAddon, self).tray_start()
        download_usd = is_usd_download_needed()
        if not download_usd:
            return

        from .download_ui import show_download_window

        download_window = show_download_window(
            download_usd
        )
        download_window.finished.connect(self._on_download_finish)
        download_window.start()
        self._download_window = download_window

    def _on_download_finish(self):
        self._download_window.close()
        self._download_window = None

    def tray_exit(self):
        """Exit tray module."""
        pass

    def tray_menu(self, tray_menu):
        """Add menu items to tray menu."""
        pass

    def get_launch_hook_paths(self):
        """Get paths to launch hooks."""
        return [
            os.path.join(USD_ADDON_DIR, "hooks")
        ]
