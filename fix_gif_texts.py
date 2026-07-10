"""Fix text placement in slot_story_v2_opt.gif without regenerating it.

Fixes (everything else stays pixel-identical):
  1. APUESTA pill: label + "$200 CLP" recentred, value resized to fit inside
     the pill instead of overflowing the right border. Applied to every frame
     (with shake-shift detection and win-screen dimming compensation).
  2. Win plaque: "50 GIROS GRATIS" resized + centred inside its gold box
     (frames 42-51 at final scale, frame 41 at the pop-in scale).
Also writes the same pill fix into frame_v2.png -> frame_v2_fixed.png.
"""

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageSequence

DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
SRC_GIF = "slot_story_v2_opt.gif"
OUT_GIF = "slot_story_v2_fixed.gif"

# full-res pill geometry (frame_v2.png, 1448x1086)
PILL_X0, PILL_X1 = 392, 623          # interior between gold borders
PILL_CX = (PILL_X0 + PILL_X1) / 2
PILL_TOP, PILL_BOT = 962, 1038       # interior between top/bottom borders
LABEL_CY, VALUE_CY = 981, 1019

# small-res patch region (500x375) with margin
REG = (130, 324, 220, 364)

WIN_START = 40                    # first win-screen (dark overlay) frame
POP_SCALES = {40: 223/310, 41: 331/310}   # plaque pop-in scales

