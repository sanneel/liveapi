"""
slot_two_spin.py — JugaBet two-spin story GIF:
  SPIN 1 -> 3 bombs on the payline -> EXPLOSION (flash, burst, shake)
  SPIN 2 -> 7 7 7 on the payline  -> Gates-of-Olympus-style WIN screen -> hold

Assets expected: frame_v2.png, divider*.png, sym_seven.png, sym_bolt.png,
sym_bomb.png, sym_coin.png
Fonts: uses the JugaBet brand fonts from ./fonts when available, falls back
to DejaVu.
"""

import math, os, random
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FRAME_PATH = "frame_v2.png"
PRIZE_TEXT = "50 GIROS GRATIS"   # <- variable prize line
SYMBOLS = {"seven": "sym_seven.png", "bolt": "sym_bolt.png", "bomb": "sym_bomb.png"}

REELS = [(185,205,315,693),(545,205,315,693),(905,205,330,693)]
ROWS = 3
OVERLAYS = [("divider1_col0.png",185,405),("divider1_col1.png",545,405),("divider1_col2.png",905,405),
            ("divider2_col0.png",185,659),("divider2_col1.png",545,659),("divider2_col2.png",905,659)]

RESULT1 = [["seven","bomb","bolt"],["bolt","bomb","seven"],["seven","bomb","bolt"]]
RESULT2 = [["bolt","seven","bomb"],["bomb","seven","bolt"],["bolt","seven","bomb"]]

STOPS1, STOPS2   = [10,13,16], [10,13,17]
EXPLOSION_FRAMES = 5
WIN_FRAMES       = 12
STRIP_LEN        = 16
FRAME_MS         = 55
FINAL_WIDTH      = 500
GIF_COLORS       = 96
OUT              = "slot_story_v2.gif"

LIME, GOLD, NAVY = (182,222,19), (244,196,48), (10,20,45)
GOLD_LIGHT, GOLD_DARK = (255,232,150), (120,88,8)
WHITE = (250,249,248)

# --- bottom control bar (drawn by the script over the frame's own bar) ------
BET_TEXT = "$200 CLP"
WIN_TEXT = "$0"
BAR_X0, BAR_Y0, BAR_X1, BAR_Y1 = 84, 946, 1364, 1054
BAR_CY  = (BAR_Y0+BAR_Y1)//2                 # common centre line for controls
TURBO_C = (723, 988)                          # matches the turbo_pulse ring

# ---------------------------------------------------------------- fonts ----

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

def _font_path(*candidates):
    for c in candidates:
        p = os.path.join(_HERE, "fonts", c)
        if os.path.exists(p):
            return p
    return _DEJAVU

FONT_DISPLAY = _font_path("Jugabet-BlackItalic.ttf")          # big headlines
FONT_HEAVY   = _font_path("RobotoCondensed-ExtraBold.ttf")    # sub-lines / prize
FONT_BODY    = _font_path("RobotoCondensed-Regular.ttf",
                          "RobotoCondensed-ExtraBold.ttf")    # small caption

def font(path, size):
    return ImageFont.truetype(path, size)

def fit_font(draw, text, path, size, max_width, min_size=24):
    """Largest font <= size whose rendered text fits max_width."""
    while size > min_size:
        f = font(path, size)
        if draw.textlength(text, font=f) <= max_width:
            return f
        size -= 2
    return font(path, min_size)

def tracked_text(draw, xy, text, f, fill, tracking=0, anchor="mm",
                 stroke_width=0, stroke_fill=None):
    """Centered text with letter-spacing (tracking in px between glyphs)."""
    if tracking <= 0:
        draw.text(xy, text, font=f, fill=fill, anchor=anchor,
                  stroke_width=stroke_width, stroke_fill=stroke_fill)
        return
    widths = [draw.textlength(ch, font=f) for ch in text]
    total = sum(widths) + tracking*(len(text)-1)
    x = xy[0] - total/2
    for ch, w in zip(text, widths):
        draw.text((x + w/2, xy[1]), ch, font=f, fill=fill, anchor="mm",
                  stroke_width=stroke_width, stroke_fill=stroke_fill)
        x += w + tracking

