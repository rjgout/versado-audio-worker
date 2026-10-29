# Piper Voice Lab V2

## Instellingen per opname

De Piper-service gebruikt nu een kleine adapter bovenop de met digest vastgelegde
Wyoming Piper 2.5.2-image. Een afzonderlijke instellingenhandshake bevestigt de
gekozen waarden voordat tekst wordt verzonden. De adapter kopieert de configuratie
per verbinding; andere verzoeken krijgen geen instellingen van eerdere gebruikers.
Piper ontvangt `length_scale = 1 / snelheid`, `sentence_silence` (seconden),
`noise_scale` en `noise_w_scale`. De server gebruikt zijn bestaande zinsdetectie;
de pauze volgt de door Piper gevonden zinsgrenzen, geen versgrenzen.

Profielen: Standaard 100%/300 ms, Rustige Schriftlezing 90%/350 ms, Extra rustig
85%/450 ms. Beide variatieparameters starten op 0,333. Dit zijn experimentele
keuzes, geen bewezen optimale kwaliteitswaarden. Nieuwe opdrachten bewaren alle
waarden; de worker gebruikt deze snapshot. Historische lege instellingen blijven
leesbaar en behouden hun oude generatiepad. Uitspraakpreviews gebruiken dezelfde
gekozen instellingen.

## Stemmen en labels

De lokale MLS-modelconfiguratie bepaalt beschikbare sprekers (officiële configuratie:
52). Modelnaam en oorspronkelijke sprekernaam worden bewaard. Persoonlijke labels
Man, Vrouw, Warm, Helder, Diep, Rustig en Favoriet worden in SQLite opgeslagen en
kunnen als filter worden gekozen. Dit zijn beoordelingen van de gebruiker. De
bestaande favorietcheckbox blijft een lokale browservoorkeur; het gedeelde label
Favoriet is apart instelbaar. Er wordt geen geslacht automatisch vastgesteld.

## Optionele lichte ruisfilter

Bij een voltooide MLS-opname maakt de filterknop via de bestaande wachtrij een
aparte opname met `afftdn=nr=6:nf=-50`, PCM16-WAV, zonder normalisatie. Het origineel
wordt niet overschreven. De nieuwe kaart bewaart de ouder-ID, filterinstellingen,
tekst, stem en generatiegegevens; beide spelers kunnen naast elkaar worden
beluisterd. Verwijder eerst afgeleide versies voordat het origineel verwijderd kan
worden. Er wordt geen sterkere stand aangeboden zonder bewijs van nut.

Synthese-artefacten hoeven geen verwijderbare achtergrondruis te zijn. Filtering
kan medeklinkers of verstaanbaarheid verslechteren. Alleen een luistervergelijking
op de echte MLS-opnamen kan bepalen of dit helpt. Geen kwaliteitswinst gemeten.
Whisper kan beide opgeslagen WAV-versies onafhankelijk analyseren.

Alle zware taken gebruiken de bestaande worker, SQLite-guard en bestandslot.
Onderbroken taken worden niet automatisch herhaald; de bestaande herstelprocedure
blijft gelden. Tijdelijke filterbestanden worden apart gemaakt, uitvoer wordt
atomair opgeslagen. Het origineel blijft bij fouten beschikbaar.

## Portainer op /volume2

Maak vooraf een consistente back-up: stop voice-lab, kopieer pronunciation en tests
(inclusief eventueel SQLite WAL/SHM), en bewaar de huidige stackconfiguratie en
image-SHA's. Verwijder of verplaats geen modellen of bestaande mappen.

De repository-Compose gebruikt `NAS_ROOT`, standaard
`/volume2/docker/versado-audio-worker`. Bestaande /volume1-installaties moeten hun
bestaande pad als NAS_ROOT houden. Behoud SECRET_KEY, PASSWORD_HASH, COOKIE_SECURE,
poort 5006, memorylimieten en persoonlijke instellingen. Behoud het bestaande
Portainer-netwerk audio-internal: pas bij het overnemen van de referentie-Compose
uitsluitend de netwerkverwijzing aan de bestaande stack aan. Engines krijgen geen
hostpoort. Geen CPU CFS-quota.

Piper gebruikt voortaan de private image
`ghcr.io/rjgout/versado-audio-worker-piper`, met dezelfde IMAGE-SHA als de app via
PIPER_IMAGE_TAG. Publicatie vindt uitsluitend na geslaagde main-CI plaats.
Controleer in GitHub dat het nieuwe package privé is en dat de bestaande Portainer
read:packages-registratie er toegang toe heeft. Bewaar modellen leesbaar voor UID
10001; tests en pronunciation moeten voor deze UID schrijfbaar zijn. Maak geen
wereldschrijfbare mappen. De modelbestanden worden hergebruikt; geen modeldownload.

Voor update: stop voice-lab, vervang de Piper-imageverwijzing door de nieuwe
private adapterimage met vaste SHA-tag, behoud alle mounts en netwerkinstellingen,
start Piper en controleer gezondheid, update/start voice-lab met dezelfde SHA.
Whisper en Supertonic blijven hun bestaande images en configuratie gebruiken.
Voor rollback: stop voice-lab, herstel de vastgelegde vorige app- en Piper-images;
herstel de databaseback-up wanneer nodig. De toevoegingen (schema 5) wijzigen geen
bestaande opname of uitspraakregel. Bewaar nieuwe audio apart vóór een datarestore.

## Acceptatie op Synology

1. Controleer private images, UID-rechten, netwerk en servicegezondheid.
2. Gebruik dezelfde tekst: “Ik, Nephi, ben geboren uit goede ouders, daarom ben ik
   enigermate in al de geleerdheid van mijn vader onderwezen”.
3. Vergelijk twee MLS-sprekers op 100%, 90% en 85%; bekijk de opgeslagen parameters.
4. Test een uitspraakvoorstel met dezelfde geselecteerde instellingen.
5. Sla persoonlijke labels op, herlaad en controleer filters op telefoon.
6. Maak een lichte filterversie, vergelijk beide spelers en download beide WAV's.
   Controleer dat het origineel bytegelijk is aan de eerdere download.
7. Analyseer beide versies met Whisper. Controleer gewone Supertonic-generatie.
8. Controleer herstart, geblokkeerde wachtrij en handmatig herstel volgens
   docs/whisper-kwaliteit.md. Doe dit met proefopnamen en consistente back-up.

Automatisch: API/validatie/snapshots/worker, echte FFmpeg-filter op synthetische WAV,
Piper-code met vervangen inference, mobiele browser/polling, builds en smoketests.
Nog fysiek te testen: echte Piper-inference en kwaliteit, J4125 zonder AVX2,
NAS-rechten, CPU/geheugen, gelijktijdigheid en Portainer-update/rollback.
