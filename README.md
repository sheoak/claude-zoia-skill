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

Python 3 only — the engine has no dependencies of its own for patch work, so
nothing needs installing beyond the clone.

## Per-patch repositories

Drop this in the `CLAUDE.md` of each patch repo so Claude knows where the skill
lives:

```markdown
ZOIA patches in this repo are edited with the zoia-patch-edit skill:
https://github.com/sheoak/claude-zoia-skill

If it is not installed:
    /plugin marketplace add sheoak/claude-zoia-skill
    /plugin install zoia-patch-edit@zoia-tools
```

A ready-made copy is in [`templates/CLAUDE.md`](templates/CLAUDE.md).

## CLI

The tool is usable on its own, without Claude, from any directory:

```bash
patch_cli.py setup                      # once per machine
patch_cli.py where                      # which engine checkout is in use
patch_cli.py info      patch.bin        # human-readable summary
patch_cli.py decode    patch.bin patch.json
patch_cli.py encode    patch.json out.bin
patch_cli.py roundtrip patch.bin        # prove decode->encode is lossless
```

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
