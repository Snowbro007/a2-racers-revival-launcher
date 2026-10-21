# Onderzoek: eenvoudige en betrouwbare fandistributie

Atlas, 21 oktober 2026. Doel: downloaden, installeren, eigen game koppelen en spelen, met Windows-beveiliging ingeschakeld. Distributie en launcher krijgen voorrang op verdere game-uitbreidingen.

## Advies

Gebruik één **ondertekende MSI per gebruiker** als aanbevolen download. Behoud de ZIP als alternatief voor ervaren gebruikers. Geef op GitHub één duidelijke downloadknop naar een vaste releaseversie; houd broncode, oude beta's en onderzoeksbuilds apart. De bestaande MSI is hiervoor een bruikbare basis: geen nieuwe installer-engine of zelfuitpakkende EXE nodig.

Een MSI lost antivirusdetecties van zijn inhoud niet op. Eerst moeten de afzonderlijke launcher, het startgedrag en de distributieketen worden beoordeeld. Pas na ondertekening en een echte Windows 11-proef is de omschrijving gebruiksklaar of plug-and-play verdedigbaar. De verbeteringen in deze wijziging leveren die acceptatie nog niet.

## Wat er werkelijk op GitHub staat

De openbare repository is [a2-racers-revival-launcher](https://github.com/Snowbro007/a2-racers-revival-launcher), niet de oudere private onderzoeksrepository. Op 21 oktober gecontroleerd via de GitHub-API:

- `main`: `c9a760dadfcac29cb5f465286dc2b318120cb511`.
- De README verwijst naar de [beta-4-ZIP](https://github.com/Snowbro007/a2-racers-revival-launcher/releases/tag/v0.1.0-beta.4), gepubliceerd op 15 oktober. Startpunt: `Launcher.cmd`. ZIP-SHA256: `1cf93216577b8d189dbe7aa353b3b3378e34a66de7839a973022c163e5e04e52`.
- Beta 5, 6 en 7 zijn concepten. Er is dus nog geen openbare MSI als opvolger van beta 4. Beta 6 is bovendien afgekeurd wegens een ontbrekende updatermodule; main bevat de correctie.
- De beta-7-MSI heeft SHA256 `48d1c72192ba1043db6cc7aa19522a69382fe9b0a98c287d2a82fbe9e732b656`. De losse ingebedde launcher heeft SHA256 `c0544d9c55380139834286832f2cbedea90588c8b60eed040e88301a322c6c62`. Deze bestanden zijn niet ondertekend.

Eerder vastgelegde scans van precies beta 7: MSI 0/53, EXE 2/71, met meldingen van Bkav Pro en SecureAge. Dit zijn historische waarnemingen van 17 oktober, geen nieuwe scan en geen bewijs van een vals alarm. Het aantal deelnemende scanners verschilt. De MSI bevat dezelfde EXE; een lagere score voor de container maakt de EXE niet vrij van meldingen.

De lokale Windows 11-installatie van beta 7 slaagde, maar de eerste start rondde niet af. Er bleef een gedeeltelijke FFmpeg-download achter. De exacte oorzaak is niet bewezen. De CI-proef met de launchercontrolemodus slaagde wel; dat is afzonderlijk bewijs en vervangt geen interactieve Windows 11-acceptatie.

## Wat vermoedelijk frictie veroorzaakt

| Waarneming in de broncode | Betekenis en grens |
| --- | --- |
| Een kleine eigen C#-EXE start een verborgen Windows PowerShell-proces met `ExecutionPolicy Bypass`; de ZIP gebruikt een CMD-startpad. | Complexer dan één gewone desktopapp; relevant voor beoordeling. Er is geen detectielog dat dit als concrete AV-oorzaak aanwijst. Deze wijziging claimt daarom geen AV-oplossing door alleen startvlaggen te veranderen. |
| De eerste voorbereiding haalt vijf vaste providerarchieven op, waaronder PowerShell en FFmpeg, voordat de gamekeuze bruikbaar is. | Veel netwerk- en uitpakwerk voor de eerste start. De bestanden worden al op SHA256 gecontroleerd, maar het blijft een kwetsbaar moment voor verbindingen en blokkades. |
| HTTP gebruikt `ResponseHeadersRead`; elke leesactie had 30 seconden wachttijd. | De HTTP-clienttimeout begrenst de volledige body dan niet. Een verbinding die langzaam bytes blijft leveren kon zonder totale streamdeadline voortduren. Dit is een concrete codebevinding, niet de bewezen oorzaak van de historische FFmpeg-hapering. |
| Het venster las procesoutput pas na afloop. | Voortgang via alleen `Write-Host` was tijdens het downloaden niet zichtbaar. Dat kan de indruk geven dat de launcher vastzit. |
| Automatische installatiecontrole plus `--approve` volstonden voor het maken van een updatevrijgavebestand. | De code eiste geen afzonderlijk verslag van interactieve Windows 11-acceptatie, handtekeningen en beoordeling van AV-meldingen. |

Een verdwijnend bestand kan quarantaine zijn, maar dat vereist het AV-log: product, detectienaam, exact pad, hash en tijdstip. SmartScreen is een reputatiecontrole bij downloaden/starten; het is niet hetzelfde als een AV-detectie. [Microsoft developer FAQ](https://learn.microsoft.com/en-us/defender-xdr/developer-faq).

Robin noemt tijdens dit onderzoek **Bitdefender** als het blokkerende product. De detectienaam en exacte bestandsversie zijn nog onbekend. Een historische online scan met de vermelding Undetected verklaart een lokale blokkade niet. Bitdefender beschrijft zelf beoordeling van verdachte false positives; er is in dit onderzoek niets ingestuurd. [Bitdefender: detecties onderzoeken](https://www.bitdefender.com/business/support/en/77212-343054-resolving-legitimate-applications-detected-as-threats-by-bitdefender.html).

## Vergelijking van distributieroutes

| Route | Gemak voor fans | Advies voor dit project |
| --- | --- | --- |
| Ondertekende MSI | Normaal installeren, A2-icoon, herstellen, updates en verwijderen. Per gebruiker mogelijk zonder onnodige beheerrechten. | Beste eerstvolgende stap; bouw en lifecyclecode bestaan al. Onderteken ook de ingebedde EXE. |
| Portable ZIP | Uitpakken en starten; gebruikers beheren zelf map en updates. Downloads en scriptstart blijven. | Optioneel alternatief, niet de hoofdroute voor beginners. |
| Zelfuitpakkende Setup.exe of één ingepakte EXE | Eén bestand lijkt eenvoudig, maar introduceert eigen uitpak-/startgedrag. | Geen aangetoonde AV-oplossing. Geen reden om de bestaande MSI hiervoor te vervangen. |
| MSIX / Microsoft Store | Kan installatie, identiteit en updates verder vereenvoudigen. | Later apart onderzoeken. Huidige schrijfbare speelkopieën, patches en runtimecache passen niet zomaar in een read-only installatiepakket; toelating tot de Store is niet vastgesteld. |

Windows Installer kent expliciet per-user installatiecontexten. [Microsoft: installation context](https://learn.microsoft.com/en-us/windows/win32/msi/installation-context). Voor MSIX moeten schrijfbare gegevens en werkdirectory-aannames eerst worden aangepast. [Microsoft: desktop-app voorbereiden](https://learn.microsoft.com/en-us/windows/msix/desktop/desktop-to-uwp-prepare). Een MSIX buiten de Store vraagt een vertrouwde handtekening; gebruikers zelf een certificaat laten vertrouwen is geen passend eenvoudig installatiepad. [MSIX signing](https://learn.microsoft.com/en-us/windows/msix/package/signing-package-overview).

## Ondertekening en reputatie

Authenticode maakt de uitgeversidentiteit controleerbaar en helpt reputatie opbouwen. Nieuwe ondertekende bestanden kunnen nog steeds worden gewaarschuwd of door AV worden geblokkeerd. EV-certificaten geven volgens Microsoft geen onmiddellijke SmartScreen-vrijstelling meer; koop geen duur EV-certificaat alleen om die reden. [Microsoft: SmartScreen-reputatie](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation).

Voor dit project verdient **SignPath Foundation** als eerste een toelatingsonderzoek: gratis voor toegelaten opensourceprojecten, maar geen automatische toelating. De voorwaarden eisen opensourcecomponenten en sluiten proprietary onderdelen uit, met beperkte systeemlibrary-uitzonderingen. Laat de signinggrens voor eigen launcher/MSI en het later ophalen van compatibiliteitssoftware beoordelen. [SignPath-voorwaarden](https://signpath.org/terms).

**Microsoft Artifact Signing Public Trust** is niet zonder meer beschikbaar voor een Nederlandse individuele ontwikkelaar: de huidige voorwaarden beperken individuen tot VS/Canada; organisaties in de EU komen wel in aanmerking. Er is niets aangevraagd of gekocht. Een commerciële OV-route is een alternatief na controle van identiteitseisen en actuele voorwaarden. [Microsoft: voorwaarden](https://learn.microsoft.com/en-us/azure/artifact-signing/quickstart), [signingopties](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/code-signing-options).

Geen nieuwe samples geüpload en geen leverancierscontact gestart. Een eventuele false-positive-melding vraagt eerst code- en herkomstcontrole en afzonderlijke toestemming voor het delen van de exacte verdachte bytes. [Microsoft: bestand indienen](https://www.microsoft.com/en-us/wdsi/filesubmission).

## Bronverbeteringen in deze wijziging

1. Een totale deadline begrenst ook de downloadbody; stilstaande en langzaam druppelende verbindingen stoppen. Een bekende Content-Length moet overeenkomen met het werkelijk ontvangen aantal bytes. SHA256, maximale grootte en atomische cachepromotie blijven vereist.
2. De eerste voorbereiding publiceert een klein lokaal voortgangsrecord. De launcher toont tijdens de download het onderdeel en ontvangen MB, vervolgens uitpakken/controleren. Verouderde, ongeldige of onveilige records worden genegeerd. De record kan geen programma, download of herstelactie autoriseren.
3. Een updatevrijgave vereist naast bouw- en automatische controle ook een aparte menselijke verklaring voor exact dezelfde MSI- en EXE-hashes: interactieve Windows 11-proef, ondertekening en beoordeelde AV-resultaten zonder open detecties. Dit is controle van een verklaring, geen geautomatiseerd bewijs dat de verklaring waar is. De bestaande updaterindeling blijft gelijk.
4. README en supportuitleg onderscheiden de bestaande testbeta van de beoogde ondertekende installer. De handleiding vraagt bij quarantaine om concrete detectiegegevens, zonder uitsluitingen of automatische herplaatsing van verwijderde bestanden.
5. Bij de synthetische tests trad herhaaldelijk Windows-fout 5 op bij het promoveren van een volledig uitgepakte map; ook een controle buiten de sandbox gaf zo'n fout. Een AV-oorzaak is niet bewezen. Runtime-extractie en deel-I/II-import proberen alleen Windows-fouten 5/32/33 beperkt opnieuw, met maximaal 750 ms aan extra wachttijd. Voor elke herpoging wordt de staged-inhoud opnieuw gecontroleerd; een verschenen doelmap wordt nooit overschreven. Blijvende fouten blijven falen. Dit herstelt geen bestanden die door antivirus zijn verwijderd.

Deze wijzigingen zijn lokaal en in een afzonderlijke openbare bronbranch voorbereid. Er is geen nieuwe installer gebouwd, geen game gestart, geen AV-instelling veranderd en geen nieuwe release vrijgegeven. De testuitkomsten worden apart vastgelegd na de volledige controles.

## Wat nog nodig is voor werkelijk plug-and-play

De volgende release moet een nieuwe versie krijgen; bestaande assets en tags worden niet vervangen. Eerst een signingdienst aansluiten, de EXE ondertekenen, daarna de MSI bouwen/ondertekenen en de uiteindelijke bytes opnieuw controleren. De huidige bouwroute is nog niet op die signingstap aangesloten; de nieuwe vrijgavecontrole houdt een onvoltooide route tegen.

Verklein daarna de voorbereiding verder: laat de UI zelfstandig openen, haal alleen onderdelen op wanneer de gekozen functie ze nodig heeft en bundel waar distributierechten dat toelaten de vaste launcher-runtimes. Dat vraagt een gerichte herziening van bootstrap en componentplanning; deze wijziging doet dat niet half in de bestaande game-startketen. Een latere native UI kan de huidige CMD/PowerShell-startketen vervangen; de bestaande compatibiliteitscode hoeft daarvoor niet te worden weggegooid.

Vrijgaveproef op een schone Windows 11-machine, als standaardgebruiker en met beveiliging aan: echte browserdownload, installatie, snelkoppeling, eerste start en game-import, race en terugkeer, tweede start zonder internet, afgebroken download en opnieuw proberen, update met savebehoud, verwijderen met savebehoud. Noteer de uiteindelijke artifacthashes en welke AV-producten werkelijk zijn getest. Geen algemene belofte dat alle AV's de build toelaten.

Gebruik herkomstattestaties aanvullend op signing en maak releases waar mogelijk immutabel na volledige voorbereiding. Dat voorkomt het ongemerkt vervangen van vrijgegeven bijlagen; het bewijst geen AV-veiligheid. [GitHub: attestaties](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations), [immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases).

Deel II verder uitbreiden en deel III vervolgen zodra deze distributieacceptatie rond is. Hun huidige speelstatus wordt niet veranderd door een pakket- of launcherverbetering.
