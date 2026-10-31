#!/usr/bin/env python3
"""The Sofa box's boot screen: what the TV shows from power-on until Sofa opens.

It's the same as Sofa's own loading screen (the glowing sofa, "Sofa" rising in, a light sweeping along
a bar), in the box's theme, with its name underneath ("Living room"). It's a Plymouth theme: the
pictures are drawn here with Pillow, and Plymouth's script animates them.

  sofa-box-art.py plymouth DIR [settings.json]   write the theme into DIR (/usr/share/plymouth/themes/sofa)
  sofa-box-art.py png [settings.json]            a picture of it (for previews), to stdout

`sofa-box apply-boot` (run by Box settings on the TV) writes it and makes it the boot screen.
"""
import io
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SIZE = (1920, 1080)
SETTINGS = os.path.expanduser("~/.config/sofa-box/settings.json")
THEMES = {"street": ("#0D0D10", "#FF2E88"), "terminal": ("#030806", "#39FF88"), "pirate": ("#0B1320", "#E6B450"),
          "midnight": ("#0A0E1A", "#F4B740"), "cinema": ("#0B0708", "#E5484D"), "ocean": ("#04131A", "#3CC8D8"),
          "forest": ("#0A120D", "#8BD46E"), "grape": ("#100A1A", "#C792FF"), "oled": ("#000000", "#F4B740")}
FONT_DIRS_OWN = (os.path.join(HERE, "fonts"),                                        # on the box
                 os.path.join(HERE, "..", "..", "client", "vendor", "fonts"))         # in Sofa itself
FONT_DIRS = ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "/usr/share/fonts/TTF",
             "/Library/Fonts", "/System/Library/Fonts/Supplemental")
_fonts = {}


def font(size, bold=False, display=False):
    """Sofa's own typefaces (Bricolage Grotesque for the word, Instrument Sans for the rest), as the app
    has them; DejaVu where they can't be read (an old Pillow, or not copied over)."""
    key = (size, bold, display)
    if key in _fonts:
        return _fonts[key]
    name = "bricolage-grotesque-latin-opsz-normal.woff2" if display else "instrument-sans-latin-wght-normal.woff2"
    for d in FONT_DIRS_OWN:
        path = os.path.join(d, name)
        if os.path.exists(path):
            try:
                f = ImageFont.truetype(path, size)
                axes = [a["name"] for a in f.get_variation_axes()]
                f.set_variation_by_axes([min(96, size) if n == b"Optical size" else (800 if display else 680 if bold else 440)
                                         for n in axes])
                _fonts[key] = f
                return f
            except (OSError, AttributeError, ValueError):
                break
    names = ("DejaVuSans-Bold.ttf", "Arial Bold.ttf") if bold or display else ("DejaVuSans.ttf", "Arial.ttf")
    for d in FONT_DIRS:
        for n in names:
            if os.path.exists(os.path.join(d, n)):
                _fonts[key] = ImageFont.truetype(os.path.join(d, n), size)
                return _fonts[key]
    try:
        _fonts[key] = ImageFont.load_default(size=size)     # Pillow 10.1+
    except TypeError:
        _fonts[key] = ImageFont.load_default()
    return _fonts[key]


def rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


class Colors:
    def __init__(self, theme):
        bg, accent = THEMES.get(theme or "midnight", THEMES["midnight"])
        self.bg, self.accent = rgb(bg), rgb(accent)
        self.paper = (237, 239, 246)
        self.mist = (140, 148, 171)


def text_size(d, text, f):
    try:
        x0, y0, x1, y1 = d.textbbox((0, 0), text, font=f)
        return x1 - x0, y1 - y0
    except AttributeError:                       # Pillow before 8
        return d.textsize(text, font=f)


