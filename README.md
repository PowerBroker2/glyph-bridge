# Font Pixel Generator

A robust, modular CLI tool and Python library designed to bridge the gap between high-quality typography and embedded systems. This tool rasterizes TTF font files from the Google Fonts library into clean, C++ compatible header files for use in memory-constrained GUI projects.

## Overview

Working with embedded displays often requires custom, bitmap-based fonts. This tool automates the process of finding fonts, rasterizing specific characters into boolean arrays, and exporting them as C++ constants. It includes intelligent symbol mapping to ensure all exported character variables adhere to C++ naming conventions.

## Features

- **Automated Repository Handling:** Automatically downloads and manages a local cache of the Google Fonts repository.
- **Fuzzy Font Discovery:** Easily find and select fonts by family name and style variant.
- **C++ Header Generation:** Exports character data into `.h` files with namespaced structures.
- **Symbol Safety:** Automatically maps non-alphanumeric characters (like `#` or `@`) to safe, readable names (e.g., `char_hash`, `char_at`).
- **Visual Previewing:** Uses `matplotlib` to render and display a pixel preview of your selected character before finalizing your export.

## Installation

Clone the repository:

```bash
pip install glyph-bridge
```

## CLI Reference

You can run the tool directly from your terminal:

```bash
glyph-bridge \
  --family "Inter" \
  --style "Regular" \
  --size 48 \
  --export \
  --output "./include/fonts" \
  --char "A"
```

### Argument Details

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--family` | String | Required | The name of the font family (e.g., `"Roboto"`). |
| `--style` | String | `"Regular"` | The specific weight/variant (e.g., `"Bold"`). |
| `--size` | Integer | `50` | Font height in pixels. |
| `--export` | Flag | `False` | If set, generates a `.h` file. |
| `--output` | String | `"."` | The target directory for the header. |
| `--char` | String | `"A"` | The character to visualize in the preview. |

## Library API Usage

Beyond the CLI, `font_gen` can be imported into your own Python automation scripts:

```python
from font_gen import get_glyph_data, export_header

# 1. Generate glyph data (returns a NumPy boolean array)
pixel_data = get_glyph_data(
    char="A",
    font_path="path/to/font.ttf",
    size=48,
    is_fake_italic=False
)

# 2. Export an entire set to a C++ header
export_header(
    font_path="path/to/font.ttf",
    fam="Inter",
    sty="Regular",
    size=48,
    is_fake_italic=False,
    output_dir="./gui_assets"
)
```

## How It Works

1. **Rasterization:** Uses the Pillow library to render text to an off-screen buffer.
2. **Thresholding:** Converts grayscale pixel data into a `bool` array (`true` for foreground, `false` for background).
3. **Serialization:** Writes the data as a namespaced C++ constant array, sanitizing special symbols to prevent compilation errors.

## License & Requirements

**Requirements:** `numpy`, `matplotlib`, `Pillow`, `requests`