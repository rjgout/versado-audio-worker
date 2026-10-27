# Versado Audio Worker

Privé Voice Lab voor Nederlandse proefopnamen en uitspraakregels, met Piper (Wyoming) en Supertonic 3. Bewaart SQLite en WAV op bindmounts. Dit project is een eerste versie: raadpleeg de NAS-acceptatietests hieronder voordat u het gebruikt.

## Installatie op Synology / Portainer

1. Maak de bestaande mappen `/volume1/docker/versado-audio-worker/{models,supertonic-models,tests,pronunciation}` aan indien nodig. Verwijder of leeg ze niet. Geef UID/GID 10001 schrijf- en directory-toegang tot `tests` en `pronunciation`; Piper en Supertonic moeten hun respectieve modelmappen kunnen lezen en schrijven. Maak een back-up van bestaande gegevens.
2. De oude proefstack bezet poort 5006. Stop deze stack in Portainer, zonder volumes of mappen te verwijderen. Bewaar diens configuratie voor terugdraaien. Controleer of de poort vrij is.
3. Stel de GitHub-package voor `ghcr.io/rjgout/versado-audio-worker` expliciet in als privé. Voeg in Portainer onder Registries een custom registry `ghcr.io` toe met uw GitHub-gebruikersnaam en een GitHub classic token met ten minste `read:packages` en toegang tot het private package. Gebruik de Portainer-secretvoorziening; zet dit token nooit in de Compose, Git of logs. Configureer indien nodig SSO-autorisatie voor de organisatie.
4. Maak afzonderlijke, sterke geheimen. Voor de sessiesleutel: `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`. Maak de wachtwoordhash met `docker run --rm --entrypoint python ghcr.io/rjgout/versado-audio-worker:latest -c "from werkzeug.security import generate_password_hash; import getpass; print(generate_password_hash(getpass.getpass()))" -i` (plaats `-i` vóór de image bij gebruik van Docker CLI). Een alternatieve interactieve opdracht: `docker run --rm -i --entrypoint python ghcr.io/rjgout/versado-audio-worker:latest -c 'from werkzeug.security import generate_password_hash; import getpass; print(generate_password_hash(getpass.getpass()))'`. Kopieer uitsluitend de hash naar `PASSWORD_HASH`; bij Compose-interpolatie moeten `$`-tekens mogelijk als `$$` worden ingevoerd. Zet `SECRET_KEY` en `PASSWORD_HASH` als Portainer environment variables, niet in de repository.
5. Maak een stack met `compose.yaml` en de environmentvariabelen uit `.env.example`. Gebruik een specifieke `IMAGE_TAG=sha-...` voor reproduceerbare updates. Alleen poort 5006 wordt gepubliceerd. De interne engines krijgen geen hostpoort. Stel de Synology-firewall zo in dat poort 5006 alleen vanaf vertrouwde LAN-adressen bereikbaar is; blokkeer toegang vanaf internet en zet geen portforwarding aan. `BIND_ADDRESS` kan op het LAN-IP worden gezet. Zonder HTTPS is verkeer binnen het LAN niet versleuteld; gebruik bij veilige HTTPS-terminatie `COOKIE_SECURE=true`.
6. Start de stack en inspecteer de logs. Piper hergebruikt `/data`; Supertonic gebruikt `/models`. Als modellen ontbreken kunnen de images ze downloaden. Geen CPU CFS-quota worden ingesteld. Geheugenlimieten zijn instelbaar. De app draait als UID 10001; engine-images beheren hun eigen gebruikers.
7. Open `http://NAS-IP:5006`, meld aan en controleer de onderstaande checklist. De eerste publicatie van het private image gebeurt pas nadat de CI op main de image gepubliceerd heeft; een draft-PR publiceert geen image.

## Acceptatie op de NAS

- Controleer dat alleen poort 5006 op de host gepubliceerd is en dat toegang van buiten het vertrouwde netwerk geblokkeerd is.
- Controleer de logs van Piper en Supertonic en hun modelbestanden. Supertonic native `/v1/tts` gebruikt `lang=nl`, `total_steps=12`, `speed=1.0`. Probeer voor beide engines een korte zin en controleer afspelen en WAV-download.
- Controleer elk van de zes Piper-stemmen afzonderlijk. Stemnamen/modelbestanden en de ondersteuning voor het kiezen van een andere stem hangen af van de specifieke Piper-image en beschikbare bestanden. Deze combinaties zijn niet op de NAS geverifieerd.
- Voeg een uitspraakvoorstel toe, luister het af, keur goed en genereer een zin met het woord. Controleer dat hetzelfde woord in de andere schriftbron niet is vervangen.
- Herstart de app en controleer opgeslagen opnamen en regels. Bij een herstart worden actieve opdrachten als mislukt gemarkeerd; maak ze opnieuw aan. Opdrachten die nog in de wachtrij stonden worden hervat.
- Test op telefoon, wijzig een label en verwijder een opname. Houd rekening met automatische downloadbeperkingen van mobiele browsers.

## Bijwerken en terugrollen

Maak een back-up van `tests` en `pronunciation` samen met de SQLite-database (gebruik een consistente SQLite-back-up en neem WAL-bestanden mee, of stop eerst de app). Download de nieuwe privé-image via Portainer en update de stack. Rol terug door `IMAGE_TAG` op een eerder gepubliceerde `sha-<commit>` te zetten en opnieuw te deployen. Verwijder geen modelmappen. Stop de nieuwe stack en start de bewaarde proefstack indien nodig.

