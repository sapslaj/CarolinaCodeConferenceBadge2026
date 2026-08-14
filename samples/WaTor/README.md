# Wa-Tor World

The viewer frame from the
[`wa-tor-whirl`](https://github.com/thomasarch/wa-tor-whirl) browser
toy, moved onto the badge: the title, the size readout, the bordered
world canvas and the fish/shark tally. The sidebar, the
play/pause/restart buttons and every input box are gone — this runs the
simulation with the page's default variables and nothing else.

Wa-Tor (A.K. Dewdney, *Scientific American*, 1984) is a predator/prey
world wrapped onto a torus. Fish wander and breed. Sharks hunt fish,
breed more slowly, and starve if they do not eat. Neither species ever
settles: the populations chase each other up and down for as long as
you leave the badge on.

## What you should see

- A 50 × 50 ocean of blue cells, 100 × 100 pixels inside a 3-pixel
  border, seeded with 500 gold fish and 125 red sharks.
- Fish spreading into open water in blooms, sharks eating holes through
  the blooms behind them, and the tally at the bottom swinging with it —
  a fish boom, then a shark boom, then a crash, over and over.
- No buttons do anything. The world reseeds itself when it ends
  (everything dead, the grid full, or one species gone for 60 turns),
  since there is no Restart button to press.

## Controls

None. The viewer runs by itself.

## The defaults, straight from the page

| Variable | Value |
|----------|-------|
| world | 50 × 50 (500 px canvas ÷ 10 px `pixelSize`) |
| `playSpeed` | 100 ms per turn |
| `startingFish` / `startFishChi` / `fishFertRate` / `fishWeight` | 500 / 5 / 2 / 1 |
| `startingSharks` / `startSharkChi` / `sharkFertRate` | 125 / 4 / 8 |

The rules are the page's rules, quirks included: **every** creature
spends one energy per move, so fish starve as well as sharks, and a
creature boxed in on all four sides simply passes — it neither ages nor
breeds that turn.

## Code design

- **The world *is* the state.** The browser version keeps a list of
  creature objects and reads the grid back out of the canvas with
  `getImageData`; neither survives contact with a microcontroller —
  2500 objects would eat the heap and the per-creature `findIndex`
  scans are quadratic. Here `cells` is one flat list of 2500 small
  ints, and "what is in the cell to my left" is a single index.
- **One creature = one int.** Type in bits 0–1, fertility in 2–6,
  energy in 7–14, and a stamp bit at 15. CircuitPython stores small
  ints inline in a list, so a full world costs one list of 2500 slots
  instead of 2500 heap objects.
- **The stamp bit flips meaning every turn.** A creature that moves
  into a cell the tick has not reached yet would otherwise move twice.
  Marking it costs one bit, and flipping what "marked" means each tick
  saves a second pass over the grid to clear the marks.
- **Torus arithmetic on flat indices** — `idx - COLS if idx >= COLS else
  idx + LAST_ROW` and friends, so a fish leaving the top edge swims in
  at the bottom with no coordinate wrapping in sight. Only the column
  has to be worked out at all; the row edges are just the ends of the
  index.
- **The bitmap is 50×50, not 100×100.** One pixel per cell, blown up by
  a `displayio.Group(scale=2)` — displayio does the zoom in C, so
  drawing a creature is a single `bmp[idx]` store instead of a 2×2
  `fill_region` call. The bitmap shares the simulation's flat index, so
  nothing converts between an index and (x, y) to draw.
- **The turn carries its own work list.** Every creature that survives
  appends where it ended up, so the next turn starts from a list of
  occupied cells instead of rescanning all 2500. Entries do go stale
  when a shark eats a fish that had already moved — the stamp check was
  catching that anyway.
- **Fish get the unrolled path.** They outnumber sharks about 10:1 and
  only ever look for open water, so their neighbour scan is four
  straight-line tests with no loop, no tuple and no "is that prey?"
  check. Sharks, being rare, keep the readable loop.
- **Only changed cells are repainted**, and populations are tracked
  incrementally as creatures are born, eaten and starved rather than
  recounted each turn.

Together those take a creature's turn to roughly half the Python-level
work of the straightforward version. At the top of a fish bloom the
world still holds ~1800 creatures and a turn costs more than the page's
100 ms budget on this hardware — the loop holds 100 ms per turn when it
has slack and free-runs when it does not, so a busy world just runs a
little slower than a sparse one.

Turn order is arbitrary in every version of this — the page pops its
creature list, this pops its work list — and it does move the numbers:
taking turns in strict grid order rather than work-list order settles
the world about 9% denser. The rules are the same either way.
