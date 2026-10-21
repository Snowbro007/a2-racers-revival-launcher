# A2 Racers Revival

Een fanlauncher voor A2 Racer I en II op Windows 11, met aanpasbare beeld- en spelinstellingen.

**[Download de Windows 11-testbeta (.zip)](https://github.com/Snowbro007/a2-racers-revival-launcher/releases/download/v0.1.0-beta.4/A2-Racers-Revival-0.1.0-beta.4-Windows-x64.zip)**

De huidige download is **0.1.0-beta.4**. Games worden niet meegeleverd. **Start deel III niet in deze beta:** het kan vastlopen en de muis vasthouden.

### Starten

1. Pak de ZIP helemaal uit via **Alles uitpakken**.
2. Open **Launcher.cmd** in de uitgepakte map.
3. Kies A2 Racer I of II en voeg je eigen volledige Nederlandse gamemap of ondersteunde ZIP toe.
4. Kies **Aanbevolen → Spelen** zodra je game klaarstaat.

Download de releasebijlage, niet de broncode via **Code → Download ZIP**. Je hoeft Python niet zelf te installeren. De eerste start gebruikt internet en haalt circa 244 MB aan hulponderdelen op. Daardoor kan de voorbereiding even duren, ook zonder toegevoegde game. Na volledige voorbereiding kun je offline spelen.

### Je eigen gamebestanden

Je originele gamemap of ZIP **mag blijven staan waar hij nu staat**. Selecteer hem in de launcher. Voor A2 Racer II hoort de map `DATA` bij de volledige gamemap; een losse EXE of minimale installatie is niet genoeg.

Wil je je bronnen bij elkaar bewaren, dan kun je zelf bijvoorbeeld deze indeling gebruiken:

```text
Gamebestanden/
├─ A2 Racer I/
└─ A2 Racer II/
```

Selecteer na het neerzetten nog steeds de volledige gamemap of ZIP in de launcher; bestanden worden niet automatisch geïmporteerd. De launcher controleert de gekozen versie en maakt een eigen kopie. Je oorspronkelijke bestanden blijven intact.

Zet geen gamebestanden in `tools`, `assets` of `payload`. Laat de launcher de map `local/` beheren: daarin staan de beheerde kopieën, instellingen en voortgang. Bewaar bij een portable update zowel `local/` als je eigen gamebronnen.

Heb je nog geen gamebestanden, dan kun je de launcher alvast bekijken. Spelen vereist je eigen ondersteunde game. De launcher downloadt geen games. Gebruik een rechtmatig verkregen eigen cd, installatie of back-up.

### Bekende beperkingen en hulp

Dit is een testbeta, nog niet digitaal ondertekend. Windows of je antivirus kan waarschuwen of blokkeren; er zijn antivirusmeldingen bekend. Zet je beveiliging niet uit en voeg geen uitzondering voor de hele launchermap toe. Noteer bij een probleem de versie, foutmelding, bestandsnaam en eventuele detectienaam. Verwijder persoonlijke gegevens uit screenshots en deel geen gamebestanden.

Meld problemen via [GitHub Issues](https://github.com/Snowbro007/a2-racers-revival-launcher/issues) of [HeySnowdude@pm.me](mailto:HeySnowdude@pm.me). [Release en SHA-256](https://github.com/Snowbro007/a2-racers-revival-launcher/releases/tag/v0.1.0-beta.4).

Onofficieel fanproject, zonder steun van de rechthebbenden. De oorspronkelijke games en merken blijven van hen. [MIT](https://github.com/Snowbro007/a2-racers-revival-launcher/blob/main/LICENSE) geldt voor eigen code; zie [overige licenties](https://github.com/Snowbro007/a2-racers-revival-launcher/blob/main/THIRD-PARTY-NOTICES.md). Beta zonder garantie, gebouwd met hulp van LLM’s.