def fit_font(draw, text, size, max_w):
    while size > 10:
        f = ImageFont.truetype(DEJAVU, size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 1
    return ImageFont.truetype(DEJAVU, 10)


def fix_pill(frame):
    """Erase APUESTA pill texts and redraw them centred (full-res frame).

    The pill is a stadium shape; erase only its interior (a rounded-rect
    mask) with the pill's own vertical gradient, sampled from the text-free
    margin column, so the gold border is untouched."""
    fixed = frame.copy()
    px = fixed.load()
    # vertical gradient from the text-free margin (x~397..404 is interior
    # for rows 978..1022; clamp outside that)
    grad = {}
    for y in range(978, 1023):
        strip = sorted((px[x, y] for x in range(396, 405)),
                       key=lambda c: c[0] + c[1] + c[2])
        grad[y] = strip[len(strip) // 2]
    for y in range(PILL_TOP, PILL_BOT + 1):
        grad.setdefault(y, grad[min(max(y, 978), 1022)])

    mask = Image.new("L", fixed.size, 0)
    r = (PILL_BOT - PILL_TOP) // 2
    ImageDraw.Draw(mask).rounded_rectangle(
        [PILL_X0, PILL_TOP, PILL_X1, PILL_BOT], r, fill=255)
    mpx = mask.load()
    for y in range(PILL_TOP, PILL_BOT + 1):
        c = grad[y]
        for x in range(PILL_X0, PILL_X1 + 1):
            if mpx[x, y]:
                px[x, y] = c

    # the old label/value overlapped the pill's gold borders; repair them:
    # 1. top border + strip above it: the old label poked above the pill, so
    #    wipe anything that differs from the row's text-free colour at x=600
    for y in range(942, PILL_TOP):
        ref = px[600, y]
        for x in range(442, 588):
            c = px[x, y]
            if abs(c[0]-ref[0]) + abs(c[1]-ref[1]) + abs(c[2]-ref[2]) > 90:
                px[x, y] = ref
    # 2. bottom border straight segment: retile from the GANANCIA pill's
    #    identical border (clean columns x 850..868)
    for y in range(1036, 1053):
        strip = sorted((px[x, y] for x in range(850, 869)),
                       key=lambda c: c[0] + c[1] + c[2])
        c = strip[len(strip) // 2]
        for x in range(424, 592):
            px[x, y] = c
    # 3. right cap: mirror the clean left cap (pill is symmetric)
    for y in range(1034, 1053):
        for x in range(592, PILL_X1 + 2):
            px[x, y] = px[PILL_X0 + (PILL_X1 - x), y]

    d = ImageDraw.Draw(fixed)
    fL = fit_font(d, "APUESTA", 34, (PILL_X1 - PILL_X0) - 40)
    d.text((PILL_CX, LABEL_CY), "APUESTA", font=fL, fill=(250, 250, 250),
           anchor="mm", stroke_width=2, stroke_fill=(10, 18, 42))
    fV = fit_font(d, "$200 CLP", 52, (PILL_X1 - PILL_X0) - 36)
    d.text((PILL_CX, VALUE_CY), "$200 CLP", font=fV, fill=(246, 199, 46),
           anchor="mm", stroke_width=2, stroke_fill=(84, 62, 6))
    return fixed


def fix_plaque(f51):
    """Return (patch, patch_box): the corrected prize-box band of frame 51.

    The old text overflowed past the gold box on both sides, so erase the
    whole horizontal band across the plaque, then redraw box + text."""
    px = f51.load()
    gold = lambda p: p[0] > 170 and 120 < p[1] < 230 and p[2] < 110
    xs = [x for x in range(100, 400)
          if gold(px[x, 205]) or gold(px[x, 240])]
    bx0, bx1 = min(xs), max(xs)
    gold_c = px[(bx0 + bx1) // 2, 204]
    fixed = f51.copy()
    px = fixed.load()
    for y in range(201, 245):               # clear band incl. overflow scraps
        for x in range(112, 391):
            px[x, y] = (7, 15, 36)
    d = ImageDraw.Draw(fixed)
    d.rounded_rectangle([bx0, 204, bx1, 241], 10, fill=(11, 24, 56),
                        outline=gold_c, width=2)
    f = fit_font(d, "50 GIROS GRATIS", 26, (bx1 - bx0) - 30)
    d.text(((bx0 + bx1) / 2, 222), "50 GIROS GRATIS", font=f,
           fill=(246, 199, 46), anchor="mm",
           stroke_width=1, stroke_fill=(60, 44, 5))
    box = (112, 199, 391, 246)
    return fixed.crop(box), box


def detect_dx(cur, ref_reg, reg):
    """Find the horizontal shake offset of the bar in `cur` vs the reference."""
    best, bdx = None, 0
    for dx in range(-4, 5):
        c = cur.crop((reg[0] + dx, reg[1], reg[2] + dx, reg[3]))
        sad = sum(abs(a - b) for a, b in zip(c.tobytes(), ref_reg.tobytes()))
        if best is None or sad < best:
            best, bdx = sad, dx
    return bdx


def main():
    full = Image.open("frame_v2.png").convert("RGB")
    full_fixed = fix_pill(full)
    full_fixed.save("frame_v2_fixed.png")

    small_o = full.resize((500, 375), Image.LANCZOS)
    small_f = full_fixed.resize((500, 375), Image.LANCZOS)
    reg_o = small_o.crop(REG)
    reg_f = small_f.crop(REG)
    ob, fb = reg_o.tobytes(), reg_f.tobytes()

    gif = Image.open(SRC_GIF)
    durs = []
    for i in range(gif.n_frames):
        gif.seek(i)
        durs.append(gif.info.get("duration", 55))
    gif.seek(0)
    frames = [f.convert("RGB") for f in ImageSequence.Iterator(gif)]

    plaque_patch, pbox = fix_plaque(frames[51])

    out = []
    for i, fr in enumerate(frames):
        cur = fr.copy()
        dx = detect_dx(cur, reg_o, REG)
        box = (REG[0] + dx, REG[1], REG[2] + dx, REG[3])
        creg = cur.crop(box)
        cb = bytearray(creg.tobytes())
        if i >= WIN_START:
            # win-screen frame: the scene sits under a 120-alpha dark overlay
            # (x0.529) with additive light rays. Rebuild: fixed art under the
            # same dim, this frame's rays re-added on top.
            A = 0.529
            for k in range(len(cb)):
                ray = max(0.0, cb[k] - ob[k]*A)
                cb[k] = max(0, min(255, int(fb[k]*A + ray)))
        else:
            for k in range(0, len(cb), 3):
                m = (abs(fb[k]-ob[k]) + abs(fb[k+1]-ob[k+1])
                     + abs(fb[k+2]-ob[k+2]))
                if m < 30:  # ignore subtle diffs: they only add speckle
                    continue
                for j in (k, k+1, k+2):
                    cb[j] = max(0, min(255, cb[j] + fb[j] - ob[j]))
        cur.paste(Image.frombytes("RGB", (box[2]-box[0], box[3]-box[1]),
                                  bytes(cb)), box)
        # plaque prize text (pop-in frames hold the plaque at other scales;
        # measured from the gold border widths: f40 223px, f41 331px, 310 final)
        if 42 <= i <= 51:
            cur.paste(plaque_patch, (pbox[0], pbox[1]))
        elif i in POP_SCALES:
            sc = POP_SCALES[i]
            pcx, pcy = 250, 186             # plaque centre (same every frame)
            w = int(round((pbox[2]-pbox[0]) * sc))
            h = int(round((pbox[3]-pbox[1]) * sc))
            sp = plaque_patch.resize((w, h), Image.LANCZOS)
            x0 = int(round(pcx + (pbox[0]-pcx) * sc))
            y0 = int(round(pcy + (pbox[1]-pcy) * sc))
            cur.paste(sp, (x0, y0))
        out.append(cur)

    # re-quantize with the ORIGINAL gif's global palette and no dithering:
    # untouched pixels are already exact palette colours, so they map back to
    # their original indices — zero quality loss outside the patched areas
    gif.seek(0)
    pal_colors = list(gif.palette.colors)          # [(r,g,b), ...] in order
    ncol = len(pal_colors)
    cmap = {c: i for i, c in enumerate(pal_colors)}
    def nearest(c):
        if c not in cmap:
            cmap[c] = min(range(ncol), key=lambda i: (pal_colors[i][0]-c[0])**2
                          + (pal_colors[i][1]-c[1])**2 + (pal_colors[i][2]-c[2])**2)
        return cmap[c]
    flat_pal = [v for c in pal_colors for v in c]
    qs = []
    for f in out:
        idx = bytes(nearest(c) for c in f.getdata())
        q = Image.frombytes("P", f.size, idx)
        q.putpalette(flat_pal)
        qs.append(q)
    # frame-diff transparency (what gifsicle does): pixels identical to the
    # previous frame become the transparent index, shrinking the file
    TR = ncol
    base_pal = qs[0].getpalette()[:TR * 3] + [0, 0, 0]
    opt = [qs[0]]
    prev = qs[0].tobytes()
    for q in qs[1:]:
        cur = q.tobytes()
        diff = bytes(TR if c == p else c for c, p in zip(cur, prev))
        f = Image.frombytes("P", q.size, diff)
        f.putpalette(base_pal)
        opt.append(f)
        prev = cur
    opt[0].save(OUT_GIF, save_all=True, append_images=opt[1:], duration=durs,
                loop=1, optimize=False, disposal=1, transparency=TR)
    print("saved", OUT_GIF, len(opt), "frames")


if __name__ == "__main__":
    main()
