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
`strength * 100`: it counts hundredths of a percent, and decode truncates it
with `int(strength_raw / 100)`, so `strength` is a display value exactly like
`parameters`. The Magician has 8 connections whose raw value is not a multiple
of 100 — `6990` shows as `69`, and recomputing it from that would write `6900`,
losing 0.9 points and the byte-exact round-trip. Edit `strength_raw` directly,
and never derive it from `strength`.

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

`zoia_lib` reports `strength = int(raw / 100)`, so a connection it calls "60" really
applies **1%**. Writing `strength_raw = percent * 100` is the same error in reverse:

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
