# Wa-Tor World

Wa-Tor (A.K. Dewdney, *Scientific American*, 1984) is a predator/prey
world wrapped onto a torus. Fish wander and breed. Sharks hunt fish,
breed more slowly, and starve if they do not eat. Neither species ever
settles: the populations chase each other up and down for as long as
you leave the badge on.

The world fills the whole 128×160 panel — **64×80 cells, each drawn
two pixels square** — with no frame, no chrome and no controls. It
began as a port of the viewer frame from the
[`wa-tor-whirl`](https://github.com/thomasarch/wa-tor-whirl) browser
toy and still runs that page's rules and colours.

## What you should see

- A blue ocean filling the screen, with gold fish and red sharks two
  pixels square each — a couple of hundred of them most of the time.
- Fish drifting apart and budding new fish, sharks cutting through the
  loose shoals, and the whole thing breathing: long thin stretches,
  then a bloom of a thousand or so, then a crash.
- A fresh world whenever one side finally loses — only sharks left,
  only fish left, or open ocean. There is no Restart button to press,
  so it reseeds itself.
- Population counts on the USB serial console every 50 turns (the
  world owns every pixel, so there is nowhere on screen to put them).

## Controls

None. The world runs by itself.

## The parameters, and why they are not the page's

| | this badge | the page |
|---|---|---|
| world | 64 × 80 = 5 120 cells, drawn 2×2 | 50 × 50 = 2 500, drawn 10×10 |
| turn | 200 ms | 100 ms |
| fish | 150 start, energy 42, breeds every 20 moves | 500, energy 5, every 2 |
| sharks | 40 start, energy 12, breeds every 16 moves | 125, energy 4, every 8 |
| a meal is worth | 12 energy | 1 |

The page's biology settles at roughly **half a full grid**, which is
more creatures per turn than this hardware wants to move. Getting a
thinly populated ocean instead comes down to one number.

A shark spends 1 energy per move and finds a fish on about
`4 × (fish density)` of its moves, so it breaks even only where
`4 × density × meal ≥ 1`. With the page's meal of 1 that needs a 25%
fish density — which is exactly why the page's world is so crowded.
Raise a meal to 12 and sharks can live at about 2%. Slowing fish
breeding from every 2 moves to every 20 then stops the fish from
simply filling the space that leaves.

Measured over 8 worlds × 6 000 turns (20 minutes of badge time each):

| | |
|---|---|
| median population | 254 (5.0% of the grid) |
| usual range | 101 – 690 (10th–90th percentile) |
| boom peak | 1 840 (36% of the grid) |
| world lifetime | median 2 269 turns ≈ 7.6 min, then it reseeds |

A world this small is the trade for the bigger cells: at one cell per
pixel (128×160, 20 480 cells) the same idea held 690 creatures and ran
past 20 minutes in 5 runs of 6, because a grid with four times the
cells rides out a crash that would finish this one.

The rules themselves are the page's, quirks included: **every**
creature spends one energy per move, so fish starve as well as sharks,
and a creature boxed in on all four sides simply passes — it neither
ages nor breeds that turn.

## Code design

- **The world *is* the state.** The browser version keeps a list of
  creature objects and reads the grid back out of the canvas with
  `getImageData`; neither survives contact with a microcontroller —
  thousands of objects would eat the heap and the per-creature
  `findIndex` scans are quadratic.
- **One creature = one 16-bit word**, in an `array("H")`: type in bits
  0–1, fertility in 2–6, energy in 7–14, and a stamp bit at 15. That
  is 10 KB against 20 KB for the same thing as a list of Python ints,
  and it stays flat if the grid is ever scaled back up.
- **The stamp bit flips meaning every turn.** A creature that moves
  into a cell the turn has not reached yet would otherwise move twice.
  Marking it costs one bit, and flipping what "marked" means each turn
  saves a second pass over the grid to clear the marks.
- **One cell, one store, one index.** `cells` and the bitmap share the
  same flat index, so drawing a creature is a single `bmp[idx]` store
  with no index-to-(x, y) conversion. The bitmap stays at world
  resolution and a `Group(scale=2)` doubles it to fill the panel, so
  displayio does the zoom in C rather than Python writing four pixels.
- **Torus arithmetic on flat indices** — only the column has to be
  worked out, because the row edges are just the ends of the index.
- **The turn carries its own work list**, so the next turn starts from
  a list of occupied cells instead of rescanning all 5 120. Entries
  go stale when a shark eats a fish that had already moved; the stamp
  check catches that.
- **Fish get the unrolled path.** They outnumber sharks and only ever
  look for open water, so their neighbour scan is four straight-line
  tests with no loop, no tuple and no "is that prey?" check.
- **Only changed cells are repainted**, and a newborn wears its
  parent's colour, so breeding does not even cost a pixel store.
  Populations are tracked incrementally as creatures are born, eaten
  and starved rather than recounted each turn.

At a typical few hundred creatures the simulation costs far less than
pushing the frame out over SPI, so the viewer is limited by the panel
rather than by Python. If you want it faster, raising the display
`baudrate` above `8_000_000` buys more than anything left in the loop.
