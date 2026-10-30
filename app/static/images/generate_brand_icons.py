from pathlib import Path
from PIL import Image, ImageDraw
import PIL.ImageOps

def generate_brand_icons():
    """Builds every icon size from `logo_source.png`, the square master (full bleed, the app
    rounds it in CSS and the OS masks the home-screen icons). Replace that file to change the logo."""
    images_dir = Path(__file__).resolve().parent
    master_dim = 1024
    master_img = Image.open(images_dir / "logo_source.png").convert("RGBA")
    if master_img.size != (master_dim, master_dim):
        master_img = master_img.resize((master_dim, master_dim), Image.Resampling.LANCZOS)

    resample_filter = Image.Resampling.LANCZOS

    # Save generated master & all 14 icon variants
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

    i112 = master_img.resize((112, 112), resample_filter)
    i112.save(images_dir / "logo-icon-112.png", "PNG")

    # Tab icons are rounded (transparent corners); the touch and PWA icons stay square because
    # the OS applies its own mask to those.
    def rounded(img, radius_ratio=0.22):
        scale = 4
        size = img.size[0]
        mask = Image.new("L", (size * scale, size * scale), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, size * scale - 1, size * scale - 1), radius=int(size * scale * radius_ratio), fill=255)
        out = img.copy()
        out.putalpha(mask.resize((size, size), Image.Resampling.LANCZOS))
        return out

    tab_master = rounded(master_img.resize((256, 256), resample_filter))
    i32 = tab_master.resize((32, 32), resample_filter)
    ico = tab_master.resize((48, 48), resample_filter)
    i32.save(images_dir / "favicon.png", "PNG")
    i32.save(images_dir / "badge-favicon.png", "PNG")
    ico.save(images_dir / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])

    print("[brand_icons] Brand icons generated from logo_source.png.")

if __name__ == "__main__":
    generate_brand_icons()
