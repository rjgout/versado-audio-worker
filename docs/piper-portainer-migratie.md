# Herstel Piper na de V2-update — bestaande handmatige Portainer-stack

## Oorzaak en beschikbare oplossing

Voice Lab vanaf PR #8 stuurt eerst `versado-settings` en wacht op
`versado-settings-ready`. De oorspronkelijke `rhasspy/wyoming-piper:2.5.2`
begrijpt deze uitbreiding niet. De app stuurt dan nog geen synthesetekst.
Op main 71a1e4e veroorzaakt de time-out een lege foutmelding en blijft de guard
conservatief bestaan. De codecorrectie in deze PR geeft een concrete melding en
heft alleen bij een bewezen fout vóór verzending van tekst de eigen guard op.
Bij een onzekere onderbreking ná verzending blijft de beveiliging actief.

De **nu al gepubliceerde adapterimage** lost de versiecombinatie op, ook zonder
installatie van deze nieuwe PR:

```
ghcr.io/rjgout/versado-audio-worker-piper:sha-71a1e4e2fb6dbff5b46b4d8fc50ea81852502d77
```

Alleen een gewijzigde Compose in GitHub werkt je handmatige stack niet bij.
De stappen hieronder worden door de eigenaar uitgevoerd; er is geen automatisch
NAS-beheer of deployment. Deze PR is niet automatisch gemerged/gepubliceerd.

## Voorbereiding en consistente back-up

1. Noteer/exporteer de huidige Portainer-stack, alle image-ID's/tags, opdrachten,
   eventuele entrypoints, netwerkaliassen, geheugenlimieten en mountdoelen.
   Bewaar credentials lokaal veilig; plak geen wachtwoorden of tokens in chat.
2. Controleer de taken in Voice Lab. Laat actieve taken afronden of stop een
   Whisper-analyse via de bestaande annuleringsknop en wacht op de eindstatus.
   Start geen nieuwe taken. Stop daarna **voice-lab** in Portainer.
3. Maak met gestopte app een volledige kopie van
   `/volume2/docker/versado-audio-worker/pronunciation` en `tests` naar een aparte
   back-upmap buiten deze twee bronmappen. Neem SQLite, eventuele WAL/SHM en
   audiobestanden samen mee. Verwijder of hernoem geen bronmap. De modellen hoeven
   niet opnieuw gedownload of verplaatst te worden.
4. Controleer onder GitHub Packages dat het Piper-package privé is en dat jouw
   bestaande Portainer-GHCR-account het met `read:packages` kan ophalen. Gebruik
   in Portainer **Images → Pull image** voor bovenstaande exacte image/tag en
   selecteer dezelfde private registry als voor Voice Lab. Een pull start niets.

## Wijzig uitsluitend de bestaande Piper-service

5. Stop de oude Piper-container en wacht tot Portainer deze echt als gestopt toont.
   Hierdoor is ook een mogelijk achtergebleven generatie definitief beëindigd.
6. Open je bestaande stack-editor. **Vervang niet de hele stack door de
   repository-Compose.** Wijzig alleen de Piper-imageverwijzing:

```yaml
# Bestaande service (behoud zijn eigen naam en overige configuratie)
piper:
  image: ghcr.io/rjgout/versado-audio-worker-piper:sha-71a1e4e2fb6dbff5b46b4d8fc50ea81852502d77
```

   Het blok is een voorbeeld van de gewijzigde regel, geen complete nieuwe stack.
   Behoud service-/containernaam en alias waar `PIPER_HOST` naartoe verwijst,
   `audio-internal`, model-bindmount en alle persoonlijke limieten/instellingen.
   Publiceer poort 10200 niet naar de host. Poort 5006 blijft ongewijzigd.
7. Controleer een eventueel expliciet `entrypoint:` bij Piper: een override naar
   `docker_run.sh` of `python -m wyoming_piper` omzeilt de adapter. Verwijder alleen
   die oude override, zodat de nieuwe image zijn eigen entrypoint gebruikt.
   Behoud je engineargumenten onder `command:`. Geef geen scriptnaam als command.
   Zorg dat de argumenten expliciet de juiste URI en modelmap bevatten; de oude
   docker_run.sh voegde enkele hiervan zelf toe. Bij modelmountdoel `/data` is dit:

```yaml
  command: ["--voice", "nl_NL-mls-medium", "--data-dir", "/data", "--download-dir", "/data", "--uri", "tcp://0.0.0.0:10200", "--local-files-only"]
```

   Behoud je bestaande standaardstem (Ronnie of MLS) in plaats van die onnodig
   te veranderen. Gebruik bij een ander mountdoel dat bestaande pad in de
   argumenten. De bron blijft `/volume2/docker/versado-audio-worker/models`.
