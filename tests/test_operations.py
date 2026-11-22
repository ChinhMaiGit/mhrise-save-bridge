import pytest

from mhrise_save_bridge import cli, container, operations, safety, slots, steam, stream
from mhrise_save_bridge.constants import CLASS_SUMMARY

from tests.fixtures import (
    EQUIP_BOX,
    FAKE_STEAM_ID64,
    ITEM_BOX,
    PC_ONLY_FIELD,
    make_pc_dir,
    make_switch_dir,
    slot_entries,
    write_pc,
)

GUID = bytes(range(16))


@pytest.fixture(scope = "module")
def dirs(tmp_path_factory):
    base = tmp_path_factory.mktemp("saves")
    return make_switch_dir(directory = base / "sw"), make_pc_dir(directory = base / "pc")


def decode(plan, name):
    return stream.parse(
        data = plan.payloads[name],
        origin = 16,
    )


def test_inspect_both_platforms(dirs):
    switch_dir, pc_dir = dirs
    rows = operations.inspect(
        directory = switch_dir,
        steam_id64 = None,
    )
    assert "platform: switch" in rows[0]
    assert any("Alice" in row and "HR 120" in row and "MR 4" in row for row in rows)
    rows = operations.inspect(
        directory = pc_dir,
        steam_id64 = FAKE_STEAM_ID64,
    )
    assert any("Bob" in row and "HR 500" in row for row in rows)
    assert sum("(empty)" in row for row in rows) == 2
    assert "PC saves are encrypted" in operations.inspect(
        directory = pc_dir,
        steam_id64 = None,
    )[-1]


def run_convert(dirs, **overrides):
    switch_dir, pc_dir = dirs
    arguments = {
        "switch_dir": switch_dir,
        "pc_dir": pc_dir,
        "steam_id64": FAKE_STEAM_ID64,
        "target_slot": None,
        "switch_slot": 1,
        "force": False,
        "guid": GUID,
    }
    arguments.update(overrides)
    return operations.plan_convert(**arguments)


def test_convert_fills_first_free_slot(dirs):
    plan = run_convert(dirs = dirs)
    assert set(plan.files) == {
        "data00-1.bin",
        "data002Slot.bin",
    }
    new_slot = decode(plan = plan, name = "data002Slot.bin")
    info = slots.slot_info(slot_entries = new_slot)
    assert (
        info.name,
        info.hunter_rank,
        info.master_rank,
    ) == (
        "Alice",
        120,
        4,
    )
    # PC order (reversed here, plus the PC-only entry), not the Switch order
    assert [native for native, _ in new_slot] == [
        0xB0000006,
        0xB0000005,
        0xB0000004,
        0xB0000003,
        0xB0000002,
        0xB0000001,
        0xB00000FF,
    ]
    pc_a = slots.find(
        entries = new_slot,
        class_hash = 0x95320424,
    )[0]
    assert [f[0] for f in pc_a[1]] == [
        1,
        2,
    ]
    assert slots.find(
        entries = new_slot,
        class_hash = 0x5766F30B,
    )[0][1][0][2] == (
        16,
        GUID,
    )
    summaries = slots.summaries(system_entries = decode(plan = plan, name = "data00-1.bin"))
    assert [s.name for s in summaries][:2] == [
        "Bob",
        "Alice",
    ]
    system = decode(plan = plan, name = "data00-1.bin")
    assert PC_ONLY_FIELD in [f[0] for f in slots.find(
        entries = system,
        class_hash = CLASS_SUMMARY,
    )[1][1]]


def test_convert_output_is_a_valid_pc_file(dirs):
    plan = run_convert(dirs = dirs)
    opened = container.open_save(
        data = plan.files["data002Slot.bin"],
        steam_id64 = FAKE_STEAM_ID64,
    )
    assert opened.hashes_ok
    assert opened.payload == plan.payloads["data002Slot.bin"]


def test_convert_refuses_used_slot_without_force(dirs):
    with pytest.raises(operations.OperationError, match = "already used"):
        run_convert(
            dirs = dirs,
            target_slot = 1,
        )
    plan = run_convert(
        dirs = dirs,
        target_slot = 1,
        force = True,
    )
    assert "overwriting" in plan.notes[0]


def test_convert_needs_a_template_character(tmp_path, dirs):
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "data00-1.bin").write_bytes((dirs[1] / "data00-1.bin").read_bytes())
    with pytest.raises(operations.OperationError, match = "no character yet"):
        run_convert(dirs = (
            dirs[0],
            empty,
        ))


def test_transfer_copies_only_the_chosen_class(tmp_path, dirs):
    pc_dir = tmp_path / "pc"
    make_pc_dir(directory = pc_dir)
    write_pc(
        path = pc_dir / "data002Slot.bin",
        entries = slot_entries(
            name = "Carol",
            hunter_rank = 9,
            master_rank = 0,
            items = [5],
            pc = True,
        ),
    )
    plan = operations.plan_transfer(
        pc_dir = pc_dir,
        steam_id64 = FAKE_STEAM_ID64,
        from_slot = 1,
        to_slot = 2,
        groups = ["item-box"],
    )
    new = decode(plan = plan, name = "data002Slot.bin")
    old = stream.parse(
        data = container.open_save(
            data = (pc_dir / "data002Slot.bin").read_bytes(),
            steam_id64 = FAKE_STEAM_ID64,
        ).payload,
        origin = 16,
    )
    box = slots.find(
        entries = new,
        class_hash = ITEM_BOX,
    )[0]
    assert [v for v in box[1][0][2]["vals"]] == [
        (9).to_bytes(4, "little"),
        (8).to_bytes(4, "little"),
    ]
    assert slots.find(
        entries = new,
        class_hash = EQUIP_BOX,
    ) == slots.find(
        entries = old,
        class_hash = EQUIP_BOX,
    )
    assert slots.slot_info(slot_entries = new).name == "Carol"


