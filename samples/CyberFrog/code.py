"""
CyberFrog with Evolutions - CCC 2026 Badge
==========================================
Evolution Stages:
  Lv 1-3  : Tadpole
  Lv 4-7  : Froglet
  Lv 8-14 : Tree Frog
  Lv 15+  : Cyber Toad

Controls:
  SW1 (IO1)  -- Feed (Catch flies & boost XP)
  SW2 (IO2)  -- Play / Hop (Boost Happiness & XP)
  SW3 (IO43) -- Sleep / Wake Toggle
"""

import time
import board
import busio
import digitalio
import displayio
import terminalio
import fourwire
import microcontroller
import adafruit_st7735r
import neopixel
from adafruit_display_text import label

# ------------------------------------------------------------------
# Hardware Initialization
# ------------------------------------------------------------------
bl = digitalio.DigitalInOut(board.IO5)
bl.direction = digitalio.Direction.OUTPUT
bl.value = True

font_cs = digitalio.DigitalInOut(board.IO9)
font_cs.direction = digitalio.Direction.OUTPUT
font_cs.value = True

pixels = neopixel.NeoPixel(board.IO4, 5, brightness=0.15, auto_write=False)


def init_btn(pin):
    b = digitalio.DigitalInOut(pin)
    b.switch_to_input(pull=digitalio.Pull.UP)
    return b


sw1 = init_btn(board.IO1)
sw2 = init_btn(board.IO2)
sw3 = init_btn(board.IO43)

displayio.release_displays()
spi = busio.SPI(clock=board.IO12, MOSI=board.IO11)
display_bus = fourwire.FourWire(
    spi, command=board.IO6, chip_select=board.IO10, reset=board.IO7, baudrate=8_000_000
)
display = adafruit_st7735r.ST7735R(
    display_bus, width=128, height=160, rotation=0, bgr=True, auto_refresh=False
)

# ------------------------------------------------------------------
# Evolution Sprites (5 Lines each)
# ------------------------------------------------------------------

# --- STAGE 1: TADPOLE (Lv 1-3) ---
TADPOLE_IDLE_1 = [
    r"               ",
    r"    (o)~~~     ",
    r"   (____) )    ",
    r"        ~~     ",
    r"               ",
]
TADPOLE_IDLE_2 = [
    r"               ",
    r"    (-)  ~     ",
    r"   (____) )~   ",
    r"         ~     ",
    r"               ",
]
TADPOLE_EAT = [
    r"               ",
    r"    (o)> *     ",
    r"   (____)~~    ",
    r"        ~      ",
    r"               ",
]
TADPOLE_SLEEP = [
    r"               ",
    r"    (-)~~   z  ",
    r"   (____)  z   ",
    r"               ",
    r"               ",
]

# --- STAGE 2: FROGLET (Lv 4-7) ---
FROGLET_IDLE_1 = [
    r"    (o) (o)    ",
    r"   ( . _ . )   ",
    r"   / (   ) \ ~ ",
    r"  (__/   \__)~ ",
    r"               ",
]
FROGLET_IDLE_2 = [
    r"    (-) (-)    ",
    r"   ( . _ . )   ",
    r"   / (   ) \   ",
    r"  (__/   \__)~ ",
    r"              ~",
]
FROGLET_EAT = [
    r"    (o) (o)    ",
    r"   ( =0=> * )  ",
    r"   / (   ) \ ~ ",
    r"  (__/   \__)~ ",
    r"               ",
]
FROGLET_SLEEP = [
    r"    (-) (-)  z ",
    r"   ( . w . )z  ",
    r"   / (   ) \   ",
    r"  (_________)~ ",
    r"               ",
]

# --- STAGE 3: TREE FROG (Lv 8-14) ---
FROG_IDLE_1 = [
    r"   (o)   (o)   ",
    r"  (   ._.   )  ",
    r"  / (     ) \  ",
    r" (__(  _  )__) ",
    r"    /_/ \_\    ",
]
FROG_IDLE_2 = [
    r"   (-)   (-)   ",
    r"  (   ._.   )  ",
    r"  / (     ) \  ",
    r" (__(  _  )__) ",
    r"    /_/ \_\    ",
]
FROG_EAT = [
    r"   (o)   (o)   ",
    r"  (  =0====> * ",
    r"  / (     ) \  ",
    r" (__(  _  )__) ",
    r"    /_/ \_\    ",
]
FROG_SLEEP = [
    r"   (-)   (-)  z",
    r"  (   .w.   )z ",
    r"  / (     ) \  ",
    r" (__(_____)__) ",
    r"               ",
]

