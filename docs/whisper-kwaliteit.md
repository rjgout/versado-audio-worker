# Lokale Whisper-kwaliteitscontrole

Deze draft ondersteunt een optionele lokale controle van nieuwe én bestaande opnamen. De controle vergelijkt Whisper primair met de daadwerkelijk uitgesproken TTS-tekst. Een rapport bevat transcript, mogelijke herhalingen, ontbrekende of afwijkende woorden, technische waarschuwingen en waar beschikbaar een **indicatief** tijdvak van een Whisper-segment. Een overeenkomst bewijst geen foutloze opname; Whisper kan stotteringen missen of zelf fouten maken. Luister altijd zelf.

## Status en beperkingen

De implementatie moet nog op de Synology en met echte Nederlandse M5-opnamen worden gecontroleerd. Het meertalige tiny-model en een Engelstalig upstream-fragment zijn lokaal met de echte binary getest; dat is geen Nederlandse kwaliteitsmeting en bewijst geen J4125-compatibiliteit. Detectie van afzonderlijke lettergreepstotteringen, lange stiltes, afgebroken begin en einde, en betrouwbare duurafwijkingen is niet compleet. Een lopende analyse kan worden gestopt; bij herstart wordt een actieve taak als onderbroken geregistreerd en wordt de service verzocht deze te beëindigen. Een gedeeld bestandslot beschermt het zware werk, maar controleer dit met echte engines op de NAS. Automatische hergeneratie en fragmentversies zijn bewust niet onderdeel van deze fase.

## Images en Portainer

Na een gecontroleerde merge naar main bouwt CI de app en de aparte `ghcr.io/rjgout/versado-audio-worker-whisper`-image, test ze en publiceert `latest` en `sha-<volledige commit>`. Een draft-PR publiceert niets. Controleer in GitHub Packages dat **beide** packages privé zijn en toegang geven aan de repository. Bij de eerste publicatie moet de eigenaar de packagezichtbaarheid zelf controleren: een workflow kan een eerder openbaar gemaakt package niet veilig privé veronderstellen.

1. Maak een consistente back-up zoals hieronder beschreven. Verwijder geen bestaande map of opname.
2. Voeg in Portainer bij Registries `ghcr.io` toe met GitHub-gebruikersnaam en een classic token met `read:packages` en toegang tot beide private packages. Bewaar het token uitsluitend in Portainer. Configureer de toegang tot private packages en eventuele SSO-autorisatie op GitHub.
3. Voeg de modelmap toe en installeer het meertalige base-model zoals hieronder. Maak ook voldoende tijdelijke schijfruimte beschikbaar voor een WAV-conversie.
4. Gebruik de `compose.yaml` uit deze repository als Portainer Git-stack of plak de volledige inhoud in de stack-editor. De Compose bevat alleen image-referenties en heeft geen NAS-buildcontext nodig. Behoud de huidige `SECRET_KEY`, `PASSWORD_HASH`, overige environmentwaarden, volumes en NAS-poort 5006. Voeg desgewenst `WHISPER_THREADS=2`, `WHISPER_TIMEOUT=7200`, `WHISPER_MEMORY=3g` en `WHISPER_IMAGE_TAG=sha-<volledige-commit>` toe. `IMAGE_TAG` selecteert de app-image. Voor een gecontroleerde update gebruik dezelfde geteste commit voor beide tags. Er zijn geen CPU CFS-quota en er wordt geen Whisper-hostpoort gepubliceerd.
5. Update de bestaande stack handmatig met de private registry. Start de service en controleer logs en de knop **Controleer beschikbaarheid** in Voice Lab. Deze toont afzonderlijk servicebereikbaarheid, binary, model, checksum en gereedheid. De gewone generatie werkt ook zonder een beschikbare Whisper-service, mits de controle uit staat.
6. Bij een bestaande voltooide opname: kies een model, selecteer **Controleer audiokwaliteit** en open **Kwaliteitsrapporten**. Bestaande WAV-bestanden worden niet gewijzigd. Rapporten blijven in de database. Een lopende of wachtende controle kan worden gestopt via de opnamegegevens; controleer dat de status verandert en de originele audio afspeelbaar blijft.

De app en Whisper mounten dezelfde `pronunciation`-map voor het werklot. Geef UID/GID 10001 lees- en schrijfrechten op die map en op `tests`; geef UID 10001 lees- en traverseerrechten op de modelmap. Gebruik niet meerdere app-instanties. `WHISPER_THREADS` is begrensd op 1–4. De app-worker en service gebruiken dezelfde lock; afhankelijk van de concrete engine kan deze na een app-crash nog werk afmaken. Test dat scenario voordat dit dagelijks wordt gebruikt.

## Base-model installeren

Op de NAS in een vertrouwde shell, als een gebruiker met rechten op de map:

