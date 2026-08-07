---
name: zoia-float-menu
description: Build Sheoak's float menu on an Empress ZOIA - a multi-option selector that costs two grid cells at rest, hides its own options, and remembers what you picked. Use when a patch needs more than two choices on a page with no room for them.
---

# The float menu

A design by Sheoak. It puts an N-way selector on a ZOIA page for **two cells**: a
launcher that shows the current choice in its colour, and options that are invisible
until you press it. Nothing else on the pedal does that — a `Sequencer` selector costs
four cells and forgets its position at load, a row of buttons costs two cells per option.

Transcribe it. Do not approximate it: every piece below is load-bearing, and the two
that look decorative are the two that break it.

## The shape

```
launcher (UI Button) ──> Trigger ──> CV Flip Flop ─┬─> each option's "in"      (reveal)
                                                    ├─> the collector's gate
                                                    ├─> Out Switch cv_input    (highlight)
                                                    └─> Logic Gate AND         (clear)

each option (UI Button) ──> Multiplier ──> Sample and Hold ──> the destination
                  each at its own connection strength = its value

Sample and Hold ─> back into the flip-flop's reset, closing the menu
                └─> Out Switch out_select   (which option is highlighted)
                └─> In Switch  in_select    (which colour the launcher wears)
```

Eight modules for any number of options: `UI Button` launcher, `Trigger`, `CV Flip Flop`,
`Multiplier` collector, `Sample and Hold` latch, `Out Switch` highlight, `In Switch` lamp,
`Logic Gate` clear — plus one `UI Button` per option and one `Value` per colour.

## The seven rules

**1. The option's value lives in its connection strength, not in the option.**
Every option button sends the same 1 into one collecting `Multiplier`, each at a strength
equal to the value it stands for. That is what makes the whole thing scale: adding an
option is one button and one connection, not a rewired switch.

**2. No option may be worth zero.**
The collector's output is also the latch's *trigger*. An option worth zero produces no
edge, so the latch never fires and that option can never be chosen. With a four-position
`In Switch` whose position 1 means "nothing selected", the three real options are
**33.3 / 66.6 / 99.9 %**. For N options, spread over the top N of N+1 zones and keep the
lowest above zero.

**3. The latch's `track & hold` must be `off`.**
With it on, the `Sample and Hold` *tracks* while its trigger is high, so holding the
switch drags the value instead of taking a snapshot, and the menu follows your finger.

**4. The flip-flop closes the menu, and the latch closes the flip-flop.**
`Sample and Hold` output → the flip-flop, so choosing an option puts the menu away by
itself. That loop is the whole user experience: press, pick, gone.

**5. The `Logic Gate AND` clears on opening, and it is not decorative.**
`AND(flip-flop, launcher trigger)` → the latch's trigger. Without it, re-opening the menu
re-latches whatever was already held, and the second option you ever pick is ignored.

**6. ⚠️ The flip-flop's state is SAVED IN THE FILE.**
`saved_data` on a `CV Flip Flop` is its state, not configuration. A template harvested
from a corpus patch usually carries `[1, 0, 0, 0]` — **set** — and a patch built from it
loads with the menu already open. Zero it:

```python
if name in SAVED_CLEAR:                    # by name, not by module type:
    m["saved_data"] = [0] * len(m["saved_data"])   # other flip-flops may want to stay set
```

This is the single most likely reason a transcription "works but opens itself".

**7. ⚠️ Colours: the bottom of a band is OFF.**
`UI Button` in `extended` range gives each colour a 0.05-wide band. Brightness ramps from
**nothing at the band's bottom** to **full at band + 0.0375**, and falls away above that.

| | band | full brightness |
| --- | --- | --- |
| Red | 0.000 – 0.049 | 0.0375 |
| Orange | 0.050 – 0.099 | 0.0875 |
| Mango | 0.100 – 0.149 | **0.1375** |
| Yellow | 0.150 – 0.199 | 0.1875 |
| Lime | 0.200 – 0.249 | 0.2375 |
| Green | 0.250 – 0.299 | **0.2875** |
| Surf | 0.300 – 0.349 | 0.3375 |
| Aqua | 0.350 – 0.399 | 0.3875 |
| Sky | 0.400 – 0.449 | 0.4375 |
| Blue | 0.450 – 0.499 | **0.4875** |
| Purple | 0.500 – 0.549 | 0.5375 |
| Magenta | 0.550 – 0.599 | 0.5875 |
| Pink | 0.600 – 0.649 | 0.6375 |
| Peach | 0.650 – 0.699 | **0.6875** |
| White | 0.700 – 0.749 | 0.7375 |

In `basic` range the bands are 0.1 wide: Blue 0–0.099, Green 0.1–0.199, Red 0.2–0.299,
Yellow 0.3–0.399, Cyan 0.4–0.499, Magenta 0.5–0.599, White 0.6–0.699.

So:

- **option buttons hold the band's bottom** — a dead pixel, which is the point
- **everything visible is added on top**, by connection strength into the same `in` block
- **the launcher wants the peak exactly**: `band + 0.0375`. Values above the peak are on
  the falling side and render dull, which is the mistake that makes a transcription look
  washed out.

The two additions should sum to 0.0375 so the chosen option reaches full brightness:

```
flip-flop -> option.in            2 %      the menu is open      -> 53 % bright
flip-flop -> Out Switch.cv_input  1.75 %   routed to the chosen  -> 100 % bright
```

Choose the split by taste. All-full-when-open is fine; Sheoak's own patches leave the
unchosen ones dimmer.

## What it cannot do

**It forgets nothing, but the pedal might.** The latch's value is a parameter, so the
chosen option survives a reload — unlike a `Sequencer` selector, which always returns to
step one. That is the reason to prefer this design.

**Options are invisible until pressed.** If a page needs its choices legible at a glance,
this is the wrong control.

## Reference implementations

Sheoak's `The_Hierophant.bin` (filter and clock menus) and `The_Lovers.bin` (`LFO` and
`Clock` menus, generated by `build.py`, one `float_menu()` call per menu). Read the
Hierophant for the original and the Lovers for a parameterised version.
