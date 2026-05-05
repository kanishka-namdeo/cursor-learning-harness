"""
Generate repository graphics using Pillow (no Cairo dependency).
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import math

assets_dir = Path(__file__).parent


def hex_to_rgb(h):
    return tuple(int(h.lstrip("#")[i:i+2], 16) for i in (0, 2, 4))


BLUE = hex_to_rgb("#3b82f6")
PURPLE = hex_to_rgb("#8b5cf6")
CYAN = hex_to_rgb("#06b6d4")
DARK_BG = hex_to_rgb("#0f172a")
LIGHT_TEXT = hex_to_rgb("#e2e8f0")
GRAY_TEXT = hex_to_rgb("#94a3b8")


def get_font(size):
    for name in ["arial", "dejavusans", "liberationsans"]:
        try:
            return ImageFont.truetype(f"{name}.ttf", size)
        except (IOError, OSError):
            continue
    try:
        return ImageFont.truetype("arial.ttf", size)
    except (IOError, OSError):
        return ImageFont.load_default()


def draw_social_preview():
    img = Image.new("RGB", (1280, 640), DARK_BG)
    draw = ImageDraw.Draw(img)

    # Grid lines
    for x in range(0, 1280, 80):
        draw.line([(x, 0), (x, 640)], fill=(255, 255, 255, 10), width=1)
    for y in range(0, 640, 80):
        draw.line([(0, y), (1280, y)], fill=(255, 255, 255, 10), width=1)

    # Decorative circles
    draw.ellipse([(1020, 20), (1180, 180)], fill=(59, 130, 246, 25))
    draw.ellipse([(930, 430), (1170, 670)], fill=(139, 92, 246, 20))
    draw.ellipse([(140, 520), (260, 640)], fill=(6, 182, 212, 25))

    # Neural network - nodes and connections
    nodes = [
        (560, 120, BLUE),
        (720, 120, PURPLE),
        (720, 280, CYAN),
        (560, 280, BLUE),
        (640, 80, PURPLE),
        (640, 320, CYAN),
        (480, 200, BLUE),
        (800, 200, PURPLE),
    ]

    connections = [
        (0, 4), (1, 4), (2, 5), (3, 5),
        (0, 6), (3, 6), (1, 7), (2, 7),
        (0, 2), (1, 3), (4, 5), (6, 7),
    ]

    for a, b in connections:
        draw.line(
            [(nodes[a][0], nodes[a][1]), (nodes[b][0], nodes[b][1])],
            fill=nodes[a][2] + (50,),
            width=2,
        )

    for x, y, color in nodes:
        draw.ellipse([(x - 8, y - 8), (x + 8, y + 8)], fill=color)

    # Center circuit pattern
    center_x, center_y = 640, 200
    circuit_pts = []
    for angle in range(0, 360, 5):
        r = 60 + 15 * math.sin(math.radians(angle * 3))
        circuit_pts.append((
            center_x + r * math.cos(math.radians(angle)),
            center_y + r * math.sin(math.radians(angle)),
        ))
    draw.polygon(circuit_pts, outline=PURPLE, width=2)

    # Cursor arrow in center
    cursor = [
        (center_x, center_y - 20),
        (center_x - 12, center_y + 15),
        (center_x - 2, center_y + 8),
        (center_x - 8, center_y + 25),
        (center_x + 6, center_y + 16),
        (center_x + 14, center_y + 5),
        (center_x + 2, center_y + 20),
    ]
    draw.polygon(cursor, fill=PURPLE)

    # Title
    font_large = get_font(48)
    draw.text((640, 370), "Cursor Learning Harness", fill=BLUE, font=font_large, anchor="mm")

    # Subtitle
    font_sub = get_font(22)
    draw.text(
        (640, 420),
        "Self-Improving AI Coding Assistant with LangGraph & LangChain",
        fill=GRAY_TEXT,
        font=font_sub,
        anchor="mm",
    )

    # Feature tags
    features = [
        ("Session Recording", BLUE),
        ("AI Summarization", PURPLE),
        ("Sentiment Analysis", CYAN),
        ("Self-Improving", hex_to_rgb("#10b981")),
    ]
    tag_y = 480
    tag_x = 290
    for text, color in features:
        font_tag = get_font(14)
        w = draw.textlength(text, font=font_tag)
        pad = 20
        total_w = w + pad * 2
        draw.rounded_rectangle(
            [(tag_x, tag_y), (tag_x + total_w, tag_y + 36)],
            radius=18,
            outline=color,
            width=1,
        )
        draw.text((tag_x + pad, tag_y + 10), text, fill=color, font=font_tag)
        tag_x += total_w + 20

    # Tech badges
    techs = ["Python", "LangGraph", "LangChain", "SQLite", "Streamlit", "Plotly", "HuggingFace"]
    badge_y = 540
    badge_x = 220
    for tech in techs:
        font_badge = get_font(12)
        w = draw.textlength(tech, font=font_badge)
        pad = 16
        total_w = w + pad * 2
        draw.rounded_rectangle(
            [(badge_x, badge_y), (badge_x + total_w, badge_y + 28)],
            radius=14,
            fill=(55, 65, 81, 150),
            outline=(75, 85, 99),
            width=1,
        )
        draw.text((badge_x + pad, badge_y + 7), tech, fill=LIGHT_TEXT, font=font_badge)
        badge_x += total_w + 15

    # Bottom accent line
    for i in range(1280):
        t = i / 1280
        if t < 0.5:
            r, g, b = int(BLUE[0] + (PURPLE[0] - BLUE[0]) * t * 2), int(BLUE[1] + (PURPLE[1] - BLUE[1]) * t * 2), int(BLUE[2] + (PURPLE[2] - BLUE[2]) * t * 2)
        else:
            r, g, b = int(PURPLE[0] + (CYAN[0] - PURPLE[0]) * (t - 0.5) * 2), int(PURPLE[1] + (CYAN[1] - PURPLE[1]) * (t - 0.5) * 2), int(PURPLE[2] + (CYAN[2] - PURPLE[2]) * (t - 0.5) * 2)
        draw.point((i, 620), fill=(r, g, b))

    path = assets_dir / "social-preview.png"
    img.save(path, "PNG")
    print(f"Created: {path}")
    return path


def draw_logo(size=512):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx, cy = size // 2, size // 2
    r = int(size * 0.44)

    # Background circle
    draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=DARK_BG + (255,))

    # Outer ring
    ring_r = int(size * 0.40)
    draw.ellipse(
        [(cx - ring_r, cy - ring_r), (cx + ring_r, cy + ring_r)],
        outline=PURPLE + (75,),
        width=4,
    )

    # Neural network nodes
    node_r = int(size * 0.015)
    nodes = [
        (int(cx * 0.70), int(cy * 0.70), BLUE),
        (int(cx * 1.30), int(cy * 0.70), PURPLE),
        (int(cx * 1.30), int(cy * 1.30), CYAN),
        (int(cx * 0.70), int(cy * 1.30), BLUE),
        (cx, int(cy * 0.55), PURPLE),
        (cx, int(cy * 1.45), CYAN),
        (int(cx * 0.55), cy, BLUE),
        (int(cx * 1.45), cy, PURPLE),
    ]

    connections = [
        (0, 4), (1, 4), (2, 5), (3, 5),
        (0, 6), (3, 6), (1, 7), (2, 7),
        (0, 2), (1, 3), (4, 5), (6, 7),
    ]

    for a, b in connections:
        draw.line(
            [(nodes[a][0], nodes[a][1]), (nodes[b][0], nodes[b][1])],
            fill=nodes[a][2] + (100,),
            width=2,
        )

    for x, y, color in nodes:
        draw.ellipse([(x - node_r, y - node_r), (x + node_r, y + node_r)], fill=color + (255,))

    # Center brain circuit
    brain_r = int(size * 0.12)
    circuit_pts = []
    for angle in range(0, 360, 5):
        rr = brain_r + int(5 * math.sin(math.radians(angle * 3)))
        circuit_pts.append((
            cx + rr * math.cos(math.radians(angle)),
            cy + rr * math.sin(math.radians(angle)),
        ))
    draw.polygon(circuit_pts, outline=PURPLE + (180,), width=3)

    # Cursor arrow
    cursor = [
        (cx, cy - int(size * 0.08)),
        (cx - int(size * 0.05), cy + int(size * 0.06)),
        (cx - int(size * 0.008), cy + int(size * 0.03)),
        (cx - int(size * 0.03), cy + int(size * 0.11)),
        (cx + int(size * 0.025), cy + int(size * 0.07)),
        (cx + int(size * 0.06), cy + int(size * 0.02)),
        (cx + int(size * 0.008), cy + int(size * 0.08)),
    ]
    draw.polygon(cursor, fill=PURPLE + (230,))

    # Resize to exact size
    img = img.resize((size, size), Image.LANCZOS)

    path = assets_dir / f"logo-{size}x{size}.png"
    img.save(path, "PNG")
    print(f"Created: {path}")
    return path


if __name__ == "__main__":
    draw_social_preview()
    for size in [16, 32, 64, 128, 256, 512]:
        draw_logo(size)
    print("\nAll graphics generated successfully!")
