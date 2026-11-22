"""The PC "Citrus" cipher (DSSS flag 0x04), re-implemented from ChevalGrand/mhrise-save-editor (MIT).

The key is the owner's SteamID64 (private scalar d = NOT(SteamID64)); no secret is needed.
"""

import hashlib
import secrets
import struct

from Crypto.Cipher import AES

from mhrise_save_bridge import _curves
from mhrise_save_bridge.constants import (
    BLOCK_DATA,
    BLOCK_ECC,
    BLOCK_HASH,
    BLOCK_SIZE,
    CHAR_PRICE,
    MASK64,
    TAIL_SIZE,
)
from mhrise_save_bridge.murmur import murmur3_32

CURVES = tuple(
    tuple(
        int.from_bytes(bytes.fromhex(value), "little")
        for value in row
    )
    for row in _curves.CURVE_ROWS
)


class CitrusError(Exception):
    """The file cannot be decrypted with this SteamID64 (wrong account or damaged file)."""


# ---- elliptic-curve arithmetic (affine, y^2 = x^3 + a x + b mod p)
def point_add(P, Q, a, p):
    if P is None:
        return Q
    if Q is None:
        return P
    x1, y1 = P
    x2, y2 = Q
    if x1 == x2 and (y1 != y2 or y1 == 0):
        return None
    if P == Q:
        slope = (3 * x1 * x1 + a) * pow(2 * y1, p - 2, p) % p
    else:
        slope = (y2 - y1) * pow(x2 - x1, p - 2, p) % p
    x3 = (slope * slope - x1 - x2) % p
    return (x3, (slope * (x1 - x3) - y1) % p)


def point_mul(k, P, a, p):
    result = None
    while k > 0:
        if k & 1:
            result = point_add(P = result, Q = P, a = a, p = p)
        P = point_add(P = P, Q = P, a = a, p = p) if P else None
        k >>= 1
    return result


# ---- AES-128-CBC with the format's extra XOR patch over every 16-byte block after the first
def _patch(buf, key, iv):
    mask = bytes(k ^ v for k, v in zip(key, iv))
    out = bytearray(buf)
    for start in range(16, len(out), 16):
        for j in range(16):
            out[start + j] ^= mask[j]
    return out


def aes_decrypt(buf, key, iv):
    plain = bytearray(AES.new(key = key, mode = AES.MODE_CBC, iv = iv).decrypt(bytes(buf)))
    return bytes(_patch(buf = plain, key = key, iv = iv))


def aes_encrypt(buf, key, iv):
    patched = _patch(buf = buf, key = key, iv = iv)
    return AES.new(key = key, mode = AES.MODE_CBC, iv = iv).encrypt(bytes(patched))