## Ontwikkelen en beperkingen

`python -m venv .venv && .venv/bin/pip install -r requirements.txt pytest` en `.venv/bin/python -m pytest -q`. Stel `SECRET_KEY`, `PASSWORD_HASH`, `DATA_DIR` en `AUDIO_DIR` in voor lokale uitvoering. De app gebruikt één Gunicorn-worker en een achtergrondthread; configureer nooit meerdere app-instanties op dezelfde database. De wachtrij beperkt de zware generatie tot één opdracht per app-instantie. Uitspraken en metadata worden bij aanmaak vastgelegd; uitgevoerde generaties worden niet automatisch herhaald. De database gebruikt WAL en een eerste schemaversie, maar heeft nog geen upgrade-migraties nodig.

De engine-integratie is met mocks getest; de concrete NAS-images, Piper-stemmen, modelindeling, J4125 zonder AVX en Portainer-installatie moeten nog fysiek worden getest. `k8bit/supertonic:latest` is niet onveranderlijk; controleer voor updates diens API en CPU-compatibiliteit. De app-image bevat geen inferentiebibliotheken, maar dit garandeert de compatibiliteit van de engine-images niet. Hoofdstukproductie, MP3 en tijdsynchronisatie zijn nog niet geïmplementeerd. CSV- en JSON-import toont eerst een preview en slaat alleen nieuwe voorstellen op.


### Piper-stemmen installeren

De selector toont alleen bekende Piper-stemmen waarvoor zowel `<stem>.onnx` als `<stem>.onnx.json` in `models` aanwezig zijn. Piper draait met `--local-files-only`; er vindt bij generatie geen modeldownload plaats. Plaats de twee officiële bestanden van iedere gewenste stem vooraf in de bestaande modelmap, met de bestandsnamen zoals op de bron vermeld. Controleer dat de Piper-container ze kan lezen; de app mount deze map alleen-lezen. Herstart Piper indien nodig. Als Ronnie ontbreekt kan Piper niet starten: installeer die eerst. Controleer op de NAS of de betreffende modelnamen en directorystructuur door de vastgelegde Piper-image worden herkend.

De import verwacht een JSON-array van objecten of een CSV met kolommen `language,source,original,replacement` en optioneel `engine,voice,note`; `source` is `bofm` of `bible`. De preview toont duplicaten; import slaat nieuwe regels op als voorstel.

### Eerste testimage zonder merge

De eigenaar kan in GitHub Actions handmatig **Publish private test image** starten op `feature/versado-audio-worker`. Configureer eerst de GitHub environment `test-image` met een verplichte reviewer, en controleer dat het GHCR-package privé is en deze repository schrijfrechten heeft. De workflow publiceert uitsluitend `test-sha-<volledige commit-SHA>`, niet `latest`; er is geen automatische publicatie vanuit een PR. Controleer de voltooiing en exact gebruikte SHA. Stel in Portainer `IMAGE_TAG=test-sha-<volledige commit-SHA>` in en gebruik de privéregistry zoals hierboven beschreven. Dit vereist geen merge. Publicatie gebeurt alleen na handmatig starten en eventuele environment-goedkeuring.

GitHub controleert unit/API-tests en de containersmoketest met een gesimuleerde HTTP-engine; dit verifieert geen echte modellen of NAS-hardware. De eigenaar controleert op de NAS beide engines, alle gewenste stemmen, mobiele weergave en afspelen, de opslagrechten, firewall en het herstel na een echte herstart. Controleer bovendien de CPU-compatibiliteit van de engine-images met de J4125. Gebruik de acceptatiechecklist hierboven.

De catalogus vermeldt `nl_NL-ronnie-medium`, `nl_NL-pim-medium`, `nl_NL-alex-medium`, `nl_NL-mls-medium`, `nl_BE-nathalie-medium` en `nl_BE-rdh-medium`. Een stem is alleen selecteerbaar wanneer het ONNX-bestand en de bijbehorende `.onnx.json` aanwezig zijn. Supertonic-stemmen worden opgehaald uit `/v1/styles`; bij een onbereikbare engine is de lijst leeg. Een uitspraakpreview gebruikt dezelfde wachtrij als opnamen en wordt na voltooiing of fout na een uur automatisch verwijderd; een herstart markeert een actieve preview als mislukt.

Let op: GitHub toont een nieuwe `workflow_dispatch`-workflow pas wanneer het workflowbestand op de standaardbranch bestaat. Zolang deze draft niet gemerged is, kan de eigenaar in een vertrouwde eigen shell de gewenste commit zonder merge publiceren: check de featurebranch uit, controleer `git rev-parse HEAD` en de geslaagde PR-checks, bouw `docker build -t ghcr.io/rjgout/versado-audio-worker:test-sha-<volledige-commit-SHA> .`, meld interactief aan bij GHCR met een token met `write:packages` via `docker login ghcr.io -u <gebruikersnaam> --password-stdin` (voer het token via een veilige prompt of secretbron in) en voer daarna `docker push` uit voor die exacte tag. Controleer vooraf dat het package privé is. Bewaar geen token in de repository of shellgeschiedenis. Gebruik daarna de tag in Portainer; publiceer nooit `latest` voor deze test.
