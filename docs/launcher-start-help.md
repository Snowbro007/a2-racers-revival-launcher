# Hulp bij starten

Download de releasebijlage via [README](../README.md), pak de ZIP helemaal uit en open `Launcher.cmd`. **Code → Download ZIP** bevat de broncode. De draagbare beta 10 is niet digitaal ondertekend.

## De eerste voorbereiding duurt lang

De eerste start haalt circa 11,4 MB aan launcherbasis op. Overige hulponderdelen volgen pas wanneer je een game toevoegt of voorbereidt. Bij deel II wordt de grote introspeler van 109,5 MiB overgeslagen. Die is alleen nodig voor deel I met ingeschakelde intro. De muziek van deel II komt uit je eigen gamebestanden. Er worden geen games gedownload. Na volledige voorbereiding kun je offline spelen.

Bij een onderbroken download kun je opnieuw proberen. Gedeeltelijk ontvangen bestanden kunnen verdergaan als de server dat ondersteunt; eerder opgehaalde onderdelen blijven bewaard. De launcher controleert de volledige download vóór gebruik.

Controleer bij een fout je verbinding en de melding onder **Support**. Beta 10 toont ook de foutdetails wanneer een eerdere versie alleen “Kon niet doorgaan” meldde. Een onderdeel met een verkeerde grootte of SHA-256 wordt geweigerd. Wis hiervoor geen voortgang of geïmporteerde games.

## Welke gamebestanden moet ik kiezen?

Spelen vereist je eigen volledige ondersteunde Nederlandse gamemap of ZIP. Je bron mag op zijn bestaande plek blijven. Kies de volledige map of het ondersteunde archief in de launcher. Voor deel II hoort `DATA` bij die map; een losse EXE is onvoldoende.

Met **Gamebestandenmap openen** maak je desgewenst een plek voor je eigen bronnen onder `Gamebestanden/A2 Racer I/` en `Gamebestanden/A2 Racer II/`. Selecteer ze daarna nog in de launcher; neerzetten importeert niets automatisch. Zet geen gamebestanden in `tools`, `assets` of `payload`.

De launcher maakt eigen kopieën en behoudt je bron. Laat hem `local/` beheren en bewaar die map met instellingen en voortgang bij een portable update.

## Deel II herkent mijn ZIP niet

Kies via **Gamearchief kiezen** de volledige `A2-Racer-II_Win_NL.zip`. Open of pak de BIN/CUE niet eerst zelf uit. Vanaf beta 9 wordt de ondersteunde Nederlandse v1.01-cd aan zijn inhoud herkend, ook wanneer de ZIP anders verpakt is. Het oorspronkelijke archief blijft intact. NRG-images, gewijzigde images en andere versies zijn nog niet ondersteund.

## Een bestand verdwijnt of wordt geblokkeerd

Controleer de beveiligingsgeschiedenis van je antivirus. Noteer de launcherversie, detectienaam, bestandsnaam en eventueel de SHA-256. Zet je beveiliging niet uit en maak geen uitzondering voor de hele launchermap. Laat een detectie eerst beoordelen; herhaald terugplaatsen lost die niet op.

Een Windows-melding over een onbekende uitgever of weinig gedownload bestand is een reputatiewaarschuwing. Dat is iets anders dan een malwaredetectie.

## Een probleem melden

Gebruik [GitHub Issues](https://github.com/Snowbro007/a2-racers-revival-launcher/issues) of [HeySnowdude@pm.me](mailto:HeySnowdude@pm.me). Vermeld versie, Windows-versie, betrokken game en relevante fouttekst. Verwijder je gebruikersnaam en persoonlijke paden uit screenshots. Deel geen gamebestanden of volledige logs met privégegevens.

## Een menu- of beeldkeuze is grijs

Bij deel II toont een grijze HUD/MAX-keuze welke lokale bronnen ontbreken. De openbare voorbereiding bouwt de originele HUD op voor 720p, 1080p en 4K; aanvullende lokale HD HUD-bronnen worden niet meegeleverd.

Voor **Origineel menu · gerestaureerd** gebruik je eerst **Game voorbereiden**. Deze keuze behoudt het oorspronkelijke artwork en de handcursor in een klassiek venster. Raceovergang en Alt+Tab zijn nog te testen. Voortgang blijft in de eigen oorspronkelijke-menukopie, apart van het Revival-menu. Het Revival-menu blijft aanbevolen.

**Deel III blijft geblokkeerd:** het kan vastlopen en de muis vasthouden.
