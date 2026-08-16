import os
import shutil
import base64
import re
import io
from pathlib import Path
from PIL import Image
import PIL.ImageOps

try:
    import cairosvg
except ImportError:
    cairosvg = None

def generate_brand_icons():
    images_dir = Path(__file__).resolve().parent
    old_dir = images_dir / "old logos and icons"
    old_dir.mkdir(parents=True, exist_ok=True)

    svg_src = images_dir / "studiamo logo.svg"
    if not svg_src.exists():
        svg_src = images_dir / "logo.svg"
    
    if not svg_src.exists():
        print("[brand_icons] Source SVG logo not found.")
        return

    # Copy SVG to standard logo.svg and logo-icon.svg
    shutil.copy2(svg_src, images_dir / "logo.svg")
    shutil.copy2(svg_src, images_dir / "logo-icon.svg")

    master_dim = 1024
    master_img = None

    # Method 1: Render vector SVG directly via cairosvg (crisp vector rendering)
    if cairosvg is not None:
        try:
            png_data = cairosvg.svg2png(url=str(svg_src), output_width=master_dim, output_height=master_dim)
            rendered = Image.open(io.BytesIO(png_data)).convert("RGBA")
            if rendered.size == (master_dim, master_dim):
                master_img = rendered
        except Exception as e:
            print(f"[brand_icons] cairosvg render failed ({e}), trying base64 extract fallback...")

    # Method 2: Extract embedded base64 PNG from older SVG format
    if master_img is None:
        with open(svg_src, "r", encoding="utf-8") as f:
            svg_content = f.read()

        match = re.search(r'data:image/png;base64,([A-Za-z0-9+/=]+)', svg_content)
        if not match:
            print("[brand_icons] Error: Could not render vector SVG or find embedded base64 image.")
            return

        b64_data = match.group(1)
        img_bytes = base64.b64decode(b64_data)
        inner_img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")

        # Create 1024x1024 master image with yellow background rgb(248, 190, 18)
        master_img = Image.new("RGBA", (master_dim, master_dim), (248, 190, 18, 255))
        target_w = 560
        target_h = 660
        resized_inner = inner_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
        offset_x = (master_dim - target_w) // 2
        offset_y = (master_dim - target_h) // 2
        master_img.paste(resized_inner, (offset_x, offset_y), resized_inner)

    resample_filter = Image.Resampling.LANCZOS

    # Save generated master & all 14 icon variants
    master_img.save(images_dir / "logo_source.png", "PNG")
    master_img.save(images_dir / "logo.png", "PNG")

    i512 = master_img.resize((512, 512), resample_filter)
    i512.save(images_dir / "logo-icon.png", "PNG")
    i512.save(images_dir / "icon-512.png", "PNG")
    i512.save(images_dir / "logo-badge.png", "PNG")
    i512.save(images_dir / "badge-icon-512.png", "PNG")

    r, g, b, a = i512.split()
    rgb_img = Image.merge("RGB", (r, g, b))
    inv_rgb = PIL.ImageOps.invert(rgb_img)
    inv_r, inv_g, inv_b = inv_rgb.split()
    inv_img = Image.merge("RGBA", (inv_r, inv_g, inv_b, a))
    inv_img.save(images_dir / "logo-icon-inverted.png", "PNG")

    i192 = master_img.resize((192, 192), resample_filter)
    i192.save(images_dir / "icon-192.png", "PNG")
    i192.save(images_dir / "badge-icon-192.png", "PNG")

    i180 = master_img.resize((180, 180), resample_filter)
    i180.save(images_dir / "apple-touch-icon.png", "PNG")
    i180.save(images_dir / "badge-apple-touch-icon.png", "PNG")

    i32 = master_img.resize((32, 32), resample_filter)
    i32.save(images_dir / "favicon.png", "PNG")
    i32.save(images_dir / "badge-favicon.png", "PNG")
    i32.save(images_dir / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])

    print("[brand_icons] All 14 brand icon variants generated successfully from SVG!")

if __name__ == "__main__":
    generate_brand_icons()
