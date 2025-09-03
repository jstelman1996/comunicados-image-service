from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import requests, os, textwrap

API_KEY = os.getenv("AGENT_API_KEY", "cambia-esto")

# Tamaño base y zonas por defecto (para 1350x1080). Se escalan a la imagen real.
BASE_W, BASE_H = 1350, 1080
ZONES = {
    "title":   (80, 180, 1270, 420),   # caja grande arriba
    "subhead": (120, 440, 1230, 520),
    "body":    (120, 560, 1230, 900),  # cuerpo
    "cta":     (120, 910, 800, 980),
    "sig":     (820, 910, 1230, 980)
}

class Payload(BaseModel):
    template_url: str
    blocks: dict = {}      # {"title": "...", "body": "...", "subhead": "...", "cta": "...", "sig": "..."}
    images: dict = {}      # no-op en esta versión simple

app = FastAPI(title="Comunicados Generator")

def load_img(url):
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return Image.open(BytesIO(r.content)).convert("RGBA")

def font(sz, bold=True):
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try:
        return ImageFont.truetype(path, sz)
    except:
        return ImageFont.load_default()

def draw_wrapped(draw, text, box, fnt, fill=(0,0,0,255), align="left", line_spacing=8):
    x0,y0,x1,y1 = box
    width = x1-x0
    if not text:
        return
    # Ajuste básico de líneas
    # estimación de caracteres por línea
    avg = max(10, int(width / max(10, fnt.getlength("ABCDEFGHIJ")/10 if hasattr(fnt,"getlength") else fnt.getsize("ABCDEFGHIJ")[0]/10)))
    lines = []
    for p in str(text).splitlines():
        lines += textwrap.wrap(p, width=avg)
    line_h = (fnt.getbbox("Ay")[3]-fnt.getbbox("Ay")[1]) if hasattr(fnt,"getbbox") else fnt.getsize("Ay")[1]
    total_h = len(lines)*line_h + (len(lines)-1)*line_spacing
    y = y0 + max(0, (y1-y0-total_h)//2) if align=="center" else y0
    for ln in lines:
        w = fnt.getlength(ln) if hasattr(fnt,"getlength") else fnt.getsize(ln)[0]
        if align=="center":
            x = x0 + (width - w)//2
        elif align=="right":
            x = x1 - w
        else:
            x = x0
        draw.text((x,y), ln, font=fnt, fill=fill)
        y += line_h + line_spacing

@app.post("/generate.png")
def generate_png(payload: Payload, authorization: str | None = Header(default=None)):
    if authorization != f"Bearer {API_KEY}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Cargar plantilla
    base = load_img(payload.template_url)
    W, H = base.size
    scale_x, scale_y = W/BASE_W, H/BASE_H

    # Preparar dibujo
    draw = ImageDraw.Draw(base)

    # Fuentes
    f_title   = font(int(64*scale_y), bold=True)
    f_subhead = font(int(38*scale_y), bold=False)
    f_body    = font(int(34*scale_y), bold=False)
    f_cta     = font(int(34*scale_y), bold=True)
    f_sig     = font(int(30*scale_y), bold=False)

    # Helper para escalar cajas
    def S(name):
        x0,y0,x1,y1 = ZONES[name]
        return (int(x0*scale_x), int(y0*scale_y), int(x1*scale_x), int(y1*scale_y))

    # Pintar bloques si existen
    if payload.blocks.get("title"):
        draw_wrapped(draw, payload.blocks["title"], S("title"), f_title, fill=(0,0,0,255), align="center")
    if payload.blocks.get("subhead"):
        draw_wrapped(draw, payload.blocks["subhead"], S("subhead"), f_subhead, fill=(0,0,0,255), align="center")
    if payload.blocks.get("body"):
        draw_wrapped(draw, payload.blocks["body"], S("body"), f_body, fill=(0,0,0,255), align="left")
    if payload.blocks.get("cta"):
        draw_wrapped(draw, payload.blocks["cta"], S("cta"), f_cta, fill=(0,0,0,255), align="left")
    if payload.blocks.get("sig"):
        draw_wrapped(draw, payload.blocks["sig"], S("sig"), f_sig, fill=(0,0,0,255), align="right")

    # Devolver PNG
    buf = BytesIO()
    base.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")