# ------------------------------------------------------- bottom bar --------

def _round_grad(size, radius, top, bottom):
    """Rounded rectangle filled with a vertical gradient, as an RGBA image."""
    w,h = size
    grad = Image.new("RGBA",(w,h))
    gd = ImageDraw.Draw(grad)
    for y in range(h):
        t = y/max(1,h-1)
        c = tuple(int(top[i]+(bottom[i]-top[i])*t) for i in range(3))+(255,)
        gd.line([(0,y),(w,y)],fill=c)
    mask = Image.new("L",(w,h),0)
    ImageDraw.Draw(mask).rounded_rectangle([0,0,w-1,h-1],radius,fill=255)
    grad.putalpha(mask)
    return grad


def _orb(ov, d, cx, cy, r):
    """Glossy lime orb with gold rim."""
    d.ellipse([cx-r,cy-r,cx+r,cy+r],fill=(120,160,10,255),outline=GOLD+(255,),width=4)
    d.ellipse([cx-r+6,cy-r+6,cx+r-6,cy+r-6],fill=LIME+(255,))
    hl = Image.new("RGBA",ov.size,(0,0,0,0))
    ImageDraw.Draw(hl).ellipse([cx-r*0.5,cy-r*0.75,cx+r*0.5,cy-r*0.2],
                               fill=(255,255,255,80))
    ov.alpha_composite(hl.filter(ImageFilter.GaussianBlur(4)))


def _square_btn(ov, d, cx, cy, s=72, r=14):
    ov.alpha_composite(_round_grad((s,s),r,(26,48,102),(10,22,54)),
                       (int(cx-s/2),int(cy-s/2)))
    d.rounded_rectangle([cx-s/2,cy-s/2,cx+s/2,cy+s/2],r,
                        outline=GOLD+(255,),width=4)


