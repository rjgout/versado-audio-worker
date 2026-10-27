import io
import wave
import pytest
from app.segmentation import split_text, join_wavs


def wav(rate=22050, channels=1):
    out=io.BytesIO()
    with wave.open(out,'wb') as w:
        w.setnchannels(channels); w.setsampwidth(2); w.setframerate(rate); w.writeframes(b'\0\0' * channels * rate)
    return out.getvalue()


def test_split_preserves_unicode_and_protected_phrase():
    text=('Dr. Nephi zei: “Dit is een voorbeeld.” ' * 12) + 'De naam Léhi eindigt hier.'
    segments=split_text(text, target=150, max_chars=200, protected=['Dit is een voorbeeld'])
    assert ''.join(segments)==text
    assert len(segments)>1
    assert all(len(s)<=200 for s in segments)
    assert all(not s.endswith('Dr.') for s in segments)
    assert sum(s.count('Dit is een voorbeeld') for s in segments)==12


def test_split_never_breaks_long_word():
    text='A ' + 'x'*400 + ' einde.'
    parts=split_text(text,150,200)
    assert ''.join(parts)==text
    assert 'x'*400 in parts[1]


def test_join_validates_and_converts():
    result=join_wavs([wav(22050), wav(44100,2)], pause_ms=250)
    with wave.open(io.BytesIO(result),'rb') as w:
        assert (w.getnchannels(),w.getsampwidth(),w.getframerate())==(1,2,44100)
        assert abs(w.getnframes()-int(44100*2.25))<5
    with pytest.raises(ValueError): join_wavs([b'invalid'])
