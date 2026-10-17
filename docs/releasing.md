# Een nieuwe Windows-beta maken

De beta-5-installer wordt momenteel niet gepubliceerd. Een lokale synthetische
testhulp is door Bitdefender geblokkeerd als `Gen:Variant.MSILHeracles.213981`;
de uitvoerbare helpertest is daarom uitgeschakeld. De eerdere Setup.exe had
7/69 VirusTotal-detecties. Onderzoek dit voordat je een nieuwe native build
uitvoert of als download aanbiedt. Een vals alarm is niet bevestigd.

De workflow **Prepare Windows beta installer** start alleen handmatig vanaf
`main`. Hij maakt een conceptrelease, geen openbare download. Een bestaande
versie, tag of bijlage wordt nooit vervangen.

1. Werk `VERSION.txt`, beide `public-release.json`-bestanden en de openbare
   releasetekst bij naar een nieuwe versie, bijvoorbeeld `0.1.0-beta.6`.
2. Push de gecontroleerde broncode. Kies in GitHub **Actions → Prepare Windows
   beta installer → Run workflow** en vul precies die versie in.
3. Download de MSI uit de conceptrelease. Test een nieuwe installatie, een
   zelfgekozen map, starten, bijwerken met behoud van die map en voortgang,
   herstellen en verwijderen op een schone Windows-pc.
4. Vermeld de echte testuitslag en eventueel het scanrapport van precies die
   MSI. Een herbouw heeft een nieuwe hash. Laat een bestand alleen extern
   scannen als daar toestemming voor is. Een scan bewijst geen veiligheid.
5. Publiceer het gecontroleerde concept en werk daarna de downloadknop in
   `README.md` en `docs/public-readme.md` bij naar die bestaande MSI-bijlage.
   Laat de vorige werkende download staan totdat de opvolger beschikbaar is.

De build gebruikt uitsluitend de openbare bronallowlist. Hij controleert de
daadwerkelijke ZIP, de eigen native launcher, alle payload- en CAB-bytes en de
tabellen en ingebedde CAB/icoonstreams van de MSI. Alleen de MSI, zijn SHA-256
en een klein bouwverslag worden als bijlagen toegevoegd. Games, saves,
persoonlijke mappen, prompts en gedownloade onderdelen worden uitgesloten.
Automatische checks installeren of starten de MSI niet en leveren geen
antivirus-, SmartScreen- of praktijktest op. De setup is nog niet ondertekend.

MSI gebruikt drie numerieke versievelden. Onze conventie is
`major.minor.(patch × 1000 + beta)`: `0.1.0-beta.6` wordt `0.1.6`, met als
downloadnaam `A2-Racers-Revival-0.1.6-beta6.msi`. Beta loopt van 1 tot 999 en
patch van 0 tot 64; major/minor maximaal 255. Gebruik altijd een hogere versie
voor een update. UpgradeCode, component-ID's en de opgeslagen installatiemap
blijven stabiel. Een andere versie krijgt een nieuw ProductCode; elke bouw een
nieuw PackageCode.

De workflow gebruikt de officiële [GitHub Actions](https://github.com/actions)
en bouwt op Windows met Python, de aanwezige .NET Framework-compiler,
Windows Installer COM en `makecab`. Er wordt geen aparte installer-toolchain
opgehaald en er worden geen Windows-beveiligingsinstellingen aangepast.

De broncheckout bevat ook synthetische regressies voor game-import, bootstrap,
instellingen, bevroren starts en de voortgang van I/II. De MSI-auteurstests lopen
mee via `tests/test_windows_msi.py`; de geblokkeerde native helper blijft bewust
uit. Deze tests worden op de daadwerkelijk uitgecheckte bron gedraaid. De
geïnstalleerde launcher heeft deze ontwikkeltests niet nodig. Runtime-extractie
en importpromotie hebben afzonderlijke foutinjectietests voor onderbrekingen en
schrijffouten. Dat vervangt geen antivirus- of Windows-praktijkproef.
