import argparse
from .core import setup_font_repo, find_font_path, get_glyph_data, export_header
import matplotlib.pyplot as plt

def main():
    parser = argparse.ArgumentParser(description="Generate font headers for PixelPlanner.")
    parser.add_argument("--family", required=True, help="Font family name")
    parser.add_argument("--style", default="Regular", help="Font style")
    parser.add_argument("--size", type=int, default=50, help="Pixel size")
    parser.add_argument("--export", action="store_true", help="Generate header file")
    parser.add_argument("--output", default=".", help="Directory to save the header file")
    parser.add_argument("--char", default="A", help="Character to visualize")
    
    args = parser.parse_args()
    
    setup_font_repo()
    path, is_fake = find_font_path(args.family, args.style)
    
    if not path:
        print(f"Error: Could not find {args.family} {args.style}")
        return

    if args.export:
        filename = export_header(path, args.family, args.style, args.size, is_fake, args.output)
        print(f"Header saved to: {filename}")
        
    data = get_glyph_data(args.char, path, args.size, is_fake)
    plt.imshow(data, cmap='binary')
    plt.axis('off')
    plt.show()