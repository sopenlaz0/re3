#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

config="${CONFIG:-release_macosx-arm64-librw_gl3_glfw-oal}"
librw_commit="${LIBRW_COMMIT:-bb7fb68}"
run_dir="${RUN_DIR:-$repo_root/run-vc}"
asset_dir="${GTA_VC_ASSET_DIR:-$HOME/Library/Application Support/Steam/steamapps/common/grand theft auto - vice city/Grand Theft Auto - Vice City.app/Contents/Resources/transgaming/c_drive/Program Files/Rockstar Games/Grand Theft Auto Vice City}"
enable_lto="${LTO:-0}"

case "$config" in
	release_*)
		buildcfg="Release"
		platform="${config#release_}"
		;;
	debug_*)
		buildcfg="Debug"
		platform="${config#debug_}"
		;;
	*)
		echo "Unsupported CONFIG '$config'. Expected release_<platform> or debug_<platform>." >&2
		exit 1
		;;
esac
built_binary="$repo_root/bin/$platform/$buildcfg/reVC"
premake_args=(--with-librw)

case "$enable_lto" in
	0|false|FALSE|no|NO)
		;;
	1|true|TRUE|yes|YES)
		premake_args+=(--lto)
		;;
	*)
		echo "Unsupported LTO value '$enable_lto'. Use LTO=1 to enable or LTO=0 to disable." >&2
		exit 1
		;;
esac

brew_packages=(premake openal-soft glfw glew mpg123 libsndfile)
if [ "${#premake_args[@]}" -gt 1 ]; then
	brew_packages+=(llvm)
fi

if ! command -v brew >/dev/null 2>&1; then
	echo "Homebrew is required. Install it from https://brew.sh, then rerun this script." >&2
	exit 1
fi

missing_packages=()
for package in "${brew_packages[@]}"; do
	if ! brew list --versions "$package" >/dev/null 2>&1; then
		missing_packages+=("$package")
	fi
done

if [ "${#missing_packages[@]}" -gt 0 ]; then
	echo "Installing missing Homebrew dependencies: ${missing_packages[*]}"
	HOMEBREW_NO_INSTALL_CLEANUP=1 brew install "${missing_packages[@]}"
else
	echo "Homebrew dependencies are already installed."
fi

if [ "${#premake_args[@]}" -gt 1 ]; then
	llvm_prefix="$(brew --prefix llvm 2>/dev/null || true)"
	llvm_ar=""
	if [ -n "$llvm_prefix" ] && [ -x "$llvm_prefix/bin/llvm-ar" ]; then
		llvm_ar="$llvm_prefix/bin/llvm-ar"
	elif command -v llvm-ar >/dev/null 2>&1; then
		llvm_ar="$(command -v llvm-ar)"
	fi
	if [ -z "$llvm_ar" ]; then
		echo "LTO requires llvm-ar. Install Homebrew llvm or rerun without LTO=1." >&2
		exit 1
	fi
	export AR="$llvm_ar"
fi

if [ -e vendor/librw ]; then
	if ! git -C vendor/librw rev-parse --is-inside-work-tree >/dev/null 2>&1; then
		echo "vendor/librw exists but is not a git checkout. Move it aside and rerun." >&2
		exit 1
	fi
else
	echo "Cloning librw..."
	git clone https://github.com/aap/librw.git vendor/librw
fi

echo "Checking out librw ${librw_commit}..."
git -C vendor/librw fetch --quiet origin
git -C vendor/librw checkout --quiet "$librw_commit"

echo "Generating shader include files..."
mkdir -p src/extras/shaders/obj
for shader in src/extras/shaders/*.vert src/extras/shaders/*.frag; do
	(cd src/extras/shaders && sh ./makeinc_glsl.sh "$(basename "$shader")")
done

echo "Generating GitSHA1.cpp..."
sh ./printHash.sh src/extras/GitSHA1.cpp

if [ ! -d "$asset_dir" ]; then
	cat >&2 <<EOF
Could not find GTA Vice City assets at:
  $asset_dir

Set GTA_VC_ASSET_DIR to the directory containing your owned Vice City files
(the one with models/, audio/, data/, TEXT/, and gta-vc.exe), then rerun.
EOF
	exit 1
fi

echo "Preparing run folder at ${run_dir}..."
mkdir -p "$run_dir"
cp -cR "$asset_dir"/. "$run_dir"/
ditto gamefiles "$run_dir"

echo "Generating makefiles..."
GTA_VC_RE_DIR="$run_dir" premake5 "${premake_args[@]}" gmake2

echo "Building ${config}..."
make -C build "config=${config}" -j"${JOBS:-$(sysctl -n hw.ncpu)}"

if [ ! -x "$built_binary" ]; then
	echo "Expected built binary not found at: $built_binary" >&2
	exit 1
fi

rm -f "$run_dir/reVC"
cp "$built_binary" "$run_dir/reVC"
if command -v codesign >/dev/null 2>&1; then
	codesign --force --sign - "$run_dir/reVC"
fi

echo
echo "Built:"
file "$run_dir/reVC"
echo
echo "Run it with:"
echo "  cd \"$run_dir\" && ./reVC"
