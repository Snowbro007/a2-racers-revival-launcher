# Een nieuwe Windows-beta maken

De workflow **Prepare Windows beta installer** start handmatig vanaf `main`.
Hij maakt alleen een conceptrelease en vervangt nooit een bestaande versie.
Beta 4 blijft de openbare download totdat een opvolger is goedgekeurd.

1. Verhoog `VERSION.txt`, beide `public-release.json`-bestanden en
   `docs/public-release-notes.md`. Beta 7 is `0.1.0-beta.7`.
2. Laat de pull-requestcontroles slagen en voeg de bronwijziging samen.
3. Start de workflow op `main` met precies die versie. Hij controleert de
   openbare bronallowlist, ZIP, eigen EXE, payload/CAB en alle MSI-tabellen.
   Games, saves, persoonlijke mappen, prompts en runtimes worden uitgesloten.
4. De workflow test installeren, upgraden, downgrade weigeren, repareren en
   verwijderen met tekstfixtures. Daarna installeert hij de echte gecontroleerde
   MSI en start uitsluitend de launchercontrole (`--check`), eerst met lege en
   daarna gevulde runtimecache. Geen game of native testhulp wordt gestart.
   Reparatie en behoud van synthetische voortgang/cache worden gecontroleerd.
5. Download de kandidaat en het artifact `installed-app-evidence`. Doe nog een
   interactieve proef op Windows 11: map kiezen, A2-icoon, launcher, Support,
   installeren/upgraden, instellingen behouden en verwijderen. Een Windows
   CI-server en een controlemodus vervangen deze gebruikersproef niet.
6. Controleer ondertekening en antivirus voor precies deze bytes. Een herbouw
   krijgt een nieuwe hash en versie. Upload niets extern zonder toestemming.
   De beta-5-MSI gaf [0/61](https://www.virustotal.com/gui/file/d3b981eb21ae3d59e86376e5be33d34098a07619b607f3782814b81e359ce1dc/detection),
   zijn launcher [2/71](https://www.virustotal.com/gui/file/594fc351184a43ec23aa149461d3365e86a45f3d8a92955ada911b86d66c4728/detection).
   Dat bewijst geen vals alarm en zegt niets over beta 7. Ondertekening is
   [voorbereid](signing-preparation.md), nog niet aangesloten.
7. Alleen na de bewuste eindbeslissing van de beheerder: maak lokaal het
   vrijgavebestand met onderstaande opdracht. Voeg het zonder vervangen van
   bestaande bijlagen aan diezelfde conceptrelease toe, controleer de hashes
   nogmaals en publiceer daarna het concept. Zonder `release-review.json`
   biedt de updater deze release niet aan. Conceptreleases worden altijd
   overgeslagen. Werk de README-downloadknop pas bij na publicatie.

```powershell
python tools/create_update_review.py --installer "pad/naar/A2-Racers-Revival-0.1.7-beta7.msi" --build-review "pad/naar/build-review.json" --app-test "pad/naar/app-install-result.json" --output "pad/naar/release-review.json" --approve
```

De opdracht controleert de exacte MSI-hash, bron/payloadcontrole en eerste en
tweede appstart, reparatie/verwijderen en databehoud uit de testrapporten.
`--approve` is de menselijke vrijgavebeslissing; het script tekent niet,
verklaart geen antivirusdetecties tot vals alarm en publiceert niets.
Een ingetrokken of gewijzigde vrijgave wordt voor installatie opnieuw geweigerd.

De downloadbijlagen zijn de MSI, `.sha256`, `build-review.json` en pas na
goedkeuring `release-review.json`. De uitvoerige installatielogs en bouwplannen
blijven aparte tijdelijke CI-artifacts. Niet als download meeleveren.

MSI-versie: `major.minor.(patch × 1000 + beta)`, bijvoorbeeld `0.1.7` voor
`0.1.0-beta.7`. Beta 1–999, patch 0–64, major/minor maximaal 255. Gebruik
altijd een hogere versie. UpgradeCode/component-ID's en de installatiemap
blijven stabiel. Een andere versie krijgt een nieuw ProductCode; elke bouw
een nieuw PackageCode. Een toekomstige stabiele versie reserveert het
numerieke slot `patch × 1000 + 1000`; de huidige bouwworkflow maakt alleen beta's.

Er worden uitsluitend officiële GitHub Actions, Python, .NET Framework,
Windows Installer COM en `makecab` gebruikt. Geen aparte installer-toolchain,
zelfuitpakkende Setup.exe of uitvoerbare Harness-testhelper. Geen wijzigingen
aan antivirus, SmartScreen, systeembeleid of permissies.
