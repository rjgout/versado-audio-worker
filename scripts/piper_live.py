"""Opt-in real inference integration test. Uses installed models, never downloads.
Run from repository root: PIPER_HOST=127.0.0.1 PIPER_PORT=11020 python scripts/piper_live.py /path/to/models
"""
import asyncio
import io
import json
import sys
import wave
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.engines import VOICES, synthesize, validate_settings, piper_health


def duration(data):
    with wave.open(io.BytesIO(data),'rb') as wav:
        assert wav.getnchannels()==1 and wav.getsampwidth()==2 and wav.getnframes()>0
        return wav.getnframes()/wav.getframerate()


def run(root):
    health=asyncio.run(piper_health())
    assert health['ready'],health
    results=[]
    for model in sorted(root.rglob('*.onnx')):
        if model.stem not in VOICES['piper']: continue
        config=json.loads(model.with_name(model.name+'.json').read_text())
        settings=validate_settings('piper',{})
        text='Ik, Nefi, ben geboren uit goede ouders.'
        normal=duration(synthesize('piper',model.stem,text,settings=settings))
        slow=duration(synthesize('piper',model.stem,text,settings={**settings,'length_scale':1.25}))
        assert slow>normal,(model.stem,normal,slow)
        results.append({'voice':model.stem,'normal_seconds':normal,'slow_seconds':slow})
        if model.stem=='nl_NL-mls-medium':
            for name,ident in sorted(config['speaker_id_map'].items(),key=lambda item:item[1]):
                voice=model.stem+'#'+name
                seconds=duration(synthesize('piper',voice,'Nefi leest.',settings=settings))
                results.append({'voice':voice,'speaker_id':ident,'seconds':seconds})
    assert results,'Geen ondersteunde modellen aangetroffen'
    return results

if __name__=='__main__': print(json.dumps(run(Path(sys.argv[1])),ensure_ascii=False,indent=2))
