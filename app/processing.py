"""Bounded, non-destructive local audio processing."""
import subprocess
import tempfile
from pathlib import Path

def filter_wav(source):
    with tempfile.TemporaryDirectory(prefix='versado-filter-') as tmp:
        target=Path(tmp)/'filtered.wav'
        subprocess.run(['ffmpeg','-nostdin','-v','error','-threads','1','-i',str(source),'-af','afftdn=nr=6:nf=-50','-c:a','pcm_s16le',str(target)],check=True,timeout=1800,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if target.stat().st_size>100*1024*1024: raise ValueError('Audio is te groot')
        return target.read_bytes()
