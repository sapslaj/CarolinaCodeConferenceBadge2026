# Doom

A raycasting first-person shooter that **plays itself**. Drop it on the badge, set it on a table, and it runs forever: a bot marine paths around a level, hunts monsters, restocks ammo when it runs low, and shoots what it can see. When it clears the level or dies, the level resets and the next round starts with a fresh layout.

## What you should see

- A 3D corridor view filling the top of the screen, with a shaded sky and floor gradient, coloured walls, and a pistol bobbing at the bottom as the marine walks.
- Brown horned imps that notice the marine, walk at him, and swipe when they get close. They flash cream-white when hit.
- Ammo crates sitting on the floor. The bot detours to grab one when it gets low; crates reappear about 11 seconds after being taken.
- A HUD strip along the bottom: health, ammo, imps remaining, and a live frame counter.
- The 5 NeoPixels as a health bar — green, then yellow, then red as the marine takes damage. They flash cream on a shot, red on a hit taken, and blue on an ammo pickup.
- `VICTORY` or `GAME OVER` for three seconds between rounds.

Rounds last roughly 15–25 seconds. The bot wins most of them but does die sometimes — the monster placement and its own starting corner are re-rolled every round, so no two look the same.

## Controls

None. The three tactile switches are deliberately never claimed, so nothing competes for them.

To play it yourself instead, replace `bot_think()` with a function that reads the switches and returns the same `(turn, walk, fire)` triple — `turn` is `-1`, `0`, or `+1`, the other two are booleans. Nothing else in the game knows or cares where that triple came from. A workable three-button scheme is SW1 = turn left, SW2 = turn right, SW3 = tap to fire / hold to walk forward.

## Is this actually DOOM?

No, and it can't be. Two hard blockers:

- **Memory.** The module on this badge is an ESP32-S3-**WROOM-1-N8** — 8 MB of flash and 512 KB of internal SRAM, with *no PSRAM* (that's what the `R2`/`R8` suffixes denote, and this part doesn't have one). The shareware `doom1.wad` alone is about 4 MB, and the engine wants several MB of working set on top. There is nowhere to put it.
- **Language.** Doom is a C program. Running it means replacing CircuitPython with an ESP-IDF firmware build — at which point `code.py` no longer exists, the USB drive workflow is gone, and the badge stops being the thing this repository is about.

So this sample takes the other road: the same idea — first-person, raycast walls, sprite monsters, hitscan weapon — written from scratch in CircuitPython, in one file, that you can open and edit on the badge like everything else here.

## Code design

- **One bitmap, filled with rectangles.** The whole 3D view is a single 128×112 indexed `displayio.Bitmap`. Every pixel that changes is written by `bitmaptools.fill_region`, which fills a rectangle in C. Nothing is plotted pixel-by-pixel from Python — that one decision is what makes this fast enough to be a game. A frame is about 160 rectangle fills: 12 for the sky/floor gradient bands, 64 wall strips, ~50 for sprites, ~36 for the weapon.

- **Palette indices, not colours.** The bitmap stores small integers and a `displayio.Palette` maps them to RGB. Wall shading is therefore free: four base wall colours × four distance shades are baked into the palette at startup, and picking a shade at render time is integer arithmetic, not colour maths.

- **DDA raycasting.** One ray per `STRIP_W` pixels marches cell-to-cell through the map grid until it hits a wall, then the perpendicular distance sets that strip's height. `STRIP_W = 2` casts 64 rays; raising it to `4` casts 32 and roughly halves the raycasting cost if you want the frame rate back.

- **A depth buffer for sprites.** Each strip's wall distance is kept in `zbuf`. Sprites are drawn as vertical column runs and each column is skipped when a wall in front is nearer, so monsters are correctly hidden behind pillars — and correctly half-hidden at the edges.

- **Sprites are pre-merged ASCII art.** The imp, the pistol, and the ammo crate are written as strings. At startup `build_columns()` collapses each column into runs of identical pixels, so drawing a monster is ~24 rectangle fills instead of ~190 individual pixels. The hit-flash and no-muzzle-flash variants are just recoloured/filtered copies of those runs, built once.

- **The bot is a separate concern.** `bot_think()` returns `(turn, walk, fire)` — exactly what a set of buttons would produce — and the game loop has no idea a bot is driving. Navigation is a breadth-first search over the 16×16 grid, re-run a few times a second, which steers toward the next cell on a shortest path. An earlier version simply walked straight at its target; that wedges permanently on the first pillar it meets, which a human would notice and correct but an unattended demo cannot.

- **The monsters are dumber on purpose.** They walk straight at the marine with no pathfinding. When both axes are blocked they sidle sideways along the wall for half a second, alternating direction, which is enough to get a pack around a pillar without any of the cost of real pathfinding. This is also why the map is open-plan: a maze would leave them stuck in corners.

- **Designed so it can't get bored.** Two failure modes would leave the badge showing a frozen standoff forever, and both are handled: ammo crates respawn on a timer (a bot that runs dry could otherwise neither win nor die), and once two or fewer monsters remain their sight range goes effectively infinite so the stragglers come to the marine instead of idling across the map.

- **Frame-rate independent.** Every movement is scaled by the measured `dt`, clamped to 0.15 s so a garbage-collection hitch can't teleport anything through a wall.

## Tuning

| Constant | Effect |
|---|---|
| `STRIP_W` | 2 = 64 rays (default), 4 = 32 rays and a faster frame |
| `ENEMY_COUNT` | monsters per round, drawn from `SPAWN_POOL` |
| `ENEMY_SPEED`, `ENEMY_DAMAGE` | how dangerous a round is |
| `SHOT_SPREAD` | how forgiving aiming is; the bot aims inside 70% of it |
| `MAP` | the level itself — keep it open-plan, and keep the border sealed |
| `baudrate` on the display bus | 8 MHz is the tested value; the SPI transfer is a real share of each frame, so this is the first thing to raise if you want more speed |
