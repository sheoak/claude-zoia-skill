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

On a patch the engine fully supports, a decode→encode is a **no-op**:
`roundtrip` reports `0` differing bytes and the re-decoded dict equals the
original. So any byte that changes is a byte your edit changed.

**Not every patch is supported.** Measured over a 216-patch collection, 86%
round-trip byte-exact with a current engine — and only 30% with an unpatched
zoia_lib, because it drops page names, out-of-range page numbers and undescribed
option bytes. Older patches use layouts the encoder cannot rebuild at all.

Still worth doing:

- `decode` **refuses** a patch that does not survive a round-trip, and writes
  no JSON — writing it back would silently alter it. The error lists which
  fields would change. Do not try to work around it: report it to the user and
  ask them to re-save the patch on the pedal, which usually converts it to a
  layout the encoder handles. `info` and `roundtrip` still work on such a
  patch, for inspection.
- Run `roundtrip` on a `.bin` you have not worked with before — one command,
  and it proves the patch is in the supported format.
- Keep a `.bak` of the original before overwriting anything.
- After encoding, re-run `info` on the result to confirm it still parses.
- Structural edits (adding/removing modules or connections) stay the riskiest
  kind — not because of the encoder, but because the pedal enforces invariants
  the JSON does not. See "Grid layout" below before moving anything.

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
  "position": [0, 1],      // cells occupied on the page; only the min is stored
  "color": "Blue",         // header color (see palette below)
  "options": {"channels": "stereo"},
  "parameters": {"level": 0.5},   // param name -> normalized value 0.0-1.0
  "connections": [...],
  "starred": [...]
}
```

A **connection**: `{"source": "0.1", "destination": "0.0", "strength": 0}`
where `"module.block"` addresses a block. `strength` is a **percentage from 0 to
999**, not a 0-100 fraction: above 100 the CV is amplified, below it is
attenuated. A destination sums everything wired into it.

`pages` is a list of page-name strings. `meta` is a computed summary
(regenerated on decode; you don't need to hand-edit it).

## ⚠️ Which fields actually get encoded

The decoder emits **two views of the same data**: readable fields, and the raw
fields it was built from. The encoder prefers the raw ones, so editing the
readable field alone changes nothing and the output is byte-identical to the
input. Edit the raw field — and update the readable one too, so the JSON stays
honest.

| To change | Edit this | Not this |
| :-- | :-- | :-- |
| a parameter | `parameters_raw[i]` | `parameters` |
| a module colour | `colors[module_number]` **and** `header_color_id` | `color` |
| an option | `options_binary` | `options` |
| a connection | `strength_raw`, `source_raw`, `source_block_raw`, `dest_raw`, `dest_block_raw` | `source`, `destination`, `strength` |

**Parameters.** `parameters_raw` is positional: index `i` is the *i*-th block of
the module with `isParam: true`, in `blocks` order — which is also the key order
of `parameters`. The value is `round(normalized * 65535)`, so `0.24` is `15500`.
Set both:

```python
i = [n for n, b in module["blocks"].items() if b["isParam"]].index("mod_depth")
module["parameters_raw"][i] = round(0.75 * 65535)
module["parameters"]["mod_depth"] = 0.75
```

Never delete `parameters_raw` to force the encoder down its `parameters`
fallback. `parameters` is a *display* value, rounded to two decimals on decode:
a raw `15500` reads back as `0.24`, and re-encoding that gives `15728`. Taking
the fallback silently shifts every parameter of the module.

**Colours are stored twice**: `header_color_id` in the module header, and the
top-level `colors` list at the end of the file. When `len(colors) ==
len(modules)` the list wins, so changing only `header_color_id` has no visible
effect. Set `colors[module["number"]]` as well, using the palette ids below
(Blue = 1 … Mango = 15).

**Connections** encode from the `_raw` fields whenever `strength_raw` is
present, which it always is after a decode. `strength_raw` is *not*
`strength * 100`: it counts hundredths of a percent, and decode truncates it
with `int(strength_raw / 100)`, so `strength` is a display value exactly like
`parameters`. The Magician has 8 connections whose raw value is not a multiple
of 100 — `6990` shows as `69`, and recomputing it from that would write `6900`,
losing 0.9 points and the byte-exact round-trip. Edit `strength_raw` directly,
and never derive it from `strength`.

**Verify every edit.** Re-encode, re-decode, and assert the value actually
changed. A `roundtrip`-style byte comparison that reports *0 differing bytes
after an edit* means the edit was ignored — not that it succeeded.

## Naming

Patch, module and page names live in fixed **16-byte** fields. Ordinary
punctuation is fine — including `/`, `!`, `&` and `"`.

