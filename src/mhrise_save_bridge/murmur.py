"""murmur3_32, the hash used for class/field names and the PC container checksum."""

import struct

C1 = 0xCC9E2D51
C2 = 0x1B873593


def _mix(k):
    k = (k * C1) & 0xFFFFFFFF
    k = ((k << 15) | (k >> 17)) & 0xFFFFFFFF
    return (k * C2) & 0xFFFFFFFF


def murmur3_32(data, seed = 0xFFFFFFFF):
    h = seed
    whole = len(data) // 4 * 4
    for offset in range(0, whole, 4):
        h ^= _mix(struct.unpack_from("<I", data, offset)[0])
        h = ((h << 13) | (h >> 19)) & 0xFFFFFFFF
        h = (h * 5 + 0xE6546B64) & 0xFFFFFFFF
    tail = data[whole:]
    k = 0
    for position in range(len(tail) - 1, -1, -1):
        k ^= tail[position] << (8 * position)
    if tail:
        h ^= _mix(k)
    h ^= len(data)
    h ^= h >> 16
    h = (h * 0x85EBCA6B) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 0xC2B2AE35) & 0xFFFFFFFF
    h ^= h >> 16
    return h


def name_hash(name):
    return murmur3_32(data = name.encode("ascii"))
