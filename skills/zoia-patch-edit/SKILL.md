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

### ⚠️ The pedal's timestamps do not move — compare the bytes

**The ZOIA has no clock.** A file it exports keeps whatever date the card's
filesystem gives it, which is usually the date of the last write *you* made to
that slot. So a slot the player just saved from the pedal can look untouched
since your own sync, and `ls -lt` will rank it as old.

**Before overwriting any slot, hash it against what you last wrote there.** If
the two differ, the pedal has been there since and that file is the newer truth:
import it before you sync anything back. This is the only reliable signal —
mtime, size and the slot name all stay put.

    a = sha256(card/NNN_zoia_Name.bin)
    b = sha256(the file you last synced)
    a != b  ->  the player saved from the pedal; import first, do not overwrite

Recorded because it cost real work: a sync was pushed over a slot whose date
said 10:36 and looked like the assistant's own write, and the export sitting
there could have been lost.

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
where `"module.block"` addresses a block. A destination **sums** everything wired
into it. `strength` is a percentage where 100 is unity and the ceiling is 398 — but
it is **stored logarithmically**, and the decoded `strength` field is not it. See
"Connection strength is logarithmic" below before writing one.

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
| a page name | `pages_raw[i]` | `pages` |
| a starred param | `block_raw` | `block` |
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

**Page names** live in `pages_raw`, which holds every name the file stores.
`pages` is the display list, trimmed to the last page that holds a module — so
it is often *shorter*, and a page carrying only a credit line has no index in
it at all. Rename in `pages_raw`, and keep `pages` in step when the index
exists. Adding a page means appending to `pages_raw` **and** incrementing
`pages_count_raw`.

**Connections** encode from the `_raw` fields whenever `strength_raw` is
present, which it always is after a decode. `strength_raw` is *not*
`strength * 100` and *not* hundredths of a percent — it is **logarithmic**, so
read "Connection strength is logarithmic" below before you reason about any
value that is not 10000. The decoded `strength` field already holds the real
percentage, so the fastest sanity check on a raw value is simply to compare the
two fields the decoder gives you side by side.

Still edit `strength_raw` directly and never derive it from `strength`: the
displayed percentage is rounded to three decimals, so round-tripping through it
loses the byte-exact encode. The Magician carries 8 connections whose raw is not
a round percentage at all — analogue capture from the pedal's encoder — and
recomputing those from the display would rewrite every one of them.

**Verify every edit.** Re-encode, re-decode, and assert the value actually
changed. A `roundtrip`-style byte comparison that reports *0 differing bytes
after an edit* means the edit was ignored — not that it succeeded.

### ⚠️ `saved_data` is runtime state, and it persists

`saved_data` is not configuration. It is what the module was *doing* when the patch
was saved, and the pedal restores it. Harvesting a template therefore imports a
stranger's runtime state:

| module | what its `saved_data` holds |
| :-- | :-- |
| `CV Flip Flop` | **its state.** `[1,0,0,0]` is *set* |
| `ADSR` | stage flags |
| `LFO` | a float, its phase or accumulator |
| `Value` | its last value |
| `Tap to CV`, `Clock Divider` | the tempo they had measured |

The corpus instance you harvest a `CV Flip Flop` from usually has it set, so every
toggle you build from that template comes up **on**: a menu that opens itself, a
sync that engages itself, a bypass that starts bypassed. Zero it deliberately, and
**by module rather than by type** — some toggles should start on:

```python
if name in SAVED_CLEAR:
    m["saved_data"] = [0] * len(m["saved_data"])
```

Symptoms this explains, all of which look like something else: a patch that "boots
into" a mode, a switch whose first press does nothing (it was already on), an LFO
whose rate is right but whose phase is not. Before building a workaround for any of
those, read `saved_data`.

## ⚠️ Do not read an option off `options_raw` by the index's order

`ModuleIndex.json` lists an option name per byte, and for at least one module the
list is short: `Midi Clock In` is missing `reset_out`, so every name after the
first is off by one. `options_raw[1]` is reset_out where the index says run_out,
and `options_raw[2]` is run_out where it says divider. Reading the index's order
onto the bytes reports an option as on when a different one is.

To learn the true byte: have the option changed on the pedal, decode before and
after, see which byte moved. Two cheap cross-checks in the meantime — the **cell
count** (a module grows a cell per enabled output) and the decoded **`blocks`**
dict, which does track the real layout.

