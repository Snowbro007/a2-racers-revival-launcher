"""Separate validated Tour 1 mouse-sharing copies; retain prior copies and saves."""
import hashlib
import json
from pathlib import Path
import tempfile

from tools import iii_mouse_fix as fix
from tools import trial_manifest as manifest
from tools.ii_frontend_state import read_regular


def prepare(root, tour, profile, source):
    # Deferred to avoid the validated launcher -> guard -> trial import cycle.
    from tools import iii_local_launcher as native, iii_compat_launcher as compat
    if type(tour) is not int or tour != 1 or profile not in ('original', *compat.PROFILES):
        raise ValueError('De vrije-muisproef is alleen voor Tour 1 beschikbaar.')
    root, source = Path(root).resolve(), Path(source)
    expected_source = (native.game_folder(root, tour) if profile == 'original'
                       else compat.folder(root, tour, profile))
    if source.absolute() != expected_source:
        raise ValueError('Andere bron voor de muisproef.')
    if profile == 'original':
        native.check_folder(root, tour, source)
    else:
        compat.check_path(root, tour, profile, source)
    source_files = compat.tree_bytes(source)
    mutable = compat.MUTABLE | set(compat.FONT_CACHE_LIMITS)
    # An original play folder also must not introduce arbitrary extra programs.
    allowed = {native.target_name(row['path']).casefold() for row in native.source_records(root, tour)}
    if profile != 'original':
        allowed |= {name.casefold() for name in compat.wrapper_inputs(root, profile)} | {'compatibility.json'}
    for name in source_files:
        if name.casefold() not in allowed and Path(name).name.casefold() not in mutable and not name.casefold().endswith('.rcr'):
            raise ValueError('Onbekend bronbestand voor de muisproef: ' + name)
    race = next(name for name in source_files if name.casefold() == 'spel.dat')
    result = dict(source_files)
    result[race], plan = fix.build(source_files[race])
    expected = {name: hashlib.sha256(raw).hexdigest() for name, raw in result.items()
                if Path(name).name.casefold() not in mutable and not name.casefold().endswith('.rcr')}
    target = root / f'local/iii-mouse/tour{tour}-{profile}'
    manifest.validate_ancestors(target)

    def check(folder):
        manifest.validate_tree(folder)
        record = json.loads(read_regular(folder/'mouse-trial.json', 65536))
        if (record.get('schema') != 1 or record.get('tour') != tour or record.get('profile') != profile
                or record.get('files') != expected):
            raise ValueError('Andere muisproefregistratie.')
        for path in folder.rglob('*'):
            if not path.is_file():
                continue
            name = path.relative_to(folder).as_posix()
            if name in expected:
                if hashlib.sha256(read_regular(path, compat.MAX_FILE_BYTES)).hexdigest() != expected[name]:
                    raise ValueError('Gewijzigde muisproef: ' + name)
            elif name != 'mouse-trial.json' and path.name.casefold() not in mutable and not name.casefold().endswith('.rcr'):
                raise ValueError('Onbekend bestand in de muisproef: ' + name)
            maximum = compat.FONT_CACHE_LIMITS.get(path.name.casefold())
            if maximum is not None:
                read_regular(path, maximum)
        if any(not (folder/name).is_file() for name in expected):
            raise ValueError('Bestand ontbreekt in de muisproef.')

    if target.exists():
        check(target)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {'schema': 1, 'tour': tour, 'profile': profile, 'files': expected,
              'mouse_fix': plan, 'source_unchanged': True, 'runtime_verified': False}
    with tempfile.TemporaryDirectory(prefix='.mouse-stage-', dir=target.parent) as directory:
        stage = Path(directory)/'candidate'
        stage.mkdir()
        for name, raw in result.items():
            path = stage/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        (stage/'mouse-trial.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
        check(stage)
        if compat.tree_bytes(source) != source_files:
            raise ValueError('De spelersbron veranderde; muisproef niet geregistreerd.')
        stage.rename(target)
    return target
