"""Command line: inspect, convert, transfer. Dry-run unless --apply (or --output-dir) is given."""

import argparse
import sys

from pathlib import Path

from mhrise_save_bridge import __version__, operations, safety, steam
from mhrise_save_bridge.constants import TRANSFER_GROUPS
from mhrise_save_bridge.citrus import CitrusError
from mhrise_save_bridge.container import ContainerError
from mhrise_save_bridge.stream import StreamError

KNOWN_ERRORS = (
    operations.OperationError,
    safety.SafetyError,
    steam.SteamError,
    ContainerError,
    CitrusError,
    StreamError,
    OSError,
    ValueError,
    EOFError,
)


def add_steam_arguments(parser):
    parser.add_argument(
        "--steam-dir",
        type = Path,
        help = "Rise save folder (...\\userdata\\<id>\\1446780\\remote\\win64_save); found automatically if omitted",
    )
    parser.add_argument(
        "--steamid64",
        help = "your SteamID64 (or the number in the userdata folder name); derived from --steam-dir if omitted",
    )


def add_write_arguments(parser):
    parser.add_argument(
        "--apply",
        action = "store_true",
        help = "really write into the Steam folder (after a backup)",
    )
    parser.add_argument(
        "--output-dir",
        type = Path,
        help = "write the new files here instead of Steam (no backup needed)",
    )
    parser.add_argument(
        "--yes",
        action = "store_true",
        help = "do not ask whether Steam Cloud is off",
    )
    parser.add_argument(
        "--skip-process-check",
        action = "store_true",
        help = "do not refuse while Steam/Rise runs",
    )


def build_parser():
    parser = argparse.ArgumentParser(
        prog = "mhrise-save-bridge",
        description = "Monster Hunter Rise: bring a Nintendo Switch save to the Steam (PC) version.",
    )
    parser.add_argument(
        "--version",
        action = "version",
        version = __version__,
    )
    commands = parser.add_subparsers(dest = "command")

    inspect_cmd = commands.add_parser(
        "inspect",
        help = "show the slots of a save folder (read only)",
    )
    inspect_cmd.add_argument(
        "directory",
        type = Path,
        help = "Switch dump folder or Steam win64_save folder",
    )
    inspect_cmd.add_argument(
        "--steamid64",
        help = "needed for PC saves outside a userdata folder",
    )

    convert_cmd = commands.add_parser(
        "convert",
        help = "Switch character -> a PC slot",
        description = "Convert one Switch character into a PC slot. Dry-run unless --apply or --output-dir.",
    )
    convert_cmd.add_argument(
        "--switch-dir",
        type = Path,
        required = True,
        help = "folder with the Switch save files",
    )
    convert_cmd.add_argument(
        "--switch-slot",
        type = int,
        default = 1,
        help = "Switch character slot (default 1)",
    )
    convert_cmd.add_argument(
        "--slot",
        type = int,
        help = "PC slot to fill (default: first free)",
    )
    convert_cmd.add_argument(
        "--force",
        action = "store_true",
        help = "allow overwriting a used PC slot",
    )
    convert_cmd.add_argument(
        "--guid",
        help = argparse.SUPPRESS,
    )
    add_steam_arguments(parser = convert_cmd)
    add_write_arguments(parser = convert_cmd)

    transfer_cmd = commands.add_parser(
        "transfer",
        help = "copy item box / equipment etc. between two PC slots",
        description = "Copy parts of one PC character to another. Dry-run unless --apply or --output-dir.",
    )
    transfer_cmd.add_argument(
        "--from-slot",
        type = int,
        required = True,
    )
    transfer_cmd.add_argument(
        "--to-slot",
        type = int,
        required = True,
    )
    transfer_cmd.add_argument(
        "--what",
        nargs = "+",
        default = ["item-box"],
        choices = sorted(TRANSFER_GROUPS),
        help = "parts to copy (default: item-box)",
    )
    add_steam_arguments(parser = transfer_cmd)
    add_write_arguments(parser = transfer_cmd)
    commands.add_parser(
        "guide",
        help = "step-by-step questions (also what a double-click on the .exe runs)",
    )
    return parser


def resolve_steam(args):
    """(save_dir, steam_id64) from the arguments, the Steam install and the folder name."""
    save_dir = steam.normalize_save_dir(path = args.steam_dir) if args.steam_dir else steam.find_save_dir()
    if args.steamid64:
        steam_id64 = steam.parse_steam_id(text = args.steamid64)
    else:
        steam_id64 = steam.steam_id64_from_dir(save_dir = save_dir)
    if steam_id64 is None:
        raise steam.SteamError("could not tell your SteamID64 from the folder: pass --steamid64")
    return save_dir, steam_id64


