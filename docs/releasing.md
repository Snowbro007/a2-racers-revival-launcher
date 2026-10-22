# Build en vrijgave

Dit document beschrijft de controleerbare bouwprocedure voor de eigen launcher. Beschikbare downloads en gebruikersinstructies staan in [README](../README.md). Een geslaagde build is geen vrijgave.

## Bron en build

1. Houd `VERSION.txt`, beide `public-release.json`-bestanden en de eerste regel van `docs/public-release-notes.md` op dezelfde nieuwe versie. Bestaande tags en releasebijlagen worden niet vervangen.
2. Controleer de openbare documentlijst met `python tools/check_public_docs.py` en voer `python -m unittest discover -s tests -v` uit. Alleen launcherbron, gebruikersdocumentatie, licenties en bouwinstructies horen in de openbare repo. Bewaar onderzoek, werkverslagen, persoonlijke gegevens en gegenereerde uitvoer apart.
3. Laat de pull-requestcontroles slagen en voeg de bronwijziging samen. Start **Prepare Windows beta installer** handmatig vanaf `main` voor precies die versie. De workflow maakt uitsluitend een conceptrelease.
4. De workflow controleert bron, ZIP, eigen EXE, payload/CAB en MSI-tabellen. Games, saves, privébestanden en gedownloade runtimes zijn uitgesloten. Installercontroles gebruiken geïsoleerde tekstfixtures; de appcontrole start alleen de launcher met `--check`.

De builder gebruikt Python, .NET Framework, Windows Installer COM en `makecab`. Zie [MSI-bouwinstructies](../tools/windows/msi/README.md). De bouwroute wijzigt geen antivirus, systeembeleid of permissies en gebruikt geen uitvoerbare testhelper.

## Vrijgavevoorwaarden

Een openbare installer vereist bewijs voor de **uiteindelijke MSI- en launcherbytes**:

- Een interactieve Windows 11-proef met eerste en tweede start, game toevoegen en terugkeren, update en verwijderen met behoud van gebruikersgegevens.
- Geldige digitale handtekeningen op launcher en MSI van dezelfde uitgever en certificaatthumbprint.
- Beoordeelde antivirusresultaten voor beide bestanden zonder open detecties.
- Geslaagde bron-, payload-, installer- en appcontroles.

De huidige bouwroute ondertekent nog niet. Zij kan daarom zelfstandig geen goedgekeurde publieke installer produceren. Een gewijzigde of opnieuw gebouwde binary vereist nieuwe controles; een hash bewijst geen veiligheid.

Vul [het lege acceptatievoorbeeld](release-acceptance.example.json) uitsluitend met vastgesteld bewijs in een lokale werkmap. Bewaar de onderliggende persoonlijke reviewgegevens en volledige logs buiten de openbare repo en downloads. Maak na de menselijke vrijgavebeslissing het vrijgavebestand:

```powershell
python tools/create_update_review.py --installer "pad/naar/installer.msi" --build-review "pad/naar/build-review.json" --app-test "pad/naar/app-install-result.json" --acceptance "pad/naar/human-acceptance.json" --output "pad/naar/release-review.json" --approve
```

Dit script controleert de verklaring en samenhang van hashes en bewijs. Het ondertekent, scant of publiceert niet en vervangt geen interactieve acceptatie. Het lege voorbeeld wordt geweigerd.

Publiceer pas na expliciete vrijgave van de beheerder dezelfde gecontroleerde conceptrelease met MSI, `.sha256`, `build-review.json` en `release-review.json`. Controleer de hashes nogmaals. Werk daarna de README-downloadlink bij. De updater slaat concepten en releases zonder geldige vrijgave over en controleert die vrijgave opnieuw vóór installatie.

## Draagbare ZIP-testbeta

**Publish game-free portable beta** publiceert na een expliciete opdracht de bestaande draagbare ZIP-route: launcherbron met `Launcher.cmd` en SHA-256, zonder games, EXE, MSI of andere meegeleverde runtimes. De workflow controleert versie, synthetische tests, documenten en de daadwerkelijke ZIP-inhoud. Bestaande tags en downloads worden niet vervangen.

Deze ZIP is een niet-ondertekende testbeta. Vermeld ontbrekende antivirus- en runtimebeoordeling in de releasetekst. De bovenstaande MSI-vrijgavevoorwaarden blijven gelden; de updater accepteert deze ZIP niet als goedgekeurde installerupdate. Gebruik voor een volgende installer een nieuwe, hogere versie. Werk de README-downloadlink pas bij nadat de ZIP-release geslaagd is.

## Versie-identiteit

De numerieke MSI-versie is `major.minor.(patch × 1000 + beta)`: `0.1.0-beta.7` wordt `0.1.7`. Beta is 1–999, patch 0–64, major/minor maximaal 255. Het stabiele versieslot is `patch × 1000 + 1000`; de workflow bouwt alleen beta's.

Gebruik steeds een hogere versie. UpgradeCode en component-ID's blijven stabiel. ProductCode verandert per versie en PackageCode per build. De MSI behoudt de bestaande installatiemap. Gebruikersgegevens vallen buiten het beheerde programmabestandsmanifest.
