# Monster Hunter Rise save format notes

What this tool relies on, found by studying real saves from both platforms and the public MIT sources
named in `NOTICE`. No game executable was read. Everything here is observation, not an official spec.

## Files

A save folder holds `data00-1.bin` (the system file: one summary per character slot), `data00NSlot.bin`
(character slot N, N = 1..3), and album photo files `SS1_dataNNNSlot.bin` / `SS7_*`.
PC: `userdata/<account id>/1446780/remote/win64_save`. Switch: the dump of title `0100E21013908000`.

## Container ("DSSS")

All main files start with `DSSS`, a u32 version (2), and a u32 **flags** word:

| bit | meaning |
|---|---|
| 0x01 | Blowfish (other RE Engine games, not Rise) |
| 0x02 | account id present (photo files on PC) |
| 0x04 | Citrus cipher (PC / Steam) |
| 0x08 | deflate (Switch) |
| 0x10 | Mandarin |

Switch main files (flags 8): 0x28-byte header, u64 inflated size at 0x20, then a raw deflate stream at
0x28. No encryption, no account id.

PC main files (flags 4): 16-byte header (`DSSS`, 2, 4, 4 zero bytes), then blocks of 0x40240 bytes, a 0x1000
zero tail, a u64 declared payload length, and a u32 murmur3_32 (seed 0xffffffff) over everything before it.

### Citrus block

```
key16 | iv16 | 0x200 wrapped keys | 0x40000 data | 32-byte SHA3-256
```

- The wrapped keys are AES-128-CBC under (key16, iv16), then XOR-patched: every 16-byte block after the
  first is XORed with `key16 ^ iv16`. The same patch is applied to the data cipher.
- The plaintext of the wrapped keys is four 128-byte EC-ElGamal ciphertexts (c1.x, c1.y, c2.x, c2.y, 32 bytes
  little-endian each). Decrypting uses the private scalar `d = NOT(SteamID64)` (64-bit complement); the message
  is `(c2 - d*c1).x / 100`, truncated to 64 bits. Four halves form the real key (2) and iv (2).
- The curve is one of 128 presets (table in `_curves.py`); it is not stored in the file. The right one is found
  by trial: it decrypts the first block to mostly zero bytes.
- Data = AES-128-CBC with the real key/iv, no padding. The SHA3 covers `key16 | iv16 | wrapped keys | plain[..0x3ffe0]`,
  with the last block zero-padded to full size.
- Writing: fresh random block keys, ElGamal with a random scalar per half. A half can only be used when
  `value * 100` is an x-coordinate on the curve, so the writer
  redraws until all four halves qualify.

SteamID64 = 76561197960265728 + the account id that is the `userdata` folder name.

## Class stream (the payload)

An RE Engine / RSZ-like stream, the same shape on both platforms:

```
stream  = { native_hash:u32, class }*
class   = field_count:u32, class_hash:u32, field*
field   = field_hash:u32, type:i32, value
value   = type -1: array | 0x11: class | 0x0f: string | else: align4, size:u32, size bytes (aligned to size)
string  = align4, length:u32 (UTF-16 units), 2*length bytes
array   = align4, member_type:i32, member_size:u32, length:u32, kind:i32 (0 values, 1 classes)
          [0xffeeffee, length x u32 hashes]? values...
```

Every field is followed by `align 4`. Alignment is measured from a stream origin: **16 for PC payloads, 12 for
Switch payloads** (found by trial; why 12 is unexplained). Class and field hashes are
murmur3_32(ASCII name, seed 0xffffffff); most names are unknown, so the tool refers to hashes.
Padding in the game's files is uninitialised memory; this tool writes zeros.

## Platform differences

- Top-level entry order differs; every Switch top-level entry exists on PC, PC has a few extra.
- A few classes have different field lists. The tool projects Switch classes onto the PC field list and fills
  PC-only fields with a blank shape (arrays keep their length, values zero). The game accepted this and
  completed the missing data on first load; it is the main risk of the conversion.
- Slot GUID: field `e40fc0cd` in class `5766f30b` (slot file) must equal the one in the summary class
  `520de8df` (system file). A fresh random GUID is written to both.
- Unused slots hold a placeholder name and 0xFFFFFFFF ranks.

## Known hashes

| hash | meaning |
|---|---|
| 520de8df | per-slot summary in `data00-1` (name f79f3af6, HR 5653c091, MR 4e428685) |
| 948b7b9d | progress (HR 5653c091, MR 4e428685) |
| 44541321 | guild card (name 02bb0110) |
| 67696161 | item box |
| f0509899 | equipment box |
| 960baed3 | equipped gear and equipment sets |
| 8923cd68 | item pouch sets |
| 079713ac | zenny (`snow.data.HandMoney`) |
| 306735ee | village points |

## Not handled

Album photos (`SS1_*`: PC adds 12 header bytes with the account id), Steam Cloud, other Switch-only unlock flags.
