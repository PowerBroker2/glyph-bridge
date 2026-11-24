"""Google Fonts discovery, bitmap rasterization, and PixelPlanner header export."""

import os
from pathlib import Path, PurePosixPath
import re
import shutil
import string
from tempfile import TemporaryDirectory, NamedTemporaryFile
from urllib.parse import quote
import zipfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import requests

SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_DIR = (Path(os.environ["GLYPH_BRIDGE_CACHE"]) if os.environ.get("GLYPH_BRIDGE_CACHE")
             else Path(os.environ.get("XDG_CACHE_HOME") or
                       os.environ.get("LOCALAPPDATA") or Path.home() / ".cache") / "glyph-bridge")
EXTRACTED_DIR = CACHE_DIR / "fonts-main"
REPO_URL = "https://github.com/google/fonts/archive/main.zip"
DEFAULT_CHARSET = string.ascii_letters + string.digits + string.punctuation + " "
LICENSE_FILES = {"ofl.txt", "ufl.txt", "license", "license.txt"}

SYMBOL_NAMES = dict(zip(" " + string.punctuation, (
    "space exclam quote hash dollar percent amp apostrophe lparen rparen star plus comma minus "
    "period slash colon semicolon less equal greater question at lbracket backslash rbracket "
    "caret underscore backtick lbrace pipe rbrace tilde"
).split()))

FONT_INTERFACE = """#ifndef CUSTOM_BITMAP_FONT_H
#define CUSTOM_BITMAP_FONT_H

struct Glyph {
  const bool* data;
  int width;
};

class BitmapFont {
public:
  typedef Glyph (*LookupFunc)(char);
private:
  LookupFunc _lookup;
  int _height;
public:
  BitmapFont(LookupFunc lookup, int height) : _lookup(lookup), _height(height) {}
  inline Glyph lookupChar(char c) const { return _lookup(c); }
  inline int getHeight() const { return _height; }
};

#endif // CUSTOM_BITMAP_FONT_H
"""


def _font_root():
    root = Path(EXTRACTED_DIR)
    legacy = SCRIPT_DIR / "fonts-main"
    if not root.exists() and not os.environ.get("GLYPH_BRIDGE_CACHE") and legacy.is_dir():
        return legacy
    return root


def setup_font_repo():
    """Populate the user cache with Google Fonts TTF files on first use."""
    root = _font_root()
    if root.is_dir():
        return

    root.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=root.parent, prefix="download-") as scratch:
        archive = Path(scratch) / "fonts.zip"
        with requests.get(REPO_URL, stream=True, timeout=(10, 60)) as response:
            response.raise_for_status()
            with archive.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    output.write(chunk)

        staged = Path(scratch) / "fonts-main"
        try:
            with zipfile.ZipFile(archive) as fonts:
                for member in fonts.infolist():
                    parts = PurePosixPath(member.filename).parts
                    if (len(parts) < 3 or parts[0] != "fonts-main" or
                            parts[1] not in {"ofl", "apache", "ufl"} or
                            any(not re.fullmatch(r"[A-Za-z0-9_,.\[\]-]+", p) or p in {".", ".."}
                                for p in parts[1:]) or
                            not (parts[-1].lower().endswith(".ttf") or
                                 parts[-1].lower() in LICENSE_FILES)):
                        continue
                    target = staged.joinpath(*parts[1:])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with fonts.open(member) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
        except zipfile.BadZipFile as exc:
            raise ValueError("The Google Fonts download is not a valid archive.") from exc

        if not staged.is_dir() or not any(p.suffix.lower() == ".ttf" for p in staged.rglob("*")):
            raise ValueError("The downloaded archive does not contain any Google Fonts TTF files.")
        try:
            staged.rename(root)
        except OSError:
            if not root.is_dir():
                raise


def _normalize(value):
    return re.sub(r"[^a-z0-9]", "", value.lower())


def fetch_font_family(family):
    """Cache one Google Fonts family without downloading the entire catalog."""
    slug = _normalize(family)
    if not slug:
        raise ValueError("Provide a Google Fonts family name.")
    parent = CACHE_DIR / "families"
    destination = parent / slug
    if destination.is_dir():
        return True
    parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=parent, prefix="download-") as scratch:
        for section in ("ofl", "apache", "ufl"):
            staged = Path(scratch) / section
            relative = f"{section}/{slug}"
            url = f"https://api.github.com/repos/google/fonts/contents/{relative}"
            with requests.get(url, timeout=(10, 30)) as response:
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                entries = response.json()
            if not isinstance(entries, list):
                raise ValueError(f"Unexpected Google Fonts catalog response for {family!r}.")
            has_fonts = False
            for entry in entries:
                name = entry.get("name", "") if isinstance(entry, dict) else ""
                if not isinstance(name, str) or not name or entry.get("type") != "file":
                    continue
                is_font = re.fullmatch(r"[A-Za-z0-9_,.\[\]-]+\.ttf", name, re.IGNORECASE)
                if not is_font and name.lower() not in LICENSE_FILES:
                    continue
                staged.mkdir(exist_ok=True)
                asset = f"https://raw.githubusercontent.com/google/fonts/main/{relative}/{quote(name)}"
                with requests.get(asset, stream=True, timeout=(10, 60)) as response:
                    response.raise_for_status()
                    with (staged / name).open("wb") as output:
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            output.write(chunk)
                has_fonts = has_fonts or bool(is_font)
            if has_fonts:
                try:
                    staged.rename(destination)
                except OSError:
                    if not destination.is_dir():
                        raise
                return True
    return False


