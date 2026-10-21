# Als de launcher niet opent of verdwijnt

De openbare download is momenteel een testbeta. De ondertekende installer is nog niet vrijgegeven. De ZIP bij een release is de speelbare testdownload; de GitHub-knop **Code → Download ZIP** bevat de broncode.

## Bestand verdwijnt uit de map

Kijk in de beveiligingsgeschiedenis van je antivirus. Noteer de launcherversie, het antivirusproduct, de detectienaam, het genoemde bestand en het tijdstip. Als beschikbaar: noteer ook de SHA256 uit het beveiligingsrapport. Alleen een melding met deze gegevens kan bevestigen of het bestand in quarantaine is gezet.

Meld dit via [GitHub Issues](https://github.com/Snowbro007/a2-racers-revival-launcher/issues). Deel alleen relevante fouttekst; verwijder je gebruikersnaam en andere persoonlijke paden. Upload geen eigen gamebestanden of volledige gamemappen. Een melding indienen verstuurt niet automatisch een sample aan een antivirusleverancier.

Zet de beveiliging niet uit en maak geen uitzondering voor de hele launchermap. Herhaald opnieuw downloaden of terugplaatsen maakt een onbeoordeelde detectie niet opgelost. Laat de bevinding eerst onderzoeken.

## Windows toont een reputatiewaarschuwing

Een waarschuwing over een onbekende uitgever of weinig gedownload bestand is iets anders dan een malwaredetectie. De huidige bestanden zijn niet digitaal ondertekend. Ondertekening wordt voorbereid; ook ondertekening garandeert niet dat ieder antivirusproduct een nieuwe versie accepteert.

## Eerste voorbereiding blijft bezig

De eerste start downloadt onderdelen vanaf hun leveranciers en controleert ze op een vaste SHA256. De nieuwe bronversie toont welk onderdeel bezig is en hoeveel MB is ontvangen. Een stilstaande verbinding stopt na maximaal 30 seconden zonder antwoord; een afzonderlijke componentdownload duurt maximaal 10 minuten. Dit geldt voor de verbeterde bronversie, nog niet voor de oude beta-4-download.

Een fout bij grootte of hash betekent dat het onderdeel niet wordt gebruikt. Bekijk de melding bij **Support**, controleer je verbinding en probeer later opnieuw. Wis je saves of geïmporteerde games hiervoor niet. De launcher vult een verkeerd bestand niet stilzwijgend opnieuw in.

Een toekomstige MSI kan normale beschadigde programmabestanden via Windows herstellen. Laat bij een AV-quarantaine eerst de detectie beoordelen. Instellingen en voortgang blijven bij een normale update of verwijdering apart bewaard; behoud zelf ook een back-up van `local/` zolang je de portable beta gebruikt.
