# 🐸 CyberFrog (Toadie) for CCC 2026 Badge

A Tamagotchi-style virtual pet built for the **Carolina Code Conference 2026 Circuit Board Badge**. 

Raise, feed, and play with your digital amphibian across 4 evolution stages directly on the badge's ST7735 color LCD, NeoPixels, and tactile switches—with non-volatile flash persistence so your frog never resets on battery changes.

---

## ✨ Features

- **Evolution System:** Watch Toadie grow as you earn XP:
  - 🫧 **Stage 1 (Lv 1–3):** `TADPOLE` — Tiny swimmer with a wiggly tail.
  - 🌿 **Stage 2 (Lv 4–7):** `FROGLET` — Sprouting back legs and learning to hop.
  - 🐸 **Stage 3 (Lv 8–14):** `TREE FROG` — Full-grown bug hunter with a long tongue.
  - 🤖 **Stage 4 (Lv 15+):** `CYBER TOAD` — Horned cybernetic bullfrog with visor eyes.
- **Hardware-Integrated Status LEDs:**
  - **LEDs 1–3:** Real-time Hunger / Energy gauge.
  - **LED 4:** Evolution Stage & Sleep indicator (Cyan → Green → Gold → Magenta / Blue when resting).
  - **LED 5:** Alert beacon (Pulses red if starving or neglected).
- **Persistent State:** Saves level, stats, and XP directly to `microcontroller.nvm` (Offset 64) without blocking the UI, causing reboots, or colliding with the stock sample launcher.
- **Launcher Compatible:** Designed to live inside `/samples/CyberFrog/` and be auto-discovered by the conference badge launcher.

---

## 🎮 Controls

| Button | Pin | Action | Description |
| :--- | :--- | :--- | :--- |
| **SW1** | `IO1` | **Feed** | Catches a bug, refills hunger (+25), and grants **+10 XP**. |
| **SW2** | `IO2` | **Play / Hop** | Hops around, boosts happiness (+20), and grants **+15 XP**. |
| **SW3** | `IO43` | **Sleep / Wake** | Toggles sleep mode to restore happiness and reduce hunger decay. |

---

## 🚀 Installation

### Option 1: Add to the Badge Sample Launcher (Recommended)

1. Connect your badge to your computer via USB (the `CIRCUITPY` drive will appear).
2. Navigate to the `samples/` directory and create a folder named `CyberFrog`:
   ```text
   CIRCUITPY/
   └── samples/
       └── CyberFrog/
           ├── code.py
           └── README.md
