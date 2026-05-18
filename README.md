# Media Capture GUI

A Flask web application that uses Playwright to launch a visible Chrome browser and capture media URLs (HLS, DASH, MP4, etc.) from network traffic during a browsing session.

**First time?** Use **§ Exact instructions: CDP mode** (recommended). **Something broken?** Jump to **§ Troubleshooting**.

## Prerequisites

- Python 3.10+
- Google Chrome installed on your machine

## Setup

### 1. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Install Playwright browser drivers

```bash
playwright install chrome
```

## Running the App

```bash
PORT=5001 .venv/bin/python app.py
```

Always prefer **`.venv/bin/python app.py`** so **Playwright** imports correctly — plain `python app.py` may hit a different interpreter and raise **`ModuleNotFoundError: playwright`**.

The app listens on **http://127.0.0.1:5000** by default if you omit **`PORT`**. If you see **`Address already in use`**, port 5000 is taken — on macOS that is commonly **AirPlay Receiver** (**System Settings → General → AirDrop & Handoff → AirPlay Receiver** → off), or another process. Easiest workaround: set **`PORT`** (remember the leading **`P`**, not **`ORT`**):

```bash
PORT=5001 .venv/bin/python app.py
```
```` windows powershell
$env:PORT=5001; .\.venv\Scripts\python.exe app.py
````

Then open **http://127.0.0.1:5001** in your browser.

You can always set **`PORT`** to any free TCP port instead of disabling AirPlay.

Optional environment variables (local dev defaults are chosen so Playwright and Chrome behave predictably):

| Variable | Default | Purpose |
|---------|---------|---------|
| `FLASK_DEBUG` | on when unset (`0` / `false` / `no` to disable) | Verbose Flask errors |
| `FLASK_USE_RELOADER` | unset (off) | Set to `1` / `true` / `yes` to enable Flask’s debug reloader; **often conflicts** with capturing while Chrome owns the profile folder |
| `CAPTURE_JOB_STORE_MAX` | `100` | Max completed/error jobs retained in memory (oldest pruned first) |
| `PLAYWRIGHT_NO_AUTO_UNLOCK` | unset (auto-cleanup **on**) | Set to `1` / `true` / `yes` on macOS/Linux to skip automatic deletion of stale `Singleton*` locks before launch |
| `PLAYWRIGHT_DISABLE_GPU` | unset | Set to `1` / `true` / `yes` if Chrome **freezes or spins** loading heavy login/player pages — adds Chromium `--disable-gpu` flags |
| `PAGE_GOTO_TIMEOUT_MS` | `180000` (3 min) | How long Playwright waits for the first **`DOMContentLoaded`** on the streaming URL (`10000`–`600000`). Increase if login redirects are slow. |
| `PLAYWRIGHT_CHROME_EXTRA_ARGS` | unset | Extra Chromium flags separated by spaces (**shell-style** quoting via `shlex`), appended at launch |
| `PLAYWRIGHT_CDP_URL` | unset | **Recommended for Google/SSO:** HTTP DevTools endpoint of **Chrome you start manually**, e.g. `http://127.0.0.1:9222` — Playwright **attaches** instead of launching automation Chrome (see **§ Exact instructions: CDP mode** below) |

## Exact instructions: CDP mode (recommended — avoids “controlled by automated test software”)

Complete **Setup** (venv, `pip install -r requirements.txt`, `playwright install chrome`) once. Then **every capture session**, follow **Terminal A → Terminal B → browser GUI** exactly.

### 1) Decide your repo folder

Set `REPO_ROOT` to **the directory that contains `app.py`** (your checkout path — **adjust for your machine**):

```bash
export REPO_ROOT="/Users/you/Documents/path/to/media_capture_gui"
```

**Example clone path** used in Nike NetDevOps worktrees (change `you`/`path` if different):

```bash
export REPO_ROOT="/Users/ryoun4/Documents/github.com/nike-netdevops/media_capture_gui"
```

Always use **`cd`**, not **`d`** (zsh typo).

Keep using the **same** `REPO_ROOT` in both terminals below.

**If `cd "$REPO_ROOT"` fails** (`cd: null directory` / “no such file”) then `REPO_ROOT` is **empty** or wrong in **this** shell — `export` is **not** remembered in a **new** Terminal tab. Run `export REPO_ROOT="…"` again in that tab, or skip the variable and `cd` to the folder that contains `app.py` by hand.

### 2) Terminal A — Chrome (normal browser, stays open)

