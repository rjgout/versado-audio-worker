"""Per-connection settings for the pinned Wyoming Piper implementation."""
import copy
import math
import runpy
from wyoming.event import Event
from wyoming_piper.handler import PiperEventHandler

original = PiperEventHandler.handle_event

async def handle(self, event):
    if event.type == 'versado-settings':
        bounds={'length_scale':(1/1.2,1/0.7),'sentence_silence':(0,3),'noise_scale':(0,1),'noise_w':(0,1)}
        options=event.data
        if not isinstance(options,dict) or set(options)!=set(bounds): return False
        if any(type(options[k]) not in (int,float) or not math.isfinite(options[k]) or not lo<=options[k]<=hi for k,(lo,hi) in bounds.items()): return False
        self.cli_args=copy.copy(self.cli_args)
        for key,value in options.items(): setattr(self.cli_args,'noise_w_scale' if key=='noise_w' else key,value)
        await self.write_event(Event(type='versado-settings-ready',data=options))
        return True
    return await original(self,event)

PiperEventHandler.handle_event=handle
if __name__=='__main__': runpy.run_module('wyoming_piper',run_name='__main__')
