# claude-zoia-skill

A [Claude Code](https://claude.com/claude-code) plugin that lets Claude read and
edit [Empress ZOIA](https://empresseffects.com/products/zoia) patches.

ZOIA patches are binary `.bin` files. The skill turns them into plain JSON, so a
patch can be inspected ("what modules are in this?") or modified ("add a delay",
"make it brighter") in text, then written back to a `.bin` the pedal loads. The
encoder round-trips **byte-exact**: an untouched decode→encode is a no-op, so
only your edits change bytes.

You keep each patch in its own repository. The skill and its engine are
installed once per machine and work from any directory.

## Install

```
/plugin marketplace add sheoak/claude-zoia-skill
/plugin install zoia-patch-edit@zoia-tools
/reload-plugins
```

The engine then has to be installed once per machine. The simplest way is to
just ask Claude to edit a patch: the skill checks for the engine and offers to
run `setup` itself.

To do it by hand, run `setup` from wherever the plugin was installed:

```
python3 <plugin-dir>/skills/zoia-patch-edit/scripts/patch_cli.py setup
```

Cloning this repository and running the script from there works too — the
script and the engine are independent.

## The engine

Parsing and encoding are done by the ZOIA Librarian's `PatchBinary` and
`PatchEncoder` ([meanmedianmoge/zoia_lib](https://github.com/meanmedianmoge/zoia_lib),
GPLv3). `setup` shallow-clones it into `~/.cache/claude-zoia-skill/zoia_lib`
(~18 MB), shared by every patch repo — you never clone it again.

Already have a checkout? Point at it instead:

```bash
export ZOIA_LIB_PATH=/path/to/zoia_lib
```

`patch_cli.py where` prints which checkout is in use.

### Use the fork until it lands upstream

**[sheoak/zoia_lib](https://github.com/sheoak/zoia_lib) is strongly
recommended.** Reading a few thousand real patches turned up module definitions
the upstream index has wrong — `Sequencer` outputs off by two, `Tremolo`'s
`depth` and outputs off by one, `Audio In Switch` inputs 9 to 14 misplaced,
`Delay Line`'s time list starting at the wrong end, `Delay w/Mod`'s knob order.
A patch that touches any of those decodes to the wrong blocks, and an edit made
on top of that writes a `.bin` the pedal reads as something else.

The fixes are offered upstream as pull requests. Until they are merged, clone
the fork and point at it:

```bash
git clone --depth 1 https://github.com/sheoak/zoia_lib.git
export ZOIA_LIB_PATH="$PWD/zoia_lib"
```

Once upstream carries them, `setup` alone is enough and this section can be
ignored.

Python 3 only — the engine has no dependencies of its own for patch work, so
nothing needs installing beyond the clone.

## Per-patch repositories

Each patch repo declares the skill in its own `.claude/settings.json`, so
opening the repo is enough — no per-repo path, and nothing to install by hand:

```json
{
  "extraKnownMarketplaces": {
    "zoia-tools": {
      "source": { "source": "github", "repo": "sheoak/claude-zoia-skill" }
    }
  },
  "enabledPlugins": {
    "zoia-patch-edit@zoia-tools": true
  }
}
```

Copy [`templates/settings.json`](templates/settings.json) to
`.claude/settings.json`, and optionally [`templates/CLAUDE.md`](templates/CLAUDE.md)
to tell Claude what the `.bin` files in the repo are.

Claude Code prompts you to install the marketplace the first time you trust the
folder. The engine clone is shared, so only the first repo pays for it.

## CLI

The tool is usable on its own, without Claude, from any directory:

```bash
patch_cli.py setup                      # once per machine
patch_cli.py where                      # which engine checkout is in use
patch_cli.py info      patch.bin        # human-readable summary
patch_cli.py decode    patch.bin patch.json
patch_cli.py encode    patch.json out.bin
patch_cli.py roundtrip patch.bin        # prove decode->encode is lossless

patch_cli.py sd /Volumes/CARD/ZOIA      # register the SD patch folder, once
patch_cli.py sd                         # show it, and whether the card is mounted
patch_cli.py sync   patch.bin           # copy it onto the card, into its slot
```

## Syncing to the SD card

Register the folder that holds the patches — not the root of the card — and it
is remembered in `~/.config/claude-zoia-skill/config.json`. Afterwards `sync`
copies a `.bin` into its slot.

The slot comes from the filename (`003_zoia_The_Hierophant.bin`), or from
`--slot N`. A slot holds exactly one file, so `sync` overwrites the file already
there and keeps its name; renaming with `--name` has to delete the old file and
therefore requires `--replace`. `--dry-run` shows the plan without touching the
card.

Before copying, `sync` parses the patch, and afterwards it reads the written
file back and compares it — a `.bin` the pedal could not read never lands on the
card.

## Caveat

Patches are written to real hardware. Keep a backup of any `.bin` before
overwriting it, and re-run `info` on the encoded file to confirm it still
parses before loading it on the pedal.

## Credits

The patch binary format was reverse-engineered by the ZOIA community —
djigneo/apparent1 did the original decoding work, and the format is documented
in zoia_lib's `documentation/Binary Format.pdf`, written with the help of
Steeve Bragg of Empress Effects. All parsing and encoding here is
[meanmedianmoge/zoia_lib](https://github.com/meanmedianmoge/zoia_lib)'s work.

## License

MIT — see [LICENSE](LICENSE). This repository contains no zoia_lib code; the
GPLv3 engine is cloned separately at setup time and stays under its own terms.