Block numbers are a separate question and the index is not the answer there
either: take the number off a wire that already works in a patch
(`source_block_raw`). `Midi Clock In.run_out` is block 3, from the Hierophant
MK2's own wire.

## ⚠️ A starred parameter is a knob, not a signal

Starring writes the block's **parameter**. Modules that act on a *change of
input* never see it: `Trigger`, `CV Flip Flop`, `ADSR.gate_input`,
`Sample and Hold.trigger`, `Device Control`. A CC there does nothing — the block
lights up, because the write really happened, and nothing downstream moves.
Judge by the module *after* the one receiving the CC.

Level destinations work: `Value.value`, filter frequency, mix, gain,
`VCA.level_control`, `Out/In Switch` select. Corpus check over 176 patches, ~400
stars: every star carrying a CC is on a level, `Value.value` alone 224 times.
Not one assigns a CC to a change-detecting block.

**To drive a trigger-ish input from MIDI**, star something whose output follows
its input and wire that output in — a `Value`, or a `Logic Gate` (which is how
The World's force pairs work: CC on `AND.in_1`, the gate's output to the flip
flop). A `Midi CC In` also works but pins the channel in the patch, where a star
follows the pedal's own channel.

The CC must fall back to 0 between presses: it sums with whatever else feeds that
input, and an input parked high can no longer rise for the CC or the button.

Never star an output — three corpus patches do, two with a live CC on an audio
out. It cannot do anything.

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

### Put the type in the name

A Trigger, a CV Flip Flop, a CV Invert and a Value are all one cell in and one
cell out. On the grid the name is the only thing that tells them apart, so every
name ends with its type in capitals:

    FF   TRI   INV   SH   COMP   MUL   DLY   RCT   ONS

A `Logic Gate` carries its own `operation` instead — `AND`, `NOR`, `NOT`. **No
tag means a `Value`**; that is the default, and tagging them all would cost the
front page its knob names.

    P.State FF     L. Short TRI     Knob down INV     Smart tap SH
    VU L1 COMP     Rate gain MUL    Lo-mid DLY        Midi active AND

The field holds 16 bytes and the pedal wants one spare, so **15 characters**.
Shorten the first part, never the tag:

- A stomp position becomes `L.`, `M.`, `R.` — `Middle Short` -> `M. Short TRI`.
- `Switch` becomes `SW`, and drops entirely only if the name still will not fit.
- Words the tag already says go: `Toggle`, `Invert`, `Trigger`, `Det.` —
  `BeatSync Toggle` -> `BeatSync TRI`, `Blend invert` -> `Blend INV`.
- If it still does not fit, ask. A half-tagged page is worse than an untagged one.

Two traps, both hit on real patches:

- **Strip only the tag belonging to that module's type** before retagging, or a
  Sample and Hold called `Sync Mul` loses the word that says what it does.
- **A tag can be glued to punctuation.** `P.NOT` is already tagged; splitting on
  spaces alone gives `P.NOT NOT`.
- `Mid` is the middle stomp in `Mid Tap` and the Mid *band* on its own. Only
  abbreviate it when a stomp word follows.

## ⚠️ Connection strength is logarithmic

The single easiest way to build a patch that loads, round-trips byte-exact, and does
nothing audible. `strength_raw` is **not** hundredths of a percent:

```
percent      = 100 * 10 ** ((strength_raw - 10000) / 2000)
strength_raw = round(10000 + 2000 * log10(percent / 100))
```

2000 raw units per decade:

| raw | on the pedal | | raw | on the pedal |
| --- | --- | --- | --- | --- |
| 0 | ~0% | | 9750 | 75% |
| 7398 | 5% | | **10000** | **100%** |
| 8000 | 10% | | 10602 | 200% |
| 8796 | 25% | | **11200** | **398.1%** — the ceiling |
| 9398 | 50% | | | |

The corpus confirms it: of 198612 connections, 81.2% sit at raw 10000, and the next
most common values are 9398, 8000, 8796, 9750 and 7398 — exactly the round
percentages 50, 10, 25, 75 and 5.

**Prove it in five seconds instead of re-deriving it.** The decoder emits both fields,
so decode any patch and compare them on a connection whose raw is not 10000:

```
raw 10685 → strength 220.039        100 * 10 ** ((10685 - 10000) / 2000) = 220.039  ✅
raw 10164 → strength 120.781                                               120.781  ✅
raw 10121 → strength 114.948                                               114.948  ✅
```

