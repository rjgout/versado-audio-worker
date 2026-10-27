"""Split prepared text without changing it and assemble compatible PCM WAVs."""
import audioop
import io
import re
import wave

# Deliberately conservative: do not interpret a period following these as a sentence end.
ABBREVIATIONS = frozenset({'dhr', 'mevr', 'dr', 'ds', 'prof', 'mr', 'mej', 'bijv', 'vgl', 'vs', 'hoofdst', 'enz', 'e.a', 'o.a', 'm.a.w', 'd.w.z', 'ca', 'nr', 'st'})


def split_text(text, target=220, max_chars=300, protected=()):
    """Return exact substrings in order. Limits are soft when a word/rule is long."""
    if not 40 <= target <= max_chars <= 1000:
        raise ValueError('Ongeldige segmentgrootte')
    spans = []
    for phrase in protected:
        if phrase:
            spans.extend((m.start(), m.end()) for m in re.finditer(re.escape(phrase), text, re.IGNORECASE))
    def safe(index):
        return not any(a < index < b for a, b in spans)
    sentence = []
    for m in re.finditer(r'[.!?]+[\u2019\u201d\"\'\)\]]*(?=\s|$)', text):
        end = m.end()
        if not safe(end):
            continue
        if m.group().startswith('.'):
            prefix = text[:m.start()]
            token = re.search(r'([\w.]+)$', prefix, re.UNICODE)
            word = token.group(1).lower() if token else ''
            # Initials, decimal numbers, and scripture book abbreviations.
            if word in ABBREVIATIONS or len(word) == 1 or re.fullmatch(r'(?:\w\.)+\w', word):
                continue
            if re.match(r'\s*\d+[:.]\d+', text[end:]):
                continue
        sentence.append(end)
    result, start = [], 0
    while start < len(text):
        remaining = len(text) - start
        if remaining <= max_chars:
            result.append(text[start:]); break
        candidates = [x for x in sentence if start < x <= start + max_chars and safe(x)]
        preferred = [x for x in candidates if x >= start + target // 2]
        if preferred:
            end = min(preferred, key=lambda x: (abs(x-(start+target)), -x))
        elif candidates and candidates[-1] >= start + target // 2:
            end = candidates[-1]
        else:
            # Split on whitespace only. Never split a protected replacement.
            spaces = [m.end() for m in re.finditer(r'\s+', text[start:start+max_chars]) if safe(start+m.end())]
            if spaces:
                end = start + spaces[-1]
            else:
                match = re.search(r'\s+', text[start+max_chars:])
                end = start+max_chars+match.end() if match else len(text)
                while end < len(text) and not safe(end):
                    match = re.search(r'\s+', text[end:])
                    end = end+match.end() if match else len(text)
        result.append(text[start:end]); start=end
    return result


def join_wavs(parts, pause_ms=250, fade_ms=8):
    """Convert uncompressed mono/stereo 16-bit PCM to 44.1kHz mono and join."""
    if not parts or not 0 <= pause_ms <= 2000 or not 0 <= fade_ms <= 50:
        raise ValueError('Ongeldige audio-instellingen')
    chunks = []
    for data in parts:
        try:
            with wave.open(io.BytesIO(data), 'rb') as w:
                channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
                if w.getcomptype() != 'NONE' or width != 2 or channels not in (1, 2) or not 8000 <= rate <= 192000:
                    raise ValueError('WAV-formaat wordt niet ondersteund')
                pcm = w.readframes(w.getnframes())
        except (wave.Error, EOFError) as e:
            raise ValueError('Ongeldig WAV-bestand') from e
        if not pcm:
            raise ValueError('Leeg WAV-bestand')
        if channels == 2:
            pcm = audioop.tomono(pcm, 2, .5, .5)
        if rate != 44100:
            pcm, _ = audioop.ratecv(pcm, 2, 1, rate, 44100, None)
        # Linear fades suppress clicks at boundaries without changing playback length.
        fade = min(int(44100 * fade_ms / 1000), len(pcm) // 4)
        if fade:
            samples = bytearray(pcm)
            for i in range(fade):
                for pos, gain in ((i, i/fade), (len(samples)//2-1-i, i/fade)):
                    value = int.from_bytes(samples[pos*2:pos*2+2], 'little', signed=True)
                    samples[pos*2:pos*2+2] = int(value*gain).to_bytes(2, 'little', signed=True)
            pcm = bytes(samples)
        chunks.append(pcm)
    data = (b'\0\0' * int(44100 * pause_ms / 1000)).join(chunks)
    if len(data) > 100 * 1024 * 1024:
        raise ValueError('Audio is te groot')
    out=io.BytesIO()
    with wave.open(out,'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(44100); w.writeframes(data)
    return out.getvalue()
