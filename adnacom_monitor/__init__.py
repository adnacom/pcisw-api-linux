"""Adnacom Monitor - PCIe Host Adapter Monitoring Tool"""

import sys
import sysconfig
from pathlib import Path

from ._version import __version__

__all__ = ["__version__"]


def _check_interpreter_supported() -> None:
    """Fail fast with a clear message when the running interpreter has no
    matching pre-compiled extension (e.g. Protocol.cpython-312-*.so)."""
    ext_suffix = sysconfig.get_config_var("EXT_SUFFIX") or ".so"
    pkg_dir = Path(__file__).resolve().parent
    if (pkg_dir / f"Protocol{ext_suffix}").exists():
        return

    supported = sorted(
        "3." + so.name.split("cpython-3", 1)[1].split("-", 1)[0]
        for so in pkg_dir.glob("Protocol.cpython-3*.so")
    )
    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    raise ImportError(
        f"adnacom-monitor {__version__} ships pre-compiled modules for "
        f"CPython {', '.join(supported) or '(none found)'}, but this "
        f"interpreter is Python {running} ({sys.executable}). "
        f"Re-install using one of the supported Python versions — "
        f"the install.sh script picks a suitable one automatically."
    )


_check_interpreter_supported()
