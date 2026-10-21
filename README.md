# A2 Racers Revival

Een fanproject voor de oude A2 Racer-games op moderne Windows-pc’s. I en II zijn speelbaar, met Full HD en optionele HD textures voor I. III is in ontwikkeling.

Deel III is voorlopig gepauzeerd: een proef liep vast en hield de muis vast. Start III niet in de oude beta 4; de volgende versie blokkeert deze starts totdat dit is opgelost.

**[Download de bestaande Windows 11-testbeta (.zip)](https://github.com/Snowbro007/a2-racers-revival-launcher/releases/download/v0.1.0-beta.4/A2-Racers-Revival-0.1.0-beta.4-Windows-x64.zip)**

1. Pak de ZIP helemaal uit via **Alles uitpakken**.
2. Open **Launcher.cmd** in de uitgepakte map.
3. Kies A2 Racer I of II. Voeg je eigen volledige Nederlandse gamemap of ondersteunde ZIP toe.
4. Kies **Aanbevolen → Spelen** zodra de launcher aangeeft dat je game klaarstaat.

Je hoeft Python niet zelf te installeren. **De oude beta 4 haalt bij de eerste start ook grote hulponderdelen op**, samen circa 244 MB boven op de ZIP. Daardoor kan de voorbereiding lang duren, ook als je nog geen game hebt toegevoegd. Dat is voorbereiding van de launcher, geen controle van een al aanwezige game. Download de releasebijlage, niet de broncode via **Code → Download ZIP**.

De volgende bronversie opent de launcher na alleen de kleine launcher-runtime; de overige onderdelen volgen wanneer je een game klaarmaakt. Die verbetering en de onderstaande nieuwe mapknop zitten nog niet in de bestaande beta-4-download. Er is nog geen nieuwe download vrijgegeven.

**Distributiestatus:** de huidige beta is nog niet plug-and-play bevestigd. Er zijn antivirusmeldingen bekend en de nieuwere MSI is nog een concept. De aanbevolen vervolgstap is een ondertekende installer met een geteste eerste start. [Onderzoek en verbeteringen](https://github.com/Snowbro007/a2-racers-revival-launcher/blob/main/docs/fan-distribution-review-20261021.md) · [Hulp als de launcher verdwijnt of niet start](https://github.com/Snowbro007/a2-racers-revival-launcher/blob/main/docs/launcher-start-help.md).

### De games

Games worden niet meegeleverd. Gebruik je eigen cd, installatie of back-up. Voor II is er een [externe downloadpagina bij MyAbandonware](https://www.myabandonware.com/game/a2-racer-ii-gri). Die site staat los van dit project; controleer of je de aangeboden kopie mag gebruiken.

**Nog geen gamebestanden?** Je kunt de launcher alvast bekijken. Spelen wordt pas beschikbaar nadat je je eigen ondersteunde game hebt toegevoegd. De launcher downloadt geen games.

### Waar zet ik mijn gamebestanden?

Je originele gamemap of ZIP **mag blijven staan waar hij nu staat**. Kies die via de knop voor een gamemap of gamearchief; je hoeft niets in `tools`, `assets` of `payload` te plaatsen.

De volgende bronversie heeft **Gamebestandenmap openen** voor wie alles bij elkaar wil bewaren:

```text
A2-Racers-Revival/
├─ Launcher.cmd
├─ Gamebestanden/          ← optionele plek voor je eigen originelen of ZIP's
│  ├─ A2 Racer I/
│  └─ A2 Racer II/
└─ local/                 ← beheerd door de launcher: kopieën, voortgang en onderdelen
```

Bestanden in `Gamebestanden` worden niet automatisch geïmporteerd. Kies na het neerzetten nog steeds de volledige gamemap of ZIP in de launcher. Voor deel II hoort de map `DATA` bij de volledige gamemap. Bij importeren controleert de launcher de gekozen versie en maakt een eigen kopie onder `local/games/a2racer1` of `local/games/a2racer2`. Je oorspronkelijke bestanden blijven intact. Bewaar bij een portable update zowel `Gamebestanden/` met je eigen bronnen als `local/` met de beheerde kopieën en voortgang. Laat de launcher `local/` beheren.

### Goed om te weten

Onofficieel fanproject, zonder steun van de rechthebbenden. De oorspronkelijke games en merken blijven van hen. [MIT](LICENSE) geldt voor eigen code; zie [overige licenties](THIRD-PARTY-NOTICES.md). Beta zonder garantie, gebouwd met hulp van **LLM’s**. Later: deel IV en multiplayer.

Nog niet digitaal ondertekend: Windows kan waarschuwen of blokkeren. [Release en SHA-256](https://github.com/Snowbro007/a2-racers-revival-launcher/releases/tag/v0.1.0-beta.4).

[GitHub Issues](https://github.com/Snowbro007/a2-racers-revival-launcher/issues) · [HeySnowdude@pm.me](mailto:HeySnowdude@pm.me)
