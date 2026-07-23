"""Labeled montages of pre-cut UI pieces so filenames can be mapped to content."""
import os, sys, math
from PIL import Image, ImageDraw

SRC = r"C:\Users\cubi7\Desktop\Claude\bar-of-exile\assets\icons"
OUT = r"C:\Users\cubi7\Desktop\Claude\bar-of-exile\assets\ui\_curate"
os.makedirs(OUT, exist_ok=True)

SETS = {
    "buttons": ("pixel_art_ui_buttons_dark", 96),
    "elements": ("pixel_art_ui_elements_diablo", 96),
    "cursors": ("pixel_art_ui_icons_cursors", 96),
    "invframes": ("pixel_art_inventory_frames_and", 140),
    "charsel": ("character_selection_menu_atlas_p", 200),
}

def load(folder):
    d = os.path.join(SRC, folder)
    out = []
    for f in sorted(os.listdir(d)):
        if f.endswith(".png"):
            im = Image.open(os.path.join(d, f)).convert("RGBA")
            out.append((f, im))
    return out

report = []
for name, (folder, cell) in SETS.items():
    pieces = load(folder)
    label_h = 14
    cols = 10
    per_page = 80
    pages = math.ceil(len(pieces) / per_page)
    for pg in range(pages):
        chunk = pieces[pg*per_page:(pg+1)*per_page]
        rows = math.ceil(len(chunk) / cols)
        W, H = cols*(cell+4), rows*(cell+label_h+6)
        canvas = Image.new("RGB", (W, H), (40, 160, 40))  # green bg exposes true edges
        dr = ImageDraw.Draw(canvas)
        for i, (f, im) in enumerate(chunk):
            cx, cy = (i % cols)*(cell+4), (i // cols)*(cell+label_h+6)
            th = im.copy()
            th.thumbnail((cell, cell), Image.NEAREST)
            canvas.paste(th, (cx + (cell-th.width)//2, cy + (cell-th.height)//2), th)
            tag = f.replace("icon_", "").replace(".png", "")
            dr.text((cx+2, cy+cell+1), tag, fill=(255,255,0))
        canvas.save(os.path.join(OUT, f"m_{name}_{pg}.png"))
    # alpha / size / white-bg report
    for f, im in pieces:
        w, h = im.size
        corners = [im.getpixel(p) for p in [(0,0),(w-1,0),(0,h-1),(w-1,h-1)]]
        whiteish = sum(1 for r,g,b,a in corners if a>200 and r>230 and g>230 and b>230)
        alpha = im.getchannel("A").getextrema()
        report.append(f"{name}/{f}\t{w}x{h}\talpha={alpha}\twhite_corners={whiteish}")

with open(os.path.join(OUT, "report.txt"), "w") as fh:
    fh.write("\n".join(report))
print("pages:", sorted(os.listdir(OUT)))
