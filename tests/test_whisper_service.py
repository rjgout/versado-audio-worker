import hashlib
import subprocess
import pytest
from whisper import service


def test_models_missing_corrupt_and_verified(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'MODEL_DIR', tmp_path)
    with pytest.raises(ValueError, match='ontbreekt'): service.validate_model('tiny')
    path=tmp_path/'ggml-tiny.bin';path.write_bytes(b'bad')
    with pytest.raises(ValueError, match='checksum'): service.validate_model('tiny')
    monkeypatch.setitem(service.MODELS,'tiny',hashlib.sha256(b'bad').hexdigest())
    assert service.validate_model('tiny')==path
    with pytest.raises(ValueError, match='Onbekend'): service.validate_model('base.en')


def test_timeout_and_invalid_language(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'validate_model', lambda _:tmp_path/'model')
    with pytest.raises(ValueError, match='Taal'): service.transcribe(b'audio','tiny','xx')
    def timed_out(*args, **kwargs): raise subprocess.TimeoutExpired('ffmpeg',300)
    monkeypatch.setattr(service.subprocess, 'run', timed_out)
    with pytest.raises(subprocess.TimeoutExpired): service.transcribe(b'audio','tiny','nl')
