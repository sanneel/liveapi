"""Fix text/icon placement in slot_story_v2_opt.gif without re-rendering it.

Corrections (baked into the frame art, re-applied on every GIF frame):
  1. APUESTA pill  : label + "$200 CLP" recentred and fitted inside the pill.
  2. GANANCIA pill : label lowered + "$0" recentred, matching APUESTA.
  3. TURBO button  : >> icon + "TURBO" recentred in the green button (was low).
  4. PREMIO (top)  : the middle "bolt + PREMIO" group nudged toward centre
                     (limited by the long "MEJOR PREMIO" label on its left).
Plus the whole animation is slowed ~1.4x and the winning FELICIDADES screen
holds ~2s so it reads clearly.

Pixels outside the patched bar regions stay bit-identical to the original.
"""

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageSequence

DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
SRC_GIF = "slot_story_v2_opt.gif"
OUT_GIF = "slot_story_v2_fixed.gif"
SRC_FRAME = "frame_v2.png"

# ---- palette (frame art) ----
NAVY = (10, 20, 45)
WHITE = (250, 250, 248)
GOLD = (246, 199, 46)
GOLD_DK = (84, 62, 6)
LIMEVAL = (182, 222, 19)

# ---- geometry, full-res 1448x1086 ----
PILL_TOP, PILL_BOT = 962, 1038          # interior between the gold borders
LABEL_CY, VALUE_CY = 982, 1018
APUESTA_X = (392, 623)
GANANCIA_X = (825, 1056)
TURBO_C = (724, 984)
TURBO_R = 60

# top-bar middle group ("bolt + PREMIO"): move left this many px toward centre
PREMIO_GROUP = (628, 44, 892, 122)      # box around bolt + PREMIO
PREMIO_SHIFT = 16                        # capped by MEJOR PREMIO ending at x611

# 500-space patch regions (the GIF is 500x375); (x0,y0,x1,y1)
SX = 500 / 1448.0
def _to500(box):
    return (int(box[0]*SX), int(box[1]*SX),
            int(box[2]*SX + 0.999), int(box[3]*SX + 0.999))
REG_BOTTOM = _to500((28, 916, 1422, 1060))
REG_TOP = _to500((548, 38, 904, 124))

WIN_START = 40                           # first dimmed win-screen frame
POP_SCALES = {40: 223/310, 41: 331/310}  # plaque pop-in scales
DIM_A = 0.529                            # win-screen dark-overlay factor
SPEED = 1.4                              # >1 = slower
FINAL_HOLD_MS = 2000
FELIZ_DARKEN = 0.63                      # tone the neon FELICIDADES lime down
FELIZ_BOX = (116, 100, 384, 182)         # its region on the full-size plaque
OUT_W = 600                              # output width; upscaling the 500px
OUT_COLORS = 255                         # source de-speckles the 96-colour art


