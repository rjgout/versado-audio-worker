# Onderzoek Supertonic-segmenten (werk in uitvoering)

De lokaal geïnspecteerde `k8bit/supertonic:latest` had digest `sha256:5471d9cf2b008aeaf2de82f87efd3426a9316c74adecd925118a8a3034a510d2` en bevatte de Python-package `supertonic` 1.3.1. Andere versies van de veranderlijke `latest`-tag kunnen afwijken.

De `synthesize`-pipeline gebruikt zelf `chunk_text`: standaard maximaal 300 tekens voor Nederlands, met 0,3 seconde stilte. De server splitst op alinea's en zinnen. Extra segmentatie in de app moet daarom elk verzoek voldoende klein en vrij van dubbele alineaovergangen houden, en moet de daadwerkelijk gegenereerde segmenten afzonderlijk opslaan. De geïnspecteerde server kan ook `max_chunk_length` en `silence_duration` ontvangen. Voor een lange niet-splitsbare uitdrukking kan interne verdere opsplitsing niet zonder meer worden uitgesloten.

Het schema van `/v1/tts` in deze image gebruikt `steps` voor het aantal generatiestappen, niet `total_steps`. De eerdere app stuurde de laatste naam, die door het servermodel als onbekend veld kan worden genegeerd; in dat geval geldt de standaard van 8 stappen. De adapter stuurt nu `steps: 12`, met `speed: 1.0`. Het onderzochte verzoekschema biedt geen seed-veld. Er wordt geen seed-parameter toegevoegd.

`app/segmentation.py` bevat voorlopig losse, geteste hulpmiddelen om tekst te splitsen en PCM-WAV te combineren. Deze zijn **nog niet aangesloten op de wachtrij of interface**. Het regenereren, beluisteren en bevestigen van een individueel fragment, het duurzaam opslaan van segmenten en het behouden van oude opnameversies ontbreken. Gebruik deze hulpmiddelen niet als afgeronde oplossing voor het stotteren.

Werkelijke verbetering en compatibiliteit met de precieze image op de Synology moeten nog door het beluisteren van M5 worden gecontroleerd. Oude opnamen en uitspraakregels worden niet aangepast.

## Gefaseerde evaluatie en fragmenteditor

De parametercorrectie staat afzonderlijk in PR #4. Voor de luistertest: noteer de exacte image-digest, tekst, stem M5, taal, stappen en snelheid; genereer ten minste drie nieuwe opnamen met en zonder correctie en beluister ze zonder de bestaande opnamen te wijzigen. Noteer per opname de positie en aard van herhalingen, en onderscheid vermoedelijke articulatiefouten van technische overgangen. De resultaten zijn nog niet bekend; concludeer niet vooraf dat de correctie stotteren oplost. Beoordeel daarna of extra segmentatie noodzakelijk is.

Een latere editor moet afzonderlijke fragmenten en versies met stabiele identifiers vastleggen, met originele en voorbereide tekst en snapshots van uitspraakregels en instellingen. Nieuwe fragmentgeneratie moet via dezelfde persistente wachtrij lopen. Een kandidaat blijft apart bewaard en afspeelbaar totdat de gebruiker deze bevestigt; pas dan wordt een nieuwe samengestelde WAV veilig weggeschreven en atomair gekoppeld, met behoud van de oude versie. Herstart- en gelijktijdigheidsafhandeling, opruiming, back-ups en rollback moeten daarbij expliciet worden getest. De server biedt geen API om zijn interne chunks als afzonderlijke bestanden te inspecteren of te vervangen; als die eis na de luistertest blijft gelden, moet de app eigen, controleerbare fragmentgrenzen hanteren en zorgen dat de server die niet verder opsplitst. De huidige helpers zijn nog geen afgeronde implementatie daarvan.
