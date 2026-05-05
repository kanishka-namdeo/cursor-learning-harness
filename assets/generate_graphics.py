"""
Generate repository graphics using Pillow - modern, clean design.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import math
import random

assets_dir = Path(__file__).parent


def hex_to_rgb(h):
    return tuple(int(h.lstrip("#")[i:i+2], 16) for i in (0, 2, 4))


# GitHub-inspired color palette
BLUE = hex_to_rgb("#3b82f6")
BLUE_LIGHT = hex_to_rgb("#60a5fa")
PURPLE = hex_to_rgb("#8b5cf6")
PURPLE_LIGHT = hex_to_rgb("#a78bfa")
CYAN = hex_to_rgb("#06b6d4")
CYAN_LIGHT = hex_to_rgb("#22d3ee")
GREEN = hex_to_rgb("#10b981")
GREEN_LIGHT = hex_to_rgb("#34d399")
BG_DARK = hex_to_rgb("#0a0f1a")
BG_CARD = hex_to_rgb("#161b22")
BORDER = hex_to_rgb("#30363d")
TEXT_PRIMARY = hex_to_rgb("#e6edf3")
TEXT_SECONDARY = hex_to_rgb("#8b949e")


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


def add_glow_blur(img, radius=10, alpha=0.3):
    """Add a glow effect by creating a blurred copy overlaid at lower opacity."""
    blurred = img.filter(ImageFilter.GaussianBlur(radius=radius))
    result = Image.blend(img, blurred, alpha)
    return result


def draw_social_preview():
    """Create the 1280x640 social preview image."""
    img = Image.new("RGB", (1280, 640), BG_DARK)
    draw = ImageDraw.Draw(img)

    # Subtle dot grid pattern
    for x in range(0, 1280, 25):
        for y in range(0, 640, 25):
            if random.random() < 0.03:
                draw.ellipse([(x-1, y-1), (x+1, y+1)], fill=(255, 255, 255, 8))

    # Ambient glow patches
    for x in range(300):
        for y in range(400):
            dist = math.sqrt((x-200)**2 + (y-250)**2)
            if dist < 300:
                alpha = int(30 * (1 - dist/300))
                draw.point((x, y), fill=(59, 130, 246, alpha))
    
    for x in range(1000, 1280):
        for y in range(200, 600):
            dist = math.sqrt((x-1150)**2 + (y-400)**2)
            if dist < 250:
                alpha = int(25 * (1 - dist/250))
                draw.point((x, y), fill=(139, 92, 246, alpha))

    # LEFT SIDE: Neural network visualization
    random.seed(42)  # Reproducibility
    
    # Layer positions
    input_x = 120
    hidden1_x = 220
    hidden2_x = 340
    output_x = 440
    
    input_nodes_y = [150, 230, 310, 390]
    hidden1_nodes_y = [120, 190, 260, 330, 400]
    hidden2_nodes_y = [160, 240, 320, 400]
    output_node_y = 280
    
    # Draw connections
    # Input to hidden1
    for iy in input_nodes_y:
        for hy in hidden1_nodes_y:
            alpha = random.randint(20, 80)
            draw.line(
                [(input_x, iy), (hidden1_x, hy)],
                fill=(59, 130, 246, alpha),
                width=random.choice([1, 2])
            )
    
    # Hidden1 to hidden2
    for hy1 in hidden1_nodes_y:
        for hy2 in hidden2_nodes_y:
            alpha = random.randint(20, 80)
            draw.line(
                [(hidden1_x, hy1), (hidden2_x, hy2)],
                fill=(139, 92, 246, alpha),
                width=random.choice([1, 2])
            )
    
    # Hidden2 to output
    for hy2 in hidden2_nodes_y:
        alpha = random.randint(40, 100)
        draw.line(
            [(hidden2_x, hy2), (output_x, output_node_y)],
            fill=(6, 182, 212, alpha),
            width=2
        )
    
    # Draw nodes
    # Input layer
    for y in input_nodes_y:
        r = random.randint(6, 10)
        draw.ellipse([(input_x-r, y-r), (input_x+r, y+r)], fill=BLUE)
        draw.ellipse([(input_x-r//2, y-r//2), (input_x+r//2, y+r//2)], fill=BLUE_LIGHT)
    
    # Hidden layer 1
    for y in hidden1_nodes_y:
        r = random.randint(8, 12)
        draw.ellipse([(hidden1_x-r, y-r), (hidden1_x+r, y+r)], fill=PURPLE)
        draw.ellipse([(hidden1_x-r//2, y-r//2), (hidden1_x+r//2, y+r//2)], fill=PURPLE_LIGHT)
    
    # Hidden layer 2
    for y in hidden2_nodes_y:
        r = random.randint(8, 14)
        draw.ellipse([(hidden2_x-r, y-r), (hidden2_x+r, y+r)], fill=PURPLE)
        draw.ellipse([(hidden2_x-r//2, y-r//2), (hidden2_x+r//2, y+r//2)], fill=PURPLE_LIGHT)
    
    # Output node (larger, glowing)
    for r_offset in [40, 30, 20]:
        alpha = int(40 * (1 - r_offset/40))
        draw.ellipse(
            [(output_x-r_offset, output_node_y-r_offset), (output_x+r_offset, output_node_y+r_offset)],
            fill=(6, 182, 212, alpha)
        )
    draw.ellipse([(output_x-14, output_node_y-14), (output_x+14, output_node_y+14)], fill=CYAN)
    draw.ellipse([(output_x-7, output_node_y-7), (output_x+7, output_node_y+7)], fill=CYAN_LIGHT)

    # RIGHT SIDE: Content cards
    
    font_title = get_font(40)
    font_subtitle = get_font(16)
    font_card_title = get_font(15)
    font_card_text = get_font(12)

    # Main title
    draw.text((680, 160), "Cursor Learning Agent", font=font_title, fill=BLUE_LIGHT)
    
    # Subtitle
    draw.text(
        (680, 210),
        "Self-improving AI coding assistant powered by LangGraph & LangChain",
        font=font_subtitle,
        fill=TEXT_SECONDARY
    )
    
    # Accent line under title
    gradient_points = []
    for i in range(500):
        t = i / 500
        if t < 0.33:
            color = BLUE
        elif t < 0.66:
            color = PURPLE
        else:
            color = CYAN
        gradient_points.append((680 + i, 240, color))
    for x, y, color in gradient_points:
        draw.point((x, y), fill=color)
    draw.line([(680, 240), (1180, 240)], fill=PURPLE, width=2)

    # Feature cards - 2x2 grid
    cards = [
        (680, 270, "Session Recording", BLUE, [
            "Captures full IDE lifecycle",
            "20 event types via hooks",
            "JSON + SQLite dual storage",
        ]),
        (940, 270, "AI Summarization", PURPLE, [
            "LangGraph StateGraph agent",
            "Session & conversation-level",
            "Human-readable narratives",
        ]),
        (680, 410, "Sentiment Analysis", CYAN, [
            "8 session archetypes",
            "HuggingFace RoBERTa scoring",
            "Geometric feature analysis",
        ]),
        (940, 410, "Self-Improving Loop", GREEN, [
            "Pattern extraction & scoring",
            "Auto-generated Cursor rules",
            "10 categories of signals",
        ]),
    ]
    
    card_w, card_h = 240, 120
    
    for cx, cy, title, color, lines in cards:
        # Card background
        draw.rounded_rectangle(
            [(cx, cy), (cx + card_w, cy + card_h)],
            radius=10,
            fill=BG_CARD,
            outline=BORDER,
            width=1,
        )
        
        # Icon circle
        icon_x = cx + 20
        icon_y = cy + 18
        draw.ellipse([(icon_x-10, icon_y-10), (icon_x+10, icon_y+10)], fill=color + (50,))
        draw.ellipse([(icon_x-7, icon_y-7), (icon_x+7, icon_y+7)], fill=color + (100,))
        
        # Card title
        draw.text((cx + 38, cy + 12), title, font=font_card_title, fill=TEXT_PRIMARY)
        
        # Card bullet points
        for i, line in enumerate(lines):
            dot_x = cx + 16
            dot_y = cy + 42 + i * 20
            draw.ellipse([(dot_x-2, dot_y-2), (dot_x+2, dot_y+2)], fill=color)
            draw.text((cx + 28, cy + 37 + i * 20), line, font=font_card_text, fill=TEXT_SECONDARY)

    # Bottom accent line
    for i in range(1280):
        t = i / 1280
        if t < 0.5:
            alpha = int(100 * math.sin(math.pi * t * 2))
            color = (BLUE[0], BLUE[1], BLUE[2], alpha)
        else:
            alpha = int(100 * math.sin(math.pi * (t-0.5) * 2))
            color = (CYAN[0], CYAN[1], CYAN[2], alpha)
        draw.point((i, 620), fill=color[:3])

    path = assets_dir / "social-preview.png"
    img.save(path, "PNG")
    print(f"Created: {path}")
    return path


def draw_logo(size=512):
    """Create a clean neural network logo."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx, cy = size // 2, size // 2
    bg_r = int(size * 0.46)

    # Rounded background
    draw.rounded_rectangle(
        [(cx-bg_r, cy-bg_r), (cx+bg_r, cy+bg_r)],
        radius=int(size * 0.15),
        fill=BG_DARK + (255,)
    )
    
    # Border
    draw.rounded_rectangle(
        [(cx-bg_r+2, cy-bg_r+2), (cx+bg_r-2, cy+bg_r-2)],
        radius=int(size * 0.15),
        outline=BORDER + (100,),
        width=1
    )

    # Neural network
    random.seed(42)
    scale = size / 512
    
    layers_x = [int(80*scale), int(170*scale), int(280*scale), int(380*scale)]
    layers_y = [
        [int(140*scale), int(220*scale), int(300*scale), int(380*scale)],
        [int(100*scale), int(180*scale), int(256*scale), int(336*scale), int(416*scale)],
        [int(150*scale), int(230*scale), int(310*scale), int(390*scale)],
        [int(256*scale)],
    ]
    layer_colors = [
        BLUE, PURPLE, CYAN
    ]
    
    # Draw connections between layers
    for l in range(len(layers_x) - 1):
        for y1 in layers_y[l]:
            for y2 in layers_y[l+1]:
                color = layer_colors[l]
                alpha = random.randint(30, 90)
                draw.line(
                    [(layers_x[l], y1), (layers_x[l+1], y2)],
                    fill=color + (alpha,),
                    width=random.choice([1, 2])
                )
    
    # Draw nodes
    node_sizes = [int(8*scale), int(10*scale), int(10*scale), int(14*scale)]
    node_colors_light = [BLUE_LIGHT, PURPLE_LIGHT, CYAN_LIGHT, CYAN_LIGHT]
    
    for l in range(len(layers_x)):
        for y in layers_y[l]:
            r = node_sizes[l]
            color = layer_colors[min(l, 2)]
            color_light = node_colors_light[l]
            
            draw.ellipse(
                [(layers_x[l]-r, y-r), (layers_x[l]+r, y+r)],
                fill=color + (230,)
            )
            draw.ellipse(
                [(layers_x[l]-r//2, y-r//2), (layers_x[l]+r//2, y+r//2)],
                fill=color_light + (200,)
            )
    
    # Central cursor arrow overlay
    arrow_scale = size / 512
    arrow = [
        (cx, cy - int(20*arrow_scale)),
        (cx - int(12*arrow_scale), cy + int(15*arrow_scale)),
        (cx - int(2*arrow_scale), cy + int(8*arrow_scale)),
        (cx - int(8*arrow_scale), cy + int(24*arrow_scale)),
        (cx + int(4*arrow_scale), cy + int(18*arrow_scale)),
        (cx + int(12*arrow_scale), cy + int(8*arrow_scale)),
        (cx + int(2*arrow_scale), cy + int(20*arrow_scale)),
    ]
    # Dark background
    draw.polygon(arrow, fill=BG_DARK + (200,))
    # Purple foreground (slightly smaller)
    inner_arrow = [
        (cx, cy - int(16*arrow_scale)),
        (cx - int(9*arrow_scale), cy + int(12*arrow_scale)),
        (cx - int(1*arrow_scale), cy + int(6*arrow_scale)),
        (cx - int(6*arrow_scale), cy + int(20*arrow_scale)),
        (cx + int(3*arrow_scale), cy + int(14*arrow_scale)),
        (cx + int(9*arrow_scale), cy + int(6*arrow_scale)),
        (cx + int(1*arrow_scale), cy + int(16*arrow_scale)),
    ]
    draw.polygon(inner_arrow, fill=PURPLE + (230,))

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
