"""Lossless-by-value parse/encode of the RE Engine class stream (port of ChevalGrand payload.rs, MIT).

Data model (plain Python, see docs/format.md):
  stream = list of (native_hash, Class); Class = (class_hash, [Field]); Field = [hash, type, value]
  value: bytes (string, UTF-16LE), (size, bytes) for scalars, Class for type 0x11, Array for -1
  Array = dict(mt, ms, at, hashes, vals)
Padding bytes are written as zeros (the game leaves them uninitialised).
"""

import struct

TYPE_ARRAY = -1
TYPE_CLASS = 0x11
TYPE_STRING = 0x0F
ARRAY_HASH_MARK = 0xFFEEFFEE


class StreamError(Exception):
    """The class stream is malformed or not from Monster Hunter Rise."""


class Reader:
    def __init__(self, data, origin):
        self.data = data
        self.pos = 0
        self.origin = origin

    def u32(self):
        value = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return value

    def i32(self):
        value = struct.unpack_from("<i", self.data, self.pos)[0]
        self.pos += 4
        return value

    def align(self, size):
        self.pos = ((self.origin + self.pos + size - 1) & ~(size - 1)) - self.origin
        if self.pos > len(self.data):
            raise StreamError("alignment runs past the end of the stream")

    def remaining(self):
        return len(self.data) - self.pos

    def peek(self):
        if self.remaining() < 4:
            return None
        return struct.unpack_from("<I", self.data, self.pos)[0]

    def take(self, size):
        if size > self.remaining():
            raise StreamError("read past the end of the stream")
        value = bytes(self.data[self.pos:self.pos + size])
        self.pos += size
        return value


def _read_sized(reader, size):
    if size <= 0:
        raise StreamError("zero-sized scalar")
    if size != 1:
        reader.align(size = size)
    return reader.take(size = size)


def _read_string(reader):
    reader.align(size = 4)
    length = reader.u32()
    if length > reader.remaining() // 2:
        raise StreamError("string longer than the stream")
    return reader.take(size = 2 * length)


def _read_array(reader):
    reader.align(size = 4)
    member_type = reader.i32()
    member_size = reader.u32()
    length = reader.u32()
    array_type = reader.i32()
    if array_type not in (
        0,
        1,
    ):
        raise StreamError("unknown array kind")
    hashes = None
    if array_type == 1 and reader.peek() == ARRAY_HASH_MARK:
        reader.u32()
        hashes = [reader.u32() for _ in range(length)]
    values = []
    for _ in range(length):
        if array_type == 1:
            values.append(_read_class(reader = reader))
        elif member_type == TYPE_ARRAY:
            values.append(_read_array(reader = reader))
        elif member_type == TYPE_STRING:
            values.append(_read_string(reader = reader))
        else:
            values.append(_read_sized(
                reader = reader,
                size = member_size,
            ))
    reader.align(size = 4)
    return {
        "mt": member_type,
        "ms": member_size,
        "at": array_type,
        "hashes": hashes,
        "vals": values,
    }


def _read_class(reader):
    count = reader.u32()
    class_hash = reader.u32()
    if count > reader.remaining() // 8:
        raise StreamError("class claims more fields than the stream holds")
    fields = []
    for _ in range(count):
        field_hash = reader.u32()
        field_type = reader.i32()
        if field_type == TYPE_ARRAY:
            value = _read_array(reader = reader)
        elif field_type == TYPE_CLASS:
            value = _read_class(reader = reader)
        elif field_type == TYPE_STRING:
            value = _read_string(reader = reader)
        else:
            reader.align(size = 4)
            size = reader.u32()
            value = (
                size,
                _read_sized(
                    reader = reader,
                    size = size,
                ),
            )
        reader.align(size = 4)
        fields.append([
            field_hash,
            field_type,
            value,
        ])
    return (
        class_hash,
        fields,
    )


def parse(data, origin):
    reader = Reader(
        data = data,
        origin = origin,
    )
    entries = []
    try:
        while reader.remaining() > 0:
            if reader.remaining() < 12 and not any(data[reader.pos:]):
                break
            native_hash = reader.u32()
            entries.append((
                native_hash,
                _read_class(reader = reader),
            ))
    except (
        struct.error,
        StreamError,
    ) as error:
        raise StreamError(f"cannot parse the class stream at offset {reader.pos}: {error}") from error
    return entries


class Writer:
    def __init__(self, origin):
        self.buf = bytearray()
        self.origin = origin

    def u32(self, value):
        self.buf += struct.pack("<I", value & 0xFFFFFFFF)

    def i32(self, value):
        self.buf += struct.pack("<i", value)

    def align(self, size):
        target = ((self.origin + len(self.buf) + size - 1) & ~(size - 1)) - self.origin
        self.buf += bytes(target - len(self.buf))


def _write_sized(writer, size, value):
    if len(value) != size:
        raise StreamError("scalar size does not match its bytes")
    if size != 1:
        writer.align(size = size)
    writer.buf += value


def _write_string(writer, value):
    writer.align(size = 4)
    writer.u32(value = len(value) // 2)
    writer.buf += value


def _write_array(writer, array):
    writer.align(size = 4)
    writer.i32(value = array["mt"])
    writer.u32(value = array["ms"])
    writer.u32(value = len(array["vals"]))
    writer.i32(value = array["at"])
    if array["hashes"] is not None:
        writer.u32(value = ARRAY_HASH_MARK)
        for item in array["hashes"]:
            writer.u32(value = item)
    for value in array["vals"]:
        if array["at"] == 1:
            _write_class(
                writer = writer,
                cls = value,
            )
        elif array["mt"] == TYPE_ARRAY:
            _write_array(
                writer = writer,
                array = value,
            )
        elif array["mt"] == TYPE_STRING:
            _write_string(
                writer = writer,
                value = value,
            )
        else:
            _write_sized(
                writer = writer,
                size = array["ms"],
                value = value,
            )
    writer.align(size = 4)


def _write_class(writer, cls):
    class_hash, fields = cls
    writer.u32(value = len(fields))
    writer.u32(value = class_hash)
    for field_hash, field_type, value in fields:
        writer.u32(value = field_hash)
        writer.i32(value = field_type)
        if field_type == TYPE_ARRAY:
            _write_array(
                writer = writer,
                array = value,
            )
        elif field_type == TYPE_CLASS:
            _write_class(
                writer = writer,
                cls = value,
            )
        elif field_type == TYPE_STRING:
            _write_string(
                writer = writer,
                value = value,
            )
        else:
            writer.align(size = 4)
            writer.u32(value = value[0])
            _write_sized(
                writer = writer,
                size = value[0],
                value = value[1],
            )
        writer.align(size = 4)


def encode(entries, origin):
    writer = Writer(origin = origin)
    for native_hash, cls in entries:
        writer.u32(value = native_hash)
        _write_class(
            writer = writer,
            cls = cls,
        )
    return bytes(writer.buf)