`raw / 100` would give 106.85 / 101.64 / 101.21. It does not match, so the law is not
linear — and values in the 8000–10000 band are exactly where a linear misreading stays
self-consistent and never throws (`8796` *looks* like 87.96%; it is 25%). Do this check
before calling any range mapping a clipping bug.

An old `int(raw / 100)` line survives in unpatched checkouts of `patch_binary.py`; if a
decode hands you integer percentages, the engine is stale — `patch_cli.py where` will
tell you which one you are on. Writing `strength_raw = percent * 100` is the same error
in reverse:

| written as | raw | what the pedal applies |
| --- | --- | --- |
| "6%" | 600 | **0.002%** |
| "20%" | 2000 | **0.01%** |
| "35%" | 3500 | **0.056%** |
| "60%" | 6000 | **1%** |
| "100%" | 10000 | 100% — right by coincidence |

That failure is silent *and* asymmetric, which is what makes it so hard to see: every
full-strength connection comes out correct, so the patch half works, while every
dosed one is written between a hundred and a thousand times too quiet. A chorus built
that way modulates the delay by a tenth of a semitone and sounds like a dry bypass.

Convert explicitly, and verify a built patch by converting back.

### A parameter block sums its knob with its cables, and clamps

A connection into a parameter block adds `source × strength` **to that block's own
knob value**, and the result is bounded by the parameter's range. Two consequences
worth knowing before you reach for extra modules:

- **You get free arithmetic.** To multiply a signal by `1 + x`, put `1` in a
  `Multiplier`'s second input as its *knob* and wire `x` into the same block. No
  `CV Mixer`, no constant module.
- **You cannot exceed the top.** A block bounded at `[0,1]` sitting at 1.0 clips
  anything positive you send it, whatever the source's own range — so a bipolar
  modulation centred on unity loses its upper half. Centre it lower and pay the
  difference back **upstream**, where a strength may exceed 100%.
- **A parameter reading 0.0 may be perfectly correct** if a cable drives it. Do not
  "fix" it without checking what arrives.
- **A nonzero knob under a dosed cable is a range window, not a bug.** `base 0.45` fed
  by a knob at 40% maps that knob onto 0.45…0.85 — someone deliberately narrowing a
  control they found too strong at the top. Round percentages (25, 40, 50, 75) are the
  tell that a human chose them. Convert the strength properly before deciding anything
  clips: read as `raw/100` the same pair looks like `0.45 + 0.92`, and "fixing" that
  phantom clip re-opens the control to full range and undoes the tuning.

Two traps in the same family:

- `CV Mixer`'s `atten` runs −1 to +1 with **0.5 as zero**. Left at the harness
  default of 0.0 it is a *full inversion*, which is silent-looking and audible.
- A `-1 to 1` source into a `[0,1]` block loses its negative half. Check the
  destination's range, not the source's.

### Sizing a strength

A connection delivers `source × percent/100` and **sums** with the destination
parameter's own value, so size it against what the destination needs rather than
picking it as a volume:

- `atten` on a `CV Mixer` spans −1…+1 with its parameter at 0.5, so +0.5 opens it
  fully — a 0…1 knob gets there at **50%**.
- an LFO onto a `Delay Line`'s `delay_time` for a chorus wants **53–92%**, the band
  the 192 corpus patches doing it use.
- above 100% is legal up to 398%, and 2% of corpus connections go there.

Doing this with strength costs no CPU and leaves no module to maintain, so prefer it
to inserting a `Multiplier`. Reach for one only when a **knob** has to move the amount
while playing, since a strength is fixed at edit time.

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

### Never two neighbours the same colour

On any page you build, no two modules whose cells touch may carry the same
colour. A row of five identical caps reads as one block and says nothing.

- Colour by what the module *drives*: a MIDI Value gets the colour of the effect
  it forces, so the CC page matches the front page.
- Exceptions: page 0, where the colour is the layout (meter columns, a row of
  toggles), and anything the user has specified — a colour-by-function scheme
  across a whole page is deliberate, do not "fix" it.
- Check it before encoding: sort each page's modules by first cell and compare
  each pair of touching neighbours.

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

## ⚠️ The module index is not ground truth — check it against real patches

`ModuleIndex.json` is the best description of the modules that exists, and it is
wrong often enough to break a patch silently. A block's `position` **is** its
connection index and an option's place in its list **is** the byte written to the
file, so an error there does not raise: the patch encodes, round-trips byte-exact,
loads on the pedal, and the connection quietly goes nowhere or the module runs on
the wrong setting.