8. De adapter draait standaard als UID/GID 10001. Controleer dat deze UID de
   modelmap kan doorzoeken en de geïnstalleerde `.onnx` én `.onnx.json` kan lezen.
   Gebruik zo nodig gerichte Synology-ACL's of leesrechten op alleen de modellen;
   voer geen recursieve chown/chmod op de volledige applicatiemap uit. Laat een
   bestaande expliciete `user:` staan tenzij de rechtencontrole een aanpassing
   vereist. De draaiende app moet zijn bestaande schrijfrechten op `tests` en
   `pronunciation` behouden.
9. Update de stack met de vooraf opgehaalde image. Laat **Re-pull all images** uit
   zodat Supertonic/Whisper niet ongemerkt een andere `latest` ophalen. Controleer
   de resulterende Piper-container: exacte image/tag, eigen adapter-entrypoint,
   juiste argumenten, bestaande volumes en netwerk. De logs moeten `Ready` tonen;
   de healthcheck controleert TCP-bereikbaarheid. `Ready` of TCP alleen bewijst
   nog geen instellingenondersteuning.
10. Start voice-lab met zijn **bestaande** image, credentials en volumes. Vervang
    of herinitialiseer geen SQLite-database. Als de eerdere versie een guard heeft
    achtergelaten, toont Voice Lab de gepauzeerde wachtrij. Controleer eerst de
    nog wachtende opdrachten; bevestig daarna **Engine is herstart; hervat
    wachtrij**, uitsluitend nadat stap 5 en 9 werkelijk zijn afgerond. Mislukte
    opdrachten worden niet automatisch opnieuw gestart; maak één nieuwe proef.

## Verificatie

- Na installatie van de app-code uit deze PR controleert **Controleer
  Piper-adapter** in het Piper-paneel de volledige instellingenhandshake zonder
  synthese. De controle wordt ook bij laden/kiezen van Piper uitgevoerd.
  De huidige app van PR #8 heeft die knop nog niet.
- Maak eerst een korte opname met je bestaande standaardstem op 100% en 90%.
  Beide moeten een geldig, afspeelbaar WAV opleveren en de opgeslagen instellingen
  moeten verschillen. Gebruik dezelfde passage: “Ik, Nephi, ben geboren uit goede
  ouders, daarom ben ik enigermate in al de geleerdheid van mijn vader onderwezen”.
- Controleer MLS met twee sprekers en daarna je individuele geïnstalleerde stemmen.
  Alleen aanwezige `.onnx`/configparen kunnen worden gebruikt. Geen nieuw model
  nodig voor een andere MLS-spreker.
- Beluister een uitspraakvoorstel met dezelfde instellingen, download een WAV,
  herlaad de browser en controleer dat oude opnamen/labels/regels behouden zijn.
- Maak ter regressie één Supertonic-opname en controleer, indien al geïnstalleerd,
  een bestaande Whisper-analyse. Hun services hoeven hiervoor niet te wijzigen.

Bij `permission denied`: controleer de concrete modelbestanden voor Piper en
schrijfbare appmappen voor de bestaande app-UID. Bij een mislukte handshake:
controleer echte containerimage én entrypoint; een correcte image met het oude
entrypoint kan nog steeds de verkeerde server starten. Bij onzekere afgebroken
synthese blijft het handmatige herstel verplicht; verwijder geen slotbestand of
SQLite-rij om de beveiliging te omzeilen.

## Terugrollen

Stop voice-lab en Piper. Herstel de geëxporteerde eerdere combinatie van app- en
Piper-image, argumenten en entrypoint. Alleen Piper terugzetten naar de rhasspy-image
bij behoud van de V2-app herintroduceert het probleem. Herstel bij een database-
rollback de volledige consistente back-up met de app gestopt; bewaar nieuwere
WAV's eerst apart. Laat geen nieuwe wachtende V2/filteropdrachten door een oudere
worker uitvoeren. Herstart pas na controle van volumes, netwerk en rechten.

## Reproduceerbare echte integratietest buiten standaard-CI

`scripts/piper_live.py` gebruikt uitsluitend vooraf geïnstalleerde modellen en
roept de adapter via Wyoming aan; het script downloadt niets. Geef PIPER_HOST,
PIPER_PORT en het pad naar de modelconfiguraties. Het test alle aanwezige
ondersteunde individuele modellen, alle MLS-sprekernamen uit de config en vergelijkt
WAV-duur bij normale en lagere snelheid. De test start echte synthese; voer hem
uitsluitend uit terwijl Voice Lab is gestopt en geen andere zware taak actief is.
Gebruik bij voorkeur een geïsoleerde ontwikkelcontainer. Er worden geen WAV's of
modellen in Git gecommit. Standaard-CI gebruikt gesimuleerde inference en de bestaande
containersmoketests, zonder modeldownloads.
