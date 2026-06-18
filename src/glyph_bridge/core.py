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
    bbox = font.getbbox(char)
    
    # Robust fallback for space character or empty glyph blocks
    if bbox is None:
        w = max(1, int(font.getlength(char))) if hasattr(font, 'getlength') else size // 3
        h = size
        left, top, right, bottom = 0, 0, w, h
    else:
        left, top, right, bottom = bbox
        
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
    
    chars = string.ascii_letters + string.digits + string.punctuation + " "
    glyph_cache = {}
    max_h = 0
    
    # Pass 1: Cache glyphs and calculate dimensions
    for char in chars:
        try:
            data = get_glyph_data(char, font_path, size, is_fake_italic)
            true_coords = np.argwhere(data)
            if true_coords.size > 0:
                min_y, min_x = true_coords.min(axis=0)
                max_y, max_x = true_coords.max(axis=0)
                char_w = int(max_x - min_x + 1)
                tight_data = data[min_y : max_y + 1, min_x : max_x + 1]
            else:
                char_w = data.shape[1]
                tight_data = data[0:1, :]
                
            gh, gw = tight_data.shape
            glyph_cache[char] = (tight_data, char_w)
            max_h = max(max_h, gh)
        except: continue

    # Pass 2: Write header file
    with open(filename, 'w') as f:
        f.write(f"#ifndef {namespace.upper()}_H\n#define {namespace.upper()}_H\n\n")
        f.write("#include <Arduino.h>\n\n")
        
        # --- GLOBAL COMMON CLASS DEFINITION ---
        # Guarded so it safely compiles only once across all imported fonts
        f.write("#ifndef CUSTOM_BITMAP_FONT_H\n")
        f.write("#define CUSTOM_BITMAP_FONT_H\n")
        f.write("struct Glyph {\n")
        f.write("  const bool* data;\n")
        f.write("  int width;\n")
        f.write("};\n\n")
        f.write("class BitmapFont {\n")
        f.write("public:\n")
        f.write("  typedef Glyph (*LookupFunc)(char);\n")
        f.write("private:\n")
        f.write("  LookupFunc _lookup;\n")
        f.write("  int _height;\n")
        f.write("public:\n")
        f.write("  BitmapFont(LookupFunc lookup, int height) : _lookup(lookup), _height(height) {}\n")
        f.write("  inline Glyph lookupChar(char c) const { return _lookup(c); }\n")
        f.write("  inline int getHeight() const { return _height; }\n")
        f.write("};\n")
        f.write("#endif // CUSTOM_BITMAP_FONT_H\n\n")
        
        # --- FONT SPECIFIC DATA ---
        f.write(f"namespace {namespace} {{\n\n")
        
        # Write left-justified, bottom-aligned PROGMEM blocks
        for char, (tight_data, char_w) in glyph_cache.items():
            gh, gw = tight_data.shape
            f.write(f"  const bool {get_safe_name(char)}[{max_h}][{char_w}] PROGMEM = {{\n")
            v_offset = max_h - gh
            
            for y in range(max_h):
                f.write("    {")
                row_str = []
                for x in range(char_w):
                    data_y = y - v_offset
                    if 0 <= data_y < gh:
                        row_str.append("true" if tight_data[data_y, x] else "false")
                    else:
                        row_str.append("false")
                f.write(", ".join(row_str) + "},\n")
            f.write("  };\n\n")
        
        # Internal unique lookup wrapper
        f.write(f"  inline Glyph internalLookup(char c) {{\n")
        f.write(f"    switch(c) {{\n")
        for char, (tight_data, char_w) in glyph_cache.items():
            safe_char = char
            if char == '\\': safe_char = "\\\\"
            elif char == "'": safe_char = "\\'"
            f.write(f"      case '{safe_char}': return {{ (const bool*){get_safe_name(char)}, {char_w} }};\n")
        f.write(f"      default: return {{ nullptr, 0 }};\n")
        f.write(f"    }}\n")
        f.write(f"  }}\n\n")
        
        f.write(f"  const int GLYPH_HEIGHT = {max_h};\n\n")
        
        # --- EXPOSE THE UNIFIED INTERFACE INSTANCE ---
        f.write(f"  // Shared interface instance of common type 'BitmapFont'\n")
        f.write(f"  const BitmapFont Font(internalLookup, GLYPH_HEIGHT);\n\n")
        
        f.write(f"}} // namespace {namespace}\n\n#endif")
    return filename