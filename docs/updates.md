# Updates

De beschikbare openbare download staat in [README](../README.md). Beta 4 heeft geen ingebouwde updatefunctie. Bewaar bij een portable update je eigen gamebronnen en `local/` met instellingen en voortgang.

## Updatefunctie in de launcherbron

Het updatevak onder **Support** kan GitHub controleren op nieuwere goedgekeurde installerversies. Automatisch controleren kan uit; downloaden en installeren vragen altijd een gebruikersactie. Er worden geen gamemappen, saves of instellingen naar GitHub verstuurd. Zonder internet blijft lokaal spelen mogelijk.

Concepten, oudere versies en releases zonder geldige vrijgave worden overgeslagen. Grootte en SHA-256 moeten overeenkomen met de release. Downloads behouden hun Windows-internetherkomst. Vóór installatie wordt de openbare vrijgave opnieuw gecontroleerd; ingetrokken of gewijzigde updates worden geweigerd. Installeren is geblokkeerd tijdens spelen of voorbereiden.

Na bevestiging sluit de launcher en opent de gewone Windows-installer. Een ongeldige handtekening wordt geweigerd. De updater zet geen beveiliging uit en deblokkeert geen bestanden. Een hashcontrole is geen veiligheidsverklaring.

De MSI behoudt de installatiemap en beheert alleen programmabestanden. Lokale gamekopieën, voorkeuren, voortgang en gedownloade onderdelen blijven apart. De updatevoorkeur staat in `local/launcher/update-settings.json`.

## Draagbare launcher werkt zichzelf bij

Vanaf beta 12 kan de uitgepakte ZIP-launcher zichzelf bijwerken. Beta 11 en ouder hebben die functie nog niet: download de nieuwe ZIP daar één keer zelf en zet je map `local/` erin terug.

1. Bij het starten controleert de launcher GitHub op een nieuwere gepubliceerde release met de launcher-ZIP en het bijbehorende `.sha256`-bestand. Concepten worden overgeslagen.
2. Is er een nieuwere versie, dan vraagt de launcher één keer per sessie of je wilt bijwerken. Kies je **Nee**, dan staat de update klaar onder **Support**.
3. Na **Ja** downloadt de launcher de ZIP en controleert hij de grootte en SHA-256 tegen GitHub en het `.sha256`-bestand. Daarna controleert hij elk bestand tegen het release-manifest. Hij pakt de update eerst apart uit in `local/launcher/updates/`.
4. De launcher sluit. Een apart updateproces wacht tot de launcher echt gesloten is, bewaart de huidige programmabestanden en vervangt alleen bestanden die in het release-manifest staan. Bestanden die niet meer in de nieuwe versie zitten, worden verwijderd. Daarna start de launcher vanzelf opnieuw en meldt hij één keer het resultaat.
5. Mislukt een stap, dan worden alle programmabestanden teruggezet en meldt de launcher dat bij de volgende start.

Een update raakt nooit de map `local/` aan, met je instellingen, voortgang, saves, geïmporteerde games en runtimes. Andere eigen bestanden die niet in het manifest staan, blijven ook staan. Tijdens spelen of voorbereiden wordt niet bijgewerkt. Een Git-checkout (met `.git`) of een MSI-installatie werkt zichzelf nooit op deze manier bij; de MSI blijft de installerroute hierboven volgen. De vorige versie blijft als back-up bewaard in `local/launcher/updates/backup-*`.