def test_transfer_validates_arguments(dirs):
    with pytest.raises(operations.OperationError):
        operations.plan_transfer(
            pc_dir = dirs[1],
            steam_id64 = FAKE_STEAM_ID64,
            from_slot = 1,
            to_slot = 1,
            groups = ["item-box"],
        )
    with pytest.raises(operations.OperationError):
        operations.plan_transfer(
            pc_dir = dirs[1],
            steam_id64 = FAKE_STEAM_ID64,
            from_slot = 1,
            to_slot = 2,
            groups = ["nonsense"],
        )


# ---- CLI and safety
def convert_args(switch_dir, pc_dir, extra = ()):
    return [
        "convert",
        "--switch-dir",
        str(switch_dir),
        "--steam-dir",
        str(pc_dir),
        "--steamid64",
        str(FAKE_STEAM_ID64),
        *extra,
    ]


def test_cli_dry_run_writes_nothing_and_output_dir_writes(tmp_path, dirs, capsys):
    base = convert_args(
        switch_dir = dirs[0],
        pc_dir = dirs[1],
    )
    before = sorted(p.name for p in dirs[1].iterdir())
    assert cli.main(argv = base) == 0
    assert "dry run" in capsys.readouterr().out
    assert sorted(p.name for p in dirs[1].iterdir()) == before
    out = tmp_path / "out"
    assert cli.main(argv = base + [
        "--output-dir",
        str(out),
    ]) == 0
    assert (out / "data002Slot.bin").is_file()
    assert sorted(p.name for p in dirs[1].iterdir()) == before


def test_cli_apply_backs_up_and_checks_cloud(tmp_path, dirs, monkeypatch, capsys):
    pc_dir = tmp_path / "pc"
    make_pc_dir(directory = pc_dir)
    monkeypatch.setattr(safety, "backup_root", lambda: tmp_path / "backups")
    monkeypatch.setattr(steam, "running_blockers", lambda: [])
    base = convert_args(
        switch_dir = dirs[0],
        pc_dir = pc_dir,
        extra = ["--apply"],
    )
    monkeypatch.setattr("builtins.input", lambda prompt: "no")
    assert cli.main(argv = base) == 1
    assert not (pc_dir / "data002Slot.bin").exists()
    assert cli.main(argv = base + ["--yes"]) == 0
    assert (pc_dir / "data002Slot.bin").is_file()
    backups = list((tmp_path / "backups").iterdir())
    assert len(backups) == 1 and (backups[0] / "data001Slot.bin").is_file()
    assert not (backups[0] / "data002Slot.bin").exists()
    assert "Steam Cloud" in capsys.readouterr().out


def test_cli_refuses_while_game_runs(tmp_path, dirs, monkeypatch, capsys):
    monkeypatch.setattr(steam, "running_blockers", lambda: ["steam.exe"])
    arguments = convert_args(
        switch_dir = dirs[0],
        pc_dir = dirs[1],
        extra = [
            "--apply",
            "--yes",
        ],
    )
    code = cli.main(argv = arguments)
    assert code == 1
    assert "Close Steam" in capsys.readouterr().err


# ---- Steam folder helpers
def test_steam_id_helpers(tmp_path):
    save = tmp_path / "Steam" / "userdata" / "123456789" / "1446780" / "remote" / "win64_save"
    save.mkdir(parents = True)
    (save / "data00-1.bin").write_bytes(b"x")
    assert steam.steam_id64_from_dir(save_dir = save) == FAKE_STEAM_ID64
    assert steam.normalize_save_dir(path = tmp_path / "Steam" / "userdata" / "123456789") == save
    assert steam.parse_steam_id(text = "123456789") == FAKE_STEAM_ID64
    assert steam.parse_steam_id(text = str(FAKE_STEAM_ID64)) == FAKE_STEAM_ID64
    assert steam.save_dirs(root = tmp_path / "Steam") == [save]
    assert steam.steam_id64_from_dir(save_dir = tmp_path) is None


def test_guide_installs_after_yes(tmp_path, dirs, monkeypatch, capsys):
    pc_dir = tmp_path / "userdata" / "123456789" / "1446780" / "remote" / "win64_save"
    make_pc_dir(directory = pc_dir)
    monkeypatch.setattr(safety, "backup_root", lambda: tmp_path / "backups")
    monkeypatch.setattr(steam, "running_blockers", lambda: [])
    monkeypatch.setattr(steam, "find_save_dir", lambda: pc_dir)
    answers = iter([
        str(dirs[0]),
        "",
        "yes",
        "yes",
    ])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    assert cli.main(argv = []) == 0
    assert (pc_dir / "data002Slot.bin").is_file()
    assert "Alice" in capsys.readouterr().out