There is a way to check, and it is cheap. Decode a corpus of real patches and count
how each block is used:

- a block used as a **connection source** has to be an output;
- a block used as a **destination** has to be an input;
- a block index used by real patches but declared empty (or past the end) is a
  block the index has misplaced.

Patch corpora usually on hand: the Librarian's own store at
`~/Library/Application Support/.ZoiaLibraryApp/**/*.bin`, and any SD backup. A few
thousand patches settle most questions in seconds.

Errors found this way so far, all now fixed upstream in `sheoak/zoia_lib`:

| module | was | really |
| --- | --- | --- |
| `Sequencer` | `out_track_1..8` at 36-43, `key_input_note/gate` at 34/35 | outputs at **34-41**; `key_input` is a MIDI mode and holds no block |
| `Tremolo` | `depth` 5, outputs 6/7 | `depth` **4**, outputs **5/6**; `direct` shares `depth`'s slot |
| `Audio In Switch` | `audio_input_9..14` two too high | inputs 1-16 at 0-15, contiguous |
| `Delay Line` | `max_time` as `1s…16s,100ms` | the list **starts** with `100ms` |
| `Delay w/Mod` | knob order | `mix 2, feedback 3, delay_time 4, tap_tempo_in 5, mod_rate 6, mod_depth 7` |

### ⚠️ Never put a patch inside the engine's checkout

**The engine's repository is code, and it is public. Patches do not go in it —
not a `.bin`, not a decoded `.json`, not a `.bak`, not a note, not for a minute.**
Work in the patch repository, or in a scratch directory outside every checkout.

This is not hygiene, it is disclosure. Fifty-one of the owner's working patches —
unreleased builds, backups, private analysis notes — were published on a public
fork for three weeks because its `backend/` directory had been used as a scratch
space. Nothing ignored them, one blanket `git add` staged them, and a merge
carried them onto a branch where nobody looked again.

`git add -A` and `git add .` are banned in the engine's checkout. Stage named
paths, and read `git status` before every commit.

**Fixes go in as pull requests, and nothing else does.** Do not commit onto a
branch of the fork, do not merge, do not rebase a shared branch and do not push
one. Open a PR and let the owner decide. Committing "helpfully" onto a branch has
cost real work: a merge resolved the wrong way silently dropped the encoder's
guards, a stray `git add -A` swept hundreds of personal files into history, and a
merge commit on a branch that was meant to stay linear had to be unwound. None of
that can happen from a PR.

Some oddities are real and must be left alone: `Pushbutton` and both
`Euro Pushbutton`s genuinely have no block at position 0 — their `cv_output` is a
source 17195 times and block 0 never is. Measure before "fixing".

### A hidden block still has its index

The decoder trims each module's `blocks` dict to what is **visible on the grid**,
which depends on the options. Visibility is a grid concern only: a hidden block
keeps its connection index and can still be wired. A `tap`-mode `Clock Divider`
shows no `divisor`, and 37 corpus patches drive it anyway. Resolve block indices
from `ModuleIndex.json`, never from a decoded module's own `blocks`.

### Which option byte is which

Options are written in the order the index lists them, one byte each. To confirm a
byte's identity, find one whose value changes the **number of visible blocks** —
that count is stored in the file independently, so it is checkable. For
`Delay Line`, byte 1 alone tracks it (0 → three blocks, 1 → four), which pins
`tap_tempo_in` and with it the position of every other option.

For a byte that reveals nothing structurally, compare the population that *cares*
against the one that does not. `Delay Line` byte 3 (`CV Input`) is set in 57.8% of
delay lines whose `delay_time` is driven by a connection against 13.5% of those
left alone — a 4.3× split, where byte 2 shows none.

### Restrict the statistics to the population you are in

That last trick cuts both ways. "57.8% of CV-driven delay lines use linear" is
true and was the wrong answer for a chorus, because that population is mostly long
delays where linear is what makes a tap tempo read in milliseconds. Narrowed to
*short* delay lines modulated by an LFO — 192 of them — the answer is unanimously
the other way. Ask the question about patches doing what you are doing.

### A geometric range is an interval ladder — work in octaves, not percent

`param_defaults` gives a range as a list of breakpoints, and they are joined
**geometrically**. A Looper's `speed_pitch` reads

    "range": [3.1, 17.7, 100, 565.7, 3200], "unit": "%"

