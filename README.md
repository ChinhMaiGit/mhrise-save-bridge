# mhrise-save-bridge

Bring a **Monster Hunter Rise** save from the **Nintendo Switch** to the **Steam (PC)** version.

The two versions store saves differently (the PC one is encrypted with your Steam account). This tool reads the
Switch save, rebuilds the character in the PC format and puts it in a free character slot of your Steam save.
It can also copy the item box (and other parts) from one PC character to another.

> Unofficial, no warranty. It was tested end to end on one real save (the game loaded and played the converted
> character), but a different save may behave differently. **It always makes a backup first, and nothing is
> written unless you say so.** Not affiliated with Capcom, Nintendo or Valve.

## Windows walkthrough (no technical knowledge needed)

### What you need

- The game installed on Steam and started **at least once**, with **one character created and saved**
  (the tool uses it as the template for the PC format). Quit the game afterwards.
- Your **Switch save files** as a folder on the PC (next section).
- `mhrise-save-bridge.exe` from the [Releases](../../releases) page.

### 1. Get the Switch save onto the PC

The Switch must be able to run homebrew; a save manager such as **Checkpoint** or **JKSV** is used for this.

1. On the Switch, open Checkpoint (or JKSV), pick **Monster Hunter Rise** (title id `0100E21013908000`) and back up
   your user's save. Wait for it to finish.
2. Copy that backup from the SD card to the PC (card reader or USB cable). Checkpoint normally keeps
   it on the SD card under `switch/Checkpoint/saves/`, in a folder named after the game, then a folder per backup
   (JKSV and other managers use their own folders: look for the one that holds `data00-1.bin`).
3. Check that the folder contains `data00-1.bin` and `data001Slot.bin`. Keep this folder; its path is asked below.

### 2. Prepare Steam

1. Turn **Steam Cloud off** for the game: Steam > Library > right-click *Monster Hunter Rise* > Properties >
   General > untick *Keep games saves in the Steam Cloud*. (Otherwise Steam can bring back the old save.)
2. **Quit Steam completely** (tray icon next to the clock > right-click > Exit) and make sure the game is closed.

### 3. Run the tool

1. Double-click `mhrise-save-bridge.exe`. Windows may warn that the file is from an unknown publisher: *More info >
   Run anyway*. The exe is not code-signed; if you prefer, you can build it from the source here.
2. Drag your Switch folder into the window (or type its path) and press Enter.
3. The tool shows your Switch characters, finds your Steam save folder
   (`C:\Program Files (x86)\Steam\userdata\<number>\1446780\remote\win64_save`) and shows your PC slots.
4. It names the slot it will fill (the first free one; it never replaces a used slot) and asks `Install it now?`.
   Type `yes`. It asks once more that Steam Cloud is off, makes a backup, and installs.
5. The backup is in `C:\Users\<you>\mhrise-save-bridge-backups\<date-time>`. To undo, quit Steam and copy those
   files back into the `win64_save` folder.

### 4. Check it

Start Steam, start the game, open the character select screen: the Switch character should be in the new slot.
Play a little, quit to the title and re-open to be sure it saved. Only then turn Steam Cloud back on (if Steam asks
which save to keep, keep the one on this PC, i.e. *Upload*).

### Problems

| message | what to do |
|---|---|
| `Close Steam completely ...` | exit Steam from the tray icon and close the game, then run again |
| `no character yet` | start the game, create any character, let it save, quit, run again |
| `all three PC slots are in use` | free a slot in-game, or use the command line with `--slot N --force` |
| `could not find your Steam save folder` | use the command line with `--steam-dir "<path to win64_save>"` |
| `no curve fits: wrong SteamID64` | the Steam account differs from the one that owns the save; pass `--steamid64` |

## Command line

```
mhrise-save-bridge inspect <folder>                      # slots, names, HR/MR (read only)
mhrise-save-bridge convert --switch-dir <folder>         # dry run: shows what would happen
mhrise-save-bridge convert --switch-dir <folder> --apply # backup, then install
mhrise-save-bridge transfer --from-slot 1 --to-slot 2 --what item-box --apply
mhrise-save-bridge guide                                 # the question-and-answer mode
```

Options: `--steam-dir` (the `win64_save` folder or a parent), `--steamid64` (full id, or the number from the
`userdata` folder name; derived from the folder when omitted), `--slot N` (PC slot, default first free),
`--switch-slot N`, `--force` (allow replacing a used slot), `--output-dir DIR` (write the files there instead of
Steam), `--yes`, `--skip-process-check`. `transfer --what` takes any of `item-box`, `equip-box`, `equipment`,
`item-sets`, `zenny`, `village-points`.

Safety built in: dry run by default; refuses while Steam or the game runs; reminds you about Steam Cloud; backs up
the whole save folder before writing; never overwrites a used slot without `--force`; writes files atomically.

## From source

```
uv sync
uv run pytest
uv run mhrise-save-bridge --help
```

Python 3.10+, one dependency (`pycryptodome`). Windows exe: `uv run pyinstaller --onefile --name mhrise-save-bridge packaging/entry.py --paths src`
(a GitHub Actions workflow builds and attaches it to tagged releases).

## Not done yet

Album photos, other Switch-only unlocks, Steam Cloud handling. Format notes: [docs/format.md](docs/format.md).

## Credits

Built on the work of ChevalGrand ([mhrise-save-editor](https://github.com/ChevalGrand/mhrise-save-editor), MIT: the
Citrus cipher and the curve table), which in turn credits jinghaihan/mhrise-save-converter and
kvasszn/ree-save-editor. See `NOTICE`. Licence: MIT.
