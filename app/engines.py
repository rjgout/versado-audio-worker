"""Adapters for the Supertonic native HTTP API and Wyoming Piper."""
import asyncio
import io
import math
import wave
import requests
from wyoming.client import AsyncTcpClient
from wyoming.tts import Synthesize, SynthesizeVoice
from wyoming.audio import AudioStart, AudioChunk, AudioStop

VOICES = {'piper': ['nl_NL-ronnie-medium', 'nl_NL-pim-medium', 'nl_NL-alex-medium', 'nl_NL-mls-medium', 'nl_BE-nathalie-medium', 'nl_BE-rdh-medium'], 'supertonic': [f'{s}{n}' for s in 'MF' for n in range(1, 6)]}

SUPERTONIC_DEFAULTS = {'steps': 12, 'speed': 1.0, 'silence_duration': 0.3}

def validate_settings(engine, settings):
    if not isinstance(settings, dict):
        raise ValueError('Instellingen moeten een object zijn')
    if engine == 'piper':
        if settings: raise ValueError('Piper ondersteunt hier geen extra instellingen')
        return {}
    if engine != 'supertonic' or set(settings) - set(SUPERTONIC_DEFAULTS):
        raise ValueError('Onbekende instelling')
    result = {**SUPERTONIC_DEFAULTS, **settings}
    steps = result['steps']
    if type(steps) is not int or not 1 <= steps <= 100:
        raise ValueError('Stappen moeten een geheel getal tussen 1 en 100 zijn')
    for name, low, high in [('speed', 0.7, 2.0), ('silence_duration', 0.0, 10.0)]:
        value = result[name]
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError('Ongeldige waarde voor ' + name)
        result[name] = float(value)
    return result

def stored_settings(engine, settings):
    # Jobs queued by older releases may use total_steps or omit silence.
    if engine == 'piper': return {}
    settings = dict(settings)
    if 'total_steps' in settings:
        settings.setdefault('steps', settings.pop('total_steps'))
    return validate_settings(engine, settings)

def synthesize(engine, voice, text, language='nl', settings=None):
    base_voice, separator, speaker = voice.partition('#')
    if base_voice not in VOICES.get(engine, []) or (separator and (engine != 'piper' or base_voice != 'nl_NL-mls-medium' or not speaker.isdecimal())):
        raise ValueError('Onbekend model of stem')
    if engine == 'supertonic':
        import os
        options = stored_settings(engine, settings or {})
        response = requests.post(os.getenv('SUPERTONIC_URL', 'http://supertonic:8000') + '/v1/tts', json={'text': text, 'voice': voice, 'lang': language.split('-')[0], **options}, timeout=(10, 1800))
        response.raise_for_status()
        return response.content
    return asyncio.run(_piper(base_voice, text, speaker if separator else None))

async def _piper(voice, text, speaker=None):
    import os
    async def run():
        client = AsyncTcpClient(os.getenv('PIPER_HOST', 'piper'), int(os.getenv('PIPER_PORT', '10200')))
        async with client:
            await client.write_event(Synthesize(text=text, voice=SynthesizeVoice(name=voice, speaker=speaker)).event())
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
