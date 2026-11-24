"""Native Glyph Bridge desktop application."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
from threading import Thread

from PIL import Image, ImageFont
import requests

from .core import CACHE_DIR, DEFAULT_CHARSET, _family_files, _font_namespace, _native_font_styles
from .core import _normalize, _rasterize_glyphs, export_header, fetch_font_family

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from PIL import ImageTk
except ImportError:
    tk = None


PAPER = "#F1F3EE"
WHITE = "#FFFFFF"
INK = "#172C25"
MUTED = "#52635C"
LINE = "#D8E1D8"
ACCENT = "#D4F47B"
PANEL = "#162821"
PANEL_MUTED = "#A9BDB1"
SCREEN = "#0D1E17"
FONT = "Segoe UI" if sys.platform == "win32" else "TkDefaultFont"
SAMPLE = "Aa Bb Gg Yy 0123"
LOCAL_SOURCE = "Local fonts"
GOOGLE_SOURCE = "Google Fonts"
ALL_CHARACTERS = "All printable ASCII"
PREVIEW_CHARACTERS = "Only preview characters"
CUSTOM_CHARACTERS = "Custom characters"
FONT_EXTENSIONS = {".ttf", ".otf", ".ttc"}
WEIGHTS = ("Thin", "Extra Light", "Light", "Regular", "Medium",
           "SemiBold", "Bold", "Extra Bold", "Black")


@dataclass(frozen=True)
class FontSelection:
    path: Path
    family: str
    style: str
    synthetic: bool


def font_options(source, value):
    if source == LOCAL_SOURCE:
        path = Path(value).expanduser()
        if not path.is_file():
            raise ValueError("Choose a local font file.")
        files, family = [path], path.stem
    else:
        files = _family_files(value, allow_partial=False)
        if not files:
            fetch_font_family(value)
            files = _family_files(value, allow_partial=False)
        family = value

    options = {}
    for key, (path, style) in _native_font_styles(files).items():
        italic = key.endswith(("italic", "oblique"))
        weight = style
        if italic:
            suffix = 7 if key.endswith("oblique") else 6
            weight = style[:-suffix].strip()
        normalized = _normalize(weight)
        if normalized in {"", "regular", "normal", "book", "roman"}:
            weight = "Regular"
        else:
            weight = next((label for label in WEIGHTS if _normalize(label) == normalized), weight)
        options.setdefault((weight, italic), FontSelection(Path(path), family, style, False))
    if not options:
        raise ValueError(f'No usable font files were found for "{family}".')
    return options


def resolve_font(source, value, weight, italic, options=None):
    if options is None:
        options = font_options(source, value)
    requested = weight, italic
    if requested in options:
        chosen = requested
    else:
        chosen = next((key for key in (("Regular", italic), (weight, not italic), ("Regular", False))
                       if key in options), None)
        if chosen is None:
            chosen = next((key for key in options if key[1] == italic), next(iter(options)))
    selection = options[chosen]
    _rasterize_glyphs(selection.path, selection.style, 24, False, "A")
    return selection, options, chosen

def google_catalog():
    """List Google Fonts families without downloading the font files."""
    cache = CACHE_DIR / "gui-families.json"
    try:
        with requests.get("https://fonts.google.com/metadata/fonts", timeout=(4, 12)) as response:
            response.raise_for_status()
            payload = response.text.lstrip()
        if payload.startswith(")]}'"):
            payload = payload.partition("\n")[2]
        names = {entry["family"] for entry in json.loads(payload)["familyMetadataList"]
                 if isinstance(entry, dict) and isinstance(entry.get("family"), str) and entry["family"].strip()}
        if not names:
            raise ValueError("The Google Fonts catalog is empty.")
    except (requests.RequestException, ValueError, KeyError, TypeError):
        try:
            names = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            names = []
        cached = {name for name in names if isinstance(name, str) and name} if isinstance(names, list) else set()
        return sorted(cached, key=str.casefold), True
    names = sorted(names, key=str.casefold)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(names), encoding="utf-8")
    except OSError:
        pass
    return names, False


def local_font_roots():
    home = Path.home()
    if sys.platform == "win32":
        return (Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
                Path(os.environ.get("LOCALAPPDATA") or home) / "Microsoft/Windows/Fonts")
    if sys.platform == "darwin":
        return (Path("/System/Library/Fonts"), Path("/Library/Fonts"), home / "Library/Fonts")
    return (Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
            Path(os.environ.get("XDG_DATA_HOME") or home / ".local/share") / "fonts", home / ".fonts")


def local_catalog(folder=None):
    fonts = {}
    seen = set()
    for root in (Path(folder),) if folder else local_font_roots():
        for directory, _, files in os.walk(root):
            for name in sorted(files, key=str.casefold):
                path = Path(directory) / name
                if path.suffix.lower() not in FONT_EXTENSIONS or path in seen:
                    continue
                seen.add(path)
                try:
                    family, face = ImageFont.truetype(str(path), 12).getname()
                except OSError:
                    continue
                label = f"{family} · {face}"
                if label in fonts:
                    label = f"{label} ({path.name})"
                if label in fonts:
                    label = f"{label} — {path.parent}"
                fonts[label] = path
    return fonts


def bitmap_preview(selection, size, text, charset, **effects):
    """Lay out the same glyph cells used by the generated BitmapFont."""
    allowed = set(DEFAULT_CHARSET if charset is None else charset)
    rows = ["".join(c for c in row if c in allowed) for row in text.split("\n")[:3]]
    chars = "".join(dict.fromkeys("".join(rows))) or " "
    height, glyphs = _rasterize_glyphs(selection.path, selection.style, size,
                                       selection.synthetic, chars, **effects)
    spacing = max(1, height // 3)
    width = max(1, *(sum(glyphs[c].shape[1] for c in row) for row in rows))
    image = Image.new("L", (width, height * len(rows) + spacing * (len(rows) - 1)))
    for i, row in enumerate(rows):
        x = 0
        for char in row:
            cell = Image.fromarray(glyphs[char]).convert("L")
            image.paste(cell, (x, i * (height + spacing)))
            x += cell.width
    return image, height


class GlyphBridgeApp:
    def __init__(self, root):
        self.root = root
        root.title("Glyph Bridge")
        root.geometry("1050x760")
        root.minsize(880, 710)
        root.configure(bg=PAPER)
        self.source = tk.StringVar(value=GOOGLE_SOURCE)
        self.font_choice = tk.StringVar()
        self.local_folder = None
        self.local_fonts = {}
        self.style_options = {}
        self.catalog_results = Queue()
        self.catalog_generation = 0
        self.weight = tk.StringVar(value="Regular")
        self.italic = tk.BooleanVar()
        self.position = tk.StringVar(value="Normal")
        self.strikethrough = tk.BooleanVar()
        self.size = tk.StringVar(value="48")
        self.sample = tk.StringVar(value=SAMPLE)
        self.charset = tk.StringVar()
        self.charset_mode = tk.StringVar(value=ALL_CHARACTERS)
        self.charset_hint = tk.StringVar()
        self.output = tk.StringVar(value=str(Path.cwd()))
        self.status = tk.StringVar(value="Select a font source to get started.")
        self.filename = tk.StringVar(value="Load a font to see the header name")
        self.metrics = tk.StringVar()
        self.selection = None
        self.loaded_key = None
        self.exported = None
        self.busy = False
        self.results = Queue()
        self.preview_timer = None
        self.reload_timer = None
        self.reload_pending = False
        self.preview_bitmap = None
        self.preview_photo = None
        self._styles()
        self._layout()
        for variable in (self.font_choice, self.weight, self.italic, self.position,
                         self.strikethrough, self.size, self.sample, self.charset_mode,
                         self.charset, self.output):
            variable.trace_add("write", self._changed)
        for variable in (self.font_choice, self.weight, self.italic):
            variable.trace_add("write", self._schedule_reload)
        root.after(40, self._poll)
        root.after(0, self._discover_fonts)

    def _styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=(FONT, 10))
        style.configure("TEntry", padding=6, fieldbackground=WHITE, foreground=INK,
                        bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
        style.configure("TCombobox", padding=5, fieldbackground=WHITE, bordercolor=LINE)
        style.configure("TSpinbox", padding=5, fieldbackground=WHITE, bordercolor=LINE)
        style.configure("TCheckbutton", background=WHITE, foreground=INK)
        style.map("TCheckbutton", background=[("active", WHITE)])
        style.configure("TButton", padding=(12, 7), background=WHITE, foreground=INK,
                        bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
        style.map("TButton", background=[("active", "#EAF0E9")])
        style.configure("Accent.TButton", background=ACCENT, foreground=INK,
                        font=(FONT, 10, "bold"), bordercolor=ACCENT,
                        lightcolor=ACCENT, darkcolor=ACCENT)
        style.map("Accent.TButton", background=[("disabled", "#E2E7DE"), ("active", "#C4E866")])

    @staticmethod
    def _label(parent, text=None, *, variable=None, size=10, color=INK, bg=WHITE, bold=False, **kwargs):
        return tk.Label(parent, text=text, textvariable=variable, bg=bg, fg=color,
                        font=(FONT, size, "bold" if bold else "normal"), anchor="w", **kwargs)

    def _layout(self):
        header = tk.Frame(self.root, bg=PANEL, padx=28, pady=14)
        header.pack(fill="x")
        self._label(header, "Glyph Bridge", size=24, color=WHITE, bg=PANEL, bold=True).pack(anchor="w")
        self._label(header, "Bitmap fonts for PixelPlanner", color=PANEL_MUTED, bg=PANEL).pack(anchor="w")

        body = tk.Frame(self.root, bg=PAPER)
        body.pack(fill="both", expand=True, padx=22, pady=(18, 12))
        controls = tk.Frame(body, bg=WHITE, width=285, padx=14, pady=12,
                            highlightbackground=LINE, highlightthickness=1)
        controls.pack(side="left", fill="y")
        controls.pack_propagate(False)
        self._label(controls, "Font source", size=13, bold=True).pack(fill="x", pady=(0, 6))
        sources = ttk.Combobox(controls, textvariable=self.source, values=(GOOGLE_SOURCE, LOCAL_SOURCE),
                               state="readonly")
        sources.pack(fill="x")
        sources.bind("<<ComboboxSelected>>", self._discover_fonts)
        self.font_field = tk.Frame(controls, bg=WHITE)
        self.font_field.pack(fill="x", pady=(7, 4))
        self.font_list = ttk.Combobox(self.font_field, textvariable=self.font_choice, state="readonly")
        self.font_list.pack(fill="x")
        self.local_controls = tk.Frame(self.font_field, bg=WHITE)
        ttk.Button(self.local_controls, text="Choose folder…",
                   command=self._browse_font_folder).pack(side="left", pady=(4, 0))
        ttk.Button(self.local_controls, text="Installed fonts",
                   command=self._installed_fonts).pack(side="right", pady=(4, 0))

        attributes = tk.Frame(controls, bg=WHITE)
        attributes.pack(fill="x", pady=(4, 8))
        left = tk.Frame(attributes, bg=WHITE)
        left.pack(side="left", fill="x", expand=True, padx=(0, 8))
        right = tk.Frame(attributes, bg=WHITE)
        right.pack(side="right")
        self._label(left, "Weight", bold=True).pack(fill="x")
        self.weight_list = ttk.Combobox(left, textvariable=self.weight, width=12, state="disabled")
        self.weight_list.pack(fill="x")
        self._label(right, "Size (px)", bold=True).pack(fill="x")
        ttk.Spinbox(right, from_=1, to=1024, textvariable=self.size, width=6).pack(fill="x")
        toggles = tk.Frame(controls, bg=WHITE)
        toggles.pack(fill="x")
        self.italic_button = ttk.Checkbutton(toggles, text="Italic", variable=self.italic)
        self.italic_button.pack(side="left")
        ttk.Checkbutton(toggles, text="Strikethrough", variable=self.strikethrough).pack(side="right")
        self._label(controls, "Vertical position", bold=True).pack(fill="x", pady=(3, 2))
        ttk.Combobox(controls, textvariable=self.position, state="readonly",
                     values=("Normal", "Superscript", "Subscript")).pack(fill="x", pady=(0, 10))

        ttk.Separator(controls).pack(fill="x", pady=(0, 10))
        self._label(controls, "Export settings", size=13, bold=True).pack(fill="x", pady=(0, 7))
        self._label(controls, "Characters to export", bold=True).pack(fill="x")
        ttk.Combobox(controls, textvariable=self.charset_mode, state="readonly",
                     values=(ALL_CHARACTERS, PREVIEW_CHARACTERS, CUSTOM_CHARACTERS)).pack(fill="x")
        self.custom_field = ttk.Entry(controls, textvariable=self.charset)
        self.character_help = self._label(controls, variable=self.charset_hint, color=MUTED,
                                          wraplength=245, justify="left")
        self.character_help.pack(fill="x", pady=(2, 0))
        self._update_charset_controls()
        self._label(controls, "Destination folder", bold=True).pack(fill="x", pady=(9, 2))
        folder = tk.Frame(controls, bg=WHITE)
        folder.pack(fill="x")
        ttk.Button(folder, text="Choose…", command=self._browse_output).pack(side="right")
        ttk.Entry(folder, textvariable=self.output).pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.export_button = ttk.Button(controls, text="Export header", style="Accent.TButton", command=self.export)
        self.export_button.pack(fill="x", pady=(11, 5))
        self.folder_button = ttk.Button(controls, text="Open output folder", command=self._open_output)
        self.folder_button.pack(fill="x")

        preview = tk.Frame(body, bg=PANEL, padx=17, pady=14)
        preview.pack(side="left", fill="both", expand=True, padx=(15, 0))
        self._label(preview, "Bitmap preview", size=15, color=WHITE, bg=PANEL, bold=True).pack(fill="x")
        self._label(preview, "Preview text", color=PANEL_MUTED, bg=PANEL).pack(fill="x", pady=(10, 4))
        ttk.Entry(preview, textvariable=self.sample).pack(fill="x")
        self.canvas = tk.Canvas(preview, bg=SCREEN, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, pady=(12, 10))
        self.canvas.bind("<Configure>", self._draw_preview)
        self._label(preview, variable=self.metrics, color=PANEL_MUTED, bg=PANEL).pack(fill="x")
        self._label(preview, variable=self.filename, color=ACCENT, bg=PANEL, bold=True).pack(fill="x", pady=(3, 0))
        self._label(self.root, variable=self.status, bg=PAPER, color=MUTED).pack(fill="x", padx=24, pady=(0, 10))
        self._buttons()

    def _key(self):
        source = self.source.get()
        choice = self.font_choice.get()
        value = str(self.local_fonts.get(choice, "")) if source == LOCAL_SOURCE else choice
        return source, value, self.weight.get(), self.italic.get()

    def _effects(self):
        return {"position": self.position.get().lower(), "strikethrough": self.strikethrough.get()}

    def _size(self):
        try:
            size = int(self.size.get())
        except ValueError:
            size = 0
        if not 1 <= size <= 1024:
            raise ValueError("Enter a font size from 1 to 1024 pixels.")
        return size

    def _charset(self):
        mode = self.charset_mode.get()
        if mode == ALL_CHARACTERS:
            return None
        value = self.sample.get() if mode == PREVIEW_CHARACTERS else self.charset.get()
        if not value:
            raise ValueError("Enter at least one character to export.")
        if any(char not in DEFAULT_CHARSET for char in value):
            raise ValueError("Use printable ASCII letters, numbers, spaces, or punctuation.")
        return "".join(dict.fromkeys(value))

    def _update_charset_controls(self):
        mode = self.charset_mode.get()
        if mode == CUSTOM_CHARACTERS:
            self.custom_field.pack(fill="x", pady=(3, 0), before=self.character_help)
            self.charset_hint.set("Type the exact characters, for example READY 0123456789. Spaces count.")
        else:
            self.custom_field.pack_forget()
            self.charset_hint.set("Exports each distinct character in the preview text."
                                  if mode == PREVIEW_CHARACTERS else
                                  "Exports all 95 letters, digits, punctuation marks, and space.")

    def _changed(self, *_):
        self._update_charset_controls()
        if self.preview_timer is not None:
            self.root.after_cancel(self.preview_timer)
        self.preview_timer = self.root.after(150, self.refresh_preview)
        self._buttons()

    def _buttons(self):
        key = self._key()
        ready = self.selection is not None and key == self.loaded_key
        options = self.style_options.get(key[:2], {})
        weights = {weight for weight, italic in options if italic == key[3]}
        ordered = [weight for weight in WEIGHTS if weight in weights]
        ordered.extend(sorted(weights.difference(WEIGHTS), key=str.casefold))
        self.weight_list.configure(values=ordered, state="readonly" if len(ordered) > 1 else "disabled")
        both_postures = len({italic for _, italic in options}) == 2
        self.italic_button.configure(state="normal" if both_postures else "disabled")
        self.export_button.configure(state="normal" if ready and not self.busy else "disabled")
        self.folder_button.configure(state="normal" if self.exported else "disabled")

    def _schedule_reload(self, *_):
        if self.reload_timer is not None:
            self.root.after_cancel(self.reload_timer)
        self.reload_timer = self.root.after(250, self._reload_if_changed)

    def _reload_if_changed(self):
        self.reload_timer = None
        key = self._key()
        if not key[1] or key == self.loaded_key:
            return
        if self.busy:
            self.reload_pending = True
        else:
            self.load_font()

    def _browse_font_folder(self):
        folder = filedialog.askdirectory(parent=self.root, title="Choose a folder containing fonts",
                                         initialdir=self.local_folder or str(Path.home()))
        if folder:
            self.local_folder = folder
            self._discover_fonts()

    def _installed_fonts(self):
        self.local_folder = None
        self._discover_fonts()

    def _discover_fonts(self, _event=None):
        source = self.source.get()
        folder = self.local_folder
        if source == LOCAL_SOURCE:
            self.local_controls.pack(fill="x")
        else:
            self.local_controls.pack_forget()
        self.catalog_generation += 1
        generation = self.catalog_generation
        self.font_list.configure(values=())
        self.font_choice.set("")
        self.status.set("Finding available fonts…")

        def worker():
            if source == LOCAL_SOURCE:
                result = local_catalog(folder), False
            else:
                result = google_catalog()
            self.catalog_results.put((generation, source, result))

        Thread(target=worker, daemon=True).start()

    def _catalog_ready(self, generation, source, result):
        if generation != self.catalog_generation:
            return
        fonts, cached = result
        if source == LOCAL_SOURCE:
            self.local_fonts = fonts
        names = sorted(fonts, key=str.casefold)
        self.font_list.configure(values=names)
        if names:
            self.font_choice.set("Inter" if source == GOOGLE_SOURCE and "Inter" in names else names[0])
            cache_label = " from the cached catalog" if cached else ""
            self.status.set(f"Found {len(names)} fonts{cache_label}.")
        elif source == GOOGLE_SOURCE:
            self.status.set("Google Fonts catalog unavailable. Switch sources to retry.")
        else:
            self.status.set("No supported fonts found. Choose another folder.")

    def _browse_output(self):
        current = Path(self.output.get()).expanduser()
        folder = filedialog.askdirectory(parent=self.root, title="Choose the sketch folder",
                                         initialdir=str(current if current.is_dir() else Path.home()))
        if folder:
            self.output.set(folder)

    def _start(self, message, work, done, *, modal_errors=False):
        if self.busy:
            return
        self.busy = True
        self.status.set(message)
        self._buttons()

        def worker():
            try:
                self.results.put((done, work(), None, modal_errors))
            except Exception as exc:
                self.results.put((done, None, exc, modal_errors))

        Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            catalog = self.catalog_results.get_nowait()
        except Empty:
            pass
        else:
            self._catalog_ready(*catalog)

        try:
            done, result, error, modal_errors = self.results.get_nowait()
        except Empty:
            pass
        else:
            self.busy = False
            if error:
                self.status.set(str(error))
                if modal_errors:
                    messagebox.showerror("Glyph Bridge", str(error), parent=self.root)
            else:
                done(result)
            self._buttons()
            if self.reload_pending:
                self.reload_pending = False
                self._schedule_reload()
        self.root.after(40, self._poll)

    def load_font(self):
        key = self._key()
        if not key[1]:
            self._discover_fonts()
            return

        def loaded(result):
            if key != self._key():
                return
            selection, options, chosen = result
            self.style_options[key[:2]] = options
            self.weight.set(chosen[0])
            self.italic.set(chosen[1])
            self.selection = selection
            self.loaded_key = self._key()
            message = f"Loaded {selection.family} · {selection.style}."
            if chosen != key[2:]:
                message += " The previous style is unavailable for this font."
            self.status.set(message)
            self.refresh_preview()

        options = self.style_options.get(key[:2])
        self._start("Loading font…", lambda: resolve_font(*key, options=options), loaded)

    def refresh_preview(self):
        if self.preview_timer is not None:
            self.root.after_cancel(self.preview_timer)
        self.preview_timer = None
        if self.selection is None or self._key() != self.loaded_key:
            self.preview_bitmap = None
            self.metrics.set("")
            self.filename.set("Load a font to see the header name")
        else:
            try:
                size = self._size()
                chars = self._charset()
                text = self.sample.get()[:48]
                effects = self._effects()
                self.preview_bitmap, height = bitmap_preview(self.selection, size, text, chars, **effects)
                omitted = sum(c not in (chars or DEFAULT_CHARSET) for c in text)
                metrics = f"{height} px glyph height  ·  {len(chars or DEFAULT_CHARSET)} glyphs  ·  1-bit"
                if omitted:
                    metrics += f"  ·  {omitted} preview characters omitted"
                self.metrics.set(metrics)
                self.filename.set(_font_namespace(self.selection.family, self.selection.style, size, **effects) + ".h")
            except (ValueError, OSError) as exc:
                self.preview_bitmap = None
                self.metrics.set(str(exc))
                self.filename.set("")
        self._draw_preview()
        self._buttons()

    def _draw_preview(self, _event=None):
        canvas = self.canvas
        canvas.delete("all")
        w, h = canvas.winfo_width(), canvas.winfo_height()
        if self.preview_bitmap is None:
            canvas.create_text(w / 2, h / 2, text="Load a font to preview its pixels",
                               fill=PANEL_MUTED, font=(FONT, 13), width=max(1, w - 24))
            return
        image = self.preview_bitmap
        scale = min(max(1, w - 30) / image.width, max(1, h - 30) / image.height, 8.0)
        if scale >= 1:
            scale = int(scale)
        image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                             Image.Resampling.NEAREST)
        display = Image.new("RGB", image.size, SCREEN)
        display.paste(ACCENT, (0, 0, image.width, image.height), image)
        self.preview_photo = ImageTk.PhotoImage(display, master=self.root)
        canvas.create_image(w / 2, h / 2, image=self.preview_photo)

    def export(self):
        if self.busy or self.selection is None or self._key() != self.loaded_key:
            return
        try:
            size, chars = self._size(), self._charset()
            if not self.output.get().strip():
                raise ValueError("Choose an output folder.")
        except ValueError as exc:
            self.status.set(str(exc))
            return
        selection = self.selection
        folder = Path(self.output.get()).expanduser()
        effects = self._effects()
        target = folder / (_font_namespace(selection.family, selection.style, size, **effects) + ".h")
        if target.exists() and not messagebox.askyesno("Replace header?", f"Replace {target.name}?",
                                                     parent=self.root):
            return

        def saved(path):
            self.exported = Path(path).resolve()
            self.status.set(f"Saved {self.exported.name} to {self.exported.parent}")

        self._start("Exporting header…",
                    lambda: export_header(selection.path, selection.family, selection.style, size,
                                          selection.synthetic, folder, chars=chars, **effects), saved,
                    modal_errors=True)

    def _open_output(self):
        if not self.exported:
            return
        folder = str(self.exported.parent)
        try:
            if sys.platform == "win32":
                os.startfile(folder)
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", folder])
        except OSError as exc:
            self.status.set(str(exc))


def main():
    if tk is None:
        raise SystemExit("Glyph Bridge GUI requires Python with Tkinter installed.")
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise SystemExit(f"Glyph Bridge could not open a desktop window: {exc}") from exc
    GlyphBridgeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