def _variation_names(font):
    try:
        names = {}
        italic = _normalize(font.getname()[1]).endswith("italic")
        for name in font.get_variation_names():
            key = _normalize(name.decode("utf-8", errors="replace"))
            if italic and not key.endswith("italic"):
                key = "italic" if key == "regular" else key + "italic"
            names[key] = name
        return names
    except OSError:
        return {}


def _family_files(family, *, allow_partial):
    family_key = _normalize(family)
    if not family_key:
        return []

    def file_family(path):
        if path.parent.parent.name in {"ofl", "apache", "ufl", "families"}:
            return _normalize(path.parent.name)
        return _normalize(path.stem.split("[", 1)[0].split("-", 1)[0])

    candidates = {}
    for root in (_font_root(), CACHE_DIR / "families"):
        for path in root.rglob("*"):
            if path.suffix.lower() == ".ttf" and not path.parent.parent.name.startswith("download-"):
                key = file_family(path)
                if family_key in key:
                    candidates.setdefault(key, []).append(path)
    if allow_partial and family_key not in candidates and len(candidates) == 1:
        family_key = next(iter(candidates))
    return sorted(set(candidates.get(family_key, [])))


def _native_font_styles(paths):
    styles = {}
    for path in paths:
        try:
            font = ImageFont.truetype(str(path), 12)
        except OSError:
            continue
        face = font.getname()[1]
        styles.setdefault(_normalize(face), (path, face))
        for key, name in _variation_names(font).items():
            label = name.decode("utf-8", errors="replace")
            if key.endswith("italic") and not _normalize(label).endswith("italic"):
                label = "Italic" if key == "italic" else f"{label} Italic"
            styles.setdefault(key, (path, label))
    return styles


def find_font_path(family, style, *, allow_partial=True):
    """Find an exact family and style, or synthesize an unavailable italic style."""
    style_key = _normalize(style)
    if not style_key:
        return None, False
    files = _family_files(family, allow_partial=allow_partial)
    synthetic = None
    for path in files:
        try:
            font = ImageFont.truetype(str(path), 12)
        except OSError:
            continue
        actual_style = _normalize(font.getname()[1])
        names = _variation_names(font)
        if style_key == actual_style or style_key in names or (
            style_key == "regular" and actual_style in {"normal", "book", "roman"}
        ):
            return str(path), False
        if style_key.endswith("italic"):
            upright = style_key[:-6] or "regular"
            if upright == actual_style or upright in names or (
                upright == "regular" and actual_style in {"normal", "book", "roman"}
            ):
                synthetic = str(path)
    return (synthetic, True) if synthetic else (None, False)


def _load_font(font_path, size, style, synthetic):
    if not isinstance(size, int) or not 1 <= size <= 1024:
        raise ValueError("Font size must be an integer between 1 and 1024.")
    font = ImageFont.truetype(os.fspath(font_path), size)
    key = _normalize(style)
    if synthetic and key.endswith("italic"):
        key = key[:-6] or "regular"
    names = _variation_names(font)
    if key in names:
        font.set_variation_by_name(names[key])
    elif names and key not in {"regular", _normalize(font.getname()[1])}:
        raise ValueError(f"Variable font has no named instance for {style!r}.")
    return font


def _render(font, char, box, synthetic, *, monochrome=False):
    left, top, right, bottom = box
    width, height = max(1, right - left), max(1, bottom - top)
    extra = int(height * 0.3) if synthetic and not char.isspace() else 0
    image = Image.new("L", (width + extra, height))
    draw = ImageDraw.Draw(image)
    if monochrome:
        draw.fontmode = "1"
    draw.text((-left, -top), char, font=font, anchor="ls", fill=255)
    if extra:
        image = image.transform(image.size, Image.Transform.AFFINE,
                                (1, 0.3, -extra, 0, 1, 0), Image.Resampling.BILINEAR)
    return np.asarray(image) > 128


def get_glyph_data(char, font_path, size, is_fake_italic=False, *, style="Regular"):
    """Rasterize one character as a 2D NumPy boolean array."""
    if len(char) != 1:
        raise ValueError("Provide exactly one character.")
    font = _load_font(font_path, size, style, is_fake_italic)
    return _render(font, char, font.getbbox(char, anchor="ls"), is_fake_italic)