```sh
mkdir -p /volume1/docker/versado-audio-worker/whisper-models
cd /volume1/docker/versado-audio-worker/whisper-models
# Stop als het doel al bestaat: controleer en hergebruik het in plaats van overschrijven.
test ! -e ggml-base.bin || { echo 'Model bestaat al; controleer de checksum.'; exit 1; }
curl -fL -o ggml-base.bin.part https://huggingface.co/ggerganov/whisper.cpp/resolve/80da2d8bfee42b0e836fc3a9890373e5defc00a6/ggml-base.bin
printf '%s  %s\n' '60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe' 'ggml-base.bin.part' | sha256sum -c - && mv -n ggml-base.bin.part ggml-base.bin
```

Controleer de uitvoer van `sha256sum -c` voordat u `mv` uitvoert; voer na een fout de laatste regel niet uit. Zorg dat UID 10001 de map kan doorlopen en het model lezen. Herstart Whisper indien nodig en controleer de beschikbaarheid in de app.

Overige meertalige modellen van dezelfde bron: `ggml-tiny.bin`, SHA-256 `be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21`; `ggml-small.bin`, SHA-256 `1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b`. Gebruik geen `.en`-modellen. De service controleert voor iedere analyse de checksum; er is geen download bij containerstart.

## Back-up, update en terugrollen

Stop de stack voordat u een consistente back-up van zowel `pronunciation` (inclusief SQLite en WAL-bestanden) als `tests` maakt. Bewaar de huidige Compose en beide image-SHA-tags. Maak tijdens het terugrollen geen mix van database en audiobestanden uit verschillende back-ups: stop de stack, herstel beide mappen uit hetzelfde back-upmoment, kies beide eerdere SHA-tags en start de oude stack. De nieuwe schemaversie voegt een tabel en kolom toe; wijzigingen ná de back-up gaan bij volledige terugzet verloren. Test de herstelprocedure eerst op een aparte kopie. Verwijder nooit modelmappen als onderdeel van rollback.

## Reproduceerbare NAS-evaluatie

1. Maak kopieën van ten minste enkele goede en hoorbaar stotterende M5-opnamen van dezelfde tekst. Noteer per opname onafhankelijk van Whisper de bekende stotteringen en tijdvakken na handmatig luisteren.
2. Analyseer elk bestand met base; herhaal met tiny en small als geheugen en tijd dat toelaten. Noteer de exacte app- en Whisper-image-SHA, modelhash, voorleesinstellingen en tijdstip van start en voltooiing.
3. Leg per opname en model vast: bekende stotteringen, door Whisper gemelde stotteringen, gemiste stotteringen, onterechte meldingen, duur en onbesliste gevallen. Beoordeel de rapporten tegen de voorbereide uitspraaktekst en beluister elk indicatief tijdvak.
4. Meet CPU en RAM tijdens de hele analyse met herhaalde `docker stats --no-stream`-metingen of de Portainer-statistieken; noteer de hoogste **waargenomen** waarden en het meetinterval. Een gemeten piek tussen samples kan hoger zijn. Test ook stoppen en herstart midden in een analyse en controleer dat originele WAV en rapportgeschiedenis intact blijven.
5. Vergelijk pas na deze metingen de modellen en beslis of fragmentgerichte hergeneratie nuttig is. Geen score of succesvolle NAS-test is hier vooraf ingevuld.

## Herkomst en toekomstige koppeling

De Whisper-image gebruikt whisper.cpp v1.7.6 commit `a8d002cfd879315632a579e73f0148d06959de36` met native optimalisatie, AVX, AVX2, AVX512, FMA, F16C en BMI2 expliciet uitgeschakeld. In de gecontroleerde bouw moet de J4125 nog worden getest. Zie [versado-app-contract.md](versado-app-contract.md) voor de toekomstige scheiding tussen tekstbron, audioproductie en publicatie. Er wordt geen Versado.app-database of -opslag aangeraakt. Bevindingen met indicatieve tijdvakken kunnen later aan stabiele fragment-ID's en versies worden gekoppeld; de huidige interne Whisper-fragmenten zijn geen vervangbare audiobestanden.

## Werkelijk uitgevoerde ontwikkeltests

Met de echte whisper.cpp-binary en het gecontroleerde meertalige tiny-model is lokaal een Engelstalige upstream-opname getranscribeerd. Daarnaast is een synthetische Nederlandstalige eSpeak NG-opname getest met de tekst “En ik, Nefi, ging verder naar het beloofde land.” De herkenning was “en in de leven ging met de harte gelofde land.”: deze test bevestigt een Nederlandse aanroep maar laat aanzienlijke herkenningsfouten zien. Dit is geen M5- of NAS-meting en zegt niet hoe base of small presteren. Een lopende echte tiny-aanroep is lokaal geannuleerd; daarna was het Whisper-proces verdwenen. De GitHub-smoketest gebruikt gesimuleerde engines en controleert ook herstart tijdens een actieve analyse.