which is one exponential with 100% at the centre of the travel:

    percent = 3.125 x 1024^travel        travel = 0.5 + log2(ratio) / 10

Verified against three readings off the pedal: 0.5 -> 100%, 0.7 -> 400.1%,
1.0 -> 3200%.

The useful consequence is that **0.1 of travel is exactly one octave**, since
1024^0.1 = 2. A fifth is 0.0585, a fourth 0.0415. So a set of speeds that stay
in tune is arithmetic on the travel, not on the percentage:

| ratio | interval | percent | travel | raw |
| --- | --- | --- | --- | --- |
| 0.5 | octave down | 50 | 0.4000 | 26214 |
| 0.667 | fifth down | 66.7 | 0.4415 | 28934 |
| 0.75 | fourth down | 75 | 0.4585 | 30048 |
| 1.0 | unison | 100 | 0.5000 | 32768 |
| 1.5 | fifth up | 150 | 0.5585 | 36601 |
| 2.0 | octave up | 200 | 0.6000 | 39321 |

Unity is the exact centre, raw 32768. A knob left a couple of raw units off it
is not at 100%, and the looper resamples for nothing — a real source of
artefacts at the loop seam.

## ⚠️ `cpu` in the file is an allocation, not what the pedal spends

Every decoded module carries a `cpu`, and `ModuleIndex.json` gives one per type.
Both are **static estimates of what a module reserves**. Neither is what the
pedal's meter shows, and the two are not even on the same scale — a patch the
librarian totals at 60 can read close to 100 on the hardware.

What the file cannot tell you is that some modules cost more **according to their
parameter values**, in real time, per block:

- A `Looper` costs more the further `speed_pitch` sits from unity. Off unity it
  has to resample, so it reads and interpolates more source samples per block.
- Overdubbing *while* the speed is off unity is far more expensive again: it
  reads, interpolates and writes at once.

So a knob can be the biggest line in the budget while its module reads 0.3 in the
file.

Options are the part you *can* read — but they do not all reserve the same
thing. `num_grains` and `channels` add voices, so they cost calculation.
`max_grain_size` and `max_rec_time` reserve **memory**: measured on the pedal,
raising a Granular's `max_grain_size` from 4s to 16s costs no CPU at all, because
the DSP does the same work per sample however long a grain is.

So read an option for *what it reserves*, not as a saving. And trimming a knob's
*range* saves nothing at all — it caps a peak the file never described.

**Never tell someone what to remove on the strength of the decoded `cpu` alone.**
Rank modules by it if you like; then ask for the pedal's own reading, knob by
knob, because that is the only place the runtime cost exists. The player sweeping
a control and watching the screen will find things this format cannot express.

### The `cpu` field is a flat rate per module type

Measured across 166 corpus patches: options do not change it. Every `Chorus` is
8.0 in mono and in stereo, every `Delay w/Mod` is 11.0 whatever its `type`, every
`Phaser` 7.5 at any number of stages, every `Env Follower` 2.5.

So the file can only tell you what *removing a module* saves. Everything an
option costs is runtime, and only the pedal can see it. Two real examples from
the pedal, not from the file:

- `Delay w/Mod` `type: tape` -> `clean` is enough on its own to stop a patch
  crackling. Tape emulation is the expensive setting.
- Halving `channels` (stereo -> `1in->1out`) halves that block's work, and the
  file's number does not move.

When asked to save CPU, name the option changes first and the module deletions
second — and ask for the pedal's reading either way.

## Building a patch from scratch

Do not synthesise module records. Harvest them: decode a corpus, keep one real
instance per `(mod_idx, options)` you need, and clone it. Every `size`, `params`
count and `saved_data` block is then one the pedal already writes.

- A current-format record satisfies `size == 14 + params + data_words` with
  `len(saved_data) == data_words * 4`. Anything else is an old short record with no
  name field — filter those out or the encoder will refuse them.
- `size_of_saveable_data` is a literal field, not a length the encoder derives.
  Keep the harvested value.
- Supply `parameters_raw`, not `parameters`. The decoder names parameters by block
  **position** order while the encoder's by-name path uses the index's `order`, and
  the two disagree for enough modules that by-name round-trips fail on more than
  half a corpus. Build the list indexed by position-sorted param blocks.
- Assert the grid yourself as you go: nothing past cell 39, no overlaps, each
  module's cells contiguous from its minimum.
