# Glyph Bridge

Turn a Google Fonts family or a local font file into a C++ bitmap font for [PixelPlanner](https://github.com/PowerBroker2/PixelPlanner).

## Install

Use Python 3.9 or newer. Install the published package with `python -m pip install glyph-bridge`, or run `python -m pip install .` from this checkout to use the features documented here.

## Desktop app

Run `glyph-bridge-gui` after installing from this checkout, or run `python -m glyph_bridge.gui` in the same Python environment. The desktop app requires Tkinter, which is included with standard Windows and macOS Python installers. Some Linux distributions package it separately.

1. Choose **Google Fonts** or **Local fonts**. The font dropdown lists the available families or installed faces. Use **Choose folder…** to scan a different directory.
2. Select a font. **Weight** and **Italic** reflect the styles available for that font. If a style from the previous font is unavailable, the app selects an available style and continues. Toggle **Strikethrough** or choose **Normal**, **Superscript**, or **Subscript** for vertical position. The preview updates automatically, and the effects are baked into the exported glyphs.
3. Under **Characters to export**, choose **All printable ASCII** for all 95 glyphs, **Only preview characters** for the distinct characters you typed in the preview, or **Custom characters** to type an explicit list like `READY 0123456789`. Case matters and spaces count.
4. Choose your sketch folder and click **Export header**. Open the output folder from the app when it's ready.

## Export a font

```sh
glyph-bridge --family "Inter" --style Bold --size 24 --export --output ./MySketch
```

The command writes `font_inter_bold_24.h`. On first use it downloads just the requested Google Fonts family and caches it with any accompanying license. Set `GLYPH_BRIDGE_CACHE` to override the cache location. Named variable-font styles such as Bold use their actual font instance when available.

To work offline or use your own font, pass `--font-file` instead of `--family`.

```sh
glyph-bridge --font-file ./MyFont.ttf --size 24 --export --output ./MySketch
```

Exports contain printable ASCII by default. Use `--charset "READY 0123456789"` to export just those characters and reduce flash usage. Check the font's license before distributing generated bitmaps.

## Draw with PixelPlanner

Place the generated header next to your Arduino sketch. The header's base name is also the C++ namespace.

```cpp
#include <PixelPlanner.h>
#include "font_inter_bold_24.h"

Pixmap<160, 40> label;

void drawLabel()
{
    label.clear();
    label.print(2, 2, "Ready", font_inter_bold_24::Font, WHITE);
}
```

Glyphs share a baseline, so descenders in letters such as `g` and `y` hang below it. Pass the pixmap's `getPixels()` and `getMask()` to TeensyTFT's `fillRegion()`, then call `swap()` to display it. Existing PixelPlanner bitmaps and generated headers use the same `BitmapFont` interface.

## Preview and automate

Run with `--char g` and omit `--export` to preview one glyph. Exports run without opening a window by default. Add `--preview` to export and preview in one command. Use `glyph-bridge --help` for the full Typer CLI.

```python
from glyph_bridge import export_header, get_glyph_data

pixels = get_glyph_data("A", "MyFont.ttf", 24)
path = export_header("MyFont.ttf", "MyFont", "Regular", 24, False, "MySketch")
```

`get_glyph_data()` returns a two-dimensional NumPy Boolean array. Use `fetch_font_family()` and `find_font_path()` for individual Google Fonts families, or `setup_font_repo()` to populate the full TTF catalog for offline lookup.
