# macOS Apple Silicon build

This fork can build a native arm64 `reVC` binary on macOS using Premake,
Homebrew libraries, OpenGL/GLFW, OpenAL, and an owned Steam copy of GTA Vice
City.

The repository does not include game assets. You must provide your own legal
Vice City install. The old Steam macOS release stores the real Windows game
files inside the app bundle at:

```sh
$HOME/Library/Application Support/Steam/steamapps/common/grand theft auto - vice city/Grand Theft Auto - Vice City.app/Contents/Resources/transgaming/c_drive/Program Files/Rockstar Games/Grand Theft Auto Vice City
```

## One-command setup

From the repo root:

```sh
./utils/build-macos-arm64.sh
```

The script will:

- install/check Homebrew packages: `premake`, `openal-soft`, `glfw`, `glew`,
  `mpg123`, and `libsndfile`
- clone `librw` into `vendor/librw`
- pin `librw` to commit `bb7fb68`, which matches this source tree's MatFX API
- generate the missing shader include files and `src/extras/GitSHA1.cpp`
- copy your owned Steam game files into `run-vc/`
- overlay this repo's `gamefiles/`
- build `release_macosx-arm64-librw_gl3_glfw-oal`
- copy the final `reVC` binary into `run-vc/`

Then run:

```sh
cd run-vc
./reVC
```

## Vice City Deluxe asset overlay

The native `reVC` binary can load replacement data, models, textures, and text
files from mods such as Vice City Deluxe. It cannot load Windows-only runtime
hooks such as `.asi`, `.dll`, or CLEO scripts.

Prepare the normal `run-vc/` folder first, then create a separate local overlay
folder:

```sh
cp -a run-vc run-vc-deluxe
rsync -rt \
  --exclude='*.dll' --exclude='*.DLL' \
  --exclude='*.asi' --exclude='*.ASI' \
  --exclude='*.cs' --exclude='*.CS' \
  --exclude='*.cleo' --exclude='*.CLEO' \
  --exclude='CLEO/' \
  "/path/to/extracted/Vice City Deluxe/" run-vc-deluxe/
python3 utils/patch-vc-deluxe-assets.py --base run-vc --target run-vc-deluxe
```

The patch step repairs local mod data that does not match this port:

- merges missing `reVC` frontend/config text keys into the Deluxe English GXT
- replaces Deluxe's white-only bike color entries for `sanchez`, `pcj600`, and
  `faggio` with working base-game color sets

After rebuilding the binary, copy it into the Deluxe run folder if needed:

```sh
./utils/build-macos-arm64.sh
rm -f run-vc-deluxe/reVC
cp run-vc/reVC run-vc-deluxe/reVC
codesign --force --sign - run-vc-deluxe/reVC
cd run-vc-deluxe
./reVC
```

## Performance notes

For a native macOS build, Game Porting Toolkit is useful as a reference and for
testing the original Windows executable, but it does not accelerate this
OpenGL/GLFW `reVC` binary directly.

To build this native port with link-time optimization, run:

```sh
LTO=1 ./utils/build-macos-arm64.sh
```

Longer-term macOS rendering performance work should target a real Metal backend
for `librw`. The current native path uses the `librw` OpenGL backend.

## Custom asset path

If your Vice City files are somewhere else, point the script at the directory
that contains `models/`, `audio/`, `data/`, `TEXT/`, and `gta-vc.exe`:

```sh
GTA_VC_ASSET_DIR="/path/to/Grand Theft Auto Vice City" ./utils/build-macos-arm64.sh
```

## Manual build notes

The important build fixes are:

- macOS Premake target flags no longer pass `-std=gnu++14` to C files
- GL3/GLFW builds define `LIBRW_GLFW`
- Apple Silicon Homebrew paths under `/opt/homebrew` are included
- Intel Homebrew and MacPorts paths are still included
- macOS GLFW keeps video-mode selection valid when fullscreen modes are missing
  or the saved fullscreen preference is unavailable
- retina framebuffer dimensions are applied before camera sizing

Local-only directories such as `run-vc/`, `vendor/librw/`, `build/`, and `bin/`
are ignored by git.
