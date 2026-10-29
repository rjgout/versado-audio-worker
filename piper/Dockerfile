FROM rhasspy/wyoming-piper:2.5.2@sha256:7d39aafac409c2b6b09d999ed04d84c311d632e558b35baa60fad6aac722af7a
COPY --chmod=644 piper/adapter.py /usr/src/versado_adapter.py
ENTRYPOINT ["/usr/src/.venv/bin/python3", "/usr/src/versado_adapter.py"]
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD /usr/src/.venv/bin/python3 -c "import socket; socket.create_connection(('127.0.0.1',10200),3).close()"
