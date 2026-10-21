# Ondertekening voorbereiden

Status: geen ondertekenaar aangesloten en geen certificaat aangemaakt.
Onderstaande tekst is voorbereiding, geen toezegging dat een dienst ons toelaat.
De MSI en launcher worden in deze bouwroute nog niet ondertekend.

Gratis opensourceroute: [SignPath Foundation](https://signpath.org/terms.html).
Toelating is niet automatisch. Het project moet onder andere actief onderhouden
zijn, een OSI-licentie en openbare broncode hebben, en controleerbaar bouwen.
Alleen eigen code/binaries komen in aanmerking. Meld bij een aanvraag dat de
launcher later afzonderlijk onderdelen van derden ophaalt, waaronder dgVoodoo;
laat de stichting beoordelen of dit past. Geen games of onderdelen van derden
meesturen voor ondertekening.

De eigenaar moet een aanvraag doen, zijn identiteit/rollen opgeven, MFA instellen
en eventuele GitHub-toegang zelf goedkeuren. Richt daarna een beperkt,
beveiligd releaseproces in: vaste broncommit, controles geslaagd, menselijke
goedkeuring per ondertekening. Stel geen persoonlijke certificaatsleutel als
bestand beschikbaar in de repository.

Te gebruiken beleid zodra een dienst is aangesloten:

- Alleen eigen launcher en MSI, gebouwd uit een gecontroleerde openbare commit.
- Elke vrijgave vereist een menselijke goedkeuring van bouw- en testresultaten.
- Een niet-gecontroleerde pull request krijgt geen toegang tot ondertekening.
- Eerst de eigen EXE ondertekenen, daarna de MSI bouwen en ondertekenen.
- Na elke handtekening de exacte bytes, payload/CAB en hashes opnieuw controleren.
- Daarna de echte installatieproef en scan uitvoeren; publiceer de uiteindelijke
  hashes, certificaatgegevens en uitslagen. Een herbouw krijgt een nieuwe versie.

Een alternatief is [Microsoft Artifact Signing](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation).
Dat vraagt een account, identiteitscontrole en een betaald abonnement.
Ondertekening kan waarschuwingen verminderen; ook een nieuw ondertekend bestand
kan nog een SmartScreen-waarschuwing krijgen. Een zelfondertekend certificaat is
geen oplossing voor publiek vertrouwen.

De eigenaar kan de aanvraag baseren op: **A2 Racers Revival**, MIT voor eigen
code, openbare broncode en CI in deze repository, contact
**HeySnowdude@pm.me**, Windows singleplayer-fanlauncher, geen games in de
distributie. Deze aanvraag is nog niet ingediend.


Gecontroleerd op 21 oktober 2026: Artifact Signing Public Trust accepteert
individuele ontwikkelaars momenteel alleen in VS/Canada; organisaties in de EU
kunnen wel in aanmerking komen. Voor een Nederlandse particulier is dit dus
geen direct beschikbare standaardroute. Zie de
[actuele voorwaarden](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart).
SignPath-toelating voor onze eigen code en de later gedownloade proprietary
compatibiliteitscomponenten moet afzonderlijk worden beoordeeld.
