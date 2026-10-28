# Whisper-kwaliteitscontrole — werk in uitvoering

Deze branch is een eerste fase en is **niet gereed voor NAS-deployment**. De controle vergelijkt de voorbereide TTS-tekst met een lokaal Whisper-transcript en meldt mogelijke toevoegingen, herhalingen en ontbrekende of andere woorden. Zij geeft altijd `manual_review`, ook bij een overeenkomst. Stotteringen kunnen onopgemerkt blijven en herkenningsfouten kunnen vals alarm geven. Het WAV-onderzoek controleert formaat, duur en vrijwel volledige stilte; er is nog geen betrouwbare detectie van lettergrepen, lange stiltes, afgebroken einden, volgorde of onwaarschijnlijke duur.

De service bouwt whisper.cpp commit `a8d002cfd879315632a579e73f0148d06959de36` (v1.7.6) zonder native optimalisatie en met AVX, AVX2, AVX512, FMA, F16C en BMI2 expliciet uitgeschakeld. De J4125 is hiermee nog niet getest. De service draait met UID 10001, accepteert maximaal één analyse tegelijk, gebruikt standaard twee threads en publiceert geen hostpoort. De app verwerkt generatie en controle na elkaar in één worker. Een gedeeld bestandslot in de pronunciation-map zorgt dat een Whisper-proces dat na een app-herstart doorloopt geen nieuwe generatie overlapt. Het stoppen van een al actieve analyse is nog niet geïmplementeerd en herstartgedrag met echte engines moet nog worden bevestigd. De gezondheidscontrole betekent alleen dat de service bereikbaar is, niet dat een model beschikbaar is.

De Compose-service heeft profiel `quality`, een interne poort, een alleen-lezen modelbindmount en instelbare `WHISPER_THREADS` (1–4), `WHISPER_TIMEOUT` en `WHISPER_MEMORY`. Deze service moet handmatig worden gebouwd uit de repository; een Portainer-stack met alleen de editor heeft geen buildcontext. De app blijft bruikbaar zonder deze service zolang de kwaliteitscontrole niet wordt gekozen. Er is nog geen goedgekeurde privé-image of uitgewerkte Portainer-updateprocedure.

## Modellen

Gebruik de meertalige ggml-modellen van `ggerganov/whisper.cpp` op Hugging Face, niet `.en`-modellen. Download ze uitsluitend handmatig naar `/volume1/docker/versado-audio-worker/whisper-models/`, controleer SHA-256 en geef UID 10001 leesrechten. De service verifieert bij ieder verzoek de volgende hashes:

| Model | Bestand | SHA-256 |
|---|---|---|
| tiny | ggml-tiny.bin | be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21 |
| base | ggml-base.bin | 60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe |
| small | ggml-small.bin | 1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b |

Bron: `https://huggingface.co/ggerganov/whisper.cpp/tree/main`. Controleer de upstream-herkomst en hash met `sha256sum`; geen model wordt automatisch gedownload. Start bij een echte evaluatie met base en vergelijk eventueel tiny en small op snelheid en kwaliteit.

## Persistente gegevens en rollback

Schemaversie 3 voegt een nullable modelkolom en de tabel `quality_tasks` toe; bestaande opnamen en uitspraakregels worden niet aangepast. Taken die tijdens een herstart actief waren krijgen de status mislukt. Wachtende taken blijven bewaard; de originele WAV blijft behouden als controle mislukt. Maak vóór iedere test een consistente back-up van de SQLite-database **en** de map `tests`, bijvoorbeeld door eerst de stack te stoppen en beide mappen inclusief WAL-bestanden te kopiëren. Voor terugrollen: stop de stack, herstel beide samen uit dezelfde back-up en start de vorige image. Test deze procedure eerst buiten productie.

## Nog te bouwen

Stabiele fragmenten, kandidaten, gerichte hergeneratie en veilige audioversies ontbreken. Automatisch verbeteren is niet beschikbaar. Het stoppen van reeds gestarte analyses en veilige afstemming bij herstart zijn niet klaar. Er is geen precieze tijdcode voor bevindingen, er zijn nog geen kwaliteitscontroles van daadwerkelijk opgenomen M5-spraak, geen J4125-test en geen betrouwbaar gemeten fout- of duurgrenzen. De UI biedt nog geen volledig beoordelingsscherm of handmatige controle van eerdere opnamen. De implementatie mag niet als volledig of productierijp worden beschouwd.

## NAS-acceptatie na afronding

Maak een back-up; installeer en controleer model en rechten. Meet per model tiny/base/small op goede en bekende stotterende M5-opnamen: herkende en gemiste herhalingen, vals alarm, tijd, CPU en RAM. Vergelijk herkenning met zowel de originele als de werkelijk uitgesproken tekst. Beoordeel iedere WAV zelf; een match bewijst geen prettige spraak. Test herstart en terugzetten van database én audio en controleer dat geen oude bestanden worden overschreven. Resultaten zijn nog niet beschikbaar.

## Uitgevoerde lokale proef

In de ontwikkelomgeving is de vastgepinde bron lokaal uitgecheckt en met dezelfde CMake-vlaggen in een container gebouwd; dit gebruikte een lokale buildcontext omdat de Docker-buildomgeving het GitHub-certificaat niet vertrouwde. Het meertalige tiny-model is handmatig gedownload en de bovenstaande SHA-256 is bevestigd. De service transcribeerde de meegeleverde Engelstalige `samples/jfk.wav` met de echte Whisper-binary. Dit controleert de technische aanroep, niet de Nederlandse herkenningskwaliteit of compatibiliteit met de J4125. De reguliere Dockerfile en de CI-build moeten afzonderlijk worden bevestigd.
