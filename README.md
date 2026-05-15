# Media Capture GUI

A Flask web application that uses Playwright to launch a visible Chrome browser and capture media URLs (HLS, DASH, MP4, etc.) from network traffic during a browsing session.

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
python app.py
```

The app listens on **http://127.0.0.1:5000** by default. If you see **`Address already in use`**, port 5000 is taken — on macOS that is commonly **AirPlay Receiver** (**System Settings → General → AirDrop & Handoff → AirPlay Receiver** → off), or another process. Easiest workaround: run on another port:

```bash
PORT=5001 python app.py
```

Then open **http://127.0.0.1:5001** in your browser.

You can always set **`PORT`** to any free TCP port instead of disabling AirPlay.

Optional environment variables (local dev defaults are chosen so Playwright and Chrome behave predictably):

| Variable | Default | Purpose |
|---------|---------|---------|
| `FLASK_DEBUG` | on when unset (`0` / `false` / `no` to disable) | Verbose Flask errors |
| `FLASK_USE_RELOADER` | unset (off) | Set to `1` / `true` / `yes` to enable Flask’s debug reloader; **often conflicts** with capturing while Chrome owns the profile folder |
| `CAPTURE_JOB_STORE_MAX` | `100` | Max completed/error jobs retained in memory (oldest pruned first) |

## How It Works

1. Enter the URL of a streaming page you want to inspect.
2. (Optional) Adjust the **Profile Directory**, **Wait Before Capture** (seconds to allow login/interaction), and **Timeout** (capture duration) settings.
3. Click **Start Capture** — a visible Chrome window will open and navigate to the URL.
4. Authenticate or interact with the page as needed, then start playing the video.
5. The app captures all network requests/responses matching common media URL patterns (`m3u8`, `mpd`, `mp4`, `hls`, `dash`, etc.).
6. Results are displayed in the GUI when capture is complete.

## Configuration Options

| Field | Default | Description |
|---|---|---|
| Profile Directory | `.playwright_profile` | Chrome user data directory (persists cookies/login state) |
| Wait Before Capture | `60` seconds | Time given to log in and start video playback before capture begins |
| Timeout | `120` seconds | Duration to listen for media URLs after the wait period |

## Login, Google sign-in, and the Playwright profile

These notes matter when the site (or Google) requires you to authenticate before playback.

### This profile is not your everyday Chrome

The **Profile Directory** (default `.playwright_profile`) is a **separate** Chrome profile. Cookies and login state from your normal Chrome windows **do not** apply here. You must sign in **once** inside this profile (or complete whatever login the host needs while using it).

### Google blocks automation browsers

Google Account sign-in often fails inside Playwright-launched Chrome (e.g. *“This browser or app may not be secure”* and a **“controlled by automated test software”** banner).

**Recommended approach:**

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
5. **Now** run `python app.py` / **Start Capture** so Playwright can open that profile.

### Google shows “400 … malformed … should not be retried”

If the **Chrome address bar is on Google** (`accounts.google.com`, `oauth`, etc.) and the page says roughly **400** and **malformed**:

- That message is from **Google’s servers**, not this Flask app. It usually means the **authorization request was corrupted or replayed**: for example refreshing an intermediate login URL, using a bookmarked SSO link, trimming or editing the URL, or bouncing between profiles so **`state`/cookies no longer match**.

**What to do:** Close that tab and **start login again from the streaming site’s home/login page** inside the profile you intend to use (preferably standalone Chrome per the steps above, then quit Chrome before launching capture). Avoid refreshing during redirect chains. Complete the flow in **one uninterrupted session** without switching `--user-data-dir` mid-login.

After you are logged in and on the destination site normally, retry capture.

### “Profile already in use” / `ProcessSingleton`

If Playwright prints an error like **failed to create a ProcessSingleton** or **profile is already in use**, Chrome still has (or thinks it still has) that profile locked.

- Ensure **every** Chrome window using `--user-data-dir=…/.playwright_profile` has been **quit** (not only closed).
- Never leave standalone Chrome logged into that profile **running** while you launch capture.

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