def get_safe_name(char):
    if char in string.ascii_letters + string.digits:
        return f"char_{char}"
    return f"char_{SYMBOL_NAMES.get(char, f'u{ord(char):04x}')}"


def _identifier(value):
    return re.sub(r"[^a-zA-Z0-9]+", "_", value).lower().strip("_")


def _font_namespace(family, style, size, *, position="normal", strikethrough=False):
    name = f"font_{_identifier(family) or 'unnamed'}_{_identifier(style) or 'regular'}_{size}"
    if position != "normal":
        name += "_" + position
    if strikethrough:
        name += "_strike"
    return name


def _rasterize_glyphs(font_path, style, size, is_fake_italic, chars=None, *,
                      position="normal", strikethrough=False):
    chars = DEFAULT_CHARSET if chars is None else "".join(dict.fromkeys(chars))
    if not chars or any(not 32 <= ord(char) <= 126 for char in chars):
        raise ValueError("The export character set must contain only printable ASCII.")
    if position not in {"normal", "superscript", "subscript"}:
        raise ValueError("Choose normal, superscript, or subscript positioning.")
    font = _load_font(font_path, size, style, is_fake_italic)

    # Measure against a common baseline, independent of the exported subset.
    boxes = {char: font.getbbox(char, anchor="ls") for char in DEFAULT_CHARSET}
    top = min(box[1] for box in boxes.values())
    bottom = max(top + 1, max(box[3] for box in boxes.values()))
    height = bottom - top
    script = position != "normal"
    render_size = size
    if script:
        # Rasterize the outline at its final size, with monochrome hinting.
        # Resampling an existing 1-bit bitmap can drop fine stems and diagonals.
        render_size = max(1, round(size * 0.65))
        font = _load_font(font_path, render_size, style, is_fake_italic)
        boxes = {char: font.getbbox(char, anchor="ls", mode="1") for char in DEFAULT_CHARSET}
        top = min(box[1] for box in boxes.values())
        bottom = max(top + 1, max(box[3] for box in boxes.values()))
    render_height = bottom - top
    height = max(height, render_height)
    offset = height - render_height if position == "subscript" else 0
    glyphs = {}
    for char in chars:
        left, _, right, _ = boxes[char]
        # Preserve advance and side bearings within the legacy width-only glyph format.
        advance = font.getlength(char, mode="1") if script else font.getlength(char)
        box = min(left, 0), top, max(right, round(advance), 1), bottom
        ink = _render(font, char, box, is_fake_italic, monochrome=script)
        glyph = np.zeros((height, ink.shape[1]), dtype=bool)
        glyph[offset:offset + render_height] = ink
        if strikethrough:
            strike_row = max(0, min(render_height - 1, round(-top - 0.25 * render_size)))
            thickness = max(1, round(render_size * 0.055))
            end = offset + min(render_height, strike_row + thickness)
            glyph[offset + strike_row:end, :] = True
        glyphs[char] = glyph
    return height, glyphs


def export_header(font_path, fam, sty, size, is_fake_italic, output_dir, *, chars=None,
                  position="normal", strikethrough=False):
    """Export printable ASCII glyphs with a shared baseline and PixelPlanner's BitmapFont API."""
    effects = {"position": position, "strikethrough": strikethrough}
    height, glyphs = _rasterize_glyphs(font_path, sty, size, is_fake_italic, chars, **effects)
    namespace = _font_namespace(fam, sty, size, **effects)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    filename = output / f"{namespace}.h"

    temp_path = None
    try:
        with NamedTemporaryFile("w", dir=output, encoding="ascii", newline="\n",
                                delete=False) as header:
            temp_path = Path(header.name)
            header.write("#pragma once\n#include <Arduino.h>\n\n")
            header.write(FONT_INTERFACE)
            header.write(f"\nnamespace {namespace} {{\n\n")
            for char, glyph in glyphs.items():
                name = get_safe_name(char)
                header.write(f"  static const bool {name}[{height}][{glyph.shape[1]}] PROGMEM = {{\n")
                for row in glyph:
                    header.write("    {" + ", ".join("1" if pixel else "0" for pixel in row) + "},\n")
                header.write("  };\n\n")
            header.write("  static Glyph internalLookup(char c) {\n    switch (c) {\n")
            for char, glyph in glyphs.items():
                header.write(f"      case {ord(char)}: return {{ &{get_safe_name(char)}[0][0], {glyph.shape[1]} }};\n")
            header.write("      default: return { nullptr, 0 };\n    }\n  }\n\n")
            header.write(f"  const int GLYPH_HEIGHT = {height};\n")
            header.write("  const BitmapFont Font(internalLookup, GLYPH_HEIGHT);\n")
            header.write(f"\n}} // namespace {namespace}\n")
        temp_path.replace(filename)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return str(filename)