1. Quit any stray Chrome tied to your capture profile (`⌘Q` on macOS; under Windows exit every Chrome window).
2. If you are stuck with **singleton / profile locks** from a crashed run (**only when Chrome is really closed**):

   ```bash
   rm -f "$REPO_ROOT/.playwright_profile/SingletonLock" \
         "$REPO_ROOT/.playwright_profile/SingletonCookie" \
         "$REPO_ROOT/.playwright_profile/SingletonSocket"
   ```

3. Start **one** Chrome with **this checkout’s profile** plus **remote debugging** on **`9222`**:

**If port `9222` is busy**, substitute the **same** port number in **three** places: **`--remote-debugging-port`** here **and** the URL in **`PLAYWRIGHT_CDP_URL=http://127.0.0.1:«port»`** in Terminal B (see step 3 below).

**macOS — copy/paste:**

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --user-data-dir="$REPO_ROOT/.playwright_profile" \
  --remote-debugging-port=9222 \
  about:blank
```

**Windows PowerShell — copy/paste:**

```powershell
$REPO_ROOT = "C:\path\to\media_capture_gui"
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --user-data-dir="$REPO_ROOT\.playwright_profile" `
  --remote-debugging-port=9222 `
  about:blank
```

4. In that Chrome window confirm there is **no** grey **“Chrome is being controlled by automated test software”** banner.
5. If the site requires login, **complete Google / SSO entirely in these Chrome tabs** until you reach the playback page normally.
6. **Leave Chrome running** — do **not** `⌘Q` before capture.

### 3) Terminal B — Flask GUI (attached to Terminal A Chrome)

Use the **venv’s interpreter** (`ModuleNotFoundError: playwright` means you accidentally used plain `python` instead of `.venv/bin/python`).

Pick a **`PORT`** that is free (macOS **`5000`** is often blocked by AirPlay Receiver). Use **`PORT`**, spelled **`PORT`** (**not `ORT`**).

**macOS / Linux** (run from the repo — the directory that contains **`app.py`**):

```bash
cd "$REPO_ROOT"
PLAYWRIGHT_CDP_URL=http://127.0.0.1:9222 PORT=5001 .venv/bin/python app.py
```

If **`cd "$REPO_ROOT"`** fails, `REPO_ROOT` is empty in this terminal: run **`export REPO_ROOT="/full/path/to/media_capture_gui"`** first, **`cd` literally to that path**, or **skip `cd`** when your prompt is **already** inside **`media_capture_gui`** and run only the second line.

**Windows CMD** (set **`REPO_ROOT`** first in this terminal — adjust the drive/path):

```batch
set REPO_ROOT=C:\Users\YOU\Documents\github.com\nike-netdevops\media_capture_gui
cd /d %REPO_ROOT%
set PLAYWRIGHT_CDP_URL=http://127.0.0.1:9222
set PORT=5001
.venv\Scripts\python.exe app.py
```

If you see **`Address already in use`**, something else listens on `PORT`; pick another (**`5002`**, **`8080`**, …):

```bash
PLAYWRIGHT_CDP_URL=http://127.0.0.1:9222 PORT=5002 .venv/bin/python app.py
```

Or kill the old listener (**macOS/Linux**):

```bash
lsof -nP -iTCP:5001 -sTCP:LISTEN
kill <PID>
```

Leave this terminal **running** while you use the GUI.

### 4) Start capture in your normal browser

Open:

`http://127.0.0.1:<PORT>`  
(example: **http://127.0.0.1:5001**).

1. **Page URL** — full streaming page URL (**must** start with `http://` or `https://`).
2. Leave **Browser profile directory** default **`.playwright_profile`** unless you know you use another folder.
3. Adjust **Wait** / **Capture duration** if you need more time before / during playback.
4. Click **Launch Browser & Capture**.

Playwright attaches to **Chrome from Terminal A**, opens **one extra tab**, loads your URL there, listens for manifest URLs.

### 5) When the job completes

Terminal B shows **complete/error** in logs. Playwright **disconnects** DevTools — your **Chrome in Terminal A keeps running**.

To run another capture: keep Chrome up, click **Launch Browser & Capture** again (or restart Flask if you changed env vars).

### 6) When you are fully done

1. **Ctrl+C** in Terminal B to stop Flask.
2. **⌘Q** / exit **Chrome** from Terminal A when you no longer need that profile.

---

## Exact instructions: automation mode (Playwright launches Chrome)

Use this only if you **do not** set **`PLAYWRIGHT_CDP_URL`**. Chrome will show the **automation** banner; **Google sign-in often fails** there.

1. **Quit all Chrome** using the capture profile.
2. Clear stale locks if needed **only when Chrome is closed**:

   ```bash
   export REPO_ROOT="/path/to/media_capture_gui"
   rm -f "$REPO_ROOT/.playwright_profile/SingletonLock" \
         "$REPO_ROOT/.playwright_profile/SingletonCookie" \
         "$REPO_ROOT/.playwright_profile/SingletonSocket"
   ```

3. Start Flask **without** `PLAYWRIGHT_CDP_URL`:

   ```bash
   cd "$REPO_ROOT"
   PORT=5001 .venv/bin/python app.py
   ```

4. Open the GUI, click **Start Capture** — Playwright opens Chrome with automation flags.

If the tab **freezes** on login, try:

```bash
PLAYWRIGHT_DISABLE_GPU=1 PORT=5001 .venv/bin/python app.py
```

## Troubleshooting

Quick fixes grouped by symptom. Prefer **§ Exact instructions: CDP mode** whenever **Google SSO** or **“controlled by automated test software”** blocks you.

### Shell / Flask / GUI

| Symptom | What to do |
|--------|------------|
| **`cd: null directory`**, **`cd: no such file`**, or **`REPO_ROOT` empty** after `cd "$REPO_ROOT"` | `export` variables **again in every new Terminal tab**. Run **`export REPO_ROOT="/full/path/to/media_capture_gui"`**, or skip it and **`cd "/full/path/to/media_capture_gui"`** by hand. If your shell is **already** in that folder (**prompt shows `media_capture_gui`**), omit `cd` and run Flask from there. |
| **`Address already in use`** on **`5000`** (no `PORT` set) | On macOS, **AirPlay Receiver** often holds **5000** — disable it (**System Settings → General → AirDrop & Handoff → AirPlay Receiver → Off**) **or** set **`PORT`** (next row). |
| **`Address already in use`** on **`5001`** (or any `PORT` you chose) | An old **`python app.py`** is still listening. **macOS/Linux:** `lsof -nP -iTCP:5001 -sTCP:LISTEN` then **`kill <PID>`** (or **`kill -9`** if needed). **Windows:** run **`netstat -ano`**, find the PID for **`LISTENING`** on that port, then **`taskkill /PID <pid> /F`**. **Or** pick another port: **`PORT=5002 ...`**. |
| **`ORT=5001`** or env var missing **`P`** | Must be **`PORT=5001`**, not **`ORT`**. Otherwise Flask falls back to **5000** and hits AirPlay / conflicts. |
| **`ModuleNotFoundError: No module named 'playwright'`** | You used **system `python`** instead of the venv. Run **`.venv/bin/python app.py`** (or **`source .venv/bin/activate`** then **`python app.py`**). |
| GUI says **error / non-JSON** or **job not found** after you restarted Flask | Old job ids are invalid. **Refresh** the page and start a **new** capture. |
| Page URL rejected with **400** / **URL must use http:// or https://** | Paste a full URL including **`https://`**. |

### Chrome profile / ProcessSingleton

| Symptom | What to do |
|--------|------------|
| **`ProcessSingleton`**, **`profile is already in use`**, **`SingletonLock: File exists`** | **Only one** Chrome may use **`.playwright_profile`** at a time. **Quit** Terminal A Chrome (**⌘Q**) before launching **automation** Chrome, and never overlap **two** Chromes on the same **`--user-data-dir`**. |
| Lock errors **with no Chrome open** | **macOS/Linux:** with Chrome fully quit, remove stale locks: **`rm -f "$REPO_ROOT/.playwright_profile/SingletonLock" ...`** (see **§ ProcessSingleton** under **Login**). This app also tries **safe auto-cleanup** via **`lsof`** before **automation** launch; **CDP** mode skips deleting locks while your Chrome is running. |
| Chrome dialog **“Something went wrong when opening your profile”** | Usually **overlapping** profile use or a **crashed** session. Fully quit Chrome, clear **Singleton**\* if needed, or **rename** `.playwright_profile` to start fresh (you lose that profile’s cookies). |

### Google / SSO / loading

| Symptom | What to do |
|--------|------------|
| **“Couldn’t sign you in”** / **`/signin/rejected`** / **“not secure”** with **automation** Chrome | Use **§ CDP mode** so **you** start Chrome (no grey automation bar). Do **not** rely on full Google password flow inside **Playwright-launched** Chrome. |
| Google **400 … malformed** | Start login again from the **site’s** home/login page; don’t **refresh** stuck OAuth URLs; finish in **one** profile without switching **`--user-data-dir`** mid-flow. Details: **§ Google shows “400…”** below. |
| Login tab **spins / freezes** | **`PLAYWRIGHT_DISABLE_GPU=1`** for **automation** mode; **`PAGE_GOTO_TIMEOUT_MS`**; preferably **CDP** + login in **your** Chrome. See **§ Chrome freezes**. |

---

## How It Works

1. Enter the URL of a streaming page you want to inspect.
2. (Optional) Adjust the **Profile Directory**, **Wait Before Capture** (seconds to allow login/interaction), and **Timeout** (capture duration) settings.
3. Click **Start Capture** — by default Playwright launches Chrome (**automation** mode). With **`PLAYWRIGHT_CDP_URL`** set on the Flask process, Chrome is **started by you** first; capture **attaches** over DevTools Protocol and opens **one tab** (see Login section).
4. Authenticate or interact with the page as needed, then start playing the video.
5. The app captures requests/responses that look like playlists, DASH manifests, or clear media URLs (`m3u8`, `mpd`, `mp4`, paths containing `/hls/`, `/dash/`, `/manifest`, `stream.mux.com`). Per-segment fetches (`*.ts`, `*.m4s`) and Mux Fastly `/v1/chunk/` URLs are skipped to keep the list usable for playback/download.
6. Results are displayed in the GUI when capture is complete.

## Configuration Options

| Field | Default | Description |
|---|---|---|
| Profile Directory | `.playwright_profile` | Chrome user data directory (persists cookies/login state) |
| Wait Before Capture | `15` seconds | Time given to log in and start video playback before capture begins |
| Timeout | `45` seconds | Duration to listen for media URLs after the wait period |

## Login, Google sign-in, and the Playwright profile

These notes matter when the site (or Google) requires you to authenticate before playback.

### This profile is not your everyday Chrome

The **Profile Directory** (default `.playwright_profile`) is a **separate** Chrome profile. Cookies and login state from your normal Chrome windows **do not** apply here. You must sign in **once** inside this profile (or complete whatever login the host needs while using it).

### Google blocks automation browsers

Google Account sign-in often fails inside Playwright-launched Chrome (e.g. *“This browser or app may not be secure”* and a **“controlled by automated test software”** banner). That banner appears because **`launch_persistent_context` runs Chrome under automation/DevTools instrumentation** — it is unrelated to malicious intent; sites like Google deliberately block scripted login there.

### Best option for Google / SSO: CDP (**your** Chrome, no automation launch)

Follow **§ Exact instructions: CDP mode** above — numbered steps from **Chrome in Terminal A** through **Flask + GUI**.

**Safety / habits:** **`9222`** is for **localhost** debugging only — don’t expose it on untrusted networks. **Exactly one** Chrome process may hold a given **`--user-data-dir`**.

Some hosts may still object to **remote debugging attachment** in edge cases; CDP removes Playwright’s default **automation-launch banner**, not every provider heuristic.

### Standalone Chrome, then Playwright-managed launch (older workflow)

**Recommended approach if you are not using CDP:**

1. **Quit Chrome completely** — on macOS use **⌘Q** until Chrome is not running in the Dock (*no dot under the icon*). If needed, disable **Chrome → Settings → System → “Continue running background apps when Google Chrome is closed”** so Chrome actually exits when you quit.
2. **Do not run this app yet** — only one Chrome process may use the profile folder at a time.
3. Open **standalone** Chrome pointing at **the same** profile path (adjust to your checkout location).

**macOS**

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --user-data-dir="/FULL/PATH/TO/media_capture_gui/.playwright_profile"
```

**Windows** (adjust the path if your Chrome install differs)

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --user-data-dir="C:\FULL\PATH\TO\media_capture_gui\.playwright_profile"
```

4. Confirm there is **no** grey “controlled by automated test software” bar, complete Google/sign-in there, then **fully quit Chrome** again (⌘Q / exit everywhere).
5. **Now** **`.venv/bin/python app.py`** (with **`PORT`** if needed) **/ Start Capture** so Playwright can open that profile.

### Google shows “400 … malformed … should not be retried”

If the **Chrome address bar is on Google** (`accounts.google.com`, `oauth`, etc.) and the page says roughly **400** and **malformed**:

- That message is from **Google’s servers**, not this Flask app. It usually means the **authorization request was corrupted or replayed**: for example refreshing an intermediate login URL, using a bookmarked SSO link, trimming or editing the URL, or bouncing between profiles so **`state`/cookies no longer match**.

**What to do:** Close that tab and **start login again from the streaming site’s home/login page** inside the profile you intend to use (preferably standalone Chrome per the steps above, then quit Chrome before launching capture). Avoid refreshing during redirect chains. Complete the flow in **one uninterrupted session** without switching `--user-data-dir` mid-login.

After you are logged in and on the destination site normally, retry capture.

### “Profile already in use” / `ProcessSingleton`

If Playwright prints an error like **failed to create a ProcessSingleton** or **profile is already in use**, Chrome still has (or thinks it still has) that profile locked.

- Ensure **every** Chrome window using `--user-data-dir=…/.playwright_profile` has been **quit** (not only closed).
- Never leave standalone Chrome logged into that profile **running** while you launch capture.
- On **macOS/Linux**, before Chrome starts, this tool tries to **delete stale `Singleton*` files** when **`lsof` reports no process is using them** (and uses an escaped **`pgrep`** check as a fallback only if `lsof` is missing). If cleanup is wrong for your setup, disable it with **`PLAYWRIGHT_NO_AUTO_UNLOCK=1`**. A failed launch is **retried once** after cleanup.
- **Windows**: no automatic lock cleanup yet — remove `Singleton*` manually if Chrome is exited and launch still fails.

If Chrome is definitely quit but startup still fails, Chrome may have left **stale singleton files** after a crash or a force-killed run. Inspect:

```bash
ls -la /FULL/PATH/TO/media_capture_gui/.playwright_profile/Singleton*
```

If `SingletonLock` is a symlink to a hostname-PID-style name whose target file no longer exists, clear the stale artifacts **only while Chrome using that folder is stopped**:

```bash
PROF="/FULL/PATH/TO/media_capture_gui/.playwright_profile"
rm -f "$PROF/SingletonLock" "$PROF/SingletonCookie" "$PROF/SingletonSocket"
```

(On Windows delete the equivalent `SingletonLock`, `SingletonCookie`, `SingletonSocket` entries in that folder if they remain after Chrome is exited.)

### Chrome freezes or hangs on the login tab

Heavy SSO flows or occasional GPU quirks can wedge the renderer so the tab spinner never settles.

1. **Force quit** Chrome (**⌘Q**), clear **Singleton**\* locks if needed, then retry.
2. Start the app with **`PLAYWRIGHT_DISABLE_GPU=1`** (disables GPU compositing for this Chrome launch):

   ```bash
   PLAYWRIGHT_DISABLE_GPU=1 PORT=5001 .venv/bin/python app.py
   ```

3. If redirects are extremely slow, increase **`PAGE_GOTO_TIMEOUT_MS`** (milliseconds; default `180000`, max `600000`).
4. For **Google / SSO**, prefer logging in via **standalone** Chrome with the same **`--user-data-dir`**, **⌘Q**, then capture — scripted Google sign-in inside Playwright is often blocked or unstable and can look like a jammed loader.

*************************8
THIS worked:
**************************
Do this:

1. Open Chrome manually first
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --user-data-dir="C:\Users\rodne\PycharmProjects\media_capture_gui\.playwright_profile" --remote-debugging-port=9222 about:blank

Leave that Chrome window open.

2. Start Flask with CDP set
cd C:\Users\rodne\PycharmProjects\media_capture_gui
$env:PLAYWRIGHT_CDP_URL="http://127.0.0.1:9222"
python app.py

.\.venv\Scripts\python.exe app.py
3. Open the GUI
http://127.0.0.1:5001

Then click Launch Browser & Capture.

Expected behavior: Chrome should already be open, and clicking the button should open a new tab in that existing Chrome window.

If nothing happens, check the Flask PowerShell window immediately after clicking. The key log should say:

Connecting to your Chrome session over CDP

If it says:

Playwright-managed Chrome

then PLAYWRIGHT_CDP_URL still was not set in the same PowerShell session that started Flask.

================
1. Start-to-finish PowerShell steps:
cd C:\Users\rodne\PycharmProjects\media_capture_gui

2. Kill old Chrome:
taskkill /F /IM chrome.exe

3. Start Chrome with CDP:
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="C:\Users\rodne\PycharmProjects\media_capture_gui\.playwright_profile" `
  --new-window about:blank

4. Open a second PowerShell:
cd C:\Users\rodne\PycharmProjects\media_capture_gui
$env:PLAYWRIGHT_CDP_URL="http://127.0.0.1:9222"
python app.py

5. http://127.0.0.1:5000 in your browser, click Launch Browser & Capture.

In the app:

Paste the Patreon URL.
Set wait time to 15.
Set capture time to 60.
Click Launch browser / capture.
In the Chrome window that opened earlier, log into Patreon if needed.
Refresh the Patreon tab.
Press play on the video.
Let it play while capture runs.
Copy the found .m3u8 / stream URL.
Paste it into the download URL box.
Set output like:
  C:\Users\rodne\Videos\patreon_video.mp4



