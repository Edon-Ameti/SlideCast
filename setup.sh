#!/bin/sh
# SlideCast setup for macOS. The Windows equivalent is setup.bat.

cd "$(dirname "$0")" || exit 1

echo
echo "  SlideCast setup"
echo "  ---------------"
echo

if ! command -v brew >/dev/null 2>&1; then
  echo "  This needs Homebrew, which was not found. Install it from"
  echo "  https://brew.sh and run this again."
  echo
  exit 1
fi

# Word-by-word highlighting listens back to the generated voice, which is the
# one thing here that needs a package rather than a program.
whisper() {
  command -v python3 >/dev/null 2>&1 || return 0
  if python3 -c "import faster_whisper" >/dev/null 2>&1; then
    echo "    [x] faster-whisper (word-by-word subtitle highlighting)"
    echo
    return 0
  fi
  echo "  Optional: word-by-word subtitle highlighting needs the faster-whisper"
  echo "  package, about 200 MB with what it depends on. Everything else works"
  echo "  without it."
  printf "  Install it now? [y/N] "
  read -r FW
  case "$FW" in
    [Yy]*) ;;
    *) return 0 ;;
  esac
  if ! python3 -m pip install faster-whisper; then
    echo
    echo "  pip refused. A Homebrew Python guards itself against system-wide"
    echo "  installs, and getting past that means saying so outright:"
    echo "      python3 -m pip install --break-system-packages faster-whisper"
  fi
  echo
}

echo "  What this machine already has:"
echo

FORMULAE=""
CASKS=""

if command -v python3 >/dev/null 2>&1; then
  echo "    [x] Python 3"
else
  FORMULAE="$FORMULAE python"
  echo "    [ ] Python 3        - will install"
fi

if command -v ffmpeg >/dev/null 2>&1; then
  echo "    [x] ffmpeg"
else
  FORMULAE="$FORMULAE ffmpeg"
  echo "    [ ] ffmpeg          - will install"
fi

if [ -d "/Applications/Google Chrome.app" ]; then
  echo "    [x] Google Chrome"
else
  CASKS="$CASKS google-chrome"
  echo "    [ ] Google Chrome   - will install"
fi

if [ -d "/Applications/Docker.app" ]; then
  echo "    [x] Docker Desktop"
else
  CASKS="$CASKS docker"
  echo "    [ ] Docker Desktop  - will install (large)"
fi

echo
if [ -z "$FORMULAE$CASKS" ]; then
  echo "  Everything SlideCast needs is already installed."
  echo
  whisper
  printf "  Start SlideCast now? [Y/n] "
  read -r GO
  case "$GO" in
    [Nn]*) exit 0 ;;
  esac
  exec ./run.sh
fi

echo "  These will be installed with Homebrew:"
echo " $FORMULAE$CASKS"
echo
printf "  Install them now? [y/N] "
read -r GO
case "$GO" in
  [Yy]*) ;;
  *) echo; echo "  Nothing was installed."; exit 1 ;;
esac

# Formulae and casks cannot go in one call: --cask applies to the whole
# command, so brew would try to install python itself as a cask.
# Unquoted on purpose, so each name reaches brew as its own word.
# shellcheck disable=SC2086
if [ -n "$FORMULAE" ]; then
  brew install $FORMULAE || exit 1
fi
# shellcheck disable=SC2086
if [ -n "$CASKS" ]; then
  brew install --cask $CASKS || exit 1
fi

echo
echo "  Done. Open Docker Desktop once by hand before the voice will work,"
echo "  then start SlideCast with:  ./run.sh"
echo
whisper
