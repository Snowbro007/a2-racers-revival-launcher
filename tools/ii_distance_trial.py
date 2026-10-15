"""Immutable, version-pinned experiment disabling adaptive chunk reduction."""
import hashlib

SOURCE_SHA256 = '1e5cef6499bd001ace3f22ff0a818101fe43bcf80b2ff086f0d912e6f3891016'
OUTPUT_SHA256 = 'fdb7213be22d1bd9fb75feebd2339a7545021afd0cd57bb99110265df395d1ba'
CONTEXT_OFFSET = 0x24098
CONTEXT = bytes.fromhex('a17c9a4d0085c0753c8b35ac9a4d00b970494e00f7de1bf683e60a83c60fe815d00100d83d78f74700d81d7cf74700dfe0f6c401740fa18c9a4d003bc67e0648a38c9a4d00')
PATCH_OFFSET = 0x240D7
LIMIT_OFFSET = 0x210BE
LIMIT_CONTEXT = bytes.fromhex('83f8327e0ac7058c9a4d0032000000')


def build_extended_trial(source: bytes, count: int = 60) -> tuple[bytes, dict]:
    """Isolated 60-chunk trial on the exact fixed-50 binary; not runtime proven."""
    if type(count) is not int or count != 60:
        raise ValueError('Alleen de afzonderlijke 60-baanstukkenproef is onderzocht.')
    if type(source) is not bytes or hashlib.sha256(source).hexdigest() != OUTPUT_SHA256:
        raise ValueError('Onbekende vaste-50-basis; uitgebreide afstandproef geweigerd.')
    if source[LIMIT_OFFSET:LIMIT_OFFSET+len(LIMIT_CONTEXT)] != LIMIT_CONTEXT:
        raise ValueError('Onbekende native bovengrens.')
    output = bytearray(source)
    output[LIMIT_OFFSET+2] = count  # CMP EAX,60 (positive imm8)
    output[LIMIT_OFFSET+11] = count  # MOV [visiblechunks],60 (imm32 low byte)
    result = bytes(output)
    return result, {'source_sha256': OUTPUT_SHA256,
                    'sha256': hashlib.sha256(result).hexdigest(),
                    'changed_bytes': 2, 'native_limit': [10,count],
                    'adaptive_reduction_disabled': True,
                    'far_plane_unchanged': True, 'native_game_executed': False,
                    'runtime_tested': False, 'experimental_above_original_limit': True}


def build_trial(source: bytes) -> tuple[bytes, dict]:
    if type(source) is not bytes or hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError('Onbekende 720p-racebasis; afstandproef geweigerd.')
    if source[CONTEXT_OFFSET:CONTEXT_OFFSET+len(CONTEXT)] != CONTEXT:
        raise ValueError('Onbekende adaptieve afstandcode.')
    output = bytearray(source)
    output[PATCH_OFFSET] = 0x90  # DEC EAX -> NOP; existing MOV stores unchanged count.
    result = bytes(output)
    if hashlib.sha256(result).hexdigest() != OUTPUT_SHA256:
        raise ValueError('Onverwachte uitvoerhash afstandproef.')
    return result, {'source_sha256': SOURCE_SHA256,
                    'sha256': hashlib.sha256(result).hexdigest(),
                    'changed_bytes': 1, 'adaptive_reduction_disabled': True,
                    'native_limit': [10, 50], 'far_plane_unchanged': True,
                    'native_game_executed': False, 'runtime_tested': False}
