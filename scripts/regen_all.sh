#!/usr/bin/env bash
# Regenerate audio for every post in content/posts/.  Runs N at a time so we
# don't hammer the Edge TTS endpoint and trip its anonymous rate limit.
set -euo pipefail
PARALLEL="${PARALLEL:-3}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
POSTS_DIR="$ROOT/content/posts"
AUDIO_DIR="$ROOT/static/audio"
mkdir -p "$AUDIO_DIR"

generate_one() {
  local md="$1"
  local slug
  slug=$(basename "$md" .md)
  local mp3="$AUDIO_DIR/$slug.mp3"
  if [[ "${SKIP_EXISTING:-1}" == "1" && -s "$mp3" ]]; then
    # Skip if MP3 already exists and is non-empty unless SKIP_EXISTING=0.
    # Caller can force regeneration with SKIP_EXISTING=0.
    echo "skip $slug (exists)"
    return
  fi
  echo "gen  $slug"
  docker run --rm --network host -v "$ROOT":/work blog-tts:latest \
    python3 /scripts/generate_audio.py \
      "/work/content/posts/$slug.md" "/work/static/audio/$slug.mp3" \
      >/dev/null 2>&1
  echo "done $slug ($(stat -c %s "$mp3") bytes)"
}
export -f generate_one
export ROOT AUDIO_DIR SKIP_EXISTING

ls "$POSTS_DIR"/*.md | grep -v '_index.md' \
  | xargs -n1 -P "$PARALLEL" -I{} bash -c 'generate_one "$@"' _ {}
