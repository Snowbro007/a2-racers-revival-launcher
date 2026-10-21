# Duidelijke eerste start en eigen gamebestanden

Bronwijziging van 21 oktober 2026. Geen nieuwe download vrijgegeven en geen
geslaagde interactieve Windows 11-proef geclaimd.

De bestaande beta 4 haalt tijdens de eerste voorbereiding vijf vaste
providerarchieven op: circa 244 MB boven op de launcher-ZIP. De launcher heeft
dan nog geen game nodig. Een melding over de game controleren beschrijft die
stap dus onvoldoende.

De nieuwe route scheidt openen van spelen. Eerst wordt alleen de kleine
launcher-runtime opgehaald en gecontroleerd. De rest van de onderdelen volgt
als de gebruiker een game klaarmaakt. Een ontbrekende game krijgt een expliciete
uitleg en een keuze voor een volledige gamemap of ondersteund ZIP-archief.
Geen handmatige Python-installatie, game-download of beveiligingsuitsluiting
wordt toegevoegd.

Voor gebruikers die hun eigen bronnen bij de launcher willen bewaren is er een
optionele `Gamebestanden/`-map, met `A2 Racer I/` en `A2 Racer II/` en uitleg.
De knop om die map te openen maakt de structuur; neerzetten van een bestand
triggert geen import. Een bron mag ook buiten de launchermap blijven staan.
De bestaande gecontroleerde kopieën blijven onder `local/games/`, instellingen,
speelkopieën en voortgang blijven onder `local/`. Bestaande mappen worden niet
automatisch verplaatst of overschreven.

De publieke pakketlijst neemt de oude `Maak-snelkoppeling.ps1` niet meer mee.
De persoonlijke oude testkit behoudt zijn eigen helper; moderne gebruikers
starten via `Launcher.cmd` of via de snelkoppeling van de MSI. De openbare
bronkopie en toekomstige MSI-payload gebruiken dezelfde opgeschoonde lijst.

Controleer met synthetische fixtures dat pakket en bronkopie zonder de oude
helper kunnen worden opgebouwd. Test vervolgens de echte browserdownload,
eerste start zonder game, de mappenknop, importkeuze en een tweede start apart.
Automatische bron-/fixturecontroles bewijzen geen game-uitvoering of volledige
Windows-gebruikersacceptatie.

Lokale broncontrole: 237 synthetische tests geslaagd, waarvan 6 expliciet
overgeslagen wegens lokale script-/linkbeperkingen en de uitgeschakelde native
testhelper. De wachtrijtest verifieert zowel publieke minimale voorbereiding als
de behouden volledige privékitroute, succesvolle hervatting met dezelfde
argumenten en stoppen bij download-/procesfout of ontbrekende speelruntime.
WPF-previews voor deel I en II zijn gerenderd zonder game, componentdownload of
cd-mount; dit controleert schermopbouw, geen echte koude browserdownload.

De game-invoermap staat in de Git-ignorelijst en is ook expliciet verboden in
de openbare bronopbouw. De oude persoonlijke snelkoppelingshelper blijft lokaal
bij de oorspronkelijke privékit; hij wordt uit deze openbare repository en
uit de moderne pakketlijst verwijderd.
