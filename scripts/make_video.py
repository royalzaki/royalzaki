"""Kollajdakı şəkillərdən retro, kinematoqrafik video hazırlayır.

İstifadə: python3 scripts/make_video.py [kollaj.png] [nəticə.mp4]
"""
import math
import random
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "assets" / "collage.png"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "output" / "kuba_retro.mp4"

W, H, FPS = 1920, 1080, 24
BAR = 138  # 2.39:1 letterbox zolaqları
XFADE = 0.8
SR = 48000

TYPE_FONT = "/usr/share/fonts/truetype/freefont/FreeMonoBold.ttf"
TITLE_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
CREAM = (238, 226, 196)

# Kollajdakı sətirlər (y0, y1) və hər sətirdə şaquli ayırıcılar (x)
ROWS = [
    ((0, 199), [338, 666, 980, 1316]),
    ((204, 378), [338, 666, 980, 1316]),
    ((383, 558), [338, 666, 980, 1316]),
    ((562, 741), [338, 619, 965, 1316]),
    ((745, 940), [258, 540, 788, 1080, 1380]),
]

# Xronoloji ardıcıllıq: (kollajdakı indeks, müddət, hərəkət, alt yazı)
SHOTS = [
    (0, 6.0, "in", None),  # başlıq kartı
    (2, 4.0, "out", "KUBA · KARİB DƏNİZİ"),
    (3, 4.0, "right", "BİRAN · 1926"),
    (4, 4.0, "left", "ATA MÜLKÜ · ORİYENTE"),
    (5, 4.0, "in", "HAVANA UNİVERSİTETİ · 1945"),
    (7, 4.0, "right", "MONKADA KAZARMASINA HÜCUM · 1953"),
    (6, 4.5, "in", "«TARİX MƏNƏ BƏRAƏT VERƏCƏK» · 1953"),
    (8, 4.0, "left", "«QRANMA» YAXTASI · 1956"),
    (9, 4.0, "out", "SYERRA-MAESTRA · 1956–1958"),
    (10, 4.5, "in", "İNQİLABIN QƏLƏBƏSİ · 1959"),
    (1, 4.0, "out", "FİDEL KASTRO"),
    (11, 4.0, "right", "ÇE GEVARA İLƏ"),
    (12, 4.0, "left", "SSRİ İLƏ İTTİFAQ"),
    (13, 4.0, "right", "DONUZLAR KÖRFƏZİ · 1961"),
    (14, 4.0, "in", "DƏNİZ BLOKADASI · 1962"),
    (15, 4.0, "up", "RAKET BÖHRANI · OKTYABR 1962"),
    (16, 4.0, "in", "CON KENNEDİ · AĞ EV"),
    (17, 4.5, "out", "DÜNYA NÜVƏ MÜHARİBƏSİNİN ASTANASINDA"),
    (20, 4.0, "left", "SAVADLILIQ KAMPANİYASI"),
    (19, 4.0, "in", "PULSUZ SƏHİYYƏ"),
    (18, 4.0, "right", "XÜSUSİ DÖVR · 1990-CI İLLƏR"),
    (21, 4.0, "in", "BALSEROLAR · 1994"),
    (22, 4.0, "out", "HAVANA KÜÇƏLƏRİ"),
    (23, 4.5, "in", "SON İLLƏR"),
    (24, 4.5, "left", "VİDA · NOYABR 2016"),
    (25, 7.0, "out", None),  # son kart
]


def cut_tiles(img):
    tiles = []
    for (y0, y1), xs in ROWS:
        edges = [0] + xs + [img.width]
        for i in range(len(edges) - 1):
            x0 = edges[i] + (4 if i else 0)
            x1 = edges[i + 1] - 1
            tiles.append(img.crop((x0 + 2, y0 + 2, x1 - 2, y1 - 2)))
    return tiles


def to_169(tile):
    """Kəsib 16:9 edir və ekran ölçüsünə böyüdür."""
    w, h = tile.size
    if w / h > 16 / 9:
        nw = int(h * 16 / 9)
        tile = tile.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = int(w * 9 / 16)
        tile = tile.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    big = tile.resize((W * 5 // 4, H * 5 // 4), Image.LANCZOS)
    return big.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))


def ease(t):
    return 0.5 - 0.5 * math.cos(math.pi * min(max(t, 0), 1))


def kb_rect(motion, t, sw, sh):
    """Ken Burns: t∈[0,1] üçün mənbədə kəsiləcək düzbucaqlı."""
    e = ease(t)
    z0, z1 = {"in": (1.0, 1.22), "out": (1.22, 1.0)}.get(motion, (1.12, 1.12))
    z = z0 + (z1 - z0) * e
    cw, ch = sw / z, sh / z
    cx, cy = sw / 2, sh / 2
    span_x, span_y = (sw - cw) / 2, (sh - ch) / 2
    if motion == "left":
        cx += span_x * (1 - 2 * e)
    elif motion == "right":
        cx -= span_x * (1 - 2 * e)
    elif motion == "up":
        cy += span_y * (1 - 2 * e)
    return cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2


