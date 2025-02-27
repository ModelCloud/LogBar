<div align=center>

<image src="https://github.com/user-attachments/assets/03e77aef-1e56-4975-bde1-cff78a4facd2" width=150 height=150>
</image>
  <h1>LogBar</h1>

  A unified Logger and ProgressBar util with zero dependencies. 
</div>


# Features

* `Once` logging: `log.info.once("this log msg will be only logged once")`
* Progress Bar: `progress_bar = log.pb(range(100))`
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
pb = log.pb(range(100)) # <-- pass in any iterable
for _ in pb:
    time.sleep(0.1)

# advanced progress bar usage
# progress bar with fixed title
pb = log.pb(range(100)).title("Super Bar:) # <-- set fixed title
for _ in pb:
    time.sleep(0.1)


# advanced progress bar usage
# progress bar with fixed title and dynamic sub_title
# dynamic title/sub_title requires manual calls to `draw()` show progress correctly in correct order
pb = log.pb(range(names_list)).title("Processing Model").manual() # <-- switch to manual render mode: call `draw()` manually
for name in pb:
    start = time.time()
    log.info(f"{name} is about to be worked on...") # <-- logs and progress bar do not conflict
    pb.subtitle(f"Processing Module: {name}").draw()
    log.info(f"{name} completed: took {time.time()-start} secs")
    time.sleep(0.1)
```

# Pending Features

* Multiple Active Progress Bars



