# main.py (fragmento completo para las nuevas rutas)
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import requests, os, textwrap
from uuid import uuid4

API_KEY = os.getenv("AGENT_API_KEY", "cambia-esto")

app = FastAPI(title="Comunicados Generator")

# --- Modelo del request ---
class Payload(BaseModel):
    template_url: str
    blocks: dict = {}       # {"title": "...", "body": "...", "subhead": "...", "cta": "...", "sig": "..."}
    images: dict = {}       # (opcional; no usado en esta versión)
    width: int | None = 1350
    height: int | None = 1080

# --- Utilidades ---
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
    avg = max(10, int(width / max(10, fnt.getlength("ABCDEFGHIJ")/10 if hasattr(fnt,"getlength") else fnt.getsize("ABCDEFGHIJ")[0]/10)))
    lines = []
    for p in str(text).splitlines():
        lines += textwrap.wrap(p, width=avg)
    line_h = (fnt.getbbox("Ay")[3]-fnt.getbbox("Ay")[1]) if hasattr(fnt,"getbbox") else fnt.getsize("Ay")[1]
    y = y0
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

# Zonas base (para 1350x1080)
BASE_W, BASE_H = 1350, 1080
ZONES = {
    "title":   (80, 180, 1270, 420),
    "subhead": (120, 440, 1230, 520),
    "body":    (120, 560, 1230, 900),
    "cta":     (120, 910, 800, 980),
    "sig":     (820, 910, 1230, 980)
}

# Memoria volátil para servir imágenes
IMAGES: dict[str, bytes] = {}

# --- NUEVO: devuelve JSON con link ---
@app.post("/generate", response_class=JSONResponse)
def generate_link(payload: Payload, request: Request, authorization: str | None = Header(default=None)):
    if authorization != f"Bearer {API_KEY}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    # 1) Cargar plantilla
    base = load_img(payload.template_url)

    # 2) Redimensionar si corresponde (reduce peso)
    W, H = base.size
    target_w = payload.width or W
    target_h = payload.height or H
    if (target_w, target_h) != (W, H):
        base = base.resize((target_w, target_h), Image.LANCZOS)
        W, H = base.size

    draw = ImageDraw.Draw(base)

    # 3) Fuentes (escalado simple)
    scale_y = H / BASE_H
    f_title   = font(int(64*scale_y), bold=True)
    f_subhead = font(int(38*scale_y), bold=False)
    f_body    = font(int(34*scale_y), bold=False)
    f_cta     = font(int(34*scale_y), bold=True)
    f_sig     = font(int(30*scale_y), bold=False)

    def S(name):
        x0,y0,x1,y1 = ZONES[name]
        sx, sy = W/BASE_W, H/BASE_H
        return (int(x0*sx), int(y0*sy), int(x1*sx), int(y1*sy))

    b = payload.blocks or {}
    if b.get("title"):   draw_wrapped(draw, b["title"],   S("title"),   f_title,   align="center")
    if b.get("subhead"): draw_wrapped(draw, b["subhead"], S("subhead"), f_subhead, align="center")
    if b.get("body"):    draw_wrapped(draw, b["body"],    S("body"),    f_body,    align="left")
    if b.get("cta"):     draw_wrapped(draw, b["cta"],     S("cta"),     f_cta,     align="left")
    if b.get("sig"):     draw_wrapped(draw, b["sig"],     S("sig"),     f_sig,     align="right")

    # 4) Guardar en memoria y devolver link
    buf = BytesIO()
    # PNG optimizado; si aún pesara mucho, puedes pasar a JPEG (ver comentario abajo)
    base.save(buf, format="PNG", optimize=True, compress_level=9)
    data = buf.getvalue()
    img_id = uuid4().hex
    IMAGES[img_id] = data

    file_url = str(request.url_for("serve_image", img_id=img_id))
    return {"file_url": file_url, "size_bytes": len(data), "width": W, "height": H}

# Servir la imagen por ID
@app.get("/i/{img_id}.png", name="serve_image")
def serve_image(img_id: str):
    data = IMAGES.get(img_id)
    if not data:
        raise HTTPException(status_code=404, detail="Not found")
    return StreamingResponse(BytesIO(data), media_type="image/png")

