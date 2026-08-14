# GameOfLife

Conway's Game of Life on a 64×72 torus, seeded from the classic patterns or from random soup. It watches itself for stalemates and reseeds when nothing is happening any more, so the badge can sit on a table running forever.

## What you should see

- A green cellular grid filling the screen, evolving a few dozen generations a second. Cells that have just been born flash bright white-green; cells that have just died leave a dim ghost for one generation, so you can see which way a pattern is travelling.
- The NeoPixels as a population meter — a dying grid visibly dims.
- A HUD line along the bottom: the current seed name, generation count, and live population.
- When a pattern settles into a still life or a blinker, `settled` on the serial console and a fresh seed a moment later. Same when a soup goes extinct.

The grid is a **torus** — the left edge is glued to the right and the top to the bottom — so a glider that walks off one side comes back in on the other and keeps going indefinitely.

## Controls

| Switch | Action |
|---|---|
| SW1 | Next seed — SOUP → GLIDER GUN → ACORN → PULSAR → R-PENTOMINO → SPACESHIP |
| SW2 | Pause / resume. **While paused, SW1 single-steps one generation** |
| SW3 | Speed: fast / normal / slow |

Single-stepping is the only way to actually read a glider, which takes four generations to move one cell diagonally.

## The rules

A live cell with 2 or 3 live neighbours survives; a dead cell with exactly 3 live neighbours is born; everything else dies. That is the whole game, and everything on screen — gliders, guns, the 1103-generation tantrum that an acorn throws — falls out of those two lines.

## How this is fast enough

The obvious implementation visits every cell and counts its eight neighbours. On this grid that is 4608 cells and about 37,000 neighbour reads per generation, and in CircuitPython that is a slideshow.

So `life_step()` does not do that. **Each row is one Python integer, one bit per cell**, and a whole row of neighbour counts is computed with about twenty integer operations — there is no per-cell loop at all. Python integers are arbitrary width and the operations happen in C, so a 64-wide row costs about the same as an 8-wide one.

The trick is a **carry-save adder**, the same one hardware uses. You cannot add two bitmaps directly, but `a ^ b` is the sum bit and `a & b` is the carry, so a stack of XOR/AND pairs adds several bitmaps at once and leaves the count in binary *spread across several words*. Three words hold the 0..9 neighbourhood total, and the Life rule becomes two bit patterns:

```
total == 3                -> born, or survives
total == 4 and was alive  -> survives
```

`total` includes the cell itself, which is why those numbers are 3 and 4 rather than the 3 and 2 in the rules as usually stated.

Measured on a desktop, on the same 4608-cell grid:

| | per generation |
|---|---|
| naive, count all eight neighbours | 3.01 ms |
| bit-parallel carry-save | **0.13 ms** |

**22.8× faster**, and that understates it on the badge: the naive version's cost is per-cell interpreter overhead, which is exactly what CircuitPython is slowest at, while the bit-parallel version's work happens inside C bigint routines.

The horizontal wrap is free, too — it is just an extra shift folded into the same expression:

```python
left  = ((r << 1) | (r >> LAST)) & MASK
right =  (r >> 1) | ((r & 1) << LAST)
```

and the vertical wrap is `rows[y - 1]`, because Python's negative indexing already means "the last row".

## Drawing is the actual bottleneck

Once the simulation is nearly free, the cost is the screen. `draw_diff()` repaints only cells that **changed**, plus the ones drawn bright or ghosted last generation so those marks fade:

| grid state | `fill_region` calls per generation |
|---|---|
| fresh random soup | ~1590 |
| the same soup at generation 300 | ~320 |
| a still life | 0 |

That is why the sample gets *faster* as a pattern settles, and why a stable pattern costs nothing at all to display. Repainting the whole grid every generation would be a flat 4608 fills.

## Not getting bored

An unattended badge showing a frozen grid looks broken, so the sample reseeds itself when:

- the population hits zero, or
- the state matches the state one or two generations ago (a still life or a period-2 oscillator) for `STALL_LIMIT` consecutive generations, or
- `MAX_GENS` generations have passed regardless.

Period-3 patterns like the pulsar are deliberately *not* caught by that test, since they are worth watching.

## Verification

The carry-save adder is clever enough to be wrong in subtle ways, so the main test runs it against a naive count-the-eight-neighbours reference on **60 random grids × 3 generations each** — plus an all-live grid and an empty one — and requires exact agreement. If those two agree on that many random boards, the adder is right.

On top of that: blinkers have period 2, blocks are still lifes, a glider moves exactly (1,1) in 4 generations and survives crossing the seam, the pulsar has period 3, the spaceship translates without losing cells, the Gosper gun starts at 36 cells and gains ~5 per 30-generation cycle (that is one glider per cycle), and an acorn is still growing after 400 generations. The renderer is checked for in-bounds fills, correct born/died masks, and for costing zero fills on a still life.

24 checks, all passing. What that cannot tell you is the real frame rate on the panel — worth a look on hardware, and `CELL = 4` is the knob if a fresh soup feels sluggish.

## Tuning

| Constant | Effect |
|---|---|
| `CELL` | pixels per cell. 2 → 64×72 (default), 4 → 32×36 and a quarter of the drawing cost |
| `SPEEDS` | seconds per generation for the three SW3 settings; `0.0` means "as fast as it will go" |
| `STALL_LIMIT` | how many repeated generations count as settled before reseeding |
| `MAX_GENS` | hard cap per seed |
| `soup()` | density is `(a | b) & c`, i.e. 3/8. Plain 50% burns down to ash much faster |
| `palette` | `BORN` and `GHOST` are what make motion legible; set them equal to `ALIVE`/`BG` for a plain grid |

Adding a pattern is one entry in `SEEDS`: ASCII art with `#` for a live cell, any other character for dead. It gets centred automatically, and rows must all be the same length.
