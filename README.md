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

De engine-integratie is met mocks getest; de concrete NAS-images, Piper-stemmen, modelindeling, J4125 zonder AVX en Portainer-installatie moeten nog fysiek worden getest. `k8bit/supertonic:latest` is niet onveranderlijk; controleer voor updates diens API en CPU-compatibiliteit. De app-image bevat geen inferentiebibliotheken, maar dit garandeert de compatibiliteit van de engine-images niet. CSV/JSON-import, hoofdstukproductie, MP3 en tijdsynchronisatie zijn nog niet geïmplementeerd.
