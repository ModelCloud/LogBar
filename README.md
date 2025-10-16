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

- Shared singleton logger with per-level colorized output.
- `once` helpers prevent duplicate log spam automatically.
- Stackable progress bars that stay anchored while your logs flow freely.
- Built-in styling for progress bar fills, colors, gradients, and head glyphs.
- Animated progress titles with a subtle sweeping highlight.
- Column-aware table printer with spans, width hints, and `fit` sizing.
- Zero dependencies; works anywhere Python runs.

# Installation

```bash
pip install logbar
```

LogBar works out-of-the-box with CPython 3.8+ on Linux, macOS, and Windows terminals.

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

Sample output (colors omitted in plain-text view):

```
INFO  hello from logbar
INFO  this line shows once
INFO  [###---------------]  20%  (1/5)
```

# Logging

The shared instance exposes the standard level helpers plus `once` variants:

```py
log.debug("details...")
log.warn("disk space is low")
log.error("cannot connect to database")
log.critical.once("fuse blown, shutting down")
```

Typical mixed-level output (Note: Markdown cannot display ANSI colors):

```
DEBUG model version=v2.9.1
WARN  disk space is low (5%)
ERROR cannot connect to database
CRIT  fuse blown, shutting down
```

# Progress Bars

Progress bars accept any iterable or integer total:

```py
for item in log.pb(tasks):
    process(item)

for _ in log.pb(500).title("Downloading"):
    time.sleep(0.05)
```

Manual mode gives full control when you need to interleave logging and redraws:

```py
pb = log.pb(jobs).title("Processing").manual()
for job in pb:
    log.info(f"starting {job}")
    pb.subtitle(f"in-flight: {job}").draw()
    run(job)
    log.info(f"finished {job}")
```

Progress bar snapshot (plain-text example):

```
INFO  Processing [##########------------]  40%  (8/20) in-flight: step-8
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

The rolling bar animates automatically while attached. Close it explicitly with `spinner.close()` if you are not using the context manager.

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
INFO  Fetch  [███████░░░░░░░░░░░░░░░░░░░░░░░░░░░░] |  58.8% 00:00:46 / 00:01:19
INFO  Train  [█████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░] |  37.5% 00:01:15 / 00:03:20
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

Styled output (plain-text view with ANSI removed):

```
INFO  Upload  [▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉▉···········] |  62.0% 00:01:48 / 00:02:52
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
    {"label": "message", "span": 2}
)

cols.info.header()
cols.info("startup", "1.2s", "ready", "subsystem online")
cols.info("alignment", "0.5s", "resizing", "fit width active")
```

Sample table output (plain-text):

```
INFO  +----------+----------+-----------------------------+------------------------------+
INFO  |  tag      |  duration |  message                     |  message                  |
INFO  +----------+----------+-----------------------------+------------------------------+
INFO  |  startup  |  1.2s     |  ready                       |  subsystem online         |
INFO  +----------+----------+-----------------------------+------------------------------+
INFO  |  alignment|  0.5s     |  resizing                    |  fit width active         |
INFO  +----------+----------+-----------------------------+------------------------------+
```

Notice how the `tag` column expands precisely to the longest value thanks to `width="fit"`.

You can update column definitions at runtime:

```py
cols.update({
    "message": {"width": "40%"},
    "duration": {"label": "time"}
})
```

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
        pb.render()
```

# Advanced Tips

- Combine columns and progress bars by logging summaries at key checkpoints.
- Use `log.warn.once(...)` to keep noisy health checks readable.
- For multi-line messages, pre-format text and pass it as a single string; LogBar keeps borders intact.