def _value_pill(ov, d, x0, x1, cy, label, value):
    """Navy pill with a small tracked label on top and a gold value below,
    both centred — replaces the frame's baked-in APUESTA/GANANCIA pills."""
    h = 92
    ov.alpha_composite(_round_grad((x1-x0,h),h//2,(22,42,92),(8,18,46)),
                       (x0,cy-h//2))
    d.rounded_rectangle([x0,cy-h//2,x1,cy+h//2],h//2,outline=GOLD+(255,),width=5)
    cx = (x0+x1)//2
    tracked_text(d,(cx,cy-21),label,font(FONT_HEAVY,30),WHITE+(255,),tracking=5)
    fV = fit_font(d,value,FONT_HEAVY,50,(x1-x0)-70)
    d.text((cx,cy+19),value,font=fV,fill=GOLD+(255,),anchor="mm",
           stroke_width=2,stroke_fill=(60,44,4,255))


def draw_bottom_bar(cv):
    """Repaint the control bar: -/+ | orb | APUESTA pill | TURBO | GANANCIA
    pill | orb | menu buttons — everything centred on one line."""
    ov = Image.new("RGBA",cv.size,(0,0,0,0))
    d  = ImageDraw.Draw(ov)
    cy = BAR_CY

    # bar background (covers the frame's baked-in texts)
    ov.alpha_composite(_round_grad((BAR_X1-BAR_X0,BAR_Y1-BAR_Y0),26,
                                   (18,34,76),(6,14,38)),(BAR_X0,BAR_Y0))
    d.rounded_rectangle([BAR_X0,BAR_Y0,BAR_X1,BAR_Y1],26,
                        outline=GOLD+(255,),width=5)
    d.rounded_rectangle([BAR_X0+9,BAR_Y0+9,BAR_X1-9,BAR_Y1-9],20,
                        outline=GOLD_LIGHT+(90,),width=2)

    # left: bet - / +
    fG = font(FONT_HEAVY,46)
    for cx,gl in ((138,"−"),(224,"+")):
        _square_btn(ov,d,cx,cy)
        d.text((cx,cy-2),gl,font=fG,fill=WHITE+(255,),anchor="mm")

    _orb(ov,d,302,cy,34)
    _value_pill(ov,d,352,660,cy,"APUESTA",BET_TEXT)
    _value_pill(ov,d,788,1096,cy,"GANANCIA",WIN_TEXT)
    _orb(ov,d,1146,cy,34)

    # right: autoplay + menu squares
    _square_btn(ov,d,1230,cy)
    d.arc([1230-20,cy-20,1230+20,cy+20],start=300,end=210,
          fill=WHITE+(255,),width=5)
    d.polygon([(1230+22,cy-16),(1230+8,cy-16),(1230+17,cy-1)],fill=WHITE+(255,))
    _square_btn(ov,d,1316,cy)
    for k in (-14,0,14):
        d.line([(1316-18,cy+k),(1316+18,cy+k)],fill=WHITE+(255,),width=5)

    # centre: TURBO button (drawn last so it sits on top of the bar)
    tx,ty = TURBO_C
    d.ellipse([tx-86,ty-86,tx+86,ty+86],fill=GOLD+(255,))
    d.ellipse([tx-78,ty-78,tx+78,ty+78],fill=(150,190,14,255))
    d.ellipse([tx-70,ty-70,tx+70,ty+70],fill=LIME+(255,))
    hl = Image.new("RGBA",cv.size,(0,0,0,0))
    ImageDraw.Draw(hl).ellipse([tx-40,ty-60,tx+40,ty-30],fill=(255,255,255,60))
    ov.alpha_composite(hl.filter(ImageFilter.GaussianBlur(6)))
    d = ImageDraw.Draw(ov)
    for ox in (-26,6):                       # fast-forward icon, above centre
        d.polygon([(tx+ox,ty-36),(tx+ox,ty+4),(tx+ox+26,ty-16)],
                  fill=NAVY+(255,))
    tracked_text(d,(tx,ty+32),"TURBO",font(FONT_HEAVY,27),NAVY+(255,),tracking=3)

    cv.alpha_composite(ov)
    return cv

# ---------------------------------------------------------------------------

def ease(t): return 1-(1-t)**3


def load_cells():
    cells = {}
    for name, path in SYMBOLS.items():
        img = Image.open(path).convert("RGBA")
        out = {}
        for (_,_,rw,rh) in REELS:
            ch = rh//ROWS
            key = (rw,ch)
            if key in out: continue
            s = img.copy(); pad = int(min(rw,ch)*0.10)
            s.thumbnail((rw-2*pad, ch-2*pad), Image.LANCZOS)
            cell = Image.new("RGBA",(rw,ch),(0,0,0,0))
            cell.paste(s,((rw-s.width)//2,(ch-s.height)//2),s)
            out[key]=cell
        cells[name]=out
    return cells


def strip_for(rw, ch, cells, result_col):
    names = list(SYMBOLS)
    seq = [random.choice(names) for _ in range(STRIP_LEN-ROWS)] + result_col
    st = Image.new("RGBA",(rw,ch*len(seq)),(0,0,0,0))
    for i,n in enumerate(seq):
        st.alpha_composite(cells[n][(rw,ch)],(0,i*ch))
    return st


def spin_frames(frame, overlays, cells, result, stops):
    """Yield frames of one spin."""
    reels=[]
    for (rx,ry,rw,rh),col in zip(REELS,result):
        ch=rh//ROWS
        st=strip_for(rw,ch,cells,col)
        reels.append(dict(rect=(rx,ry,rw,rh),strip=st,final=st.height-rh,ch=ch))
    out=[]
    for f in range(max(stops)+1):
        cv=frame.copy()
        for r,stop in zip(reels,stops):
            rx,ry,rw,rh=r["rect"]
            if f>=stop: off,spd=r["final"],0.0
            else:
                t,t2=ease(f/stop),ease(min((f+1)/stop,1.0))
                off,spd=t*r["final"],(t2-t)*r["final"]
            crop=r["strip"].crop((0,int(off),rw,int(off)+rh))
            if spd>r["ch"]*0.6:
                crop=crop.filter(ImageFilter.GaussianBlur(min(spd/25,6)))
            cv.alpha_composite(crop,(rx,ry))
        for ov,ox,oy in overlays: cv.alpha_composite(ov,(ox,oy))
        out.append(cv)
    return out


def explosion_frames(base):
    """Bombs on the payline blow up: flash, expanding burst, particles, shake."""
    centers=[(rx+rw//2, 205+693//2) for (rx,ry,rw,rh) in REELS]
    shakes=[10,-8,6,-4,2,0]
    frames=[]
    rnd=random.Random(7)
    for i in range(EXPLOSION_FRAMES):
        cv=base.copy()
        fx=Image.new("RGBA",cv.size,(0,0,0,0))
        d=ImageDraw.Draw(fx)
        t=i/(EXPLOSION_FRAMES-1)
        rad=int(50+t*230)
        for cx,cy in centers:
            if i==0:
                d.ellipse([cx-150,cy-120,cx+150,cy+120],fill=(255,255,240,230))
            a_out=max(0,int(200*(1-t)))
            d.ellipse([cx-rad,cy-rad,cx+rad,cy+rad],outline=LIME+(a_out,),width=18)
            d.ellipse([cx-rad//2,cy-rad//2,cx+rad//2,cy+rad//2],fill=GOLD+(max(0,int(160*(1-t))),))
            d.ellipse([cx-rad//4,cy-rad//4,cx+rad//4,cy+rad//4],fill=(255,255,230,max(0,int(220*(1-t)))))
            for _ in range(18):
                ang=rnd.uniform(0,6.283); rr=rad*rnd.uniform(0.6,1.15)
                px,py=cx+rr*math.cos(ang),cy+rr*math.sin(ang)
                pc=LIME if rnd.random()<0.6 else GOLD
                d.ellipse([px-7,py-7,px+7,py+7],fill=pc+(max(0,int(230*(1-t))),))
        fx=fx.filter(ImageFilter.GaussianBlur(2))
        cv.alpha_composite(fx)
        # screen shake
        sh=shakes[i]
        canvas=Image.new("RGBA",cv.size,(0,0,10,255))
        canvas.paste(cv,(sh,0))
        frames.append(canvas)
    return frames


def arched_text(ov, text, cx, arc_r, arc_center_y, font_path, size,
                fill, stroke, stroke_w, span=None):
    """Draw text along a gentle upward arch, spacing glyphs by their real
    width so wide and narrow letters sit evenly. Returns nothing (draws on ov)."""
    f = font(font_path, size)
    meas = ImageDraw.Draw(ov)
    widths = [meas.textlength(ch, font=f) for ch in text]
    total = sum(widths)
    # angular width of the whole word on the circle of radius arc_r
    if span is None:
        span = math.degrees(total*1.12/arc_r)      # 12% breathing room
    # walk the arc, advancing per glyph width
    ang = -span/2
    tile = int(size*2.2)
    for ch, w in zip(text, widths):
        step = span*(w/total)
        a = ang + step/2
        x = cx + arc_r*math.sin(math.radians(a))
        y = arc_center_y - arc_r*math.cos(math.radians(a))
        t = Image.new("RGBA", (tile, tile), (0,0,0,0))
        td = ImageDraw.Draw(t)
        td.text((tile//2, tile//2), ch, font=f, fill=fill, anchor="mm",
                stroke_width=stroke_w, stroke_fill=stroke)
        t = t.rotate(-a, resample=Image.BICUBIC, center=(tile//2, tile//2))
        ov.alpha_composite(t, (int(x)-tile//2, int(y)-tile//2))
        ang += step


def draw_plaque(prize_text):
    """Pragmatic-style congratulations plaque as an RGBA overlay (1448x1086)."""
    W,H = 1448,1086
    ov = Image.new("RGBA",(W,H),(0,0,0,0))
    d  = ImageDraw.Draw(ov)

    # geometry — everything hangs off the plaque rect
    PL, PT, PR, PB = 274, 330, 1174, 800
    CX = (PL+PR)//2

    # soft drop shadow under the plaque
    sh = Image.new("RGBA",(W,H),(0,0,0,0))
    ImageDraw.Draw(sh).rounded_rectangle([PL+10,PT+16,PR+10,PB+16],38,fill=(0,0,0,140))
    ov.alpha_composite(sh.filter(ImageFilter.GaussianBlur(14)))

    # gold plaque
    d.rounded_rectangle([PL,PT,PR,PB],38,fill=(6,14,36,244),outline=GOLD+(255,),width=14)
    d.rounded_rectangle([PL+18,PT+18,PR-18,PB-18],28,outline=GOLD_LIGHT+(255,),width=3)
    # --- arched headline, riding the top edge of the plaque -----------------
    arched_text(ov, "¡FELICIDADES!", CX,
                arc_r=900, arc_center_y=PT+900-16,  # crest ~16px above plaque top
                font_path=FONT_DISPLAY, size=94,
                fill=LIME+(255,), stroke=GOLD+(255,), stroke_w=7)

    # --- inside the plaque: three bands, evenly spaced ----------------------
    inner_top, inner_bot = PT+120, PB-46           # below the arched crest
    band = (inner_bot-inner_top)/3
    y_sub   = int(inner_top + band*0.5)
    y_prize = int(inner_top + band*1.5)
    y_claim = int(inner_bot - 18)

    fS = font(FONT_HEAVY, 54)
    tracked_text(d,(CX,y_sub),"HAS GANADO",fS,WHITE+(255,),tracking=6,
                 stroke_width=3,stroke_fill=NAVY+(255,))

    # prize box sized to its text
    fP = fit_font(d, prize_text, FONT_DISPLAY, 78, (PR-PL)-260)
    tw = d.textlength(prize_text, font=fP)
    bh = max(int(fP.size*1.55), 100)
    bx0,bx1 = int(CX-tw/2-56), int(CX+tw/2+56)
    d.rounded_rectangle([bx0,y_prize-bh//2,bx1,y_prize+bh//2],22,
                        fill=(12,26,60,255),outline=GOLD+(255,),width=7)
    d.text((CX,y_prize-int(fP.size*0.06)),prize_text,font=fP,fill=GOLD+(255,),
           anchor="mm",stroke_width=3,stroke_fill=GOLD_DARK+(255,))

    fC = font(FONT_HEAVY, 33)
    tracked_text(d,(CX,y_claim),"PRESIONA PARA RECLAMAR",fC,
                 GOLD_LIGHT+(235,),tracking=5)
    return ov


def win_frames(base):
    """Pop-in plaque + rotating rays + falling coins, Pragmatic style."""
    W,H=base.size
    sx=W/1448.0
    plaque=draw_plaque(PRIZE_TEXT)
    coin=Image.open("sym_coin.png").convert("RGBA"); coin.thumbnail((110,110),Image.LANCZOS)
    rnd=random.Random(11)
    coin_x=[rnd.randint(120,1330) for _ in range(8)]
    coin_v=[rnd.randint(70,130) for _ in range(8)]
    coin_y0=[rnd.randint(-500,-80) for _ in range(8)]
    frames=[]
    for i in range(WIN_FRAMES):
        cv=base.copy()
        ov=Image.new("RGBA",cv.size,(0,0,0,0))
        d=ImageDraw.Draw(ov)
        d.rectangle([0,0,cv.width,cv.height],fill=(0,0,15,120))
        rot=min(i,6)*7
        rcx,rcy=cv.width//2,int(cv.height*0.5)
        for k in range(12):
            a0=math.radians(rot+k*30); a1=math.radians(rot+k*30+13)
            col=(GOLD if k%2 else LIME)+(65,)
            L=max(cv.width,cv.height)
            d.polygon([(rcx,rcy),(rcx+L*math.cos(a0),rcy+L*math.sin(a0)),
                       (rcx+L*math.cos(a1),rcy+L*math.sin(a1))],fill=col)
        cv.alpha_composite(ov)
        # falling coins (behind plaque)
        if i>=2:
            for c in range(8):
                y=coin_y0[c]+coin_v[c]*(i-1)
                if -120<y<1086:
                    cc=coin.rotate((c*37+i*9)%360,resample=Image.BICUBIC)
                    cs=cc.resize((int(cc.width*sx),int(cc.height*sx)),Image.LANCZOS)
                    cv.alpha_composite(cs,(int(coin_x[c]*sx),int(y*sx)))
        # plaque pop-in
        scale=[0.72,1.07,1.0][i] if i<3 else 1.0
        pls=plaque.resize((int(1448*scale*sx),int(1086*scale*sx)),Image.LANCZOS)
        cv.alpha_composite(pls,((cv.width-pls.width)//2,(cv.height-pls.height)//2))
        frames.append(cv)
    return frames


def main():
    frame=draw_bottom_bar(Image.open(FRAME_PATH).convert("RGBA"))
    overlays=[(Image.open(p).convert("RGBA"),x,y) for p,x,y in OVERLAYS]
    cells=load_cells()

    def turbo_pulse(frames_list, phase_offset=0):
        cx,cy,r=723,988,86
        for idx,cv in enumerate(frames_list):
            g=Image.new("RGBA",cv.size,(0,0,0,0)); dg=ImageDraw.Draw(g)
            a=210 if (idx+phase_offset)%4<2 else 90
            dg.ellipse([cx-r,cy-r,cx+r,cy+r],outline=LIME+(a,),width=12)
            g=g.filter(ImageFilter.GaussianBlur(7))
            cv.alpha_composite(g)
        return frames_list

    seq =turbo_pulse(spin_frames(frame,overlays,cells,RESULT1,STOPS1))
    seq+=[seq[-1]]*2                                   # beat before the boom
    seq+=explosion_frames(seq[-1])
    seq+=turbo_pulse(spin_frames(frame,overlays,cells,RESULT2,STOPS2),phase_offset=1)
    seq+=[seq[-1]]*2                                   # beat before celebration
    seq+=win_frames(seq[-1])
    seq+=[seq[-1]]*4                                   # freeze

    small=[]
    for cv in seq:
        if cv.width>FINAL_WIDTH:
            cv=cv.resize((FINAL_WIDTH,int(cv.height*FINAL_WIDTH/cv.width)),Image.LANCZOS)
        small.append(cv.convert("RGB"))
    mosaic=Image.new("RGB",(small[0].width,small[0].height*2))
    mosaic.paste(small[len(small)//3],(0,0)); mosaic.paste(small[-1],(0,small[0].height))
    pal=mosaic.quantize(colors=GIF_COLORS,method=Image.MEDIANCUT)
    qs=[f.quantize(colors=GIF_COLORS,palette=pal,dither=Image.FLOYDSTEINBERG) for f in small]
    qs[0].save(OUT,save_all=True,append_images=qs[1:],duration=FRAME_MS,loop=1,
               optimize=True,disposal=2)
    print(f"Saved {OUT} ({len(qs)} frames)")


if __name__=="__main__":
    main()
