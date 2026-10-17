# Updates in de launcher

Vanaf beta 6 staat bij Support een updatevak. De openbare launcher controleert
na zijn voorbereiding eenmaal per start op nieuwere releases. Automatisch
controleren kun je uitzetten; handmatig controleren kan altijd. Alleen GitHub
ontvangt de normale netwerkaanvraag, geen gamemappen, saves of instellingen.
Zonder internet kun je blijven spelen. Downloaden en installeren gebeuren nooit
automatisch.

De controle slaat concepten, oudere versies en releases zonder goedgekeurde MSI
over. Beta-versies worden numeriek vergeleken. Zowel het vrijgavebestand als de
installer moeten exact overeenkomen met GitHubs bestandsgrootte en SHA-256.
Downloads komen in een eigen cachemap en houden hun Windows-internetherkomst.
Bij installeren wordt de openbare vrijgave opnieuw gecontroleerd. Een veranderde
download of ingetrokken update wordt geweigerd. Installeren is geblokkeerd
tijdens een game of voorbereiding.

Na bevestiging sluit de launcher en opent de gewone Windows-installer. Er wordt
geen beveiliging uitgezet, blokkade omzeild of bestand gedeblokkeerd. Een ongeldige
handtekening wordt geweigerd; bij een niet-ondertekende MSI staat dit expliciet
in de bevestiging. Een SHA-256 bewijst de herkomst binnen deze releaseketen,
niet dat software veilig is.

De MSI houdt dezelfde productfamilie en onthoudt de installatiemap. Alleen
beheerde programmabestanden worden bijgewerkt. Lokale gamekopieën, voorkeuren,
voortgang en gedownloade onderdelen vallen buiten het MSI-bestandsmanifest.
De updatevoorkeur staat apart in `local/launcher/update-settings.json`.

De bestaande beta 4 krijgt deze functie niet vanzelf: daarvoor moet je eenmaal
de nieuwe installer installeren zodra die openbaar is vrijgegeven. De updater
installeert ook geen oudere beta-5-kandidaat.