- Then verify what you built the same way you verified the index: every connection's
  source block should be one the corpus uses as a source, every destination one it
  uses as a destination.

### A harvested module brings the source patch's knobs *and its state*

Harvesting gives you a working record — and the **parameter values of the patch
it came from**. Where those parameters were driven by cables, the record has them
at **zero**, because that is what the knob was left at.

Cloning the Magician's `Looper` into a patch with no `Value` on it gives
`loop_length` 0: a loop a few milliseconds long, which cracks instead of playing.
Same trap for `speed_pitch` 0, a filter cutoff 0, a mix 0.

**`saved_data` comes along too**, and that one boots the patch into a state you
never chose. Cloning a `Sample and Hold` copied `[68, 20, 0, 64]` — 2.0012 as a
float — so both cloned latches booted *high*.

It cost nothing until the consumer changed. The latch fed a `Trigger`, which
reads an **edge** and saw none at boot. Rewired to an `ADSR`, which reads a
**level**, the envelope fired at power-on and toggled the record flip flop before
a note was played.

So after cloning, do both:

- Set every parameter the new patch does not cable. The source patch's own
  `Value` defaults are the sane numbers — the Magician drives `loop_length` from
  a `Value` at 65535 and `speed_pitch` from one at 32768.
- **Zero `saved_data`** unless you want that state, keeping the array the length
  `size_of_saveable_data` declares. A real `Sample and Hold` with `[0, 0, 0, 0]`
  is the proof that zero is valid.

### Copy the numbers from patches that already work

Ranges and strengths are where a structurally perfect patch still sounds wrong, and
the corpus has the answers. A ZOIA chorus, for instance: `Delay Line` on the short
range with the **exponential** CV curve, the base delay held in the `delay_time`
**parameter** (0.10 to 0.86 across the ones sampled), and the LFO landing on
`delay_time` at **53% to 92%** — not through a chain of attenuators at 6%, which is
a tenth of a semitone and inaudible. Sample the patches that do the thing before
choosing a number.

## ⚠️ A parameter's range is interpolated **geometrically**

`param_defaults[name]["range"]` gives breakpoints, and a normalised value lands between
them — but **not linearly**. Look at a typical range: `[1.33, 18.7, 283, 4120, 60000]` ms.
Each breakpoint is about 14 times the last. It is a log scale, and the pedal interpolates
it as one:

```python
def real(v, rng):                  # 5-point ranges
    s = v * 4
    i = min(int(s), 3)
    return rng[i] * (rng[i+1] / rng[i]) ** (s - i)      # geometric
```

Interpolating linearly is wrong by 25-65% in the middle of a segment, and it is wrong in
the direction that makes a control feel mysteriously fast. Two readings taken off a pedal
settle it:

| parameter | normalised | pedal reads | linear says | geometric says |
| :-- | --: | --: | --: | --: |
| `Env Follower.rise_time` | 0.21 | **12.6 ms** | 15.9 | **12.3** |
| `Env Follower.fall_time` | 0.42 | **120 ms** | 198 | **119** |
| `LFO.cv_control` | 0.62 | **9.00 Hz** | 10.1 | **8.80** |

Values that land exactly on a breakpoint are right under either model, which is how a
wrong conversion survives being spot-checked. `0.25`, `0.5` and `0.75` prove nothing.

**Ranges containing 0 are the exception.** `LFO.cv_control` is `[0, 1.53, 5.4, 15.2, 40]`,
and no geometric step starts at zero. That first segment is curved but is neither model —
0.12 reads 0.561 Hz where linear predicts 0.734. Measure the bottom segment; do not
compute it.

### ⚠️ Some ranges are linear — read the breakpoints, do not assume

Geometric is common, not universal, and the breakpoints tell you which it is for free:
**compare the middle breakpoint to the arithmetic and the geometric mean of the two ends.**

| parameter | range | mid | arithmetic | geometric | law |
| :-- | :-- | --: | --: | --: | :-- |
| `Compressor.release` | `[0.01, 0.51, 1.01, 1.5, 2]` s | 1.01 | **1.005** | 0.141 | **linear** |
| `Compressor.ratio` | `[1, 5.8, 10.5, 15.3, inf]` :1 | 10.5 | **10.5** | — | **linear**, then `inf` at 1.0 |
| `Tone Control.mid_freq_1` | `[28, 156, 880, 4978, 23999]` Hz | 880 | 12013 | **820** | **geometric** |
| `CV Delay.delay_time` | `[1.33, 18.7, 283, 4120, 60000]` ms | 283 | 30001 | **282** | **geometric** |

