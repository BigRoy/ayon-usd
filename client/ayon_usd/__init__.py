"""USD Addon for AYON - client part."""
import os
import sys

from .addon import USD_ADDON_DIR, USDAddon
from .utils import extract_zip_file, get_download_dir, get_downloaded_usd_root

__all__ = (
    "USDAddon",
    "get_downloaded_usd_root",
    "extract_zip_file",
    "get_download_dir",
)


def initialize_environment():
    """Initialize environment for USD.

    This should be called from Python console or any script running
    within AYON Python interpreter to initialize USD environment.
    It cannot be set automatically during AYON startup because it would then
    pollute environment for other processes - some of them having USD
    already embedded.

    """
    sys.path.append(
        os.path.join(get_downloaded_usd_root(), "lib", "python"))

    # Resolver settings
    os.environ["PXR_PLUGINPATH_NAME"] = USD_ADDON_DIR
    os.environ["USD_ASSET_RESOLVER"] = ""
    os.environ["TF_DEBUG"] = "1"
    os.environ["PYTHONPATH"] = os.path.join(
        get_downloaded_usd_root(), "lib", "python")
    os.environ["PATH"] = f"{os.getenv('PATH')}{os.path.pathsep}{os.path.join(get_downloaded_usd_root(), 'bin')}"
    os.environ["AYONLOGGERLOGLVL"] = "WARN"
    os.environ["AYONLOGGERSFILELOGGING"] = "1"
    os.environ["AYONLOGGERSFILEPOS"] = ".log"
