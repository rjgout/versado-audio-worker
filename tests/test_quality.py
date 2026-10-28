import io
import wave
import pytest
from app.quality import compare, inspect_wav


def test_compare_uses_prepared_pronunciation_and_detects_repeat():
    report=compare('En ik, Neefi, ging verder.', 'En ik Neefi ging ging verder')
    assert report['status']=='manual_review'
    assert any(x['type']=='possible_repetition' for x in report['findings'])
    assert not any('neefi' in x.get('expected',[]) for x in report['findings'])


def test_uncertain_and_missing():
    assert compare('Dit is tekst','')['findings'][0]['type']=='uncertain'
    assert any(x['type']=='possibly_missing' for x in compare('een twee drie','een drie')['findings'])
    assert compare('Léhi, zei: “Hallo!”','léhi zei hallo')['findings']==[]
    assert compare('één twee','één twee')['status']=='manual_review'


def test_wav_silence_and_invalid():
    output=io.BytesIO()
    with wave.open(output,'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0\0'*16000)
    result=inspect_wav(output.getvalue())
    assert result['near_silence'] and result['duration_seconds']==1
    with pytest.raises(ValueError): inspect_wav(b'invalid')


def test_time_ranges_are_coarse_not_word_precision():
    from app.quality import attach_time_ranges
    report=compare('Neefi ging verder', 'Neefi ging ging verder')
    segments=[{'text':'Neefi ging','start_ms':0,'end_ms':2000}, {'text':'ging verder','start_ms':2000,'end_ms':4800}]
    finding=attach_time_ranges(report['findings'], segments)[0]
    assert finding['time_range']['approximate'] is True
    assert finding['time_range']['start_ms'] in (0,2000)
