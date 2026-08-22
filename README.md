<div align=center>

<image src="https://github.com/user-attachments/assets/ce85bc38-6741-4a86-8ca9-71c13c7fc563" width=50%>
</image>
  <h1>LogBar</h1>

  A unified logger, table renderer, and progress bar utility with zero runtime dependencies.
</div>

<p align="center" >
    <a href="https://github.com/ModelCloud/LogBar/releases" style="text-decoration:none;"><img alt="GitHub release" src="https://img.shields.io/github/release/ModelCloud/LogBar.svg"></a>
    <a href="https://pypi.org/project/logbar/" style="text-decoration:none;"><img alt="PyPI - Version" src="https://img.shields.io/pypi/v/logbar"></a>
    <a href="https://pepy.tech/projects/logbar" style="text-decoration:none;"><img src="https://static.pepy.tech/badge/logbar" alt="PyPI Downloads"></a>
    <a href="https://github.com/ModelCloud/LogBar/blob/main/LICENSE"><img src="https://img.shields.io/pypi/l/logbar" alt="License"></a>
    <a href="https://huggingface.co/modelcloud/"><img src="https://img.shields.io/badge/Hugging%20Face-ModelCloud-%23ff8811.svg"></a>
</p>


# Features

- Shared singleton logger with automatic per-level colorized `◼` glyph prefixes on interactive ANSI terminals.
- `once` helpers prevent duplicate log spam automatically.
- Stackable progress bars that stay anchored while your logs flow freely.
- Sub-cell Unicode bar rasterization for smoother, more accurate terminal fills.
- Built-in styling for progress bar fills, colors, gradients, and head glyphs.
- Animated progress titles with a subtle sweeping highlight.
  Set `LOGBAR_ANIMATION=0` to disable the highlight animation (applies to stacked, region, and spinner bars).
- Progress output throttling for reducing redraw churn in batch-heavy jobs.
  Set `LOGBAR_PROGRESS_OUTPUT_INTERVAL=10` to render every 10 logical updates instead of every update (applies to all progress bar types including spinners and split-pane region bars).
- Headless/CI/AI-agent fast path: title, subtitle, and draw calls skip expensive width/padding math and the shared render lock when no interactive terminal is present.
- Column-aware table printer with spans, width hints, and `fit` sizing.
- Zero dependencies; works anywhere Python runs.

# Installation

```bash
pip install logbar
```

LogBar works out-of-the-box with CPython 3.8+ on Linux, macOS, and Windows terminals.

## Automatic level glyphs

On an interactive ANSI terminal, LogBar uses a compact `◼` prefix by default.
The glyph is colored by level: cyan for `DEBUG`, green for `INFO`, yellow for
`WARN`, and red for `ERROR` and `CRIT`. This keeps tables aligned while still
making severity visible at a glance.

| Level | README visual key | Terminal glyph color |
| --- | --- | --- |
| `DEBUG` | 🔵 `◼` | cyan |
| `INFO` | 🟢 `◼` | green |
| `WARN` | 🟡 `◼` | yellow |
| `ERROR` / `CRIT` | 🔴 `◼` | red |

The colored circle is a README-only visual key; the adjacent `◼` is the exact
glyph LogBar emits. GitHub repository Markdown cannot apply terminal ANSI
colors directly to text, so the rendered color is visible in the emoji key.

<details>
<summary>ANSI sequences emitted by the terminal renderer</summary>

```text
DEBUG  \x1b[36m◼\x1b[0m
INFO   \x1b[32m◼\x1b[0m
WARN   \x1b[33m◼\x1b[0m
ERROR  \x1b[31m◼\x1b[0m
CRIT   \x1b[31m◼\x1b[0m
```

</details>

When output is redirected, headless, or color-disabled, LogBar automatically
falls back to text prefixes such as `INFO`, `WARN`, and `ERROR`. Disable glyphs
for a logger with `log.set_symbol_prefix(False)`, or set
`LOGBAR_DISABLE_SYMBOL_PREFIX=1` before creating the logger. To explicitly use
glyphs on a redirected stream, set both `LOGBAR_FORCE_ANSI=1` and
`LOGBAR_FORCE_SYMBOL_PREFIX=1`.

## Renderer Design

LogBar keeps progress bars, spinners, tables, and normal log lines readable in the same terminal session. Compared with traditional loggers, it lets long-running CLI programs show live status without flooding the screen with repeated status lines or breaking the flow of regular logs.

Main rendering APIs:

- `log.pb(...)` for live progress bars
- `log.spinner(...)` for work with no fixed total
- `log.columns(...)` for aligned table output

Examples:

```py
from logbar import LogBar

log = LogBar.shared()

for _ in log.pb(range(5)).title("下载 📦").subtitle("phase 1"):
    pass
```