Two-point ranges are linear: `Compressor.threshold` `[-80, 0]` dB, `attack` `[0, 10]` ms,
`Tone Control` gains `[-18, 18]` dB. So `travel = (dB + 18) / 36` for a gain, and a gain
of 0 dB is `0.5` exactly.

Getting this backwards is how "155 ms" becomes "a bracket of 150 to 225".

## Diffing a patch the pedal has saved

Round-tripping through the hardware is the only way to learn some things, and the
diff is not straightforward: **the pedal renumbers modules.** Match by
`(name, mod_idx, page)`, never by `number`, or every connection appears to differ.

Then compare, in this order:

1. `saved_data` — the state that persists, and usually the answer
2. `parameters_raw` — the knobs, including ones moved while playing
3. `options_binary` — a mode changed on the device
4. `position` / `page` — a module moved
5. connections and `strength_raw`, matched by name

And keep the generator authoritative: fold what the pedal changed back into the
script rather than adopting its `.bin`, or the two diverge and the script stops
being the description of the patch. Beware of diffing against a card copy that is
older than your last build — you will "import" your own superseded values.

## Color palette

Header colors (name used in JSON): Blue, Green, Red, Yellow, Aqua, Magenta,
White, Orange, Lima, Surf, Sky, Purple, Pink, Peach, Mango.

A cell's colour lives in **two** places and both must be written: the module's own
`header_color_id` (a coarse 1–7 group) and the top-level `colors` array, one entry
per module, which carries the fine 1–15 id. The encoder prefers the array when its
length matches the module count. The fine → coarse map, verified against a patch:

    Blue 1→1 · Green 2→2 · Red 3→3 · Yellow 4→4 · Aqua 5→5 · Magenta 6→6
    White 7→7 · Orange 8→3 · Lima 9→2 · Surf 10→5 · Sky 11→1 · Purple 12→6
    Pink 13→3 · Peach 14→3 · Mango 15→4

On a `Value` or `Pushbutton` that id *is* what the cell shows. On a `UI Button` it
is only the editor header — the cell shows the value at `in`.

### The brightness ceiling is exclusive

Each colour owns a 0.05 band whose bottom is the hue at zero brightness. Full
brightness is `bottom + 0.0375`. **Past that point, and exactly on it, the cell goes
dark — it does not saturate.** Landing a lit state on `bottom + 0.0375` is the same
bug as overshooting it.

So a brightness adder can only be 3.75% when the base sits exactly on the band
bottom. A base deliberately lifted above the bottom — the idiom for a cell that
stays dimly lit when off — needs the adder reduced by that same offset:

    adder = 0.0375 - (base - band_bottom)          # then land just under, never on

Rounding a base to a band bottom must go **up**, not to nearest: `0.70 × 65535` is
45874.5, and 45874 drops a white cap into the peach band at full brightness.

Empirically, module names only ever use space, `-`, `.` and `/` — `+`, `<`, `>`, `*`
and `#` appear zero times in a 796-name corpus, so assume the pedal cannot type them.

## The community tips document

`~/Downloads/Empress ZOIA_Zebu Tips, Tricks, and Explanations.md` — ~4600 lines by
Christopher (u/…) and contributors, organised module by module. It is the best source
of *idiom* there is, and far better than reasoning from the module index.

**But parts of it predate current firmware.** It tells you to set a sequencer's output
to `gate` for the overdub bypass; a device check said `cv`, not `gate`. Treat it as a
source of ideas to verify, never as ground truth about current behaviour.

### Things it settles that are easy to get wrong

**A looper's buttons are destinations *and* interface modules.** Wiring something to
`record` or `playback` **changes that button's state as you connect it**. After wiring a
looper, press the button again. This is why a record flip-flop's value can end up
inverted relative to what the looper is actually doing — the control and the module
desync, and no amount of reading the flip-flop will tell you the truth.

**ZOIA's `Trigger` module makes a poor trigger.** Christopher: "the actual triggers ZOIA
produces kind of suck, and I would recommend replacing them with a short AD envelope."
If an edge is being missed or is mistimed, an ADSR with a very short attack/decay is the
fix, not a second Trigger.

