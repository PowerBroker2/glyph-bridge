import os
import requests
import zipfile
import shutil
import string
import numpy as np
from PIL import Image, ImageFont, ImageDraw

# Internal Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EXTRACTED_DIR = os.path.join(SCRIPT_DIR, "fonts-main")
ZIP_NAME = os.path.join(SCRIPT_DIR, "fonts-main.zip")
REPO_URL = "https://github.com/google/fonts/archive/main.zip"

SYMBOL_NAMES = {
    ' ': 'space', '!': 'exclam', '"': 'quote', '#': 'hash', '$': 'dollar',
    '%': 'percent', '&': 'amp', "'": 'apostrophe', '(': 'lparen', ')': 'rparen',
    '*': 'asterisk', '+': 'plus', ',': 'comma', '-': 'minus', '.': 'period',
    '/': 'slash', ':': 'colon', ';': 'semicolon', '<': 'less', '=': 'equal',
    '>': 'greater', '?': 'question', '@': 'at', '[': 'lbracket', '\\': 'backslash',
    ']': 'rbracket', '^': 'caret', '_': 'underscore', '`': 'backtick', '{': 'lbrace',
    '|': 'pipe', '}': 'rbrace', '~': 'tilde'
}

def setup_font_repo():
    """Downloads and extracts the Google Fonts repository if not present."""
    if not os.path.exists(EXTRACTED_DIR):
        response = requests.get(REPO_URL, stream=True)
        with open(ZIP_NAME, 'wb') as f:
            shutil.copyfileobj(response.raw, f)
        with zipfile.ZipFile(ZIP_NAME, 'r') as zip_ref:
            zip_ref.extractall(SCRIPT_DIR)
        os.remove(ZIP_NAME)

def find_font_path(family, style):
    family_query = family.replace(" ", "").lower()
    style_query = style.replace(" ", "").lower()
    for root, _, files in os.walk(EXTRACTED_DIR):
        for file in files:
            f_lower = file.lower()
            if family_query in f_lower and file.endswith(".ttf"):
                if style_query in f_lower or ("[" in f_lower and "]" in f_lower):
                    return os.path.join(root, file), False
    return None, False

def get_glyph_data(char, font_path, size, is_fake_italic):
    font = ImageFont.truetype(font_path, size)
    left, top, right, bottom = font.getbbox(char)
    w, h = max(1, right - left), max(1, bottom - top)
    
    img = Image.new('L', (w, h), color=0)
    draw = ImageDraw.Draw(img)
    draw.text((-left, -top), char, font=font, fill=255)
    
    if is_fake_italic:
        shear_factor = 0.3
        extra_w = int(h * shear_factor)
        new_w = w + extra_w
        new_img = Image.new('L', (new_w, h), color=0)
        new_img.paste(img, (0, 0))
        img = new_img.transform((new_w, h), Image.AFFINE, (1, shear_factor, -extra_w, 0, 1, 0))
        w = new_w
        
    return np.array([[img.getpixel((x, y)) > 128 for x in range(w)] for y in range(h)])

def get_safe_name(char):
    if char.isalnum(): return f"char_{char}"
    return f"char_{SYMBOL_NAMES.get(char, 'unknown')}"

def export_header(font_path, fam, sty, size, is_fake_italic, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    namespace = f"font_{fam.replace(' ','_')}_{sty.replace(' ','_')}_{size}".lower()
    filename = os.path.join(output_dir, f"{namespace}.h")
    
    chars = string.ascii_letters + string.digits + string.punctuation
    glyph_cache = {}
    max_w, max_h = 0, 0
    
    # Pass 1: Cache glyphs and find dimensions
    for char in chars:
        try:
            data = get_glyph_data(char, font_path, size, is_fake_italic)
            h, w = data.shape
            glyph_cache[char] = data
            max_w, max_h = max(max_w, w), max(max_h, h)
        except: continue

    # Pass 2: Write header file
    with open(filename, 'w') as f:
        f.write(f"#ifndef {namespace.upper()}_H\n#define {namespace.upper()}_H\n\n")
        f.write("#include <Arduino.h>\n\n")
        f.write(f"namespace {namespace} {{\n\n")
        
        # Write glyph arrays with padding and PROGMEM
        for char, data in glyph_cache.items():
            f.write(f"  const bool {get_safe_name(char)}[{max_h}][{max_w}] PROGMEM = {{\n")
            for y in range(max_h):
                f.write("    {")
                row_str = ["true" if (y < data.shape[0] and x < data.shape[1] and data[y, x]) else "false" for x in range(max_w)]
                f.write(", ".join(row_str) + "},\n")
            f.write("  };\n\n")
        
        # Write lookup function
        f.write(f"  inline const bool* lookupChar(char c) {{\n")
        f.write(f"    switch(c) {{\n")
        for char, data in glyph_cache.items():
            f.write(f"      case '{char}': return (const bool*){get_safe_name(char)};\n")
        f.write(f"      default: return nullptr;\n")
        f.write(f"    }}\n")
        f.write(f"  }}\n\n")
        
        # Helper to export constants for user
        f.write(f"  const int GLYPH_WIDTH = {max_w};\n")
        f.write(f"  const int GLYPH_HEIGHT = {max_h};\n\n")
        
        f.write(f"}} // namespace {namespace}\n\n#endif")
    return filename