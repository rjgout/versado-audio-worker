"""Adapters for the Supertonic native HTTP API and Wyoming Piper."""
import asyncio
import io
import wave
import requests
from wyoming.client import AsyncTcpClient
from wyoming.tts import Synthesize, SynthesizeVoice
from wyoming.audio import AudioStart, AudioChunk, AudioStop

VOICES = {'piper': ['nl_NL-ronnie-medium', 'nl_NL-pim-medium', 'nl_NL-alex-medium', 'nl_NL-mls-medium', 'nl_BE-nathalie-medium', 'nl_BE-rdh-medium'], 'supertonic': [f'{s}{n}' for s in 'MF' for n in range(1, 6)]}

def synthesize(engine, voice, text, language='nl'):
    if voice not in VOICES.get(engine, []):
        raise ValueError('Onbekend model of stem')
    if engine == 'supertonic':
        import os
        response = requests.post(os.getenv('SUPERTONIC_URL', 'http://supertonic:8000') + '/v1/tts', json={'text': text, 'voice': voice, 'lang': language.split('-')[0], 'steps': 12, 'speed': 1.0}, timeout=(10, 1800))
        response.raise_for_status()
        return response.content
    return asyncio.run(_piper(voice, text))

async def _piper(voice, text):
    import os
    async def run():
        client = AsyncTcpClient(os.getenv('PIPER_HOST', 'piper'), int(os.getenv('PIPER_PORT', '10200')))
        async with client:
            await client.write_event(Synthesize(text=text, voice=SynthesizeVoice(name=voice)).event())
            fmt = None
            chunks = []
            total = 0
            while True:
                event = await client.read_event()
                if event is None:
                    raise RuntimeError('Piper heeft de verbinding gesloten')
                if AudioStart.is_type(event.type):
                    fmt = AudioStart.from_event(event)
                elif AudioChunk.is_type(event.type):
                    chunk = AudioChunk.from_event(event)
                    total += len(chunk.audio)
                    if total > 100 * 1024 * 1024:
                        raise ValueError('Audio is te groot')
                    chunks.append(chunk.audio)
                elif AudioStop.is_type(event.type):
                    break
            if not fmt or not chunks:
                raise RuntimeError('Piper gaf geen audio terug')
            output = io.BytesIO()
            with wave.open(output, 'wb') as wav:
                wav.setnchannels(fmt.channels)
                wav.setsampwidth(fmt.width)
                wav.setframerate(fmt.rate)
                wav.writeframes(b''.join(chunks))
            return output.getvalue()
    return await asyncio.wait_for(run(), 1800)
