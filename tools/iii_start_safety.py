"""Fail-closed III start policy after a confirmed hang and mouse-capture incident.

Preparation and static inspection remain available. There is deliberately no
environment variable, CLI flag or user preference that bypasses this stop.
"""

BLOCK_REASON = (
    'Start van A2 Racer III is tijdelijk geblokkeerd: een raceproef liep vast '
    'en hield de muis vast. Eerst moeten de racehang en het vrijgeven van de '
    'muis bij focusverlies veilig zijn opgelost. Voorbereiden blijft mogelijk.'
)


def assert_start_allowed() -> None:
    raise ValueError(BLOCK_REASON)


def status() -> dict:
    return {'start_blocked': True, 'start_allowed': False, 'reason': BLOCK_REASON}
