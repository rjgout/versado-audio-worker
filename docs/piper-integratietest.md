# Echte Piper-integratietest — 29 oktober 2026

Uitgevoerd in de lokale Linux/AMD64-ontwikkelomgeving met de adapter gebouwd uit main 71a1e4e, de vastgelegde rhasspy-image-digest en UID/GID 10001. Modelbindmount was read-only. Geen NAS-test, geen kwaliteits- of prestatiemeting.

Het ongewijzigde main-pad met de oorspronkelijke rhasspy-container reproduceerde `TimeoutError` met lege fouttekst. De nieuwe diagnostiek meldde dezelfde server als bereikbaar maar zonder instellingenondersteuning. De adapter bevestigde de handshake en leverde audio.

Het script `scripts/piper_live.py` voerde 64 echte syntheseaanroepen uit: twee snelheden voor elk van de zes modellen en één korte zin per MLS-spreker. Alle WAV-antwoorden waren niet-leeg, mono, PCM16. Alle 52 namen uit de echte MLS-configuratie werden geaccepteerd.

| Model | Duur 100% | Duur 80% (length_scale 1,25) |
|---|---:|---:|
| nl_BE-nathalie-medium | 2.601 s | 3.007 s |
| nl_BE-rdh-medium | 2.392 s | 2.705 s |
| nl_NL-alex-medium | 2.879 s | 3.460 s |
| nl_NL-mls-medium | 3.460 s | 5.027 s |
| nl_NL-pim-medium | 3.808 s | 4.598 s |
| nl_NL-ronnie-medium | 4.029 s | 4.818 s |

Tekst voor de snelheidsvergelijking: “Ik, Nefi, ben geboren uit goede ouders.” Voor MLS-sprekers: “Nefi leest.” Overige parameters: sentence_silence 0,3; noise_scale 0,333; noise_w 0,333. Grotere WAV-duur controleert dat snelheid werkelijk wordt toegepast; dit bewijst geen betere uitspraak.

De modellen zijn buiten CI opgehaald van https://huggingface.co/rhasspy/piper-voices/tree/main/nl (nl_NL voor Ronnie/Pim/Alex/MLS en nl_BE voor Nathalie/RDH). Geen modellen of WAV-bestanden zijn toegevoegd aan Git. Bron/licentie per model is te vinden bij de bijbehorende MODEL_CARD op die bron. Deze test stelt geen NAS-licentie- of hardwareclaims vast.

SHA-256 van de daadwerkelijk geteste modelbestanden:

```
49cf48023861f9fd42e13a8632f068fee67d1ce244a6ee38f29595afbf0a6be4  nl_BE-nathalie-medium.onnx
fb1a9d89ff53dbd510c5d10bd1365c36a5f76249c3ca603076646fd778003db1  nl_BE-rdh-medium.onnx
22f0497c4d895a09fbc6a469459aa8954ea0955d3c6e19dbcc2e23acbb93e30b  nl_NL-alex-medium.onnx
88312e0fbf505b87caf2373d94c1384892e86b1bf2ee482cf65dc8ba179cc7d3  nl_NL-mls-medium.onnx
403e58c3675c394f505c2428117bf34cc56e9542dcf6eadbdd3a84706c12e048  nl_NL-pim-medium.onnx
ac9aba346d2088ed1ddea646a843ef97dc8e1514cc75e969c90a0c843bb5cbf5  nl_NL-ronnie-medium.onnx
```

Nog op de NAS: bevestig de gebruikte containerimage en entrypoint, behoud en controleer toegangsrechten, download/afspelen en luisterkwaliteit, CPU/geheugen en AVX-vrije werking. De test downloadt niets bij herhaling; zie de migratiehandleiding voor veilige uitvoering met bestaande modellen.
