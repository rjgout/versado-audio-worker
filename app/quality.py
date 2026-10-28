"""Conservative transcript comparisons; speech recognition is never proof of quality."""
import difflib
import io
import re
import unicodedata
import wave


def words(text):
    text = unicodedata.normalize('NFC', text).casefold()
    return re.findall(r"[^\W_]+(?:['’][^\W_]+)*", text, flags=re.UNICODE)


def compare(expected, transcript):
    """Compare ASR to text actually sent to TTS; all differences require review."""
    source, heard = words(expected), words(transcript)
    if not source or not heard:
        return {'status':'manual_review', 'findings':[{'type':'uncertain', 'message':'Geen bruikbare tekst herkend.'}]}
    findings=[]
    matcher=difflib.SequenceMatcher(a=source,b=heard,autojunk=False)
    for tag,a,b,c,d in matcher.get_opcodes():
        if tag == 'equal': continue
        if tag == 'insert':
            extra=heard[c:d]
            repeated = (c >= len(extra) and heard[c-len(extra):c] == extra) or (heard[d:d+len(extra)] == extra)
            findings.append({'type':'possible_repetition' if repeated else 'unexpected_words', 'expected':[], 'heard':extra, 'expected_index':a})
        elif tag == 'delete':
            findings.append({'type':'possibly_missing', 'expected':source[a:b], 'heard':[], 'expected_index':a})
        else:
            findings.append({'type':'possible_substitution', 'expected':source[a:b], 'heard':heard[c:d], 'expected_index':a})
    return {'status':'manual_review', 'findings':findings, 'message':'Whisper kan fouten maken of hoorbare problemen missen; beoordeel de opname zelf.'}


def inspect_wav(data):
    """Report technical characteristics and silence; never accept audio by itself."""
    try:
        with wave.open(io.BytesIO(data),'rb') as w:
            rate, channels, width, frames = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
            if rate < 1 or channels not in (1,2) or width != 2 or frames < 1 or w.getcomptype() != 'NONE':
                raise ValueError('WAV-formaat niet ondersteund')
            raw = w.readframes(frames)
            if len(raw) != frames * channels * width: raise ValueError('WAV-bestand is afgebroken')
    except (EOFError, wave.Error) as e:
        raise ValueError('Ongeldig WAV-bestand') from e
    samples = memoryview(raw).cast('h')
    # Fraction is a technical measurement, not a speech recognition score.
    active = sum(abs(x) > 164 for x in samples)
    return {'duration_seconds':frames/rate,'sample_rate':rate,'channels':channels,'near_silence':active / len(samples) < 0.01}
