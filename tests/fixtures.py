"""Synthetic fixtures: tiny fake class streams that use the real class/field hashes but invented values."""

import struct
import zlib

from pathlib import Path

from mhrise_save_bridge import container, stream
from mhrise_save_bridge.constants import (
    CLASS_GUILD_CARD,
    CLASS_PROGRESS,
    CLASS_SUMMARY,
    FIELD_CARD_NAME,
    FIELD_GUID,
    FIELD_HUNTER_RANK,
    FIELD_MASTER_RANK,
    FIELD_SUMMARY_NAME,
    PC_STREAM_ORIGIN,
    SWITCH_STREAM_ORIGIN,
    TRANSFER_GROUPS,
)

FAKE_STEAM_ID64 = 76561197960265728 + 123456789  # invented account, not a real one
FAST_CURVE = 0
PC_ONLY_FIELD = 0x1234ABCD
ITEM_BOX = TRANSFER_GROUPS["item-box"][0]
EQUIP_BOX = TRANSFER_GROUPS["equip-box"][0]


def scalar(field_hash, value, size = 4):
    return [field_hash, 8, (size, value.to_bytes(size, "little"))]


def text(field_hash, value):
    return [field_hash, 0x0F, value.encode("utf-16le")]


def guid_field(value):
    return [FIELD_GUID, 0x10, (16, value)]


def int_array(field_hash, values):
    return [
        field_hash,
        -1,
        {
            "mt": 8,
            "ms": 4,
            "at": 0,
            "hashes": None,
            "vals": [v.to_bytes(4, "little") for v in values],
        },
    ]


def summary(name, hunter_rank, master_rank, guid = bytes(16), pc = False):
    fields = [
        text(field_hash = FIELD_SUMMARY_NAME, value = name),
        scalar(field_hash = FIELD_HUNTER_RANK, value = hunter_rank),
        scalar(field_hash = FIELD_MASTER_RANK, value = master_rank),
        guid_field(value = guid),
    ]
    if pc:
        fields.append(scalar(field_hash = PC_ONLY_FIELD, value = 7))
    return (CLASS_SUMMARY, fields)


def system_entries(slot_summaries, pc):
    array = {
        "mt": 0x11,
        "ms": 0,
        "at": 1,
        "hashes": None,
        "vals": list(slot_summaries),
    }
    holder = (0x11111111, [[0x22222222, -1, array]])
    return [(0xAAAA0001, holder)]


def slot_entries(name, hunter_rank, master_rank, items, pc, guid = bytes(16)):
    card = (
        CLASS_GUILD_CARD,
        [
            text(field_hash = FIELD_CARD_NAME, value = name),
            scalar(field_hash = 0x0A0A0A0A, value = 5, size = 1),
        ],
    )
    progress = (
        CLASS_PROGRESS,
        [
            scalar(field_hash = FIELD_HUNTER_RANK, value = hunter_rank),
            scalar(field_hash = FIELD_MASTER_RANK, value = master_rank),
        ],
    )
    projected_a = (
        0x95320424,
        [scalar(field_hash = 1, value = 11)] + ([scalar(field_hash = 2, value = 22, size = 8)] if pc else []),
    )
    projected_b = (0x5766F30B, [guid_field(value = guid), scalar(field_hash = 3, value = 33)])
    item_box = (ITEM_BOX, [int_array(field_hash = 4, values = items)])
    equip_box = (EQUIP_BOX, [scalar(field_hash = 5, value = len(name))])
    entries = [
        (0xB0000001, card),
        (0xB0000002, progress),
        (0xB0000003, projected_a),
        (0xB0000004, projected_b),
        (0xB0000005, item_box),
        (0xB0000006, equip_box),
    ]
    if pc:
        entries.reverse()  # the platforms order the top-level entries differently
        entries.append((0xB00000FF, (0x77777777, [scalar(field_hash = 6, value = 9)])))
    return entries


def write_switch(path, entries):
    payload = stream.encode(entries = entries, origin = SWITCH_STREAM_ORIGIN)
    compressor = zlib.compressobj(wbits = -15)
    body = compressor.compress(payload) + compressor.flush()
    header = b"DSSS" + struct.pack("<II", 2, 8) + bytes(0x28 - 12)
    header = header[:0x20] + struct.pack("<Q", len(payload))
    Path(path).write_bytes(header + body)


def write_pc(path, entries):
    payload = stream.encode(entries = entries, origin = PC_STREAM_ORIGIN)
    Path(path).write_bytes(
        container.pack_pc(
            payload = payload,
            steam_id64 = FAKE_STEAM_ID64,
            curve_index = FAST_CURVE,
        ),
    )


def make_switch_dir(directory):
    directory.mkdir(parents = True, exist_ok = True)
    summaries = [summary(name = "Alice", hunter_rank = 120, master_rank = 4)]
    summaries += [summary(name = "(unset)", hunter_rank = 0xFFFFFFFF, master_rank = 0xFFFFFFFF)] * 2
    write_switch(path = directory / "data00-1.bin", entries = system_entries(slot_summaries = summaries, pc = False))
    write_switch(
        path = directory / "data001Slot.bin",
        entries = slot_entries(name = "Alice", hunter_rank = 120, master_rank = 4, items = [1, 2, 3], pc = False),
    )
    return directory


def make_pc_dir(directory):
    directory.mkdir(parents = True, exist_ok = True)
    summaries = [summary(name = "Bob", hunter_rank = 500, master_rank = 2, pc = True)]
    summaries += [summary(name = "(unset)", hunter_rank = 0xFFFFFFFF, master_rank = 0xFFFFFFFF, pc = True)] * 2
    write_pc(path = directory / "data00-1.bin", entries = system_entries(slot_summaries = summaries, pc = True))
    write_pc(
        path = directory / "data001Slot.bin",
        entries = slot_entries(name = "Bob", hunter_rank = 500, master_rank = 2, items = [9, 8], pc = True),
    )
    return directory
