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
            findings.append({'type':'possible_repetition' if repeated else 'unexpected_words', 'expected':[], 'heard':extra, 'expected_index':a, 'heard_start':c, 'heard_end':d})
        elif tag == 'delete':
            findings.append({'type':'possibly_missing', 'expected':source[a:b], 'heard':[], 'expected_index':a, 'heard_start':c, 'heard_end':d})
        else:
            findings.append({'type':'possible_substitution', 'expected':source[a:b], 'heard':heard[c:d], 'expected_index':a, 'heard_start':c, 'heard_end':d})
    return {'status':'manual_review', 'findings':findings, 'message':'Whisper kan fouten maken of hoorbare problemen missen; beoordeel de opname zelf.'}


def inspect_wav(data):
    """Inspect PCM incrementally so large recordings do not fill memory."""
    try:
        source=io.BytesIO(data) if isinstance(data,bytes) else str(data)
        with wave.open(source,'rb') as w:
            rate, channels, width, frames = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
            if rate < 1 or channels not in (1,2) or width != 2 or frames < 1 or w.getcomptype() != 'NONE':
                raise ValueError('WAV-formaat niet ondersteund')
            active=count=0
            remaining=frames
            while remaining:
                raw=w.readframes(min(remaining,32768))
                if not raw or len(raw) % (channels*width): raise ValueError('WAV-bestand is afgebroken')
                chunk=memoryview(raw).cast('h')
                active+=sum(abs(x)>164 for x in chunk)
                count+=len(chunk)
                remaining-=len(raw)//(channels*width)
    except (EOFError, wave.Error) as e:
        raise ValueError('Ongeldig WAV-bestand') from e
    return {'duration_seconds':frames/rate,'sample_rate':rate,'channels':channels,'near_silence':active / count < 0.01}


def attach_time_ranges(findings, segments):
    """Map token spans to coarse ASR segment ranges, never word-level precision."""
    positions=[]
    for segment in segments:
        if not isinstance(segment,dict): continue
        start,end=segment.get('start_ms'),segment.get('end_ms')
        count=len(words(segment.get('text','')))
        if type(start) not in (float,int) or type(end) not in (float,int) or start<0 or end<start:
            positions.extend([None]*count)
        else:
            positions.extend([{'start_ms':start,'end_ms':end}]*count)
    for finding in findings:
        i=finding.get('heard_start')
        if type(i) is not int or not positions: continue
        start=max(0,min(i,len(positions)-1)); end=max(start,min(max(i, finding.get('heard_end',i)-1),len(positions)-1))
        if positions[start] and positions[end]:
            finding['time_range']={'start_ms':positions[start]['start_ms'],'end_ms':positions[end]['end_ms'],'approximate':True}
    return findings
