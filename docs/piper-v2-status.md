# Piper Voice Lab V2 — tussentijdse stand

Deze draft is **niet compleet en niet gereed voor uitrol**. De officiële
[MLS-modelconfiguratie](https://huggingface.co/rhasspy/piper-voices/blob/main/nl/nl_NL/mls/medium/nl_NL-mls-medium.onnx.json)
vermeldt 52 sprekers; de applicatie leest de naam-ID-koppeling uit de
geïnstalleerde configuratie en meldt alleen geldige sprekers daaruit. Het
stemkenmerk `nl_NL-mls-medium#<sprekernaam>` wordt in de opname opgeslagen;
Wyoming ontvangt de modelnaam en de oorspronkelijke sprekernaam afzonderlijk.
Een stemregel voor het hele MLS-model blijft ook voor diens individuele
sprekers geldig; een specifieke sprekerregel krijgt voorrang. Persoonlijke
favorieten worden uitsluitend in de browser op het apparaat bewaard. Er wordt
geen geslacht of stemkwaliteit afgeleid.

Uit de code van Wyoming Piper volgt dat sprekerselectie per verzoek wordt
verwerkt, maar dat `length_scale`, `noise_scale` en `noise_w_scale` uit de
serverconfiguratie komen. De bestaande Wyoming-aanroep biedt daarvoor geen
bevestigde per-verzoekinstellingen. Een andere, aantoonbaar veilige adapter en
uitgebreide tests zijn nog nodig. Ook de niet-destructieve ruisbewerking,
persoonlijke labels/filters en de verdere integratietests ontbreken nog.
De aard van de gehoorde MLS-ruis is niet vastgesteld; ruisreductie kan spraak
verslechteren. Nog geen echte generatie of luistertest op de NAS uitgevoerd.

Geen NAS-paden, containers, bestaande bestanden of data worden aangepast.
Deze tussenstand moet niet worden gemerged of geïnstalleerd.