def run_inspect(args):
    directory = Path(args.directory)
    steam_id64 = None
    if args.steamid64:
        steam_id64 = steam.parse_steam_id(text = args.steamid64)
    else:
        steam_id64 = steam.steam_id64_from_dir(save_dir = directory)
    for row in operations.inspect(
        directory = directory,
        steam_id64 = steam_id64,
    ):
        print(row)


def finish(plan, args, save_dir):
    """Print the plan; write it only when asked, with the safety steps in front."""
    for note in plan.notes:
        print(note)
    for name, data in plan.files.items():
        print(f"  {name}: {len(data):,} bytes")
    if args.output_dir:
        args.output_dir.mkdir(
            parents = True,
            exist_ok = True,
        )
        for name, data in plan.files.items():
            safety.write_atomic(
                path = args.output_dir / name,
                data = data,
            )
        print(f"written to {args.output_dir} (Steam folder untouched)")
        return
    if not args.apply:
        print("dry run: nothing was written. Add --apply to install into the Steam folder.")
        return
    if not args.skip_process_check:
        safety.refuse_if_running()
    safety.confirm_cloud_off(assume_yes = args.yes)
    backup = safety.make_backup(save_dir = save_dir)
    print(f"backup of the save folder: {backup}")
    for name, data in plan.files.items():
        safety.write_atomic(
            path = save_dir / name,
            data = data,
        )
    print("done. Start the game and check the slot before turning Steam Cloud back on.")


def run_convert(args):
    save_dir, steam_id64 = resolve_steam(args = args)
    guid = bytes.fromhex(args.guid) if args.guid else None
    plan = operations.plan_convert(
        switch_dir = args.switch_dir,
        pc_dir = save_dir,
        steam_id64 = steam_id64,
        target_slot = args.slot,
        switch_slot = args.switch_slot,
        force = args.force,
        guid = guid,
    )
    finish(
        plan = plan,
        args = args,
        save_dir = save_dir,
    )


def run_transfer(args):
    save_dir, steam_id64 = resolve_steam(args = args)
    plan = operations.plan_transfer(
        pc_dir = save_dir,
        steam_id64 = steam_id64,
        from_slot = args.from_slot,
        to_slot = args.to_slot,
        groups = args.what,
    )
    finish(
        plan = plan,
        args = args,
        save_dir = save_dir,
    )


def ask_path(question):
    return Path(input(question).strip().strip('"').strip("'"))


def run_guide(args):
    """Plain question-and-answer flow for people who never use a terminal."""
    print("Monster Hunter Rise: Switch save -> Steam (PC)\n")
    print("Tip: you can drag the folder into this window instead of typing its path.\n")
    switch_dir = ask_path(question = "Folder with your Switch save files (contains data00-1.bin): ")
    for row in operations.inspect(
        directory = switch_dir,
        steam_id64 = None,
    ):
        print("  " + row)
    switch_slot = int(input("Which Switch slot to bring over? [1]: ").strip() or "1")
    save_dir, steam_id64 = resolve_steam(args = argparse.Namespace(steam_dir = None, steamid64 = None))
    print(f"\nYour Steam save folder: {save_dir}")
    for row in operations.inspect(
        directory = save_dir,
        steam_id64 = steam_id64,
    ):
        print("  " + row)
    plan = operations.plan_convert(
        switch_dir = switch_dir,
        pc_dir = save_dir,
        steam_id64 = steam_id64,
        target_slot = None,
        switch_slot = switch_slot,
        force = False,
    )
    for note in plan.notes:
        print("\n" + note)
    if input("Install it now? Type yes to continue: ").strip().lower() != "yes":
        print("Nothing was changed.")
        return
    options = argparse.Namespace(output_dir = None, apply = True, yes = False, skip_process_check = False)
    finish(
        plan = plan,
        args = options,
        save_dir = save_dir,
    )


def main(argv = None):
    args = build_parser().parse_args(args = argv)
    guided = args.command in (
        None,
        "guide",
    )
    handlers = {
        None: run_guide,
        "guide": run_guide,
        "inspect": run_inspect,
        "convert": run_convert,
        "transfer": run_transfer,
    }
    try:
        handlers[args.command](args = args)
    except KNOWN_ERRORS as error:
        print(
            f"error: {error}",
            file = sys.stderr,
        )
        return 1
    finally:
        if guided and getattr(sys, "frozen", False):
            input("\nPress Enter to close this window.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
