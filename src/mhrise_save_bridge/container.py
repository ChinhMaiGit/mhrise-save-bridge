"""DSSS save containers: read either platform, write the PC (Citrus) one."""

import struct
import zlib

from dataclasses import dataclass

from mhrise_save_bridge import citrus
from mhrise_save_bridge.constants import (
    FLAG_CITRUS,
    FLAG_DEFLATE,
    MAGIC,
    PC_HEADER,
    PC_STREAM_ORIGIN,
    SWITCH_DEFLATE_OFFSET,
    SWITCH_INFLATED_SIZE_OFFSET,
    SWITCH_STREAM_ORIGIN,
)
from mhrise_save_bridge.murmur import murmur3_32


class ContainerError(Exception):
    """The file is not a Rise save, or not one this tool can read."""


@dataclass
class Opened:
    """A decoded save file: the class-stream bytes plus how they were wrapped."""

    payload: bytes
    origin: int
    flags: int
    curve_index: int | None
    hashes_ok: bool


def header_flags(data):
    if len(data) < 16 or data[:4] != MAGIC:
        raise ContainerError("not a Rise save file (missing DSSS header)")
    return struct.unpack_from("<I", data, 8)[0]


def kind_of(data):
    flags = header_flags(data = data)
    if flags & FLAG_CITRUS:
        return "pc"
    if flags & FLAG_DEFLATE:
        return "switch"
    return "other"


def open_save(data, steam_id64 = None):
    """Decode a save file. PC files need the owner's SteamID64."""
    flags = header_flags(data = data)
    if flags & FLAG_CITRUS:
        if steam_id64 is None:
            raise ContainerError("this is a PC save: a SteamID64 is needed to decrypt it")
        if not citrus.outer_hash_ok(data = data):
            raise ContainerError("file checksum is wrong: the save is damaged")
        payload, curve_index, _, ok = citrus.decrypt_payload(body = data[16:-4], steam_id64 = steam_id64)
        return Opened(
            payload = payload,
            origin = PC_STREAM_ORIGIN,
            flags = flags,
            curve_index = curve_index,
            hashes_ok = ok,
        )
    if flags & FLAG_DEFLATE:
        expected = struct.unpack_from("<Q", data, SWITCH_INFLATED_SIZE_OFFSET)[0]
        stream = zlib.decompressobj(wbits = -15)
        payload = stream.decompress(data[SWITCH_DEFLATE_OFFSET:])
        if len(payload) != expected:
            raise ContainerError("Switch save is truncated (inflated size does not match)")
        return Opened(
            payload = payload,
            origin = SWITCH_STREAM_ORIGIN,
            flags = flags,
            curve_index = None,
            hashes_ok = True,
        )
    raise ContainerError(f"unsupported container flags 0x{flags:02x} (not a main save file)")


def pack_pc(payload, steam_id64, curve_index):
    """Build a complete PC save file around a class stream."""
    body = (
        MAGIC
        + struct.pack("<II", PC_HEADER["version"], PC_HEADER["flags"])
        + bytes(4)
        + citrus.encrypt_payload(payload = payload, steam_id64 = steam_id64, curve_index = curve_index)
    )
    body += bytes((-len(body)) % 4)
    return body + struct.pack("<I", murmur3_32(data = body))
