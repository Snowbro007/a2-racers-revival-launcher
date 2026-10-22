"""Only the validated Tour 1 parent may enter the owned, supervised play route."""
import json
import os
from pathlib import Path

from tools import iii_session_guard as guard, iii_start_safety as safety
from tools import iii_mouse_trial
from tools.local_game_data import launch_environment
from tools.trial_manifest import validate_ancestors


def run(root, tour, profile, target):
    safety.assert_start_allowed(tour, profile)
    root, target = Path(root).resolve(), Path(target)
    expected = (root / f'local/iii-play/tour{tour}' if profile == 'original'
                else root / f'local/iii-trials/tour{tour}-{profile}')
    validate_ancestors(target)
    if target.absolute() != expected:
        raise ValueError('De bewaakte start accepteert alleen de gecontroleerde eigen speelkopie.')
    target = iii_mouse_trial.prepare(root, tour, profile, target)
    parent = target / f'A2 Racer III Tour {tour}.exe'
    validate_ancestors(parent)
    if not parent.is_file():
        raise ValueError('De oorspronkelijke tourstarter ontbreekt.')
    result = guard.supervise_play([str(parent)], target, {**os.environ, **launch_environment(target)})
    report = root / 'reports/a2racer3/guarded-runs'
    validate_ancestors(report)
    report.mkdir(parents=True, exist_ok=True)
    destination = report / f'tour{tour}-{profile}-last.json'
    validate_ancestors(destination)
    data = {**result, 'tour': tour, 'profile': profile, 'game_path': str(target),
            'runtime_verified': False, 'disc_image_used': False, 'shared_mouse_trial': True}
    destination.write_text(json.dumps(data, indent=2), encoding='utf-8')
    print('Bewaakte deel-III-sessie afgesloten: ' + result['reason'])
    return 0