# ---- ElGamal-wrapped block keys
def _decode_segment(segment, d, curve):
    p, a = curve[0], curve[1]
    c1 = (int.from_bytes(segment[0:32], "little"), int.from_bytes(segment[32:64], "little"))
    c2 = (int.from_bytes(segment[64:96], "little"), int.from_bytes(segment[96:128], "little"))
    shared = point_mul(k = d, P = c1, a = a, p = p)
    if shared is None:
        return None
    message = point_add(P = c2, Q = (shared[0], (p - shared[1]) % p), a = a, p = p)
    if message is None:
        return None
    return (message[0] // CHAR_PRICE) & MASK64


def _decode_keys(ecc, d, curve):
    halves = [
        _decode_segment(segment = ecc[i * 128:(i + 1) * 128], d = d, curve = curve)
        for i in range(4)
    ]
    if None in halves:
        return None
    return struct.pack("<QQ", halves[0], halves[1]), struct.pack("<QQ", halves[2], halves[3])


def _encode_segment(value, public, curve):
    p, a, b, gx, gy = curve
    x = value * CHAR_PRICE
    rhs = (pow(x, 3, p) + a * x + b) % p
    y = pow(rhs, (p + 1) // 4, p)
    if y * y % p != rhs:
        return None  # x is not on the curve; the caller draws other key halves
    k = secrets.randbits(64) | 1
    c1 = point_mul(k = k, P = (gx, gy), a = a, p = p)
    c2 = point_add(
        P = (x, y),
        Q = point_mul(k = k, P = public, a = a, p = p),
        a = a,
        p = p,
    )
    return b"".join(v.to_bytes(32, "little") for v in (c1[0], c1[1], c2[0], c2[1]))


def _encode_keys(real_key, real_iv, public, curve):
    out = b""
    for value in struct.unpack("<QQQQ", real_key + real_iv):
        segment = _encode_segment(value = value, public = public, curve = curve)
        if segment is None:
            return None
        out += segment
    return out


# ---- whole payloads
def decrypt_payload(body, steam_id64):
    """Decrypt a PC file body (the bytes after the 16-byte header, up to the u64 length).

    Returns (plain, curve_index, declared_length, hashes_ok).
    """
    d = (~steam_id64) & MASK64
    declared = struct.unpack("<Q", body[-8:])[0]
    enc = body[:-8]
    if len(enc) < TAIL_SIZE or (len(enc) - TAIL_SIZE) % BLOCK_SIZE:
        raise CitrusError("file size does not fit the block layout")
    count = (len(enc) - TAIL_SIZE) // BLOCK_SIZE
    curve_index = detect_curve(first_block = enc[:BLOCK_SIZE], d = d)
    curve = CURVES[curve_index]
    out = bytearray()
    ok = True
    for index in range(count):
        block = enc[index * BLOCK_SIZE:(index + 1) * BLOCK_SIZE]
        ecc = aes_decrypt(buf = block[32:32 + BLOCK_ECC], key = block[0:16], iv = block[16:32])
        keys = _decode_keys(ecc = ecc, d = d, curve = curve)
        if keys is None:
            raise CitrusError("block key does not decode")
        plain = bytearray(
            aes_decrypt(buf = block[0x220:0x220 + BLOCK_DATA], key = keys[0], iv = keys[1]),
        )
        size = declared - len(out) if index == count - 1 else BLOCK_DATA
        out += plain[:size]
        plain[size:] = bytes(len(plain) - size)  # the digest covers the zero-padded block
        digest = hashlib.sha3_256(
            block[0:32] + ecc + bytes(plain[:BLOCK_DATA - BLOCK_HASH]),
        ).digest()
        if digest != block[0x40220:BLOCK_SIZE]:
            ok = False
    return bytes(out), curve_index, declared, ok


def detect_curve(first_block, d):
    """The curve preset is not stored; the right one yields mostly zero bytes (padding)."""
    ecc = aes_decrypt(buf = first_block[32:32 + BLOCK_ECC], key = first_block[0:16], iv = first_block[16:32])
    for index, curve in enumerate(CURVES):
        keys = _decode_keys(ecc = ecc, d = d, curve = curve)
        if keys is None:
            continue
        sample = aes_decrypt(buf = first_block[0x220:0x220 + BLOCK_DATA], key = keys[0], iv = keys[1])
        if sample.count(0) > len(sample) // 2:
            return index
    raise CitrusError("no curve fits: wrong SteamID64 for this file?")


def encrypt_payload(payload, steam_id64, curve_index):
    """Inverse of decrypt_payload; returns the file body (blocks + zero tail + u64 length)."""
    d = (~steam_id64) & MASK64
    curve = CURVES[curve_index]
    if curve[0] % 4 != 3:
        raise CitrusError("this curve preset cannot be used to write files (p mod 4 != 3)")
    public = point_mul(k = d, P = (curve[3], curve[4]), a = curve[1], p = curve[0])
    out = bytearray()
    for start in range(0, len(payload), BLOCK_DATA):
        chunk = payload[start:start + BLOCK_DATA]
        plain = chunk + bytes(BLOCK_DATA - len(chunk))
        key = secrets.token_bytes(16)
        iv = secrets.token_bytes(16)
        while True:
            real_key = secrets.token_bytes(16)
            real_iv = secrets.token_bytes(16)
            ecc = _encode_keys(real_key = real_key, real_iv = real_iv, public = public, curve = curve)
            if ecc is not None:
                break
        digest = hashlib.sha3_256(key + iv + ecc + plain[:BLOCK_DATA - BLOCK_HASH]).digest()
        out += key + iv
        out += aes_encrypt(buf = ecc, key = key, iv = iv)
        out += aes_encrypt(buf = plain, key = real_key, iv = real_iv)
        out += digest
    out += bytes(TAIL_SIZE)
    return bytes(out) + struct.pack("<Q", len(payload))


def outer_hash_ok(data):
    return murmur3_32(data = data[:-4]) == struct.unpack("<I", data[-4:])[0]