class Film:
    """Kadr titrəməsi, toz və cızıqlar."""

    def __init__(self, seed=7):
        self.rng = random.Random(seed)
        self.dx = self.dy = 0.0
        self.scratch = None

    def step(self):
        r = self.rng
        self.dx = self.dx * 0.7 + r.gauss(0, 0.9)
        self.dy = self.dy * 0.7 + r.gauss(0, 0.9)
        if self.scratch is None and r.random() < 0.02:
            self.scratch = [r.randint(200, W - 200), r.randint(6, 30)]
        elif self.scratch is not None:
            self.scratch[0] += r.randint(-3, 3)
            self.scratch[1] -= 1
            if self.scratch[1] <= 0:
                self.scratch = None

    def damage(self, draw):
        r = self.rng
        for _ in range(r.choice([0, 0, 0, 1, 2, 4])):
            x, y = r.randint(0, W), r.randint(BAR, H - BAR)
            s = r.randint(1, 4)
            c = r.choice([(20, 15, 10), (240, 235, 220)])
            draw.ellipse((x, y, x + s, y + s * r.randint(1, 3)), fill=c)
        if r.random() < 0.08:
            x, y = r.randint(0, W), r.randint(BAR, H - BAR)
            pts = [(x + r.randint(-12, 12), y + i * 6) for i in range(r.randint(3, 8))]
            draw.line(pts, fill=(25, 20, 15), width=1)
        if self.scratch:
            x = self.scratch[0]
            draw.line((x, BAR, x + r.randint(-2, 2), H - BAR), fill=(225, 220, 205), width=1)


def spaced(draw, xy, text, font, fill, spacing, anchor_center=True):
    widths = [draw.textlength(ch, font=font) for ch in text]
    total = sum(widths) + spacing * (len(text) - 1)
    x, y = xy
    if anchor_center:
        x -= total / 2
    for ch, w in zip(text, widths):
        draw.text((x, y), ch, font=font, fill=fill)
        x += w + spacing


def render_shot(base, motion, dur, caption, film, kind, fonts):
    n = int(round(dur * FPS))
    sw, sh = base.size
    frames = []
    for i in range(n):
        t = i / (n - 1)
        film.step()
        x0, y0, x1, y1 = kb_rect(motion, t, sw, sh)
        k = (x1 - x0) / W
        rect = (x0 + film.dx * k, y0 + film.dy * k, x1 + film.dx * k, y1 + film.dy * k)
        fr = base.transform((W, H), Image.EXTENT, rect, Image.BICUBIC)
        d = ImageDraw.Draw(fr)
        film.damage(d)
        d.rectangle((0, 0, W, BAR), fill=(0, 0, 0))
        d.rectangle((0, H - BAR, W, H), fill=(0, 0, 0))
        sec = i / FPS
        if caption:
            shown = caption[: max(0, int((sec - 0.5) * 22))]
            if shown:
                cur = "▌" if len(shown) < len(caption) and i % 6 < 3 else ""
                d.text((120, H - BAR + 46), shown + cur, font=fonts["type"], fill=CREAM)
        if kind == "title":
            a = ease((sec - 0.8) / 1.5)
            if a > 0:
                fr = title_card(fr, a, "KUBA", "İNQİLABIN XRONİKASI", fonts)
        elif kind == "end":
            a = ease((sec - 1.5) / 1.5)
            if a > 0:
                fr = title_card(fr, a, "1926 — 2016", "SON", fonts)
        frames.append(fr)
    return frames


def title_card(fr, alpha, big, small, fonts):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    a = int(255 * alpha)
    d.rectangle((0, BAR, W, H - BAR), fill=(0, 0, 0, int(110 * alpha)))
    spaced(d, (W / 2, H / 2 - 120), big, fonts["title"], (*CREAM, a), 28)
    d.line((W / 2 - 260, H / 2 + 30, W / 2 + 260, H / 2 + 30), fill=(*CREAM, a), width=2)
    spaced(d, (W / 2, H / 2 + 55), small, fonts["sub"], (*CREAM, a), 10)
    return Image.alpha_composite(fr.convert("RGBA"), layer).convert("RGB")


def leader(fonts, film):
    """Klassik kino lentinin geri sayımı: 3, 2, 1."""
    frames = []
    for num in (3, 2, 1):
        for i in range(FPS):
            film.step()
            fr = Image.new("RGB", (W, H), (150, 140, 120))
            d = ImageDraw.Draw(fr)
            cx, cy = W / 2 + film.dx, H / 2 + film.dy
            ang = -90 + 360 * i / FPS
            d.pieslice((cx - 700, cy - 700, cx + 700, cy + 700), -90, ang, fill=(110, 102, 88))
            d.line((0, cy, W, cy), fill=(30, 28, 25), width=3)
            d.line((cx, 0, cx, H), fill=(30, 28, 25), width=3)
            for r in (300, 340):
                d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(240, 235, 220), width=6)
            d.text((cx, cy), str(num), font=fonts["leader"], fill=(20, 18, 15), anchor="mm")
            film.damage(d)
            frames.append(fr)
    frames += [Image.new("RGB", (W, H), (0, 0, 0))] * 6
    return frames


