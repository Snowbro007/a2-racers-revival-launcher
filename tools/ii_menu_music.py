"""Hash-pinned original II menu music extraction, no audio/game execution."""
import hashlib
import io
import wave

INDEX_SHA256 = '811ce46f5054cad00f83c4eee3d3f493f5742fea8c5dbf9dcedfbb2f22541afc'
IMAGE_SHA256 = 'd94ad3c690f9223fc75b95ad4bca6a659ab47b15f324d9c7de5f94510c6c697f'
TRACK_SHA256 = {
    'speed2.wav':'2260590622ba7f3dcac2f55cc17a9cbe4c5dfe8b1f16715b36948d48cb09f432',
    'disco.wav':'1c9dca5c694401614ef0a25a20eab0657f9b14a70fbb719fef81a6936e68c380',
    'moody.wav':'113af8664213cbf1ff96b24d42ee01e31f8bf9f269a236cca6e372b44a60c8ce',
    'jammin.wav':'c39f2494ca06dd97da29742613e82f07d3a28727fc4ea2f73841e51e2816c5d1',
    'energy.wav':'46dc8f6ec59d53086e09114c5c91564c3870a76eef86fcd18eb3ad79932f2a2b',
    'speed.wav':'08b3ea190871b454d1bcf1e59e95d9ca6d6e8f596e68357f7b57b759124fa1ec',
}
MUSIC_FILES = {f'assets/music/{name}' for name in TRACK_SHA256}


def extract_tracks(index: bytes, image: bytes) -> dict[str, bytes]:
    from tools.ii_frontend_prepare import resource
    if (hashlib.sha256(index).hexdigest()!=INDEX_SHA256 or
            hashlib.sha256(image).hexdigest()!=IMAGE_SHA256):
        raise ValueError('Ander origineel menuarchief; muziekextractie geweigerd.')
    result={}
    for name,digest in TRACK_SHA256.items():
        raw=resource(index,image,name)
        if hashlib.sha256(raw).hexdigest()!=digest:
            raise ValueError('Andere menumuziek: '+name)
        with wave.open(io.BytesIO(raw)) as audio:
            if (audio.getcomptype()!='NONE' or audio.getnchannels() not in (1,2)
                    or audio.getsampwidth() not in (1,2) or audio.getframerate()!=22050
                    or not 20 < audio.getnframes()/audio.getframerate() < 120):
                raise ValueError('Onverwacht muziekformaat: '+name)
        result[f'assets/music/{name}']=raw
    return result
