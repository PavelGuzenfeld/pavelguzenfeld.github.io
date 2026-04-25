# Image with edge-tts (Microsoft Neural voices, free, no API key).
# Build:  docker build -t blog-tts -f scripts/Dockerfile scripts/
# Run:    docker run --rm -v $(pwd):/work blog-tts \
#           python3 /scripts/generate_audio.py /work/content/posts/foo.md /work/static/audio/foo.mp3
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir edge-tts==7.2.8 pyyaml==6.0.2

COPY generate_audio.py /scripts/generate_audio.py
RUN chmod +x /scripts/generate_audio.py

WORKDIR /work
