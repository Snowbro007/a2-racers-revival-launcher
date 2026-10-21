# Als de launcher niet opent of verdwijnt

De openbare download is momenteel een testbeta. De ondertekende installer is nog niet vrijgegeven. De ZIP bij een release is de speelbare testdownload; de GitHub-knop **Code → Download ZIP** bevat de broncode.

## Bestand verdwijnt uit de map

Kijk in de beveiligingsgeschiedenis van je antivirus. Noteer de launcherversie, het antivirusproduct, de detectienaam, het genoemde bestand en het tijdstip. Als beschikbaar: noteer ook de SHA256 uit het beveiligingsrapport. Alleen een melding met deze gegevens kan bevestigen of het bestand in quarantaine is gezet.

Meld dit via [GitHub Issues](https://github.com/Snowbro007/a2-racers-revival-launcher/issues). Deel alleen relevante fouttekst; verwijder je gebruikersnaam en andere persoonlijke paden. Upload geen eigen gamebestanden of volledige gamemappen. Een melding indienen verstuurt niet automatisch een sample aan een antivirusleverancier.

Zet de beveiliging niet uit en maak geen uitzondering voor de hele launchermap. Herhaald opnieuw downloaden of terugplaatsen maakt een onbeoordeelde detectie niet opgelost. Laat de bevinding eerst onderzoeken.

## Windows toont een reputatiewaarschuwing

Een waarschuwing over een onbekende uitgever of weinig gedownload bestand is iets anders dan een malwaredetectie. De huidige bestanden zijn niet digitaal ondertekend. Ondertekening wordt voorbereid; ook ondertekening garandeert niet dat ieder antivirusproduct een nieuwe versie accepteert.

## Eerste voorbereiding blijft bezig

De openbare beta 4 haalt tijdens de eerste start alle hulponderdelen op, ook als er nog geen game is gekozen. Dat zijn samen circa 244 MB boven op de ZIP. De melding over controleren kan daardoor verwarrend zijn: de launcher bereidt dan zijn eigen onderdelen voor. Games worden niet meegeleverd of gedownload.

In de volgende bronversie zijn dit aparte stappen. Bij openen wordt alleen de launcher-runtime voorbereid. Grotere onderdelen voor spelen volgen als je je game klaarmaakt. De status noemt het onderdeel en de ontvangen MB. Een stilstaande verbinding stopt na maximaal 30 seconden zonder antwoord; een afzonderlijke componentdownload duurt maximaal 10 minuten. Deze bronverbeteringen zijn nog geen nieuwe openbare release en gelden niet voor de oude beta-4-download.

Een fout bij grootte of hash betekent dat het onderdeel niet wordt gebruikt. Bekijk de melding bij **Support**, controleer je verbinding en probeer later opnieuw. Wis je saves of geïmporteerde games hiervoor niet. De launcher vult een verkeerd bestand niet stilzwijgend opnieuw in.

Een toekomstige MSI kan normale beschadigde programmabestanden via Windows herstellen. Laat bij een AV-quarantaine eerst de detectie beoordelen. Instellingen en voortgang blijven bij een normale update of verwijdering apart bewaard; behoud zelf ook een back-up van `local/` zolang je de portable beta gebruikt.

## Ik heb nog geen game of weet niet welke map ik moet kiezen

De launcher en de oorspronkelijke games zijn aparte downloads. Je kunt de launcher bekijken zonder een game, maar voor spelen heb je je eigen ondersteunde volledige Nederlandse gamebestanden nodig. Een ontbrekende game hoort als **Nog geen game toegevoegd** te worden getoond, niet als een controle die blijft doorlopen.

Je eigen bron mag op zijn bestaande plek blijven. Kies **Gamemap kiezen** voor de volledige map, of de archiefknop voor je ondersteunde ZIP. Voor A2 Racer II moet `DATA` in die volledige gamemap zitten. Een losse EXE of minimale installatie is niet genoeg.

De nieuwe knop **Gamebestandenmap openen** maakt een overzichtelijke optionele plek met `Gamebestanden/A2 Racer I` en `Gamebestanden/A2 Racer II`. Zet daar desgewenst je eigen ZIP of complete gamemap neer en selecteer hem daarna in de launcher. Er wordt niet op de achtergrond gezocht of automatisch geïmporteerd. Zet geen gamebestanden tussen de launcheronderdelen in `tools`, `assets` of `payload`.

Na importeren staan de door de launcher beheerde bronkopieën onder `local/games/a2racer1` of `local/games/a2racer2`. De launcher bereidt daaruit speelkopieën voor. Verplaats die interne mappen niet handmatig; je eigen oorspronkelijke map of ZIP blijft behouden.
