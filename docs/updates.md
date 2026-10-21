# Updates

De beschikbare openbare download staat in [README](../README.md). Beta 4 heeft geen ingebouwde updatefunctie. Bewaar bij een portable update je eigen gamebronnen en `local/` met instellingen en voortgang.

## Updatefunctie in de launcherbron

Het updatevak onder **Support** kan GitHub controleren op nieuwere goedgekeurde installerversies. Automatisch controleren kan uit; downloaden en installeren vragen altijd een gebruikersactie. Er worden geen gamemappen, saves of instellingen naar GitHub verstuurd. Zonder internet blijft lokaal spelen mogelijk.

Concepten, oudere versies en releases zonder geldige vrijgave worden overgeslagen. Grootte en SHA-256 moeten overeenkomen met de release. Downloads behouden hun Windows-internetherkomst. Vóór installatie wordt de openbare vrijgave opnieuw gecontroleerd; ingetrokken of gewijzigde updates worden geweigerd. Installeren is geblokkeerd tijdens spelen of voorbereiden.

Na bevestiging sluit de launcher en opent de gewone Windows-installer. Een ongeldige handtekening wordt geweigerd. De updater zet geen beveiliging uit en deblokkeert geen bestanden. Een hashcontrole is geen veiligheidsverklaring.

De MSI behoudt de installatiemap en beheert alleen programmabestanden. Lokale gamekopieën, voorkeuren, voortgang en gedownloade onderdelen blijven apart. De updatevoorkeur staat in `local/launcher/update-settings.json`.