```py
jobs = ["scan", "parse", "index", "flush"]
pb = log.pb(jobs, output_interval=1).title("Indexing").manual()
for job in pb:
    log.info("processing %s", job)
    pb.subtitle(job).draw()
```

```py
cols = log.columns(
    {"label": "task", "width": "fit"},
    {"label": "status", "width": "fit"},
    {"label": "detail", "width": "50%"},
)

cols.info.header()
cols.info("render", "active", "width and alignment stay terminal-aware")
```

Experimental split-screen sessions:

```py
from logbar import RegionScreenSession, rows

with RegionScreenSession.columns("left", rows("right_top", "right_bottom")) as ui:
    left = ui.create_logger("left", supports_ansi=False)
    right_top = ui.create_logger("right_top", supports_ansi=False)
    right_bottom = ui.create_logger("right_bottom", supports_ansi=False)

    left.setLevel("INFO")
    right_top.setLevel("INFO")
    right_bottom.setLevel("INFO")

    left.info("download queue ready")
    right_top.info("worker online")
    right_bottom.set_footer_lines(["gpu warmup", "epoch 1/8"])
```

Plain-text sketch (this example explicitly disables ANSI in the pane loggers):

```text
+----------------------+----------------------+
| INFO  download ...   | INFO  worker online  |
|                      |----------------------|
|                      | gpu warmup           |
|                      | epoch 1/8            |
+----------------------+----------------------+
```

# Quick Start

```py
import time
from logbar import LogBar

log = LogBar.shared()

log.info("hello from logbar")
log.info.once("this line shows once")
log.info.once("this line shows once")  # silently skipped

for _ in log.pb(range(5)):
    time.sleep(0.2)
```

Sample output after stripping ANSI color codes from an interactive terminal:

```
◼ hello from logbar
◼ this line shows once
```

# Logging

The shared instance exposes the standard level helpers plus `once` variants:

```py
log.debug("details...")
log.warn("disk space is low")
log.error("cannot connect to database")
log.critical.once("fuse blown, shutting down")
```

Set a minimum output threshold per logger instance:

```py
log.setLevel("WARN")           # accepts DEBUG/INFO/WARN/ERROR/CRIT strings
log.setLevel("ERROR")
log.setLevel(LogBar.WARNING)   # alias to logging.WARNING
```

Typical mixed-level output after stripping ANSI color codes:

```
◼ model version=v2.9.1       # DEBUG, cyan
◼ disk space is low (5%)     # WARN, yellow
◼ cannot connect to database  # ERROR, red
◼ fuse blown, shutting down   # CRIT, red
```

Use `log.set_symbol_prefix(False)` when the level names should remain visible
in every output mode:

```py
log.set_symbol_prefix(False)
log.info("text prefix enabled")  # INFO text prefix enabled
```

# Progress Bars

Progress bars accept any iterable or integer total:

```py
for item in log.pb(tasks):
    process(item)

for _ in log.pb(500).title("Downloading"):
    time.sleep(0.05)
```

When a workload updates progress very frequently, throttle redraw churn globally or per bar:

```py
for _ in log.pb(500, output_interval=10).title("Quantizing"):
    time.sleep(0.01)
```

`output_interval=10` means LogBar will emit a fresh snapshot after roughly every 10 logical progress steps, while still forcing the last pending step to render before the bar closes. Set `LOGBAR_PROGRESS_OUTPUT_INTERVAL=10` to apply the same default process-wide. This default is now honored by stacked progress bars, pane-local region bars, and rolling spinners.

When LogBar detects a headless/CI/AI-agent environment (e.g. `CI`, `DEVIN_*`, `CODEX_*`, Jupyter, or `TERM=dumb`), it suppresses visual progress-bar output and short-circuits the title/subtitle/draw pipeline. This makes frequent progress updates in long batch loops cheap without flooding logs.

Manual mode gives full control when you need to interleave logging and redraws:

```py
pb = log.pb(jobs).title("Processing").manual()
for job in pb:
    log.info(f"starting {job}")
    pb.subtitle(f"in-flight: {job}").draw()
    run(job)
    log.info(f"finished {job}")
```

Progress bar snapshot (the live progress row has no log-level prefix):

```
Downloading [2 of 5] ███████████████▌░░░░░░░░░░░░░░░░░░░░░░░| 0:00:00 / 0:00:00 [2/5] 40.0%
```

The bar always re-renders at the bottom, so log lines never overwrite your progress.

### Indeterminate Progress

When the total work is unknown, `log.spinner()` provides a rolling indicator that redraws every 500 ms until closed:

```py
with log.spinner("Loading model") as spinner:
    load_weights()
    spinner.subtitle("warming up")
    warm_up()
```

