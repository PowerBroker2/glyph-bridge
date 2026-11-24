from pathlib import Path
from typing import Optional

import requests
import typer

from .core import export_header, fetch_font_family, find_font_path, get_glyph_data

app = typer.Typer(no_args_is_help=True, help="Generate bitmap font headers for PixelPlanner.")


@app.command()
def run(
    family: Optional[str] = typer.Option(None, help="Google Fonts family name."),
    style: str = typer.Option("Regular", help="Font style or named variable-font instance."),
    size: int = typer.Option(50, min=1, max=1024, help="Rasterization size in pixels."),
    export: bool = typer.Option(False, "--export", help="Write a C++ header."),
    output: Path = typer.Option(Path("."), help="Header output directory."),
    char: str = typer.Option("A", help="Character to preview."),
    font_file: Optional[Path] = typer.Option(None, "--font-file", exists=True, dir_okay=False,
                                            readable=True, help="Use a local font without downloading."),
    preview: Optional[bool] = typer.Option(None, "--preview/--no-preview", help="Show a glyph preview."),
    charset: Optional[str] = typer.Option(None, help="Export only these ASCII characters."),
):
    if bool(family) == bool(font_file):
        raise typer.BadParameter("Choose either --family or --font-file.")
    if not export and preview is False:
        raise typer.BadParameter("Select --export or enable the preview.")
    show_preview = preview if preview is not None else not export
    if show_preview and len(char) != 1:
        raise typer.BadParameter("Provide exactly one character.", param_hint="--char")

    try:
        if font_file is None:
            path, fake = find_font_path(family, style, allow_partial=False)
            if path is None:
                fetch_font_family(family)
                path, fake = find_font_path(family, style)
            if path is None:
                raise ValueError(f"Could not find {family} in style {style}")
        else:
            path, fake = font_file, False
            family = font_file.stem
        if export:
            header = export_header(path, family, style, size, fake, output, chars=charset)
            typer.echo(f"Header saved to: {header}")
        if show_preview:
            import matplotlib.pyplot as plt

            data = get_glyph_data(char, path, size, fake, style=style)
            plt.imshow(data, cmap="binary", vmin=0, vmax=1, interpolation="nearest")
            plt.axis("off")
            plt.show()
    except (OSError, ValueError, RuntimeError, requests.RequestException) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc


def main():
    app()


if __name__ == "__main__":
    main()
