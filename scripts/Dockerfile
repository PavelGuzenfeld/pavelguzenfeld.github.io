# Image with Piper TTS + ffmpeg + the Amy voice baked in.
# Build:  docker build -t blog-tts -f scripts/Dockerfile scripts/
# Run:    docker run --rm -v $(pwd):/work blog-tts \
#           python3 /scripts/generate_audio.py /work/content/posts/foo.md /work/static/audio/foo.mp3
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir piper-tts==1.4.2

# Pull the en_US Amy medium voice once so CI doesn't re-download every run.
RUN mkdir /voices && cd /voices \
    && curl -L -o en_US-amy-medium.onnx \
         https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx \
    && curl -L -o en_US-amy-medium.onnx.json \
         https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json

COPY generate_audio.py /scripts/generate_audio.py
RUN chmod +x /scripts/generate_audio.py

WORKDIR /work
