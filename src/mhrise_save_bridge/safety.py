"""Safety net around writes: backup, atomic replace, running-game check, Cloud reminder."""

import datetime as dt
import os
import shutil

from pathlib import Path

from mhrise_save_bridge import steam

CLOUD_REMINDER = (
    "Before continuing: turn Steam Cloud OFF for Monster Hunter Rise\n"
    "  (Steam > Library > right-click Monster Hunter Rise > Properties > General >\n"
    "   untick 'Keep games saves in the Steam Cloud'), otherwise Steam may restore the old save."
)


class SafetyError(Exception):
    """A safety check refused the operation."""


def backup_root():
    return Path.home() / "mhrise-save-bridge-backups"


def make_backup(save_dir):
    """Copy the whole target folder to a timestamped folder; returns its path."""
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_root() / stamp
    shutil.copytree(src = save_dir, dst = target)
    return target


def write_atomic(path, data):
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    os.replace(src = temp, dst = path)


def refuse_if_running():
    blockers = steam.running_blockers()
    if blockers:
        raise SafetyError(
            "Close Steam completely (right-click its tray icon > Exit) and the game first. "
            f"Still running: {', '.join(blockers)}. Use --skip-process-check to override.",
        )


def confirm_cloud_off(assume_yes):
    print(CLOUD_REMINDER)
    if assume_yes:
        return
    if input("Type yes once Steam Cloud is off: ").strip().lower() != "yes":
        raise SafetyError("stopped: Steam Cloud not confirmed off")
