import pytest

from mhrise_save_bridge import citrus, container, stream
from mhrise_save_bridge.constants import BLOCK_DATA
from mhrise_save_bridge.murmur import murmur3_32, name_hash

from tests.fixtures import FAKE_STEAM_ID64, FAST_CURVE, scalar, text


def test_murmur_reference_vectors():
    assert murmur3_32(
        data = b"",
        seed = 0,
    ) == 0
    assert murmur3_32(
        data = b"test",
        seed = 0,
    ) == 0xBA6BD213
    assert murmur3_32(
        data = b"Hello, world!",
        seed = 0x9747B28C,
    ) == 0x24884CBA


def test_murmur_tail_lengths_differ():
    hashes = {murmur3_32(data = b"abcdefg"[:n]) for n in range(1, 8)}
    assert len(hashes) == 7


def test_class_name_hash():
    assert name_hash(name = "snow.data.HandMoney") == 0x079713AC


@pytest.mark.parametrize("origin", [
    12,
    16,
])
def test_stream_roundtrip(origin):
    array_of_classes = {
        "mt": 0x11,
        "ms": 0,
        "at": 1,
        "hashes": [
            7,
            8,
        ],
        "vals": [
            (
                0x10,
                [scalar(
                    field_hash = 1,
                    value = 1,
                )],
            ),
            (
                0x10,
                [scalar(
                    field_hash = 1,
                    value = 2,
                )],
            ),
        ],
    }
    strings = {
        "mt": 0x0F,
        "ms": 0,
        "at": 0,
        "hashes": None,
        "vals": [
            b"a\x00",
            b"b\x00c\x00",
        ],
    }
    entries = [
        (
            0xAA,
            (
                0xBB,
                [
                    scalar(
                        field_hash = 1,
                        value = 1,
                        size = 1,
                    ),
                    scalar(
                        field_hash = 2,
                        value = 2**40,
                        size = 8,
                    ),
                    text(
                        field_hash = 3,
                        value = "hi",
                    ),
                    [
                        4,
                        -1,
                        array_of_classes,
                    ],
                    [
                        5,
                        -1,
                        strings,
                    ],
                    [
                        6,
                        0x11,
                        (
                            0xCC,
                            [scalar(
                                field_hash = 9,
                                value = 3,
                                size = 2,
                            )],
                        ),
                    ],
                ],
            ),
        ),
    ]
    raw = stream.encode(
        entries = entries,
        origin = origin,
    )
    assert stream.parse(
        data = raw,
        origin = origin,
    ) == entries
    assert stream.encode(entries = stream.parse(
        data = raw,
        origin = origin,
    ), origin = origin) == raw


def test_stream_rejects_garbage():
    with pytest.raises(stream.StreamError):
        stream.parse(
            data = b"\xff" * 64,
            origin = 16,
        )


def test_sqrt_mod_both_prime_classes():
    for curve_index in (
        0,
        3,
    ):  # p = 3 mod 4 and p = 1 mod 4
        p = citrus.CURVES[curve_index][0]
        assert p % 4 == (3 if curve_index == 0 else 1)
        for value in (
            4,
            12345,
            2**100 + 7,
        ):
            root = citrus.sqrt_mod(
                value = value * value % p,
                p = p,
            )
            assert root * root % p == value * value % p


@pytest.mark.parametrize("curve_index", [
    0,
    3,
])
def test_citrus_roundtrip_small_payload_any_curve(curve_index):
    payload = b"\x01\x02\x03" + bytes(300)
    body = citrus.encrypt_payload(
        payload = payload,
        steam_id64 = FAKE_STEAM_ID64,
        curve_index = curve_index,
    )
    assert citrus.decrypt_payload(
        body = body,
        steam_id64 = FAKE_STEAM_ID64,
    )[:2] == (
        payload,
        curve_index,
    )


def test_citrus_roundtrip_two_blocks():
    payload = bytes(range(251)) * 3 + bytes(BLOCK_DATA)  # mostly zero, so the curve check can tell
    payload = payload[:BLOCK_DATA + 777]
    body = citrus.encrypt_payload(
        payload = payload,
        steam_id64 = FAKE_STEAM_ID64,
        curve_index = FAST_CURVE,
    )
    plain, curve_index, declared, ok = citrus.decrypt_payload(
        body = body,
        steam_id64 = FAKE_STEAM_ID64,
    )
    assert (
        plain,
        curve_index,
        declared,
        ok,
    ) == (
        payload,
        FAST_CURVE,
        len(payload),
        True,
    )


def test_citrus_wrong_account_fails():
    body = citrus.encrypt_payload(
        payload = bytes(100),
        steam_id64 = FAKE_STEAM_ID64,
        curve_index = FAST_CURVE,
    )
    with pytest.raises(citrus.CitrusError):
        citrus.decrypt_payload(
            body = body,
            steam_id64 = FAKE_STEAM_ID64 + 1,
        )


def test_pc_container_header_and_checksums():
    payload = stream.encode(entries = [(
        1,
        (
            2,
            [scalar(
                field_hash = 3,
                value = 4,
            )],
        ),
    )], origin = 16)
    data = container.pack_pc(
        payload = payload,
        steam_id64 = FAKE_STEAM_ID64,
        curve_index = FAST_CURVE,
    )
    assert data[:4] == b"DSSS"
    assert container.header_flags(data = data) == 0x04
    assert container.kind_of(data = data) == "pc"
    assert citrus.outer_hash_ok(data = data)
    opened = container.open_save(
        data = data,
        steam_id64 = FAKE_STEAM_ID64,
    )
    assert (
        opened.payload,
        opened.hashes_ok,
        opened.origin,
    ) == (
        payload,
        True,
        16,
    )
    damaged = bytearray(data)
    damaged[100] ^= 1
    with pytest.raises(container.ContainerError):
        container.open_save(
            data = bytes(damaged),
            steam_id64 = FAKE_STEAM_ID64,
        )


def test_pc_needs_steam_id_and_switch_does_not(tmp_path):
    from tests.fixtures import make_pc_dir, make_switch_dir

    pc = (make_pc_dir(directory = tmp_path / "pc") / "data00-1.bin").read_bytes()
    with pytest.raises(container.ContainerError):
        container.open_save(
            data = pc,
            steam_id64 = None,
        )
    switch = (make_switch_dir(directory = tmp_path / "sw") / "data00-1.bin").read_bytes()
    assert container.kind_of(data = switch) == "switch"
    assert container.open_save(data = switch).origin == 12


def test_non_save_rejected():
    with pytest.raises(container.ContainerError):
        container.header_flags(data = b"not a save at all, sorry")
