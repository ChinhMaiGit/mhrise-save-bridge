"""Finding the Steam save folder, the SteamID64, and whether Steam / Rise is running."""

import os
import subprocess
import sys

from pathlib import Path

from mhrise_save_bridge.constants import (
    RISE_APP_ID,
    SAVE_SUBDIR,
    STEAM_ID64_BASE,
)

# Process names whose presence means a save could be rewritten behind our back.
WINDOWS_PROCESSES = ("steam.exe", "monsterhunterrise.exe")


class SteamError(Exception):
    """The Steam folder or account could not be determined."""


def steam_roots():
    """Likely Steam install folders on this OS, existing ones only."""
    candidates = []
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                candidates.append(Path(winreg.QueryValueEx(key, "SteamPath")[0]))
        except OSError:
            pass
        for variable in ("ProgramFiles(x86)", "ProgramFiles"):
            base = os.environ.get(variable)
            if base:
                candidates.append(Path(base) / "Steam")
        candidates.append(Path("C:/Program Files (x86)/Steam"))
    else:
        home = Path.home()
        candidates.extend([
            home / ".steam" / "steam",
            home / ".local" / "share" / "Steam",
            home / "Library" / "Application Support" / "Steam",
        ])
    return [path for path in candidates if (path / "userdata").is_dir()]


def save_dirs(root):
    """All Rise save folders (one per Steam account) under a Steam root."""
    found = []
    userdata = root / "userdata"
    if userdata.is_dir():
        for account in sorted(userdata.iterdir()):
            candidate = account.joinpath(RISE_APP_ID, *SAVE_SUBDIR)
            if candidate.is_dir():
                found.append(candidate)
    return found


def normalize_save_dir(path):
    """Accept the win64_save folder itself or a parent of it (account folder, remote, ...)."""
    path = Path(path)
    for tail in ((), SAVE_SUBDIR, (RISE_APP_ID, *SAVE_SUBDIR)):
        candidate = path.joinpath(*tail)
        if (candidate / "data00-1.bin").is_file():
            return candidate
    raise SteamError(f"no Rise save (data00-1.bin) found in or under {path}")


def find_save_dir():
    """The Rise save folder when there is exactly one Steam account with a save."""
    found = []
    for root in steam_roots():
        found.extend(save_dirs(root = root))
    if not found:
        raise SteamError("could not find your Steam save folder: pass --steam-dir")
    if len(found) > 1:
        listing = "\n  ".join(str(path) for path in found)
        raise SteamError(f"several Steam accounts have a Rise save, pass --steam-dir:\n  {listing}")
    return found[0]


def steam_id64_from_dir(save_dir):
    """The account folder name (userdata/<id>/...) is the SteamID3; add the universe base."""
    parts = Path(save_dir).resolve().parts
    for index, part in enumerate(parts[1:], start = 1):
        if parts[index - 1] == "userdata" and part.isdigit():
            return STEAM_ID64_BASE + int(part)
    return None


def parse_steam_id(text):
    """Accept a full SteamID64 or the short account id used as the userdata folder name."""
    value = int(text)
    return value if value >= STEAM_ID64_BASE else STEAM_ID64_BASE + value


def running_blockers():
    """Names of running Steam / Rise processes (cross-platform, no third-party package)."""
    if os.name == "nt":
        output = subprocess.run(
            args = ["tasklist", "/FO", "CSV", "/NH"],
            capture_output = True,
            text = True,
            check = False,
        ).stdout.lower()
        return [name for name in WINDOWS_PROCESSES if f'"{name}"' in output]
    if sys.platform == "darwin":
        output = subprocess.run(
            args = ["ps", "-A", "-o", "command"],
            capture_output = True,
            text = True,
            check = False,
        ).stdout.lower()
        return [marker for marker in ("steam_osx", "monster hunter rise") if marker in output]
    hits = []
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            argv = (proc / "cmdline").read_bytes().decode("utf-8", "replace").lower().split("\0")
        except OSError:
            continue
        if argv and Path(argv[0]).name == "steam" and "steam" not in hits:
            hits.append("steam")
        if any("monsterhunterrise.exe" in part for part in argv) and "monsterhunterrise" not in hits:
            hits.append("monsterhunterrise")
    return hits
