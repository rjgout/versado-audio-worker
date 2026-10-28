FROM debian:bookworm-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends git cmake build-essential ca-certificates && rm -rf /var/lib/apt/lists/*
ARG WHISPER_COMMIT=a8d002cfd879315632a579e73f0148d06959de36
RUN git clone https://github.com/ggml-org/whisper.cpp.git /src && cd /src && git checkout "$WHISPER_COMMIT" && test "$(git rev-parse HEAD)" = "$WHISPER_COMMIT"
RUN cmake -S /src -B /build -DBUILD_SHARED_LIBS=OFF -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_SERVER=OFF -DGGML_NATIVE=OFF -DGGML_CPU_ALL_VARIANTS=OFF -DGGML_SSE42=OFF -DGGML_AVX=OFF -DGGML_AVX2=OFF -DGGML_AVX_VNNI=OFF -DGGML_AVX512=OFF -DGGML_AVX512_VBMI=OFF -DGGML_AVX512_VNNI=OFF -DGGML_AVX512_BF16=OFF -DGGML_FMA=OFF -DGGML_F16C=OFF -DGGML_BMI2=OFF && cmake --build /build --config Release --target whisper-cli -j2
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates libgomp1 && rm -rf /var/lib/apt/lists/* && useradd --uid 10001 --create-home app
RUN mkdir -p /app && chmod 755 /app
COPY --from=build /build/bin/whisper-cli /usr/local/bin/whisper-cli
COPY --chmod=644 whisper/service.py /app/service.py
USER 10001:10001
ENV WHISPER_THREADS=2 WHISPER_TIMEOUT=7200
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health',timeout=3)" || exit 1
CMD ["python", "/app/service.py"]