# --- STAGE 4: CYBER TOAD (Lv 15+) ---
TOAD_IDLE_1 = [
    r"   /| /---\ |\  ",
    r"  <[O] === [O]> ",
    r" ==(   .w.   )==",
    r"  /(  =====  )\ ",
    r" (__(  \_/  )__)",
]
TOAD_IDLE_2 = [
    r"   /| /---\ |\  ",
    r"  <[-] === [-]> ",
    r" ==(   .w.   )==",
    r"  /(  =====  )\ ",
    r" (__(  \_/  )__)",
]
TOAD_EAT = [
    r"   /| /---\ |\  ",
    r"  <[O] === [O]> ",
    r" ==(=0=====> *==",
    r"  /(  =====  )\ ",
    r" (__(  \_/  )__)",
]
TOAD_SLEEP = [
    r"   /| /---\ |\ z",
    r"  <[-] === [-]>z",
    r" ==(   -.-   )==",
    r"  /(  =====  )\ ",
    r" (__(_______)__)",
]

# ------------------------------------------------------------------
# Persistence Layer (microcontroller.nvm offset 64)
# ------------------------------------------------------------------
NVM_OFFSET = 64
MAGIC_HEADER = b"FROG"


def save_pet(pet):
    try:
        data = bytearray(9)
        data[0:4] = MAGIC_HEADER
        data[4] = min(255, max(1, pet.level))
        data[5] = min(100, max(0, pet.hunger))
        data[6] = min(100, max(0, pet.happiness))
        xp_clamped = min(65535, max(0, pet.xp))
        data[7] = (xp_clamped >> 8) & 0xFF
        data[8] = xp_clamped & 0xFF
        microcontroller.nvm[NVM_OFFSET : NVM_OFFSET + 9] = data
    except Exception as e:
        print("Save failed:", e)


def load_pet(pet):
    try:
        header = bytes(microcontroller.nvm[NVM_OFFSET : NVM_OFFSET + 4])
        if header == MAGIC_HEADER:
            pet.level = microcontroller.nvm[NVM_OFFSET + 4]
            pet.hunger = microcontroller.nvm[NVM_OFFSET + 5]
            pet.happiness = microcontroller.nvm[NVM_OFFSET + 6]
            hi = microcontroller.nvm[NVM_OFFSET + 7]
            lo = microcontroller.nvm[NVM_OFFSET + 8]
            pet.xp = (hi << 8) | lo
            pet.action_msg = "Welcome back!"
            return True
    except Exception as e:
        print("Load failed:", e)
    return False


