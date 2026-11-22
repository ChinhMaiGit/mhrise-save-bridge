"""Slot-level operations on parsed class streams: find, blank, project, replace, summaries."""

import copy

from dataclasses import dataclass

from mhrise_save_bridge.constants import (
    CLASS_GUILD_CARD,
    CLASS_PROGRESS,
    CLASS_PROJECTED,
    CLASS_SUMMARY,
    FIELD_CARD_NAME,
    FIELD_GUID,
    FIELD_HUNTER_RANK,
    FIELD_MASTER_RANK,
    FIELD_SUMMARY_NAME,
)
from mhrise_save_bridge.stream import (
    TYPE_ARRAY,
    TYPE_CLASS,
    TYPE_STRING,
)


UNSET_RANK = 0xFFFFFFFF


@dataclass
class SlotInfo:
    name: str
    hunter_rank: int
    master_rank: int

    @property
    def used(self):
        # unused slots hold a placeholder name and 0xFFFFFFFF ranks
        return 0 < self.hunter_rank < UNSET_RANK


# ---- walking
def find(entries, class_hash):
    """Every instance of a class anywhere in the stream, in file order."""
    found = []

    def walk_class(cls):
        if cls[0] == class_hash:
            found.append(cls)
        for _, field_type, value in cls[1]:
            if field_type == TYPE_CLASS:
                walk_class(cls = value)
            elif field_type == TYPE_ARRAY:
                walk_array(array = value)

    def walk_array(array):
        for value in array["vals"]:
            if array["at"] == 1:
                walk_class(cls = value)
            elif array["mt"] == TYPE_ARRAY:
                walk_array(array = value)

    for _, cls in entries:
        walk_class(cls = cls)
    return found


def replace_class(entries, class_hash, make):
    """Copy of the stream where every instance of a class is replaced by make(instance)."""

    def map_class(cls):
        if cls[0] == class_hash:
            return make(cls)
        fields = []
        for field_hash, field_type, value in cls[1]:
            if field_type == TYPE_CLASS:
                value = map_class(cls = value)
            elif field_type == TYPE_ARRAY:
                value = map_array(array = value)
            fields.append([field_hash, field_type, value])
        return (cls[0], fields)

    def map_array(array):
        out = dict(array)
        values = []
        for value in array["vals"]:
            if array["at"] == 1:
                value = map_class(cls = value)
            elif array["mt"] == TYPE_ARRAY:
                value = map_array(array = value)
            values.append(value)
        out["vals"] = values
        return out

    return [(native, map_class(cls = cls)) for native, cls in entries]


# ---- reading summaries
def _field(cls, field_hash):
    for candidate, field_type, value in cls[1]:
        if candidate == field_hash:
            return field_type, value
    return None, None


def _u32(cls, field_hash):
    _, value = _field(cls = cls, field_hash = field_hash)
    return int.from_bytes(value[1], "little") if value else 0


def _text(cls, field_hash):
    field_type, value = _field(cls = cls, field_hash = field_hash)
    if field_type != TYPE_STRING:
        return ""
    return value.decode("utf-16le", "replace")


def summaries(system_entries):
    """The three per-slot summaries in data00-1, in slot order."""
    return [
        SlotInfo(
            name = _text(cls = cls, field_hash = FIELD_SUMMARY_NAME),
            hunter_rank = _u32(cls = cls, field_hash = FIELD_HUNTER_RANK),
            master_rank = _u32(cls = cls, field_hash = FIELD_MASTER_RANK),
        )
        for cls in find(entries = system_entries, class_hash = CLASS_SUMMARY)
    ]


def slot_info(slot_entries):
    """Name/HR/MR read from the slot file itself (None if the classes are missing)."""
    cards = find(entries = slot_entries, class_hash = CLASS_GUILD_CARD)
    progress = find(entries = slot_entries, class_hash = CLASS_PROGRESS)
    if not cards or not progress:
        return None
    return SlotInfo(
        name = _text(cls = cards[0], field_hash = FIELD_CARD_NAME),
        hunter_rank = _u32(cls = progress[0], field_hash = FIELD_HUNTER_RANK),
        master_rank = _u32(cls = progress[0], field_hash = FIELD_MASTER_RANK),
    )


# ---- building a PC slot from a Switch one
def blank(field):
    """Shape of a PC-only field: arrays keep their length, scalars/strings inside are zeroed.

    A top-level scalar is kept as it is (it may be a constant).
    """
    field_hash, field_type, value = copy.deepcopy(field)

    def zero_class(cls):
        for item in cls[1]:
            zero_field(item = item)

    def zero_array(array):
        for index, element in enumerate(array["vals"]):
            if array["at"] == 1:
                zero_class(cls = element)
            elif array["mt"] == TYPE_ARRAY:
                zero_array(array = element)
            elif array["mt"] == TYPE_STRING:
                array["vals"][index] = b""
            else:
                array["vals"][index] = bytes(len(element))

    def zero_field(item):
        if item[1] == TYPE_ARRAY:
            zero_array(array = item[2])
        elif item[1] == TYPE_CLASS:
            zero_class(cls = item[2])
        elif item[1] == TYPE_STRING:
            item[2] = b""
        else:
            item[2] = (item[2][0], bytes(item[2][0]))

    if field_type == TYPE_ARRAY:
        zero_array(array = value)
    elif field_type == TYPE_CLASS:
        zero_class(cls = value)
    elif field_type == TYPE_STRING:
        value = b""
    return [field_hash, field_type, value]


def project(switch_cls, pc_template, guid):
    """PC field list and order; Switch values where the field exists, a blank PC shape otherwise."""
    switch_fields = {field[0]: field for field in switch_cls[1]}
    fields = []
    for field in pc_template[1]:
        if field[0] == FIELD_GUID:
            fields.append([field[0], field[1], (16, guid)])
        elif field[0] in switch_fields:
            fields.append(copy.deepcopy(switch_fields[field[0]]))
        else:
            fields.append(blank(field = field))
    return (switch_cls[0], fields)


def build_pc_slot(switch_slot, pc_slot_template, guid):
    """Switch slot stream re-ordered to the PC layout (PC-only entries become blank shapes)."""
    switch_by_hash = {native: cls for native, cls in switch_slot}
    entries = []
    for native, pc_cls in pc_slot_template:
        if native in switch_by_hash:
            entries.append((native, copy.deepcopy(switch_by_hash[native])))
        else:
            entries.append((native, (pc_cls[0], [blank(field = f) for f in pc_cls[1]])))
    for class_hash in CLASS_PROJECTED:
        template = find(entries = pc_slot_template, class_hash = class_hash)[0]
        entries = replace_class(
            entries = entries,
            class_hash = class_hash,
            make = lambda cls, template = template: project(
                switch_cls = cls,
                pc_template = template,
                guid = guid,
            ),
        )
    return entries


def replace_summary(pc_system, switch_system, switch_slot, target_slot, guid):
    """data00-1 with the target slot's summary swapped for the Switch character's summary."""
    switch_summary = find(entries = switch_system, class_hash = CLASS_SUMMARY)[switch_slot - 1]
    pc_template = find(entries = pc_system, class_hash = CLASS_SUMMARY)[0]
    projected = project(switch_cls = switch_summary, pc_template = pc_template, guid = guid)
    counter = {"seen": 0}

    def pick(cls):
        counter["seen"] += 1
        return projected if counter["seen"] == target_slot else cls

    return replace_class(entries = pc_system, class_hash = CLASS_SUMMARY, make = pick)
