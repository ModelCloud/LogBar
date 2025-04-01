<div align=center>

<image src="https://github.com/user-attachments/assets/ce85bc38-6741-4a86-8ca9-71c13c7fc563" width=50%>
</image>
  <h1>LogBar</h1>

  A unified Logger and ProgressBar util with zero dependencies. 
</div>

<p align="center" >
    <a href="https://github.com/ModelCloud/LogBar/releases" style="text-decoration:none;"><img alt="GitHub release" src="https://img.shields.io/github/release/ModelCloud/LogBar.svg"></a>
    <a href="https://pypi.org/project/logbar/" style="text-decoration:none;"><img alt="PyPI - Version" src="https://img.shields.io/pypi/v/logbar"></a>
    <a href="https://pepy.tech/projects/logbar" style="text-decoration:none;"><img src="https://static.pepy.tech/badge/logbar" alt="PyPI Downloads"></a>
    <a href="https://github.com/ModelCloud/LogBar/blob/main/LICENSE"><img src="https://img.shields.io/pypi/l/logbar" alt="License"></a>
    <a href="https://huggingface.co/modelcloud/"><img src="https://img.shields.io/badge/🤗%20Hugging%20Face-ModelCloud-%23ff8811.svg"></a>
</p>


# Features

* `Once` logging: `log.info.once("this log msg will be only logged once")`
* Progress Bar: `progress_bar = log.pb(100)`
* Sticky Bottom Progress Bar: Default behavior!
* Logging and Porgress Bar work hand-in-hand with no conflict: logs are printed before the progress bar

# Usage:

```py
# logs
log = LogBar.shared() # <-- single global log (optional), shared everywhere
log.info("super log!")
log.info.once("Show only once")
log.info.once("Show only once") # <-- not logged


# progress bar
pb = log.pb(100) # <-- pass in any iterable or int
for _ in pb:
    time.sleep(0.1)

# advanced progress bar usage
# progress bar with fixed title
pb = log.pb(100).title("Super Bar:") # <-- set fixed title
for _ in pb:
    time.sleep(0.1)


# advanced progress bar usage
# progress bar with fixed title and dynamic sub_title
# dynamic title/sub_title requires manual calls to `draw()` show progress correctly in correct order
pb = log.pb(names_list).title("Processing Model").manual() # <-- switch to manual render mode: call `draw()` manually
for name in pb:
    start = time.time()
    log.info(f"{name} is about to be worked on...") # <-- logs and progress bar do not conflict
    pb.subtitle(f"Processing Module: {name}").draw()
    log.info(f"{name} completed: took {time.time()-start} secs")
    time.sleep(0.1)
```

## `tqdm` replacement
Replacing `tqdm` with `logbar` is effortless and most time most pythonic and easier to use while being more powerful in the construction

```py
# tqdm
sum = 0
for n in tqdm.tqdm(range(1000)):
  sum += n
  time.sleep(0.1)
```

```py
# logbar
sum = 0
for n in LogBar.pb(100,000):
  sum += n
  time.sleep(0.1)
```

```py
# tqdm, manual update mode
with tqdm.tqdm(total=len(f.keys())) as pb:
      for k in f.keys():
          x = f.get_tensor(k)
          tensors[k] = x.half()
          del x
          pb.update()
```

```py
# manual render mode, call ui render manually in each step 
with LogBar.pb(f.keys()) as pb:
  for k in pb:
      x = f.get_tensor(k)
      tensors[k] = x.half()
      del x
      pb.render()
```

```py
# tqdm
for n in tqdm.tqdm(range(100,000)):
  sum += n
```


# Pending Features

* Multiple Active Progress Bars



