# Voorleesprofielen

Voor Supertonic zijn drie experimentele startpunten beschikbaar: Standaard (100%, 12 stappen, 300 ms), Rustige Schriftlezing (90%, 12 stappen, 350 ms) en Extra rustig (85%, 12 stappen, 450 ms). Wijzig een waarde om Eigen instellingen te gebruiken. De browser bewaart de laatste instellingen lokaal; de server bewaart een afzonderlijke snapshot bij elke nieuwe opdracht, ook bij uitspraakpreviews. Reset herstelt de standaardinstellingen.

De pauze is de stilte tussen tekstfragmenten die de Supertonic-server zelf bepaalt; dit is geen gegarandeerde pauze tussen iedere zin. De app splitst geen tekst extra op. De onderzochte `k8bit/supertonic`-image met digest `sha256:5471d9cf2b008aeaf2de82f87efd3426a9316c74adecd925118a8a3034a510d2` bevat supertonic 1.3.1 en accepteert snelheid 0,7–2,0, stappen 1–100 en `silence_duration` 0–10 seconden. De interface toont de stilte in milliseconden. De `latest`-tag is veranderlijk; controleer het server-schema opnieuw bij een image-update. Piper heeft in deze integratie geen extra instelbare parameters.

Historische opnamen blijven ongewijzigd. Bij eerdere metadata met `total_steps` is niet gegarandeerd dat de server die parameter destijds toepaste. Oude wachtrijopdrachten gebruiken voor ontbrekende stilte de standaard 300 ms.

Vergelijk de profielen met dezelfde tekst en stem op de Synology. Automatische tests gebruiken gesimuleerde TTS-antwoorden en bewijzen geen audiokwaliteit of optimale instellingen.