The rolling bar animates automatically while attached. Close it explicitly with `spinner.close()` if you are not using the context manager. Set `LOGBAR_ANIMATION=0` to disable the title highlight sweep on progress labels. You can also set `LOGBAR_PROGRESS_OUTPUT_INTERVAL=10` to throttle the spinner's phase updates, which is helpful when many spinners are running in headless or CI environments.

### Multiple Progress Bars

LogBar keeps each progress bar on its own line and restacks them whenever they redraw. Later bars always appear closest to the live log output.

```py
pb_fetch = log.pb(range(80)).title("Fetch").manual()
pb_train = log.pb(range(120)).title("Train").manual()

for _ in pb_fetch:
    pb_fetch.draw()
    time.sleep(0.01)

for _ in pb_train:
    pb_train.draw()
    time.sleep(0.01)

pb_train.close()
pb_fetch.close()
```

Sample stacked output (plain-text view):

```
Fetch [12 of 20] █████████████████████░░░░░░░░░░░░░░| 0:00:00 / 0:00:00 [12/20] 60.0%
Train [7 of 20] ████████████▉░░░░░░░░░░░░░░░░░░░░░░░░| 0:00:00 / 0:00:00 [7/20] 35.0%
```

## Progress Bar Styling

Pick from bundled palettes or create your own blocks and colors:

```py
pb = log.pb(250)
pb.style('sunset')  # bundled gradients: emerald_glow, sunset, ocean, matrix, mono
pb.fill('▓', empty='·')  # override glyphs
pb.colors(fill=['#ff9500', '#ff2d55'], head='mint')  # custom palette, optional head accent
pb.colors(empty='slate')  # tint the empty track
pb.head('>', color='82')  # custom head glyph + color index
```

`ProgressBar.available_styles()` lists builtin styles, and you can register additional ones with `ProgressBar.register_style(...)` or switch defaults globally via `ProgressBar.set_default_style(...)`. Custom colors accept ANSI escape codes, 256-color indexes (e.g. `'82'`), or hex strings (`'#4c1d95'`).

For direct style registration and introspection, import the advanced style APIs from `logbar.progress`:

```py
from logbar.progress import ProgressBar, ProgressStyle, progress_style_names

print(ProgressBar.available_styles())
print(progress_style_names())

ProgressBar.register_style(
    ProgressStyle(
        name="ice",
        fill_char="■",
        empty_char="·",
        fill_colors=("#7dd3fc", "#38bdf8"),
        gradient=True,
        head_char=">",
    )
)

ProgressBar.set_default_style("ice")
```

Styled output (plain-text view with ANSI removed):

```
Upload [12 of 20] ▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉···········| 0:01:48 / 0:02:52 [12/20] 62.0%
```

# Columns (Table) 

Use `log.columns(...)` to format aligned tables while logging data streams. Print the column header per context with `cols.info.header()` (or `cols.warn.header()`, etc.). Columns support spans and three width hints:

- character width: `"24"`
- percentage of the available log width: `"30%"`
- content-driven fit: `"fit"`

```py
cols = log.columns(
    {"label": "tag", "width": "fit"},
    {"label": "duration", "width": 8},
    {"label": "message", "width": "50%"}
)

cols.info.header()
cols.info("startup", "1.2s", "ready")
cols.info("alignment", "0.5s", "resizing")
```

Sample table output (plain-text):

```
◼ +---------------------------+--------+-----------------------------------+
◼ |  tag                      |duration|message                            |
◼ +---------------------------+--------+-----------------------------------+
◼ |  startup                  |1.2s    |ready                              |
◼ +---------------------------+--------+-----------------------------------+
◼ |  alignment                |0.5s    |resizing                           |
◼ +---------------------------+--------+-----------------------------------+
```

Notice how the `tag` column expands precisely to the longest value thanks to `width="fit"`.

You can update column definitions at runtime:

```py
cols.update({
    "message": {"width": "40%"},
    "duration": {"label": "time"}
})
```

Useful column helpers:

- `cols.info.header()` or `cols.info.headers()` prints the current border + header block.
- `cols.info.simulate(...)` recomputes widths without emitting a row.
- `cols.update(...)` changes labels, spans, or widths at runtime.
- `cols.width()` returns the current rendered table width, including borders.
- `cols.widths`, `cols.padding`, and `cols.column_specs` expose the current layout.

# Replacing `tqdm`

The API mirrors common `tqdm` patterns while staying more Pythonic:

```py
# tqdm
for n in tqdm.tqdm(range(1000)):
    consume(n)

# logbar
for n in log.pb(range(1000)):
    consume(n)
```

Manual update comparison:

```py
# tqdm manual mode
with tqdm.tqdm(total=len(items)) as pb:
    for item in items:
        handle(item)
        pb.update()

# logbar manual redraw
with log.pb(items).manual() as pb:
    for item in pb:
        handle(item)
        pb.draw()
```

