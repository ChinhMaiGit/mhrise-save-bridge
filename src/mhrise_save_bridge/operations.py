"""convert / transfer / inspect as library functions; the CLI only parses arguments and prints.

Every operation returns a Plan (what would be written); applying it is a separate, guarded step.
"""

import secrets

from dataclasses import dataclass, field
from pathlib import Path

from mhrise_save_bridge import container, slots, stream
from mhrise_save_bridge.constants import (
    MAX_SLOTS,
    PC_STREAM_ORIGIN,
    SWITCH_STREAM_ORIGIN,
    TRANSFER_GROUPS,
)

SYSTEM_FILE = "data00-1.bin"


class OperationError(Exception):
    """The request cannot be carried out (missing file, used slot, bad slot number)."""


@dataclass
class Plan:
    """Files to write (name -> bytes) plus human-readable notes."""

    files: dict = field(default_factory = dict)
    notes: list = field(default_factory = list)
    payloads: dict = field(default_factory = dict)


def slot_file(slot):
    if not 1 <= slot <= MAX_SLOTS:
        raise OperationError(f"slot must be 1..{MAX_SLOTS}")
    return f"data00{slot}Slot.bin"


def _load(directory, name, steam_id64):
    path = Path(directory) / name
    if not path.is_file():
        raise OperationError(f"missing file: {path}")
    opened = container.open_save(
        data = path.read_bytes(),
        steam_id64 = steam_id64,
    )
    if not opened.hashes_ok:
        raise OperationError(f"{path}: block checksums fail, the save looks damaged")
    return opened, stream.parse(
        data = opened.payload,
        origin = opened.origin,
    )


def _existing_slots(save_dir):
    return [n for n in range(1, MAX_SLOTS + 1) if (Path(save_dir) / slot_file(slot = n)).is_file()]


# ---- inspect
def inspect(directory, steam_id64):
    """Rows describing a save folder (Switch or PC)."""
    directory = Path(directory)
    rows = []
    system_path = directory / SYSTEM_FILE
    if not system_path.is_file():
        raise OperationError(f"no {SYSTEM_FILE} in {directory}")
    kind = container.kind_of(data = system_path.read_bytes())
    rows.append(f"platform: {kind}  ({len(list(directory.glob('SS*_*.bin')))} album files)")
    if kind == "pc" and steam_id64 is None:
        rows.append("PC saves are encrypted: pass --steamid64 (or point at the userdata folder).")
        return rows
    _, system = _load(
        directory = directory,
        name = SYSTEM_FILE,
        steam_id64 = steam_id64,
    )
    for number, info in enumerate(slots.summaries(system_entries = system), start = 1):
        state = f"{info.name!r}  HR {info.hunter_rank}  MR {info.master_rank}" if info.used else "(empty)"
        have = "file present" if (directory / slot_file(slot = number)).is_file() else "no slot file"
        rows.append(f"slot {number}: {state}  [{have}]")
    return rows


# ---- convert
def plan_convert(switch_dir, pc_dir, steam_id64, target_slot, switch_slot, force, guid = None):
    switch_dir, pc_dir = Path(switch_dir), Path(pc_dir)
    _, switch_system = _load(
        directory = switch_dir,
        name = SYSTEM_FILE,
        steam_id64 = None,
    )
    switch_open, switch_slot_entries = _load(
        directory = switch_dir,
        name = slot_file(slot = switch_slot),
        steam_id64 = None,
    )
    if switch_open.origin != SWITCH_STREAM_ORIGIN:
        raise OperationError("the --switch-dir files are not Switch saves")
    pc_system_open, pc_system = _load(
        directory = pc_dir,
        name = SYSTEM_FILE,
        steam_id64 = steam_id64,
    )
    present = _existing_slots(save_dir = pc_dir)
    if not present:
        raise OperationError(
            "the PC save folder has no character yet: start the game once, create any character "
            "and save, then run this again (its structure is used as the template).",
        )
    summaries = slots.summaries(system_entries = pc_system)
    if target_slot is None:
        free = [n for n in range(1, MAX_SLOTS + 1) if not summaries[n - 1].used and n not in present]
        if not free:
            raise OperationError("all three PC slots are in use: pass --slot N --force to replace one")
        target_slot = free[0]
    target_used = summaries[target_slot - 1].used or target_slot in present
    if target_used and not force:
        raise OperationError(
            f"PC slot {target_slot} is already used ({summaries[target_slot - 1].name!r}); "
            "choose a free slot or pass --force to overwrite it",
        )
    _, template = _load(
        directory = pc_dir,
        name = slot_file(slot = present[0]),
        steam_id64 = steam_id64,
    )
    guid = guid or secrets.token_bytes(16)
    new_slot = slots.build_pc_slot(
        switch_slot = switch_slot_entries,
        pc_slot_template = template,
        guid = guid,
    )
    new_system = slots.replace_summary(
        pc_system = pc_system,
        switch_system = switch_system,
        switch_slot = switch_slot,
        target_slot = target_slot,
        guid = guid,
    )
    plan = Plan()
    for name, entries in (
        (
            SYSTEM_FILE,
            new_system,
        ),
        (
            slot_file(slot = target_slot),
            new_slot,
        ),
    ):
        payload = stream.encode(
            entries = entries,
            origin = PC_STREAM_ORIGIN,
        )
        plan.payloads[name] = payload
        plan.files[name] = container.pack_pc(
            payload = payload,
            steam_id64 = steam_id64,
            curve_index = pc_system_open.curve_index,
        )
    info = slots.slot_info(slot_entries = new_slot)
    plan.notes.append(
        f"Switch slot {switch_slot} ({info.name!r}, HR {info.hunter_rank}, MR {info.master_rank}) "
        f"-> PC slot {target_slot}" + (" (overwriting a used slot)" if target_used else ""),
    )
    return plan


# ---- transfer
def plan_transfer(pc_dir, steam_id64, from_slot, to_slot, groups):
    if from_slot == to_slot:
        raise OperationError("--from-slot and --to-slot must differ")
    unknown = [g for g in groups if g not in TRANSFER_GROUPS]
    if unknown:
        raise OperationError(f"unknown group(s) {unknown}; choose from {sorted(TRANSFER_GROUPS)}")
    _, donor = _load(
        directory = pc_dir,
        name = slot_file(slot = from_slot),
        steam_id64 = steam_id64,
    )
    target_open, target = _load(
        directory = pc_dir,
        name = slot_file(slot = to_slot),
        steam_id64 = steam_id64,
    )
    plan = Plan()
    out = target
    for group in groups:
        for class_hash in TRANSFER_GROUPS[group]:
            donor_items = slots.find(
                entries = donor,
                class_hash = class_hash,
            )
            target_items = slots.find(
                entries = out,
                class_hash = class_hash,
            )
            if not donor_items or len(donor_items) != len(target_items):
                raise OperationError(f"{group}: slot layouts differ, nothing was changed")
            queue = iter(donor_items)
            out = slots.replace_class(
                entries = out,
                class_hash = class_hash,
                make = lambda cls, queue = queue: next(queue),
            )
        plan.notes.append(f"{group}: copied from slot {from_slot} to slot {to_slot}")
    name = slot_file(slot = to_slot)
    payload = stream.encode(
        entries = out,
        origin = PC_STREAM_ORIGIN,
    )
    plan.payloads[name] = payload
    plan.files[name] = container.pack_pc(
        payload = payload,
        steam_id64 = steam_id64,
        curve_index = target_open.curve_index,
    )
    return plan
