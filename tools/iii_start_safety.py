"""Tour-specific III policy: restored guarded Tour 1, stopped Tour 2 research."""

BLOCK_REASON = (
    'unstable · Start van A2 Racer III Tour 2 is tijdelijk geblokkeerd: een race liep vast '
    'en hield de muis vast. Eerst moeten de racehang en het vrijgeven van de '
    'muis bij focusverlies veilig zijn opgelost. Voorbereiden blijft mogelijk.'
)


PLAY_REASON = ('Tour 1 · untested · Bewaakte start met vrije muis. Ctrl+Shift+F8 sluit de eigen sessie af. '
               'Alt+Tab wordt niet automatisch afgesloten; maximaal vier uur per sessie. '
               'De gebruiker kon deze tour eerder spelen; de nieuwe bewaker '
               'is nog niet met de game speelgetest.')


def status(tour=None, profile=None) -> dict:
    allowed = type(tour) is int and tour == 1 and profile in ('original','compat','fullhd-skyoff')
    return {'start_blocked': not allowed, 'start_allowed': allowed,
            'guard_required': True, 'reason': PLAY_REASON if allowed else BLOCK_REASON}


def assert_start_allowed(tour=None, profile=None) -> None:
    state = status(tour, profile)
    if not state['start_allowed']:
        raise ValueError(state['reason'])
