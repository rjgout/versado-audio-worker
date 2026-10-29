"""Runs inside the pinned engine; substitutes only model inference."""
import sys
sys.path.insert(0,'/usr/src')
import asyncio
import argparse
import io
import wave
import versado_adapter
import wyoming_piper.handler as engine
from wyoming.event import Event

handler=engine.PiperEventHandler.__new__(engine.PiperEventHandler)
original=argparse.Namespace(length_scale=None,noise_scale=None,noise_w_scale=None,sentence_silence=0,use_cuda=False)
handler.cli_args=original
received=[]
async def write(event): received.append(event)
handler.write_event=write
options={'length_scale':1.25,'sentence_silence':0.45,'noise_scale':0.2,'noise_w':0.4}
assert asyncio.run(handler.handle_event(Event(type='versado-settings',data=options)))
assert handler.cli_args is not original and original.length_scale is None
assert received[0].data==options
seen=[]
class Voice:
    config=argparse.Namespace(speaker_id_map={'2450':0})
    def synthesize_wav(self,text,wav,config): seen.append((text,config))
engine._VOICE=Voice();engine._VOICE_NAME='nl_NL-mls-medium'
handler._synthesize_piper('tekst',None,'nl_NL-mls-medium','2450')
config=seen[0][1]
assert config.length_scale==1.25 and config.noise_scale==0.2 and config.noise_w_scale==0.4 and config.speaker_id==0
assert handler.cli_args.sentence_silence==0.45
print('Real Piper synthesis configuration verified; inference mocked, no model download.')