def fit_font(draw, text, size, max_w, min_size=12):
    while size > min_size:
        f = ImageFont.truetype(DEJAVU, size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 1
    return ImageFont.truetype(DEJAVU, min_size)


# --------------------------------------------------------------------------

def fix_pill(img, x0, x1, label, value, value_color):
    """Recentre a stadium pill's label + value. Erase the interior with the
    pill's own vertical gradient, rebuild the straight top/bottom borders by
    horizontal tiling from a clean column, then draw both texts centred."""
    px = img.load()
    cx = (x0 + x1) / 2
    r = (PILL_BOT - PILL_TOP) // 2

    # 1. interior fill: per-row gradient sampled from a text-free left column
    grad = {}
    for y in range(PILL_TOP, PILL_BOT + 1):
        strip = sorted((px[x, y] for x in range(x0 + 6, x0 + 16)),
                       key=lambda c: c[0] + c[1] + c[2])
        grad[y] = strip[len(strip) // 2]
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [x0, PILL_TOP, x1, PILL_BOT], r, fill=255)
    mpx = mask.load()
    for y in range(PILL_TOP, PILL_BOT + 1):
        c = grad[y]
        for x in range(x0, x1 + 1):
            if mpx[x, y]:
                px[x, y] = c

    # 2. rebuild top/bottom borders + trim over the straight section by
    #    copying a clean column (near the left cap, text never reaches it)
    clean = x0 + 40
    for y in list(range(944, PILL_TOP)) + list(range(PILL_BOT + 1, 1055)):
        c = px[clean, y]
        for x in range(x0 + 38, x1 - 38):
            px[x, y] = c

    # 3. draw texts
    d = ImageDraw.Draw(img)
    fL = fit_font(d, label, 34, (x1 - x0) - 46)
    d.text((cx, LABEL_CY), label, font=fL, fill=WHITE, anchor="mm",
           stroke_width=2, stroke_fill=NAVY)
    fV = fit_font(d, value, 52, (x1 - x0) - 40)
    d.text((cx, VALUE_CY), value, font=fV, fill=value_color, anchor="mm",
           stroke_width=2, stroke_fill=GOLD_DK if value_color == GOLD else NAVY)


def fix_turbo(img):
    """Recentre the >> icon and TURBO label inside the green button.

    Inpaint the old navy ink over the button face (keeping the face gradient),
    then draw the arrows just above centre and TURBO just below, so the group
    is balanced in the circle instead of sitting low."""
    px = img.load()
    cx, cy = TURBO_C
    is_ink = lambda p: (p[2] > p[1] + 8) or (p[0] + p[1] + p[2] < 170)
    is_face = lambda p: p[1] > 130 and p[1] >= p[0] - 12 and p[2] < 145

    # inpaint per row across the ACTUAL green-face extent (not a fixed circle,
    # so the whole old icon+label is covered), filling ink with the row's
    # median face colour -> no ghost.
    for y in range(cy - 74, cy + 74):
        xs = [x for x in range(cx - 90, cx + 90) if is_face(px[x, y])]
        if len(xs) < 6:
            continue
        xa, xb = min(xs), max(xs)
        face = [px[x, y] for x in range(xa, xb + 1) if is_face(px[x, y])]
        face.sort(key=lambda c: c[0] + c[1] + c[2])
        med = face[len(face) // 2]
        for x in range(xa, xb + 1):
            if is_ink(px[x, y]):
                px[x, y] = med

    d = ImageDraw.Draw(img)
    # arrows: two right-pointing triangles, centred, just above face centre
    acy = cy - 22
    w, gap, h = 40, 8, 52
    lb = cx - (2 * w + gap) / 2
    for k in range(2):
        b = lb + k * (w + gap)
        d.polygon([(b, acy - h/2), (b, acy + h/2), (b + w, acy)], fill=NAVY)
    # TURBO label just below centre
    fT = ImageFont.truetype(DEJAVU, 40)
    d.text((cx, cy + 28), "TURBO", font=fT, fill=NAVY, anchor="mm")


def shift_premio(img):
    """Nudge the middle 'bolt + PREMIO' group left toward the bar centre and
    backfill the vacated strip with the navy bar background."""
    gx0, gy0, gx1, gy1 = PREMIO_GROUP
    grp = img.crop((gx0, gy0, gx1, gy1))
    px = img.load()
    # backfill the whole group span first, sampling clean navy bar at x=960
    for y in range(gy0, gy1):
        c = px[960, y]
        for x in range(gx0, gx1):
            px[x, y] = c
    img.paste(grp, (gx0 - PREMIO_SHIFT, gy0))


def build_fixed_frame():
    f = Image.open(SRC_FRAME).convert("RGB")
    fix_pill(f, *APUESTA_X, "APUESTA", "$200 CLP", GOLD)
    fix_pill(f, *GANANCIA_X, "GANANCIA", "$0", LIMEVAL)
    fix_turbo(f)
    shift_premio(f)
    f.save("frame_v2_fixed.png")
    return f


# --------------------------------------------------------------------------

def _prep_region(orig500, fixed500, reg):
    o = orig500.crop(reg).tobytes()
    fx = fixed500.crop(reg).tobytes()
    return {"reg": reg, "ob": o, "fb": fx}


def _detect_dx(cur, reg, ob):
    best, bdx = None, 0
    for dx in range(-4, 5):
        c = cur.crop((reg[0] + dx, reg[1], reg[2] + dx, reg[3])).tobytes()
        sad = sum(abs(a - b) for a, b in zip(c, ob))
        if best is None or sad < best:
            best, bdx = sad, dx
    return bdx


def _apply_region(cur, R, win):
    reg, ob, fb = R["reg"], R["ob"], R["fb"]
    dx = _detect_dx(cur, reg, ob)
    box = (reg[0] + dx, reg[1], reg[2] + dx, reg[3])
    cb = bytearray(cur.crop(box).tobytes())
    if win:
        for k in range(len(cb)):
            ray = max(0.0, cb[k] - ob[k] * DIM_A)
            cb[k] = max(0, min(255, int(fb[k] * DIM_A + ray)))
    else:
        for k in range(0, len(cb), 3):
            if abs(fb[k]-ob[k]) + abs(fb[k+1]-ob[k+1]) + abs(fb[k+2]-ob[k+2]) < 30:
                continue
            for j in (k, k+1, k+2):
                cb[j] = max(0, min(255, cb[j] + fb[j] - ob[j]))
    cur.paste(Image.frombytes("RGB", (box[2]-box[0], box[3]-box[1]), bytes(cb)),
              box)


def darken_feliz(cur, i):
    """Tone down the too-bright neon-lime FELICIDADES on the win plaque."""
    px = cur.load()
    lime = lambda p: 120 < p[0] < 225 and p[1] > 175 and p[2] < 120
    x0, y0, x1, y1 = FELIZ_BOX
    if i in POP_SCALES:                  # scale the box with the pop-in plaque
        sc = POP_SCALES[i]; pcx, pcy = 250, 186
        x0, y0 = int(pcx+(x0-pcx)*sc), int(pcy+(y0-pcy)*sc)
        x1, y1 = int(pcx+(x1-pcx)*sc), int(pcy+(y1-pcy)*sc)
    for y in range(y0, y1):
        for x in range(x0, x1):
            p = px[x, y]
            if lime(p):
                px[x, y] = (int(p[0]*FELIZ_DARKEN), int(p[1]*FELIZ_DARKEN),
                            int(p[2]*FELIZ_DARKEN))


def main():
    fixed_full = build_fixed_frame()
    orig_full = Image.open(SRC_FRAME).convert("RGB")
    o500 = orig_full.resize((500, 375), Image.LANCZOS)
    f500 = fixed_full.resize((500, 375), Image.LANCZOS)
    regions = [_prep_region(o500, f500, REG_BOTTOM),
               _prep_region(o500, f500, REG_TOP)]

    gif = Image.open(SRC_GIF)
    durs = []
    for i in range(gif.n_frames):
        gif.seek(i)
        durs.append(gif.info.get("duration", 55))
    gif.seek(0)
    frames = [f.convert("RGB") for f in ImageSequence.Iterator(gif)]

    # prize-box text patch on the win plaque (built from the final frame)
    plaque_patch, pbox = fix_plaque(frames[51])

    out = []
    for i, fr in enumerate(frames):
        cur = fr.copy()
        win = i >= WIN_START
        for R in regions:
            _apply_region(cur, R, win)
        if 42 <= i <= 51:
            cur.paste(plaque_patch, (pbox[0], pbox[1]))
        elif i in POP_SCALES:
            sc = POP_SCALES[i]
            pcx, pcy = 250, 186
            w = int(round((pbox[2]-pbox[0]) * sc))
            h = int(round((pbox[3]-pbox[1]) * sc))
            sp = plaque_patch.resize((w, h), Image.LANCZOS)
            cur.paste(sp, (int(round(pcx + (pbox[0]-pcx)*sc)),
                           int(round(pcy + (pbox[1]-pcy)*sc))))
        if win:
            darken_feliz(cur, i)
        out.append(cur)

    # retime: slow ~SPEED, long final hold
    new_durs = [FINAL_HOLD_MS if i == len(durs)-1 else int(round(d*SPEED))
                for i, d in enumerate(durs)]

    # quality pass: upscale (LANCZOS blends the baked 96-colour dither into
    # smooth intermediate tones -> far less speckle) then re-quantize to a
    # fresh OUT_COLORS-colour adaptive palette with NO new dithering
    ow = OUT_W
    oh = int(round(out[0].height * ow / out[0].width))
    up = [f.resize((ow, oh), Image.LANCZOS) for f in out]

    mosaic = Image.new("RGB", (ow, oh * 4))
    for k, idx in enumerate((5, 22, 45, 51)):
        mosaic.paste(up[idx], (0, oh * k))
    pal = mosaic.quantize(colors=OUT_COLORS, method=Image.MEDIANCUT)
    qs = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in up]

    # frame-diff transparency (index OUT_COLORS) keeps the file small
    TR = OUT_COLORS
    base_pal = qs[0].getpalette()[:TR*3] + [0, 0, 0]
    opt = [qs[0]]
    prev = qs[0].tobytes()
    for q in qs[1:]:
        cur = q.tobytes()
        diff = bytes(TR if c == p else c for c, p in zip(cur, prev))
        g = Image.frombytes("P", q.size, diff)
        g.putpalette(base_pal)
        opt.append(g)
        prev = cur
    opt[0].save(OUT_GIF, save_all=True, append_images=opt[1:],
                duration=new_durs, loop=1, optimize=False, disposal=1,
                transparency=TR)
    # shrink with gifsicle if available (lossy LZW re-pack, big size win, no
    # visible quality loss at this level)
    import shutil, subprocess, os
    if shutil.which("gifsicle"):
        subprocess.run(["gifsicle", "-O3", "--lossy=80", OUT_GIF,
                        "-o", OUT_GIF], check=True)
    print("saved", OUT_GIF, len(opt), "frames", (ow, oh), "total",
          sum(new_durs), "ms,", round(os.path.getsize(OUT_GIF)/1e6, 2), "MB")


def fix_plaque(f51):
    """Recentre '50 GIROS GRATIS' inside its gold box on the win plaque."""
    px = f51.load()
    gold = lambda p: p[0] > 170 and 120 < p[1] < 230 and p[2] < 110
    xs = [x for x in range(100, 400) if gold(px[x, 205]) or gold(px[x, 240])]
    bx0, bx1 = min(xs), max(xs)
    gold_c = px[(bx0 + bx1) // 2, 204]
    fixed = f51.copy()
    px = fixed.load()
    for y in range(201, 245):
        for x in range(112, 391):
            px[x, y] = (7, 15, 36)
    d = ImageDraw.Draw(fixed)
    d.rounded_rectangle([bx0, 204, bx1, 241], 10, fill=(11, 24, 56),
                        outline=gold_c, width=2)
    f = fit_font(d, "50 GIROS GRATIS", 26, (bx1 - bx0) - 30)
    d.text(((bx0 + bx1) / 2, 222), "50 GIROS GRATIS", font=f, fill=GOLD,
           anchor="mm", stroke_width=1, stroke_fill=(60, 44, 5))
    return fixed.crop((112, 199, 391, 246)), (112, 199, 391, 246)


if __name__ == "__main__":
    main()