# ------------------------------------------------------------------
# Frog State & Evolution Logic
# ------------------------------------------------------------------
class CyberFrog:
    def __init__(self, name="TOADIE"):
        self.name = name
        self.hunger = 100
        self.happiness = 100
        self.is_sleeping = False
        self.xp = 0
        self.level = 1
        self.stage = 1
        self.stage_title = "TADPOLE"
        self.action_msg = "Ribbit!"
        self.eat_timer = 0
        self.dirty = False

    def feed(self):
        if self.is_sleeping:
            self.action_msg = "Zzz... Wake first!"
            return
        self.hunger = min(100, self.hunger + 25)
        self.xp += 10
        self.eat_timer = 4
        self.action_msg = "*Munch munch!*"
        self.dirty = True
        self.update_level()

    def play(self):
        if self.is_sleeping:
            self.action_msg = "Zzz... Wake first!"
            return
        self.happiness = min(100, self.happiness + 20)
        self.hunger = max(0, self.hunger - 5)
        self.xp += 15
        self.action_msg = "*Splash & hop!*"
        self.dirty = True
        self.update_level()

    def toggle_sleep(self):
        self.is_sleeping = not self.is_sleeping
        self.action_msg = "Sleeping... zZz" if self.is_sleeping else "Croak! Woke up!"
        self.dirty = True

    def update_level(self):
        old_lvl = self.level
        old_stage = self.stage
        self.level = (self.xp // 50) + 1

        # Calculate Evolution Stage
        if self.level < 4:
            self.stage = 1
            self.stage_title = "TADPOLE"
        elif self.level < 8:
            self.stage = 2
            self.stage_title = "FROGLET"
        elif self.level < 15:
            self.stage = 3
            self.stage_title = "TREE FROG"
        else:
            self.stage = 4
            self.stage_title = "CYBER TOAD"

        if self.stage > old_stage:
            self.action_msg = f"EVOLVED! {self.stage_title}"
        elif self.level > old_lvl:
            self.action_msg = f"Level UP! (Lv.{self.level})"

    def decay(self):
        if not self.is_sleeping:
            self.hunger = max(0, self.hunger - 2)
            self.happiness = max(0, self.happiness - 2)
        else:
            self.happiness = min(100, self.happiness + 3)
            self.hunger = max(0, self.hunger - 1)
        self.dirty = True

    def get_sprites(self):
        if self.stage == 1:
            return TADPOLE_IDLE_1, TADPOLE_IDLE_2, TADPOLE_EAT, TADPOLE_SLEEP
        elif self.stage == 2:
            return FROGLET_IDLE_1, FROGLET_IDLE_2, FROGLET_EAT, FROGLET_SLEEP
        elif self.stage == 3:
            return FROG_IDLE_1, FROG_IDLE_2, FROG_EAT, FROG_SLEEP
        else:
            return TOAD_IDLE_1, TOAD_IDLE_2, TOAD_EAT, TOAD_SLEEP


pet = CyberFrog("TOADIE")
load_pet(pet)
pet.update_level()

# ------------------------------------------------------------------
# UI / Displayio Hierarchy
# ------------------------------------------------------------------
root = displayio.Group()

bg = displayio.Bitmap(128, 160, 1)
bg_pal = displayio.Palette(1)
bg_pal[0] = 0x001206
root.append(displayio.TileGrid(bg, pixel_shader=bg_pal))

# Title / Stage banner
lbl_title = label.Label(terminalio.FONT, text="", color=0x00FF88)
lbl_title.anchor_point = (0.5, 0.5)
lbl_title.anchored_position = (64, 9)
root.append(lbl_title)

# Stats readout
lbl_hunger = label.Label(terminalio.FONT, text="", color=0xFFAA00)
lbl_hunger.anchor_point = (0.0, 0.5)
lbl_hunger.anchored_position = (8, 22)
root.append(lbl_hunger)

lbl_happy = label.Label(terminalio.FONT, text="", color=0x00FFFF)
lbl_happy.anchor_point = (0.0, 0.5)
lbl_happy.anchored_position = (8, 33)
root.append(lbl_happy)

# Sprite lines (5 rows)
sprite_labels = []
for i in range(5):
    lbl_sp = label.Label(terminalio.FONT, text="", color=0x39FF14)
    lbl_sp.anchor_point = (0.5, 0.5)
    lbl_sp.anchored_position = (64, 54 + (i * 12))
    root.append(lbl_sp)
    sprite_labels.append(lbl_sp)

lbl_action = label.Label(terminalio.FONT, text="", color=0xFFFFFF)
lbl_action.anchor_point = (0.5, 0.5)
lbl_action.anchored_position = (64, 126)
root.append(lbl_action)

lbl_legend = label.Label(terminalio.FONT, text="S1:Fly S2:Hop S3:Zz", color=0x707070)
lbl_legend.anchor_point = (0.5, 0.5)
lbl_legend.anchored_position = (64, 148)
root.append(lbl_legend)

display.root_group = root

# ------------------------------------------------------------------
# Main Loop
# ------------------------------------------------------------------
last_decay = time.monotonic()
last_anim = time.monotonic()
last_autosave = time.monotonic()
anim_frame = 0

prev1 = prev2 = prev3 = True

while True:
    now = time.monotonic()

    # --- Button Input ---
    v1, v2, v3 = sw1.value, sw2.value, sw3.value
    if prev1 and not v1:
        pet.feed()
    if prev2 and not v2:
        pet.play()
    if prev3 and not v3:
        pet.toggle_sleep()
    prev1, prev2, prev3 = v1, v2, v3

    # --- Decay & Autosave ---
    if now - last_decay >= 4.0:
        pet.decay()
        last_decay = now

    if pet.dirty and (now - last_autosave >= 10.0):
        save_pet(pet)
        pet.dirty = False
        last_autosave = now

    # --- Animation Timer ---
    if now - last_anim >= 0.5:
        anim_frame = 1 - anim_frame
        if pet.eat_timer > 0:
            pet.eat_timer -= 1
        last_anim = now

    # --- NeoPixels Update ---
    # LEDs 0-2: Hunger
    pixels[0] = (0, 180, 0) if pet.hunger >= 25 else (0, 0, 0)
    pixels[1] = (0, 180, 0) if pet.hunger >= 55 else (0, 0, 0)
    pixels[2] = (0, 180, 0) if pet.hunger >= 85 else (0, 0, 0)

    # LED 3: Stage color indicator (Stage 1 cyan -> Stage 4 gold)
    if pet.is_sleeping:
        pixels[3] = (0, 0, 180)
    else:
        stage_colors = [(0, 150, 150), (0, 180, 50), (180, 180, 0), (220, 0, 180)]
        pixels[3] = stage_colors[pet.stage - 1]

    # LED 4: Warning Pulse
    if pet.hunger < 20 or pet.happiness < 20:
        pixels[4] = (220, 0, 0) if anim_frame == 1 else (0, 0, 0)
    else:
        pixels[4] = (0, 0, 0)

    pixels.show()

    # --- Render Display ---
    lbl_title.text = f"{pet.stage_title} Lv.{pet.level} XP:{pet.xp}"
    lbl_hunger.text = f"Hunger : {'#' * (pet.hunger // 10):<10}"
    lbl_happy.text = f"Happy  : {'*' * (pet.happiness // 10):<10}"
    lbl_action.text = pet.action_msg

    # Choose sprite by current stage
    s_idle1, s_idle2, s_eat, s_sleep = pet.get_sprites()
    if pet.is_sleeping:
        active_sprite = s_sleep
    elif pet.eat_timer > 0:
        active_sprite = s_eat
    elif anim_frame == 0:
        active_sprite = s_idle1
    else:
        active_sprite = s_idle2

    for i in range(5):
        sprite_labels[i].text = active_sprite[i]

    display.refresh()
    time.sleep(0.02)
