# Factorio

A top-down factory that **builds itself**. It starts as one mining drill and one furnace, and every time enough material piles up in the storage chest — or a research finishes in the lab — the next machine gets built. About two and a half minutes later the factory is complete, the badge celebrates, and the whole thing starts over from one lonely drill.

The factory must grow.

## What you should see

- A concrete factory floor filling the top of the screen. Machines that don't exist yet sit there as cyan **blueprint ghosts**, so you can see the shape of the finished factory from the first second.
- A mining drill chewing at an ore patch, its head sweeping back and forth, dropping ore onto a short yellow **transport belt** that runs into a furnace. The furnace glows brighter as the plate inside it gets closer to done.
- A **main bus** belt, treads scrolling, carrying mixed iron and copper plates from the furnaces all the way down to the storage chest bottom-right.
- **Inserter arms** swinging out of the assemblers and the lab to snatch what they need off the bus as it goes past, carrying the item across in their claw. Whatever nobody wants rides to the end and gets stored.
- The lab's three beakers bubbling while it researches; a boiler with a flickering firebox and a steam engine with a turning flywheel keeping the lights on.
- A HUD strip along the bottom: the current build target or research, grid satisfaction, the goal you're working toward, and total items in storage.
- The 5 NeoPixels as a progress bar toward the current goal — yellow while you're stockpiling material, red during red-science research, green during green. They flash cyan when something gets built and cream on each science pack.

Watch for the small authentic details. The drill mines faster than the furnace smelts, so the ore belt backs up and the drill visibly parks with a full output. The circuit assembler sits **upstream** of the gear assembler on the bus, so it gets first pick of the iron plates and the gear line runs lean — a bus-priority problem anyone who has played the game has had. And building the beacon at the last stage pushes the grid past what one steam engine can supply, so `PWR` drops to 90% and everything slows down slightly, which is the most Factorio thing that happens in the whole demo.

## Controls

| Switch | Action |
|---|---|
| SW1 | Toggle **ALT-MODE** — labels every machine with what it makes, exactly like holding Alt in the real game |
| SW2 | Hold for **3× speed** |
| SW3 | Tear it down and start a fresh factory |

Left alone it needs no input at all — it will keep building and rebuilding factories for as long as the badge has power.

## The growth plan

Each stage builds something the moment it starts, then waits for a goal. Meeting the goal starts the next stage, so the factory expands the way it does in the game: because the last expansion finally paid off.

| Stage | Builds | Goal |
|---|---|---|
| IRON SMELTING | iron drill, furnace, chest, boiler, steam engine | 10 iron plates in storage |
| COPPER SMELTING | copper drill, furnace | 8 copper plates in storage |
| IRON GEARS | gear assembler | 6 gears in storage |
| AUTOMATION | lab | 8 red science (1 gear + 1 copper plate) |
| ELECTRONICS | circuit assembler | 10 green science (1 gear + 1 circuit) |
| SPEED MODULES | beacon, and everything speeds up | 12 more science |

## Is this actually Factorio?

No. Factorio is a large C++ program that wants gigabytes of RAM and a GPU; this badge is an ESP32-S3-WROOM-1-N8 with 512 KB of internal SRAM, no PSRAM, and a 128×160 SPI panel, running CircuitPython. Nothing about that gap is bridgeable.

So this sample takes the other road — the same *ideas*, written from scratch in one CircuitPython file you can open and edit on the badge like everything else here: belts as real item queues, inserters that grab off a shared bus, recipes with ingredients, machines that stall when their output backs up, research that unlocks the next thing, and a power grid you can brown out.

Two deliberate simplifications, so you aren't surprised when you read the code:

- **The lab consumes ingredients directly.** In the real game an assembler crafts science packs and the lab consumes those; here the lab takes gears and copper plates (or gears and circuits) straight off the bus and each completed craft *is* one science pack. That saves a machine on a floor that only has 128 pixels of width to spend.
- **Green circuits take 1 iron + 1 copper plate**, skipping the copper-cable intermediate step.

## Code design

- **One bitmap, filled with rectangles.** The whole factory floor is a single 128×120 indexed `displayio.Bitmap`, and every pixel that changes is written by `bitmaptools.fill_region`, which fills a rectangle in C. Nothing is plotted pixel-by-pixel from Python — that one decision is what makes this run at a watchable frame rate. Same trick as the Doom sample.

- **Static and moving parts are separated.** The floor, ore patches and machine shells only change when a structure appears, so they are painted into the bitmap once and left alone; a `static_dirty` flag repaints them on a build. Each frame repaints only the moving parts — belt lanes, the items riding them, inserter arms, and the one small animated panel inside each machine. That is about 140 rectangle fills per frame instead of 400.

- **Belts are real queues, and that is where the game lives.** A `Belt` is a polyline of axis-aligned segments; its items are kept sorted front-first, and `advance()` never lets an item pass the one ahead of it. Backpressure then falls out for free: a slow consumer stalls the whole line behind it, a full belt refuses an insert, and a machine that cannot push its product out sets `blocked` and stops. Nothing in the code implements "the drill waits when the belt is full" — it just happens.

- **Machines are one class with plumbing in fields.** Every machine is the same three steps: take inputs, craft, push the result out. What differs is only *where* things come from and go, so that is data (`eat_end`, `in_belt`/`in_pos`, `out_belt`/`out_pos`) rather than subclasses. A machine with no inputs is a drill — it mines from nothing. One with no output is the lab — its product is research, which isn't an item.

- **Positions on the bus are the wiring diagram.** Each consumer grabs at a single float position measured along the bus polyline, and drops its product a few pixels *downstream* so it cannot immediately pick back up what it just made. The `BUS_*` constants near the top of the file are the entire routing table; `bus.point_at()` converts any of them back to a pixel so the drawing code and the simulation can never disagree about where a machine is.

- **The floor plan is hand-placed and gap-checked.** Belts are drawn 9 px wide, and the 4–5 px gaps deliberately left between a belt and the machine beside it are the channels the inserter arms swing in. Nothing overlaps anything, which is what lets the renderer repaint a belt every frame without having to restore machine pixels underneath it.

- **Frame-rate independent.** Every movement is scaled by the measured `dt`, clamped to 0.15 s so a garbage-collection hitch can't teleport an item through a machine.

## Tuning

| Constant | Effect |
|---|---|
| `BELT_SPEED` | pixels/second; the single biggest lever on how long a run takes |
| `ITEM_GAP` | how densely items pack onto a belt — lower is busier and slower to draw |
| `DRILL_TIME`, `FURNACE_TIME`, `GEAR_TIME`, `CHIP_TIME` | seconds per craft. Iron is deliberately the bottleneck; raise `FURNACE_TIME` to make it worse |
| `STAGE_PLAN` | the whole growth arc — names, what each stage builds, and its goal |
| `POWER_SUPPLY` | 85 units. Total demand ends at 94, which is the endgame brownout; raise it to 100 to remove it |
| `BUF_CAP` | how many ingredients a machine hoards. Large values let one assembler starve the ones downstream of it |
| `baudrate` on the display bus | 8 MHz is the tested value; the SPI transfer is a real share of each frame |

Adding a machine is three steps: give it a rect in the floor plan, add a `recipe()` plus its bus positions, and add its name to a stage's `build` tuple. Give it a rect that doesn't collide with a belt frame and the renderer needs nothing else.
