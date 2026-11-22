"""Format constants of the Rise save container and class stream (see docs/format.md)."""

STEAM_ID64_BASE = 76561197960265728
RISE_APP_ID = "1446780"
SAVE_SUBDIR = (
    "remote",
    "win64_save",
)
MAX_SLOTS = 3

MAGIC = b"DSSS"
FLAG_BLOWFISH = 0x01
FLAG_HAS_ID = 0x02
FLAG_CITRUS = 0x04
FLAG_DEFLATE = 0x08
PC_HEADER = {
    "version": 2,
    "flags": FLAG_CITRUS,
}

# Offset of the class stream measured from the stream's own alignment origin; it decides the
# padding bytes. Found by trial on real files (docs/format.md).
PC_STREAM_ORIGIN = 16
SWITCH_STREAM_ORIGIN = 12
SWITCH_DEFLATE_OFFSET = 0x28
SWITCH_INFLATED_SIZE_OFFSET = 0x20

BLOCK_SIZE = 0x40240
BLOCK_DATA = 0x40000
BLOCK_ECC = 0x200
BLOCK_HASH = 0x20
TAIL_SIZE = 0x1000
MASK64 = (1 << 64) - 1
HASH_SEED = 0xFFFFFFFF
CHAR_PRICE = 100  # ElGamal-encoded key halves are multiplied by this before going on the curve

# Class hashes (murmur3_32 of the class name, seed 0xffffffff) and field hashes.
CLASS_SUMMARY = 0x520DE8DF  # data00-1: one per slot (class snow.data.<...> summary)
CLASS_PROGRESS = 0x948B7B9D
CLASS_GUILD_CARD = 0x44541321
CLASS_PROJECTED = (
    0x95320424,
    0x5766F30B,
)  # classes whose field lists differ Switch vs PC
FIELD_GUID = 0xE40FC0CD
FIELD_HUNTER_RANK = 0x5653C091
FIELD_MASTER_RANK = 0x4E428685
FIELD_CARD_NAME = 0x2BB0110
FIELD_SUMMARY_NAME = 0xF79F3AF6

# Classes that `transfer` can copy between slots.
TRANSFER_GROUPS = {
    "item-box": (0x67696161,),
    "equip-box": (0xF0509899,),
    "equipment": (0x960BAED3,),
    "item-sets": (0x8923CD68,),
    "zenny": (0x079713AC,),
    "village-points": (0x306735EE,),
}
