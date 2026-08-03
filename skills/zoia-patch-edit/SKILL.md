---
name: zoia-patch-edit
description: Edit Empress ZOIA .bin patches as JSON using AI. Use when the user asks to inspect, modify, or generate a ZOIA patch — e.g. "add a delay", "make this brighter", "retune this patch", "what modules are in this patch", or any request involving a .bin ZOIA patch file.
---

# Editing ZOIA patches with AI

ZOIA patches are binary `.bin` files. This skill lets you edit them as plain
JSON: **decode** a `.bin` to JSON, edit the JSON, then **encode** it back.

Work in the user's own patch repository — the CLI runs from any directory and
writes its output next to the files you give it.

## The CLI

```bash
CLI="${CLAUDE_PLUGIN_ROOT}/skills/zoia-patch-edit/scripts/patch_cli.py"
```

Parsing and encoding are done by the ZOIA Librarian's engine (`zoia_lib`),
which lives in a shared cache and is **cloned once per machine**, never per
patch repo.

**Before the first patch command in a session**, check it is installed:

```bash
python3 "$CLI" where
```

If it reports `NOT FOUND`, tell the user a one-time ~18 MB clone into
`~/.cache/claude-zoia-skill/` is needed, then run:

```bash
python3 "$CLI" setup
```

If the user already has a `zoia_lib` checkout, they can point at it instead
with `export ZOIA_LIB_PATH=/path/to/zoia_lib` — no clone needed.

## Workflow

```bash
# Quick summary of a patch (no file written)
python3 "$CLI" info patch.bin

# 1. Binary -> editable JSON
python3 "$CLI" decode patch.bin patch.json

# 2. Edit patch.json with the Edit tool (see structure below)

# 3. Edited JSON -> binary
python3 "$CLI" encode patch.json out.bin

# Check that a patch survives decode->encode untouched
python3 "$CLI" roundtrip patch.bin
```

## Copying a patch to the SD card

The card's patch folder is registered once, then `sync` writes into it:

```bash
python3 "$CLI" sd                       # show the registered folder and whether it is mounted
python3 "$CLI" sd /Volumes/CARD/ZOIA    # register it (the patch folder, not the card root)
python3 "$CLI" sync patch.bin           # copy into the slot its filename says
python3 "$CLI" sync patch.bin --slot 3  # or name the slot explicitly
```

`sync` parses the `.bin` before copying and compares the bytes afterwards, so a
file the pedal cannot read never reaches the card.

Rules to respect:

- A slot holds exactly one file. By default `sync` overwrites the file already
  in that slot, keeping its name — nothing is deleted.
- Renaming (`--name`) means deleting the slot's old file, so it requires
  `--replace`. Do not pass `--replace` unless the user asked for the rename.
- Use `--dry-run` first when you are unsure which file you are about to
  overwrite, and show the user the plan.
- If the folder is missing, the card is unmounted — say so rather than
  registering a different path.
- Tell the user to eject the card before unplugging it.

The JSON is exactly the dict produced by the parser, so `encode` reads back
anything `decode` wrote. Prefer targeted `Edit` calls on the JSON over
regenerating it wholesale.

## Fidelity

The encoder round-trips **byte-exact**: `roundtrip` reports `0` differing
bytes, the result re-decodes cleanly, and the re-decoded dict equals the
original. An unmodified decode→encode is a no-op, so any byte that changes is
a byte your edit changed.

Still worth doing:

- Run `roundtrip` on a `.bin` you have not worked with before — one command,
  and it proves the patch is in the supported format.
- Keep a `.bak` of the original before overwriting anything.
- After encoding, re-run `info` on the result to confirm it still parses.
- Structural edits (adding/removing modules or connections) stay the riskiest
  kind — not because of the encoder, but because the pedal enforces invariants
  the JSON does not. Check block counts and grid positions.

## JSON structure

Top-level keys: `name`, `size`, `modules`, `connections`, `pages`,
`pages_count`, `starred`, `colors`, `meta`.

A **module** looks like:

```json
{
  "number": 0,             // index of this module in the list
  "mod_idx": 1,            // module TYPE id -> see ModuleIndex.json
  "name": "my osc",        // user-assigned label
  "category": "Interface",
  "cpu": 0.3,
  "page": 0,               // which grid page (0-63)
  "position": [0, 1],      // grid block indices the module occupies
  "color": "Blue",         // header color (see palette below)
  "options": {"channels": "stereo"},
  "parameters": {"level": 0.5},   // param name -> normalized value 0.0-1.0
  "connections": [...],
  "starred": [...]
}
```

A **connection**: `{"source": "0.1", "destination": "0.0", "strength": 0}`
where `"module.block"` addresses a block, and `strength` is 0-100.

`pages` is a list of page-name strings. `meta` is a computed summary
(regenerated on decode; you don't need to hand-edit it).

## Module reference

The authoritative module database is `ModuleIndex.json` inside the engine
checkout — `$(python3 "$CLI" where)` prints its root, and the file is at
`zoia_lib/common/schemas/ModuleIndex.json`. It is keyed by `mod_idx` (as a
string) and gives each module's real parameter names, value ranges and units
(`param_defaults`), block layout, options and CPU. Read it before changing
parameters, so you use correct names and 0.0-1.0 normalized values.

## Color palette

Header colors (name used in JSON): Blue, Green, Red, Yellow, Aqua, Magenta,
White, Orange, Lima, Surf, Sky, Purple, Pink, Peach, Mango.

## Tips for musical edits

- "Brighter": raise filter cutoff / high-frequency params toward 1.0.
- "Add a module": copy an existing module dict, give it a fresh `number`, a
  free `position` on some `page`, then wire it with a connection.
- On a `UI Button`, the `in` value drives colour/brightness, and a connection
  delivers `source × (strength / 100)` — it does not add the raw value.
- Confirm the intended result with `info`, and when possible by re-decoding
  the encoded `.bin`.