# Advanced Tips

- Combine columns and progress bars by logging summaries at key checkpoints.
- Use `log.warn.once(...)` to keep noisy health checks readable.
- For multi-line messages, pre-format text and pass it as a single string; LogBar keeps borders intact.
- In headless, notebook, or CI environments, LogBar auto-disables high-frequency progress output. Set `LOGBAR_FORCE_PROGRESS=1` to render anyway, or `LOGBAR_DISABLE_HEADLESS_DETECTION=1` to disable the heuristic.

# Environment Variables

- `LOGBAR_ANIMATION` — Set to `0`/`false`/`off` to disable the title highlight sweep.
- `LOGBAR_PROGRESS_OUTPUT_INTERVAL` — Default logical step interval between progress renders (default `1`). Applies to stacked bars, region panes, and rolling spinners.
- `LOGBAR_FORCE_PROGRESS=1` — Force progress rendering in headless/AI-agent/notebook/CI shells.
- `LOGBAR_DISABLE_HEADLESS_DETECTION=1` — Disable headless/notebook/CI auto-detection.
- `LOGBAR_DISABLE_SYMBOL_PREFIX=1` — Use text level names instead of the automatic `◼` glyph prefix.
- `LOGBAR_FORCE_SYMBOL_PREFIX=1` — Request glyph prefixes when ANSI color support is available.
- `LOGBAR_FORCE_ANSI=1` — Force ANSI color support on redirected streams; combine with `LOGBAR_FORCE_SYMBOL_PREFIX=1` for glyphs there.
- `NO_COLOR=1` or `ANSI_COLORS_DISABLED=1` — Disable ANSI colors.
- `COLUMNS` / `LINES` — Override the detected terminal size.

# API Reference

## `LogBar`

- `LogBar.shared(override_logger=False)` returns the process-wide shared logger.
- `override_logger=True` is useful in tests or embedded environments that replaced the active `logging` logger class.
- Level methods: `debug`, `info`, `warn`, `error`, `critical`.
- Deduplicated level methods: `debug.once`, `info.once`, `warn.once`, `error.once`, `critical.once`.
- `setLevel(level)` accepts strings like `"INFO"`, `"WARN"`, `"CRIT"`, numeric levels, numeric strings, and constants such as `LogBar.WARNING`.
- `pb(iterable_or_total, output_interval=None)` creates and attaches a progress bar.
- `spinner(title="", output_interval=None, interval=0.5, tail_length=4)` creates and attaches an indeterminate rolling progress bar.
- `columns(..., cols=None, width=None, padding=2)` creates a column printer.
- `set_symbol_prefix(enabled=True)` toggles the automatic glyph prefix for that logger.

## `ProgressBar`

`log.pb(...)` returns an attached `ProgressBar`. For direct imports, use:

```py
from logbar.progress import ProgressBar, ProgressStyle
```

Common chainable methods:

- `title(text)` and `subtitle(text)`
- `style(name_or_style)`
- `fill(fill_char, empty=None)`
- `colors(fill=None, empty=None, gradient=None, head=None)`
- `head(char=None, color=None)`
- `set(show_left_steps=None, left_steps_offset=None)`
- `output_interval(interval)`
- `mode(RenderMode)` if you prefer explicit mode switching over `auto()` / `manual()`

Render and lifecycle control:

- `draw(force=False)` renders the current snapshot immediately.
- `auto()` enables redraw-on-iteration mode.
- `manual()` disables automatic redraw so you can call `draw()` yourself.
- `attach(logger=None)` attaches the bar to a logger.
- `detach()` detaches the bar without destroying the object.
- `close()` forces a final render if needed and removes the bar from the stack.
- `step()` returns the current iteration index and `next()` advances once outside a `for` loop.

Style registry helpers:

- `ProgressBar.available_styles()`
- `ProgressBar.register_style(style)`
- `ProgressBar.set_default_style(style)`
- `ProgressBar.default_style()`

## `RollingProgressBar`

`log.spinner(...)` returns a `RollingProgressBar`, which inherits from `ProgressBar` and adds:

- `pulse()` to advance the spinner immediately between automatic ticks.
- `interval` and `tail_length` constructor arguments for animation speed and tail size.

## `ColumnsPrinter`

`log.columns(...)` returns a `ColumnsPrinter` with per-level proxies:

- `cols.info(...)`, `cols.warn(...)`, `cols.error(...)`, `cols.debug(...)`, `cols.critical(...)`
- `cols.info.header()` and `cols.info.headers()` for border + header emission
- `cols.info.simulate(...)` for dry-run width growth without output
- `cols.update(...)` for runtime schema changes
- `cols.width()` for the current rendered width