def rounded(d, box, r, fill):
    """A rounded rectangle on any Pillow (rounded_rectangle only came in 8.2)."""
    x0, y0, x1, y1 = [int(v) for v in box]
    r = int(max(0, min(r, (x1 - x0) // 2, (y1 - y0) // 2)))
    if r == 0:
        d.rectangle((x0, y0, x1, y1), fill=fill)
        return
    d.rectangle((x0 + r, y0, x1 - r, y1), fill=fill)
    d.rectangle((x0, y0 + r, x1, y1 - r), fill=fill)
    for cx, cy, a in ((x0, y0, 180), (x1 - 2 * r, y0, 270), (x0, y1 - 2 * r, 90), (x1 - 2 * r, y1 - 2 * r, 0)):
        d.pieslice((cx, cy, cx + 2 * r, cy + 2 * r), a, a + 90, fill=fill)


def logo(d, x, y, scale, color):
    """Sofa's mark (the little sofa), from the app's 30x22 icon."""
    s = scale
    rounded(d, (x + 5 * s, y, x + 25 * s, y + 13 * s), 4.5 * s, color)            # the back
    rounded(d, (x, y + 9 * s, x + 6 * s, y + 20 * s), 3 * s, color)               # the arms
    rounded(d, (x + 24 * s, y + 9 * s, x + 30 * s, y + 20 * s), 3 * s, color)
    d.rectangle((x + 3 * s, y + 15 * s, x + 27 * s, y + 20 * s), fill=color)       # the seat
    d.rectangle((x + 4 * s, y + 20 * s, x + 7 * s, y + 22 * s), fill=color)        # the legs
    d.rectangle((x + 23 * s, y + 20 * s, x + 26 * s, y + 22 * s), fill=color)


def load(path=None):
    try:
        with open(path or SETTINGS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def pieces(settings):
    """The boot screen's pictures, each on its own (Plymouth moves them): glow, mark, word, name."""
    c = Colors(settings.get("theme"))
    glow = Image.new("RGBA", (360, 240), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((60, 40, 300, 200), fill=c.accent + (120,))
    glow = glow.filter(ImageFilter.GaussianBlur(46)).resize((1040, 700), getattr(Image, "BICUBIC", 3))

    mark = Image.new("RGBA", (300, 220), (0, 0, 0, 0))
    logo(ImageDraw.Draw(mark), 0, 0, 10, c.accent + (255,))
    mark = mark.resize((138, 101), getattr(Image, "LANCZOS", 1))

    def words(text, size, color, bold=True, display=False):
        f = font(size, bold, display)
        tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        w, h = text_size(tmp, text, f)
        im = Image.new("RGBA", (max(1, w + 8), max(1, int(size * 1.35))), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((4, 0), text, font=f, fill=color + (255,))
        return im

    word = words("Sofa", 112, c.paper, True, True)
    name = words(settings.get("boot_text") or "", 30, c.mist, False) if settings.get("boot_text") else None
    track = Image.new("RGBA", (240, 5), c.paper + (26,))
    light = Image.new("RGBA", (96, 5), c.accent + (255,))
    return {"glow": glow, "mark": mark, "word": word, "name": name, "track": track, "light": light, "colors": c}


def render(settings, size=SIZE, phase=0.4):
    """One frame of the boot screen (phase: how far the light is along the bar)."""
    p = pieces(settings)
    c = p["colors"]
    im = Image.new("RGBA", size, c.bg + (255,))
    k = size[1] / 1080.0

    def put(img, cx, cy):
        if img is None:
            return
        img = img.resize((max(1, int(img.size[0] * k)), max(1, int(img.size[1] * k))))
        im.alpha_composite(img, (int(cx - img.size[0] / 2), int(cy - img.size[1] / 2)))
    cx, cy = size[0] / 2, size[1] / 2
    put(p["glow"], cx, cy - 90 * k)
    put(p["mark"], cx, cy - 120 * k)
    put(p["word"], cx, cy + 10 * k)
    put(p["track"], cx, cy + 112 * k)
    light = p["light"].resize((int(96 * k), max(1, int(5 * k))))
    lx = cx - 120 * k + (240 - 96) * k * phase
    im.alpha_composite(light, (int(lx), int(cy + 112 * k - light.size[1] / 2)))
    put(p["name"], cx, size[1] - 90 * k)
    return im.convert("RGB")


SCRIPT = r"""// Sofa box boot screen (written by sofa-box-art.py)
Window.SetBackgroundTopColor(%(r)f, %(g)f, %(b)f);
Window.SetBackgroundBottomColor(%(r)f, %(g)f, %(b)f);
sw = Window.GetWidth(); sh = Window.GetHeight(); k = sh / 1080;
cx = Window.GetX() + sw / 2; cy = Window.GetY() + sh / 2;

fun place(file, x, y, z) {
  img = Image(file);
  img = img.Scale(img.GetWidth() * k, img.GetHeight() * k);
  s = Sprite(img);
  s.SetX(x - img.GetWidth() / 2); s.SetY(y - img.GetHeight() / 2); s.SetZ(z);
  return s;
}
glow = place("glow.png", cx, cy - 90 * k, 1);
mark = place("mark.png", cx, cy - 120 * k, 3);
word = place("word.png", cx, cy + 10 * k, 3);
track = place("track.png", cx, cy + 112 * k, 2);
light = place("light.png", cx, cy + 112 * k, 3);
%(name)s
word.SetOpacity(0); track.SetOpacity(0); light.SetOpacity(0); mark.SetOpacity(0);
t = 0;
fun tick() {
  t++;
  a = Math.Min(t / 22, 1);                                  // the mark pops in
  mark.SetOpacity(a);
  w = Math.Clamp((t - 12) / 26, 0, 1);                       // the word rises
  word.SetOpacity(w); word.SetY(cy + 10 * k - word.GetImage().GetHeight() / 2 + (1 - w) * 18 * k);
  b = Math.Clamp((t - 25) / 20, 0, 1);
  track.SetOpacity(b);
  p = (t %% 55) / 55;                                        // the light sweeps along the bar
  light.SetX(cx - 120 * k + (240 - 96) * k * p);
  light.SetOpacity(b * Math.Sin(p * Math.Pi));
  glow.SetOpacity(0.55 + 0.45 * Math.Sin(t / 50 * Math.Pi)); // and the glow breathes
}
Plymouth.SetRefreshFunction(tick);

msg = Sprite(); msg.SetZ(5);
fun message(text) {
  msg.SetImage(Image.Text(text, 0.6, 0.62, 0.7));
  msg.SetX(cx - msg.GetImage().GetWidth() / 2); msg.SetY(Window.GetY() + sh - 50 * k);
}
Plymouth.SetMessageFunction(message);
"""

THEME = """[Plymouth Theme]
Name=Sofa
Description=Sofa box: the same as Sofa's loading screen
ModuleName=script

[script]
ImageDir=%(dir)s
ScriptFile=%(dir)s/sofa.script
"""


def write_plymouth(target, settings):
    os.makedirs(target, exist_ok=True)
    p = pieces(settings)
    for name in ("glow", "mark", "word", "track", "light"):
        p[name].save(os.path.join(target, name + ".png"))
    name_line = ""
    if p["name"] is not None:
        p["name"].save(os.path.join(target, "name.png"))
        name_line = 'name = place("name.png", cx, Window.GetY() + sh - 90 * k, 3);'
    elif os.path.exists(os.path.join(target, "name.png")):
        os.remove(os.path.join(target, "name.png"))
    r, g, b = [v / 255.0 for v in p["colors"].bg]
    with open(os.path.join(target, "sofa.script"), "w") as f:
        f.write(SCRIPT % {"r": r, "g": g, "b": b, "name": name_line})
    with open(os.path.join(target, "sofa.plymouth"), "w") as f:
        f.write(THEME % {"dir": target})


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "plymouth":
        write_plymouth(sys.argv[2], load(sys.argv[3] if len(sys.argv) > 3 else None))
    elif len(sys.argv) >= 2 and sys.argv[1] == "png":
        buf = io.BytesIO()
        render(load(sys.argv[2] if len(sys.argv) > 2 else None), (960, 540)).save(buf, "PNG")
        sys.stdout.buffer.write(buf.getvalue())
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
