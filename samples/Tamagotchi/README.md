# Tamagotchi (virtual pet)

A tiny virtual pet that lives on your badge. It gets hungry, bored and
tired over time — feed it, play with it, and let it sleep. Its mood
shows on the display as an ASCII face and on the 5 NeoPixels as a mood
colour that gently breathes. Stats and total age persist in NVM, so it
remembers you across resets and power cycles.

## What you should see

- An ASCII face (`^_^`, `:)`, `>o<`, `:(`, `-_-`, `Z z z`) that reflects
  the pet's most urgent need, with a short blink every few seconds when
  awake.
- Three stat bars — **FOOD**, **FUN**, **ENER** — that decay while awake
  and regenerate while asleep. A transient toast line (`nom nom`, `yay!`,
  `too tired to play`, …) confirms each action.
- The status line shows awake/asleep and the pet's accumulated age.
- The LEDs breathe in a mood colour: green when happy, orange when
  hungry, blue when bored, purple when tired, dim cyan when asleep.

## Controls

| Switch | Action |
|--------|--------|
| SW1 (IO1)  | **Feed** (+30 food, small energy cost; no-op if full) |
| SW2 (IO2)  | **Play** (+25 fun, −12 energy, −5 food; no-op if exhausted) |
| SW3 (IO43) | **Sleep / Wake** toggle |

## Code design

- **Time-delta decay, not tick counting** — every loop iteration computes
  `dt = now - last_tick` and scales each stat by its rate
  (`food −1/7s`, `fun −1/10s`, `energy −1/15s` awake; `energy +1/4s`
  asleep). This is frame-rate independent: it decays the same whether
  the loop runs at 20 Hz or 5 Hz.
- **NVM persistence at offset 76..81** — `hunger`, `fun`, `energy`
  (one byte each) plus a 3-byte big-endian age. Written at most every
  20 s and on each interaction, to stay within flash write-endurance.
  Because the badge has no battery-backed RTC, the pet doesn't age or
  get hungry while powered off — it resumes exactly as you left it,
  which is the honest behaviour.
- **No-clock persistence** — age is accumulated *live* seconds
  (`age += dt`) and saved, so "age" means total time the pet has been
  awake/alive across all sessions.
- **Mood is the lowest stat** — `face_for()` picks the single most
  urgent need rather than averaging, so the face always tells you the
  one thing to do next.
- **Blink after render** — `render()` sets the normal face each tick;
  the blink then overrides `face_lbl.text` to `"-_-"` for 0.15 s and
  re-refreshes, so the blink actually shows instead of being clobbered.

## Notes

- The first boot on fresh NVM starts a happy pet (all stats 80). To
  reset the pet, clear bytes 76–81 of `microcontroller.nvm`.