def soundtrack(seconds, path):
    """Proyektor səsi + qramofon xışıltısı + melanxolik akkordlar."""
    n = int(seconds * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(3)
    hiss = np.convolve(rng.normal(0, 1, n), np.ones(12) / 12, "same") * 0.025
    clicks = np.zeros(n)
    idx = rng.choice(n, size=int(seconds * 9), replace=False)
    clicks[idx] = rng.uniform(0.15, 0.5, len(idx)) * rng.choice([-1, 1], len(idx))
    clicks = np.convolve(clicks, np.exp(-np.arange(60) / 8), "same") * 0.35
    proj = (np.sin(2 * np.pi * 24 * t) > 0.92).astype(float)
    proj = np.convolve(proj * rng.normal(0, 1, n), np.exp(-np.arange(200) / 30), "same") * 0.012

    # Dm – B♭ – F – A, hər akkord 6 saniyə
    chords = [[146.83, 174.61, 220.0], [116.54, 146.83, 174.61], [174.61, 220.0, 261.63], [110.0, 138.59, 164.81]]
    music = np.zeros(n)
    seg = 6.0
    for k in range(int(math.ceil(seconds / seg))):
        s, e = int(k * seg * SR), min(n, int((k + 1) * seg * SR + SR))
        tt = t[s:e] - k * seg
        env = np.minimum(1, tt / 1.5) * np.exp(-np.maximum(0, tt - seg) / 0.4)
        for f in chords[k % 4]:
            for det in (-0.7, 0.7):
                music[s:e] += np.sin(2 * np.pi * (f + det) * tt) * env * 0.05
            music[s:e] += np.sin(2 * np.pi * f / 2 * tt) * env * 0.03
    music *= 0.85 + 0.15 * np.sin(2 * np.pi * 0.5 * t)  # lent "vau-flatter"i
    lead_in = 3.25
    music *= np.clip((t - lead_in) / 2, 0, 1) * np.clip((seconds - t) / 4, 0, 1)
    mix = np.tanh((music + hiss + clicks + proj) * 1.4) * 0.8
    pcm = (np.stack([mix, np.roll(mix, 90)], 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def main():
    fonts = {
        "type": ImageFont.truetype(TYPE_FONT, 40),
        "title": ImageFont.truetype(TITLE_FONT, 150),
        "sub": ImageFont.truetype(TYPE_FONT, 44),
        "leader": ImageFont.truetype(TITLE_FONT, 420),
    }
    tiles = cut_tiles(Image.open(SRC).convert("RGB"))
    assert len(tiles) == 26, len(tiles)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    film = Film()

    # Səs əvvəlcədən lazımdır, ona görə ümumi uzunluğu qabaqcadan hesablayırıq
    nx = int(XFADE * FPS)
    n_leader = 3 * FPS + 6
    total = n_leader + sum(int(round(d * FPS)) for _, d, _, _ in SHOTS) - nx * (len(SHOTS) - 1)
    seconds = total / FPS
    wav = OUT.with_suffix(".wav")
    soundtrack(seconds, wav)

    vf = (
        "curves=r='0/0.07 0.5/0.56 1/0.95':g='0/0.05 0.5/0.50 1/0.90':b='0/0.03 0.5/0.40 1/0.78',"
        "eq=saturation=0.6:contrast=1.06:brightness='0.018*sin(2*PI*t*5)+0.012*random(1)':eval=frame,"
        "gblur=sigma=0.6,noise=alls=10:allf=t,vignette=angle=PI/4.2,format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
        "-i", str(wav),
        "-vf", vf, "-c:v", "libx264", "-preset", "fast", "-crf", "24", "-maxrate", "6M", "-bufsize", "12M",
        "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(OUT),
    ]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    # Keçid üçün yalnız son nx kadr yaddaşda saxlanılır
    tail = []

    def push(frames):
        tail.extend(frames)
        while len(tail) > nx:
            p.stdin.write(tail.pop(0).tobytes())

    push(leader(fonts, film))
    for si, (ti, dur, motion, cap) in enumerate(SHOTS):
        kind = "title" if si == 0 else "end" if si == len(SHOTS) - 1 else None
        frames = render_shot(to_169(tiles[ti]), motion, dur, cap, film, kind, fonts)
        if si:
            for j in range(nx):
                tail[j] = Image.blend(tail[j], frames[j], ease((j + 1) / (nx + 1)))
            frames = frames[nx:]
        if si == len(SHOTS) - 1:
            fade = int(2 * FPS)
            for j in range(fade):
                k = len(frames) - fade + j
                frames[k] = Image.blend(frames[k], Image.new("RGB", (W, H)), (j + 1) / fade)
        push(frames)
        print(f"kadr {si + 1}/{len(SHOTS)}", flush=True)
    for fr in tail:
        p.stdin.write(fr.tobytes())
    p.stdin.close()
    p.wait()
    wav.unlink()
    print(f"hazırdır: {OUT} ({seconds:.1f} s)")


if __name__ == "__main__":
    main()