Which characters actually survive depends on the engine, so `encode` measures
it rather than assuming: it encodes a witness name per class of character and
checks whether it reads back. On an unpatched zoia_lib the two failures below
apply; on a patched or newer one they may not, and the check adapts.

**Reading** — the parser does not decode the bytes, it string-splits their
Python `repr()`. Everything `repr` escapes therefore truncates the name: a
backslash, an apostrophe, or a control character (below `0x20`, plus `DEL`).
Those all encode perfectly well, at one byte each; they simply cannot be read
back.

| stored in the field | read back |
| :-- | :-- |
| `Don't Panic` | `t Panic` |
| `A\B` | `A` |
| `A<TAB>B` | `A` |

**Writing** — a non-ASCII character cannot be encoded at all. The encoder sizes
the field in characters but fills it with UTF-8 bytes, so `é` raises
`struct.error` and no patch is produced.

`encode` checks all three cases and refuses, listing the offending names.
`--force` overrides it — useful when you know a name is safe — but it cannot
rescue a non-ASCII name, since the failure is in the encoder itself.

Unlike the grid and raw-field traps, `roundtrip` *does* catch a mangled name:
it re-encodes to different bytes, so the patch stops being byte-exact.

## Grid layout

Each page is an 8×5 grid, and a module occupies cells on it. This is the
easiest thing to get wrong, and `roundtrip` will not catch it: connections are
index-based, so a scrambled layout still encodes byte-exact. Check it yourself.

- **Only `min(position)` is stored.** The encoder writes one cell number per
  module; the pedal then lays the module's blocks out in *contiguous* cells
  from there, in reading order. `"position": [20, 0]` puts the module at cells
  0-1, not at 20. You cannot scatter a module's blocks around the page.
- **Give every visible block a cell.** How many blocks are visible depends on
  the options — `Delay w/Mod` has 7 blocks in mono and 9 as `2in->2out`. Count
  them in `ModuleIndex.json` under the module's options, and make `position`
  that long. If it is too short, the pedal places the leftovers wherever it
  likes.
- **A page holds 40 cells**, numbered `row * 8 + col`, so 0-39. Anything past
  39 lands off-grid and the module *disappears on the device*, or the patch
  crashes. Before encoding, assert that each page's highest cell is ≤ 39 and
  that no two modules overlap.

Overlaps are occasionally deliberate — a Pixel sitting on a knob's cell is the
usual way to draw an indicator ring, and to hide an unwanted `cv_output` block.
So report overlaps, do not silently "fix" them.

**A block's connection index is not its grid cell.** Connections address blocks
by the logical `position` listed in `ModuleIndex.json`, which stays the same
whatever the options hide: a Multiplier's `cv_output` is block 8 no matter how
many inputs it shows. Grid cells, by contrast, are handed out only to visible
blocks, counting from `min(position)`. Read the index for connection indices;
count visible blocks for layout.

## Module reference

The authoritative module database is `ModuleIndex.json` inside the engine
checkout — `$(python3 "$CLI" where)` prints its root, and the file is at
`zoia_lib/common/schemas/ModuleIndex.json`. It is keyed by `mod_idx` (as a
string) and gives each module's real parameter names, value ranges and units
(`param_defaults`), block layout, options and CPU. Read it before changing a
parameter or placing a module — it is the only place the names, the block count
and the real scale of a value are written down.

**A normalized value is not a percentage.** `param_defaults` gives the range it
maps onto, and gain-like params are in **dB**: a VCA's `level_control` has
`range: [-inf, -12, -6, -2.5, 0]`, so `0.0` is silence, `0.5` is −6 dB and only
`1.0` is unity. Setting a pass-through level to "half" buries the signal. Check
the `unit` before assuming a value is linear.

## Color palette

Header colors (name used in JSON): Blue, Green, Red, Yellow, Aqua, Magenta,
White, Orange, Lima, Surf, Sky, Purple, Pink, Peach, Mango.

## Tips for musical edits

- "Brighter": raise filter cutoff / high-frequency params toward 1.0.
- "Add a module": copy an existing module dict of the same `mod_idx`, give it a
  fresh `number`, then a `page` and a `position` that satisfy the grid rules
  above, and wire it with a connection. Appending (new `number` = current module
  count) is safe: it shifts no existing index, so connections and starred params
  stay valid — bump `meta.n_modules` and append to `colors` too. Removing a
  module means remapping every index that follows.
- On a `UI Button`, the `in` value drives colour/brightness, and a connection
  delivers `source × (strength / 100)` — it does not add the raw value.
- Confirm the intended result with `info`, and when possible by re-decoding
  the encoded `.bin`.