**A `Value` is a one-tick CV buffer.** Out is what went in one tick earlier; chain N for N
ticks. Use it to order events that fire on the same tick, or to pad fast paths so several
land together. `cpu 0.15` vs `CV Delay` `1.5`. **A Value orders, a CV Delay spaces** — one
tick is inaudible, so it never substitutes for a mute window. Unverified.

**Modulate a looper's parameters *after* the loop is recorded** — modulation during
recording can affect performance. And if a looper misbehaves after rewiring, save and
reload the patch; that alone often fixes it.

**The canonical overdub bypass sends its trigger to `playback`**, not to `record`:
momentary → flip flop → `record`; the same switch → a 3-step one-shot sequencer
(`off on off`) → `Trigger` → `playback`. The second press releases the flip flop, which
*would* start overdub, but the same press advances the sequencer and the trigger jumps
past it. One-shot means later presses only toggle overdub layers.

### The min/max idiom, stated properly

This is the canonical form of "a destination sums everything wired into it":

- **the destination's own value sets the minimum**, or with a bipolar source, the centre
- **the connection strength sets the maximum**, or with a bipolar source, the range each
  way

To sweep a phaser mix from 40% to 70%: park `mix` at 0.4 and wire the LFO at **30%**.
With a −1..1 LFO the same numbers give 10%→70%, centred on 40%.

### Connection strength can exceed 100%

Strengths below 100% divide, **above 100% they multiply**. Six connections in Sheoak's own
patches are above unity, up to **220.04%** (raw 10685); the observed floor is 0.2955%
(raw 4941). The logarithmic formula extends across the whole span, so nothing special is
needed to write one.

A **`Multiplier` used as a CV VCA** is a connection strength you can reach and modulate:
source → in 1, a `Value` → in 2, multiplier → destination. One `Value` can scale several
connections at once by feeding several multipliers. Feed the *same* source into two
inputs and you get `Y²` — that is how you make an exponential response.

### Splitting audio doubles the gain

Whenever one output feeds two paths that later recombine, **the sum is twice the signal —
attenuate the split.** This is exactly the class of bug found in the Hierophant Mono,
where a stray wire put a compressor in parallel with the switch that was supposed to
route around it: the drive ran 6 dB hot and the compressor was never bypassed. A
`Buffer Delay` may also be needed when recombining, to fix the phase.

### Routing recipes worth copying

**Order switching** — three 2-output `Audio Out Switch`, one control to all three:

```
in  -> sw1: out1 -> FX1        FX1 -> sw2: out1 -> FX2   FX2 -> sw3: out1 -> out
            out2 -> FX2                    out2 -> out               out2 -> FX1
```

**Series/parallel** — same shape, but `sw1.out2` feeds *both* effects. Swap the out
switches for **panners** and the series/parallel amount becomes continuous.

Double everything for stereo.

### Hiding a block

An **unconnected `Pixel` placed over a block makes it unlit** — it stops you connecting
to it by accident and cleans up the grid. That is what the isolated `cv_in: 0` Pixels
scattered through Sheoak's patches are for; they are layout, not dead modules. Do not
report them as defects.

**This means a "cell claimed twice" check produces false positives.** In Float Menu every
Mask Pixel sits exactly on its option button's `cv_output` cell — deliberately, because
that is how the block gets hidden. Overlapping positions are an idiom here, not a bug.
The cost, worth documenting when you meet one: the Pixel has to be moved or deleted
before that block's connections can be edited on the pedal.

### There is no way to lock a UI Button's value

A `UI Button` has one parameter, `in`, and the user can always turn it — and it *sums*
with any CV, so the offset cannot be cancelled. If a control must not be editable, use a
**`Pushbutton`** or a **`Stompswitch`**: both have **zero parameters** and only a
`cv_output` block, so there is nothing to turn. The cost is that the colour becomes the
module attribute, fixed, so you lose the band-bottom + brightness idiom.

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

## Writing the documentation

The patch docs are read by players, not by engineers. Write for someone who has
never opened the patch.

- Short sentences. One idea each.
- Point by point, as a bulleted list. Blank line between blocks.
- Say the thing. No metaphors, no "which is what makes it", no clause piled on
  clause to sound clever.
- Name the colour in brackets after what it means: "the rate knob (peach), tap
  tempo (aqua) or an incoming MIDI clock (magenta)" — not a paragraph, not a
  table.
- Use the word the user uses for a control, even if the module inside is named
  something else.
- An LED description says what the brightness means and what the colour means,
  separately, in that order.
