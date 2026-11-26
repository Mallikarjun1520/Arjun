"""
generate_icon.py — Creates arjun_icon.ico for the desktop shortcut.
Run once during setup. Requires Pillow.
Draws the orange brain-molecule look as a 256x256 icon.
"""

import math
import struct
import zlib
import os

def create_arjun_icon():
    """
    Creates a simple but distinctive orange molecule icon as a .ico file
    using only the Python standard library (no Pillow needed).
    Falls back gracefully if something goes wrong.
    """
    try:
        from PIL import Image, ImageDraw
        _create_with_pillow()
    except ImportError:
        _create_minimal_ico()

def _create_with_pillow():
    from PIL import Image, ImageDraw
    import math

    sizes = [256, 128, 64, 48, 32, 16]
    images = []

    for size in sizes:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        cx, cy = size // 2, size // 2
        scale  = size / 256

        # Dark background circle
        r = int(120 * scale)
        draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(18, 10, 4, 240))

        # Outer glow ring
        rg = int(118 * scale)
        draw.ellipse([cx-rg, cy-rg, cx+rg, cy+rg], outline=(255, 120, 10, 160),
                     width=max(1, int(3*scale)))

        # Draw molecule bonds
        node_positions = []
        rings = [(int(40*scale), 5), (int(80*scale), 8)]
        for orbit_r, count in rings:
            for i in range(count):
                angle = i * 2 * math.pi / count
                x = cx + orbit_r * math.cos(angle)
                y = cy + orbit_r * math.sin(angle)
                node_positions.append((x, y, orbit_r))

        # Bonds
        inner = [(x, y) for x, y, r in node_positions if r < 50*scale]
        outer = [(x, y) for x, y, r in node_positions if r >= 50*scale]

        bond_color = (220, 100, 20, 180)
        for i in range(len(inner)):
            j = (i + 1) % len(inner)
            draw.line([inner[i], inner[j]], fill=bond_color, width=max(1, int(2*scale)))
        for i, ip in enumerate(inner):
            if i < len(outer):
                draw.line([ip, outer[i]], fill=bond_color, width=max(1, int(1*scale)))

        # Nodes
        for x, y, orbit_r in node_positions:
            nr = int((7 if orbit_r < 50*scale else 5) * scale)
            col = (255, 190, 60, 255) if orbit_r < 50*scale else (255, 140, 20, 255)
            draw.ellipse([x-nr, y-nr, x+nr, y+nr], fill=col)

        # Central core
        cr = int(14 * scale)
        draw.ellipse([cx-cr, cy-cr, cx+cr, cy+cr], fill=(255, 255, 200, 255))
        cr2 = int(10 * scale)
        draw.ellipse([cx-cr2, cy-cr2, cx+cr2, cy+cr2], fill=(255, 240, 180, 255))

        images.append(img)

    # Save as .ico
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "arjun_icon.ico")
    images[0].save(out_path, format="ICO", sizes=[(s, s) for s in sizes],
                   append_images=images[1:])
    print(f"Icon saved to {out_path}")


def _create_minimal_ico():
    """
    Pure stdlib fallback: creates a minimal 32x32 orange circle .ico.
    No Pillow required.
    """
    import struct, zlib

    size = 32
    # Create raw RGBA pixels: orange circle on transparent background
    pixels = []
    cx = cy = size // 2
    for y in range(size):
        for x in range(size):
            dist = math.sqrt((x - cx)**2 + (y - cy)**2)
            if dist <= 14:
                # Core: bright orange
                pixels += [255, 160, 20, 255]
            elif dist <= 15:
                # Edge glow
                pixels += [255, 100, 10, 200]
            else:
                pixels += [0, 0, 0, 0]

    raw = bytes(pixels)
    # Build PNG for the ICO
    def png_chunk(tag, data):
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    png  = b"\x89PNG\r\n\x1a\n"
    png += png_chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    raw_rows = b"".join(b"\x00" + raw[y*size*4:(y+1)*size*4] for y in range(size))
    png += png_chunk(b"IDAT", zlib.compress(raw_rows))
    png += png_chunk(b"IEND", b"")

    # Minimal ICO with one PNG entry
    ico  = struct.pack("<HHH", 0, 1, 1)  # header
    ico += struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(png), 22)
    ico += png

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "arjun_icon.ico")
    with open(out_path, "wb") as f:
        f.write(ico)
    print(f"Minimal icon saved to {out_path}")


if __name__ == "__main__":
    create_arjun_icon()
