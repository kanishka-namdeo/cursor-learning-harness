"""
Convert SVG files to PNG using cairosvg.
"""
import subprocess
import sys

try:
    import cairosvg
except ImportError:
    print("Installing cairosvg...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "cairosvg"])
    import cairosvg

from pathlib import Path

assets_dir = Path(__file__).parent

# Convert social preview
svg_path = assets_dir / "social-preview.svg"
png_path = assets_dir / "social-preview.png"
cairosvg.svg2png(url=str(svg_path), write_to=str(png_path), output_width=1280, output_height=640)
print(f"Created: {png_path}")

# Convert logo
svg_path = assets_dir / "logo.svg"
png_path = assets_dir / "logo.png"
cairosvg.svg2png(url=str(svg_path), write_to=str(png_path), output_width=512, output_height=512)
print(f"Created: {png_path}")

# Also create favicon sizes
for size in [16, 32, 192]:
    png_path = assets_dir / f"logo-{size}x{size}.png"
    cairosvg.svg2png(url=str(assets_dir / "logo.svg"), write_to=str(png_path), output_width=size, output_height=size)
    print(f"Created: {png_path}")

print("\nAll graphics converted successfully!")
