"""Versioned material-based cockpit plans; no file I/O or game execution.

Keep the accepted dashboard material plane. Only native animation apertures
receive new HD crops/faces/spokes. The historical vector experiment is intact.
Image sources are pinned by the integrating loader, not read by this module.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import math
import struct

from tools import hud_cockpit_assets as original
from tools.hud_hd_assets import COCKPIT_BY_NAME, SOURCE_SHA256

SCHEMA = 1
ASSET_ROOT = "local/mods/a2racer1/hud-cockpit-material-v1"
ASSET_ROOT_V2 = "local/mods/a2racer1/hud-cockpit-material-v2"
VARIANTS = ("v1", "v2")
SOURCE_SLOTS = (
    ("accepted_dashboard", "local/mods/a2racer1/dashboard-native-v1.source.png", (640, 480)),
    ("clean_plate", ASSET_ROOT + "/refined-clean-plate-v1.source.png", (640, 480)),
    ("neutral_spokes", ASSET_ROOT + "/refined-neutral-spokes-v1.source.png", (330, 240)),
    ("native_dashboard", ASSET_ROOT + "/native-dashboard-coverage-v1.mask.png", (640, 480)),
)
ACCEPTED_DASHBOARD_SHA256 = "8d061d27e37cc48211ffaf7baa5fdcbdc8d4d0f9ef9d03728f0920a357321dcc"
ATLASES = tuple(replace(a, name=a.name.replace("vector-v1", "material-v1"))
                for a in original.ATLASES)
ATLAS_BY_NAME = {a.name: a for a in ATLASES}
FIXED_PATCHES = (original.PatchSpec("left-material-v1", (89, 329, 40, 45), 4, (256, 256)),)
ATLASES_V2 = tuple(replace(a, name=a.name.replace("material-v1", "material-v2")) for a in ATLASES)
FIXED_PATCHES_V2 = tuple(replace(p, name=p.name.replace("material-v1", "material-v2"))
                         for p in FIXED_PATCHES)
LEFT_COMPOSITE_SHA256 = "3d843a7a6ba976c5c4867a3756647bd584b5d54555850c3deedd5e98377a475b"
LEFT_FACE_CLIP = ("M 18 5 C 28 5 37 13 38 23 C 38 33 30 41 20 41 "
                  "C 12 41 7 37 4 31 L 2 27 C 2 21 6 12 11 8 Z")
# Versioned, bounded contours of the visible black openings in the pinned own
# accepted material plane. Derived from its near-black center components;
# they are artwork visibility contracts, not native telemetry or CAD geometry.
# The first source image command remains unclipped, preserving all leather.
METER_FACE_CLIPS = {
    'left_gauge': 'M 0.0000 29.4530 L 0.2818 29.4530 L 0.2818 28.5691 L 1.1657 28.1271 L 1.1657 27.6851 L 1.6077 27.6851 L 1.6077 26.8011 L 2.0497 26.8011 L 2.4917 25.9171 L 3.3757 25.4751 L 3.3757 24.5912 L 3.8177 24.5912 L 3.8177 24.1492 L 4.2597 24.1492 L 4.2597 23.7072 L 4.7017 23.7072 L 5.1436 22.8232 L 5.5856 22.8232 L 6.0276 21.9392 L 6.4696 21.9392 L 6.4696 21.0552 L 7.3536 20.6133 L 7.7956 19.7293 L 8.2376 19.7293 L 8.2376 19.2873 L 8.6796 19.2873 L 8.6796 18.8453 L 9.1215 18.8453 L 9.1215 17.9613 L 9.5635 17.9613 L 9.5635 17.5193 L 10.0055 17.5193 L 10.0055 17.0773 L 10.4475 17.0773 L 10.8895 16.1934 L 11.3315 16.1934 L 11.3315 15.7514 L 11.7735 15.7514 L 11.7735 15.3094 L 12.2155 15.3094 L 12.2155 14.8674 L 12.6575 14.8674 L 13.0994 13.9834 L 13.5414 13.9834 L 13.5414 13.5414 L 13.9834 13.5414 L 13.9834 13.0994 L 14.4254 13.0994 L 14.4254 12.6575 L 14.8674 12.6575 L 15.3094 11.7735 L 15.7514 11.7735 L 15.7514 11.3315 L 16.1934 11.3315 L 16.1934 10.8895 L 16.6354 10.8895 L 16.6354 10.4475 L 17.0773 10.4475 L 17.5193 9.5635 L 18.4033 9.5635 L 18.8453 8.6796 L 19.2873 8.6796 L 19.2873 8.2376 L 19.7293 8.2376 L 19.7293 7.7956 L 20.6133 7.7956 L 21.0552 6.9116 L 21.4972 6.9116 L 21.4972 6.4696 L 21.9392 6.4696 L 21.9392 6.0276 L 22.3812 6.0276 L 22.3812 5.5856 L 22.8232 5.5856 L 22.8232 5.1436 L 23.7072 5.1436 L 24.1492 4.2597 L 26.8011 4.7017 L 26.8011 5.1436 L 28.5691 5.1436 L 29.0110 6.0276 L 30.7790 6.4696 L 31.2210 7.3536 L 32.1050 7.7956 L 32.1050 8.2376 L 32.9890 8.2376 L 32.9890 8.6796 L 33.8729 9.1215 L 33.8729 10.0055 L 34.7569 10.4475 L 34.7569 10.8895 L 35.1989 10.8895 L 35.1989 11.3315 L 35.6409 11.3315 L 35.6409 12.2155 L 36.5249 12.6575 L 36.5249 13.5414 L 36.9669 13.5414 L 37.4088 15.3094 L 37.8508 15.3094 L 37.8508 16.1934 L 38.2928 16.1934 L 38.2928 17.9613 L 38.7348 17.9613 L 38.7348 19.2873 L 39.1768 19.2873 L 39.1768 26.3591 L 38.7348 26.3591 L 38.7348 28.5691 L 38.2928 28.5691 L 38.2928 29.8950 L 37.8508 29.8950 L 37.8508 31.2210 L 37.4088 31.2210 L 36.9669 32.9890 L 36.0829 33.4309 L 36.0829 34.3149 L 35.1989 34.7569 L 35.1989 35.6409 L 34.7569 35.6409 L 34.7569 36.0829 L 34.3149 36.0829 L 33.8729 36.9669 L 33.4309 36.9669 L 33.4309 37.4088 L 32.9890 37.4088 L 32.5470 38.2928 L 32.1050 38.2928 L 32.1050 38.7348 L 31.2210 39.1768 L 31.2210 39.6188 L 30.3370 39.6188 L 29.8950 40.5028 L 29.0110 40.5028 L 28.5691 41.3867 L 26.8011 41.8287 L 26.8011 42.2707 L 25.4751 42.2707 L 25.4751 42.7127 L 24.1492 42.7127 L 24.1492 43.1547 L 22.8232 43.1547 L 22.8232 43.5967 L 19.2873 43.5967 L 19.2873 44.0387 L 16.1934 44.0387 L 16.1934 43.5967 L 13.5414 43.5967 L 13.5414 43.1547 L 12.2155 43.1547 L 12.2155 42.7127 L 10.4475 42.7127 L 10.4475 42.2707 L 9.5635 42.2707 L 9.5635 41.8287 L 8.6796 41.8287 L 8.6796 41.3867 L 7.3536 41.3867 L 6.9116 40.5028 L 6.0276 40.5028 L 5.5856 39.6188 L 5.1436 39.6188 L 5.1436 39.1768 L 4.2597 38.7348 L 3.8177 37.8508 L 3.3757 37.8508 L 3.3757 37.4088 L 2.9337 37.4088 L 2.9337 36.9669 L 2.4917 36.9669 L 2.4917 36.0829 L 1.6077 35.6409 L 1.6077 34.7569 L 0.7238 34.3149 L 0.7238 33.8729 L 0.2818 33.8729 Z',
    'tachometer': 'M 0.0000 29.7293 L 0.2486 29.7293 L 0.2486 27.0773 L 0.6906 27.0773 L 0.6906 25.3094 L 1.1326 25.3094 L 1.1326 23.9834 L 1.5746 23.9834 L 1.5746 22.6575 L 2.0166 22.6575 L 2.4586 20.8895 L 2.9006 20.8895 L 2.9006 20.0055 L 3.3425 20.0055 L 3.3425 19.1215 L 3.7845 19.1215 L 3.7845 18.2376 L 4.2265 18.2376 L 4.2265 17.3536 L 5.1105 16.9116 L 5.1105 16.0276 L 5.9945 15.5856 L 5.9945 14.7017 L 6.4365 14.7017 L 6.8785 13.8177 L 7.7624 13.3757 L 7.7624 12.4917 L 8.6464 12.0497 L 8.6464 11.6077 L 9.0884 11.6077 L 9.5304 10.7238 L 9.9724 10.7238 L 9.9724 10.2818 L 10.8564 9.8398 L 10.8564 9.3978 L 11.2983 9.3978 L 11.7403 8.5138 L 12.6243 8.5138 L 12.6243 8.0718 L 13.5083 7.6298 L 13.5083 7.1878 L 13.9503 7.1878 L 13.9503 6.7459 L 14.8343 6.7459 L 15.2762 5.8619 L 16.1602 5.8619 L 16.6022 4.9779 L 17.4862 4.9779 L 17.4862 4.5359 L 18.3702 4.5359 L 18.3702 4.0939 L 19.2541 4.0939 L 19.2541 3.6519 L 20.1381 3.6519 L 20.1381 3.2099 L 21.0221 3.2099 L 21.0221 2.7680 L 22.3481 2.7680 L 22.3481 2.3260 L 23.2320 2.3260 L 23.2320 1.8840 L 24.5580 1.8840 L 24.5580 1.4420 L 25.8840 1.4420 L 25.8840 1.0000 L 28.0939 1.0000 L 28.0939 0.5580 L 29.8619 0.5580 L 29.8619 0.1160 L 40.9116 0.1160 L 40.9116 0.5580 L 43.1215 0.5580 L 43.1215 1.0000 L 44.8895 1.0000 L 44.8895 1.4420 L 46.6575 1.4420 L 46.6575 1.8840 L 48.4254 2.3260 L 48.4254 2.7680 L 49.7514 2.7680 L 49.7514 3.2099 L 51.5193 3.6519 L 51.5193 4.0939 L 53.2873 4.5359 L 53.7293 5.4199 L 54.6133 5.4199 L 55.0552 6.3039 L 55.9392 6.3039 L 56.3812 7.1878 L 56.8232 7.1878 L 56.8232 7.6298 L 57.2652 7.6298 L 57.2652 8.0718 L 58.1492 8.0718 L 58.1492 8.5138 L 58.5912 8.5138 L 59.0331 9.3978 L 59.4751 9.3978 L 59.4751 9.8398 L 59.9171 9.8398 L 59.9171 10.2818 L 60.3591 10.2818 L 60.3591 10.7238 L 61.2431 11.1657 L 61.2431 11.6077 L 61.6851 11.6077 L 61.6851 12.4917 L 62.1271 12.4917 L 62.5691 13.3757 L 63.0110 13.3757 L 63.0110 14.2597 L 63.8950 14.7017 L 63.8950 15.1436 L 64.3370 15.1436 L 64.3370 16.0276 L 65.2210 16.4696 L 65.6630 18.2376 L 66.1050 18.2376 L 66.1050 19.1215 L 66.5470 19.1215 L 66.5470 20.0055 L 66.9890 20.0055 L 66.9890 21.3315 L 67.4309 21.3315 L 67.4309 22.6575 L 67.8729 22.6575 L 67.8729 23.9834 L 68.3149 23.9834 L 68.3149 25.3094 L 68.7569 25.3094 L 68.7569 27.5193 L 69.1989 27.5193 L 69.1989 31.4972 L 69.6409 31.4972 L 69.6409 35.0331 L 69.1989 35.0331 L 69.1989 39.0110 L 68.7569 39.0110 L 68.7569 41.6630 L 68.3149 41.6630 L 68.3149 42.9890 L 67.8729 42.9890 L 67.8729 43.8729 L 67.4309 43.8729 L 67.4309 45.6409 L 66.9890 45.6409 L 66.5470 47.4088 L 66.1050 47.4088 L 66.1050 48.2928 L 65.6630 48.2928 L 65.6630 49.1768 L 65.2210 49.1768 L 65.2210 50.0608 L 64.7790 50.0608 L 64.7790 50.9448 L 63.8950 51.3867 L 63.8950 52.2707 L 63.0110 52.7127 L 63.0110 53.5967 L 62.5691 53.5967 L 62.1271 54.4807 L 61.6851 54.4807 L 61.6851 54.9227 L 61.2431 54.9227 L 61.2431 55.8066 L 60.3591 56.2486 L 60.3591 56.6906 L 59.9171 56.6906 L 59.9171 57.1326 L 59.4751 57.1326 L 59.0331 58.0166 L 58.5912 58.0166 L 58.5912 58.4586 L 58.1492 58.4586 L 57.7072 59.3425 L 57.2652 59.3425 L 57.2652 59.7845 L 56.3812 59.7845 L 55.9392 60.6685 L 55.4972 60.6685 L 55.4972 61.1105 L 54.6133 60.6685 L 54.6133 61.5525 L 54.1713 61.5525 L 54.1713 61.9945 L 53.2873 61.5525 L 53.2873 62.4365 L 52.8453 62.4365 L 52.8453 62.8785 L 51.9613 62.4365 L 52.4033 63.3204 L 51.5193 63.3204 L 51.5193 63.7624 L 50.6354 63.7624 L 50.6354 64.2044 L 49.7514 64.2044 L 49.7514 64.6464 L 48.4254 64.6464 L 48.4254 64.2044 L 47.9834 64.2044 L 48.4254 65.0884 L 47.5414 65.0884 L 47.5414 65.5304 L 46.2155 65.5304 L 46.2155 65.0884 L 45.7735 65.0884 L 46.2155 65.9724 L 45.3315 65.9724 L 45.3315 66.4144 L 41.7956 66.8564 L 41.7956 67.2983 L 39.1436 67.2983 L 39.1436 67.7403 L 29.4199 67.7403 L 29.4199 67.2983 L 26.3260 67.2983 L 26.3260 66.8564 L 24.5580 66.8564 L 24.5580 66.4144 L 23.2320 66.4144 L 23.2320 65.9724 L 21.9061 65.9724 L 21.9061 65.5304 L 21.0221 65.5304 L 21.0221 65.0884 L 19.6961 65.0884 L 19.6961 64.6464 L 18.8122 64.6464 L 18.8122 64.2044 L 18.3702 64.2044 L 18.3702 63.7624 L 16.6022 63.3204 L 16.6022 62.8785 L 15.7182 62.8785 L 15.7182 62.4365 L 14.8343 62.4365 L 14.3923 61.5525 L 13.9503 61.5525 L 13.9503 61.1105 L 13.5083 61.1105 L 13.5083 60.6685 L 12.6243 60.6685 L 12.6243 60.2265 L 11.7403 59.7845 L 11.2983 58.9006 L 10.4144 58.9006 L 10.4144 58.0166 L 9.5304 58.0166 L 9.5304 57.1326 L 8.6464 57.1326 L 8.6464 56.2486 L 8.2044 56.2486 L 8.2044 55.8066 L 7.3204 55.3646 L 7.3204 54.9227 L 6.8785 54.9227 L 6.8785 54.0387 L 6.4365 54.0387 L 5.9945 53.1547 L 5.5525 53.1547 L 5.5525 52.2707 L 4.6685 51.8287 L 4.6685 50.9448 L 3.7845 50.5028 L 3.7845 49.6188 L 3.3425 49.6188 L 3.3425 48.7348 L 2.9006 48.7348 L 2.9006 47.8508 L 2.4586 47.8508 L 2.4586 46.5249 L 2.0166 46.5249 L 2.0166 45.6409 L 1.5746 45.6409 L 1.5746 43.8729 L 2.0166 43.8729 L 2.0166 43.4309 L 1.1326 43.8729 L 1.1326 42.9890 L 0.6906 42.9890 L 0.6906 41.2210 L 0.2486 41.2210 L 0.2486 38.1271 L 0.0000 38.1271 Z',
    'speedometer': 'M 0.2486 29.6133 L 0.6906 29.6133 L 0.6906 26.9613 L 1.1326 26.9613 L 1.1326 25.6354 L 1.5746 25.6354 L 1.5746 23.8674 L 2.0166 23.8674 L 2.0166 22.9834 L 2.4586 22.9834 L 2.4586 21.6575 L 2.9006 21.6575 L 3.3425 19.8895 L 3.7845 19.8895 L 3.7845 19.0055 L 4.2265 19.0055 L 4.2265 18.1215 L 4.6685 18.1215 L 4.6685 17.2376 L 5.1105 17.2376 L 5.1105 16.3536 L 5.5525 16.3536 L 5.9945 15.4696 L 6.4365 15.4696 L 6.4365 14.5856 L 7.3204 14.1436 L 7.3204 13.7017 L 7.7624 13.7017 L 7.7624 12.8177 L 8.2044 12.8177 L 8.6464 11.9337 L 9.0884 11.9337 L 9.0884 11.4917 L 9.5304 11.4917 L 9.5304 11.0497 L 9.9724 11.0497 L 9.9724 10.6077 L 10.4144 10.6077 L 10.8564 9.7238 L 11.2983 9.7238 L 11.2983 9.2818 L 11.7403 9.2818 L 11.7403 8.8398 L 12.1823 8.8398 L 12.6243 7.9558 L 13.5083 7.9558 L 13.9503 7.0718 L 14.3923 7.0718 L 14.3923 6.6298 L 15.2762 6.6298 L 15.7182 5.7459 L 16.6022 5.7459 L 17.0442 4.8619 L 18.8122 4.4199 L 18.8122 3.9779 L 19.6961 3.9779 L 19.6961 3.5359 L 21.4641 3.0939 L 21.4641 2.6519 L 22.3481 2.6519 L 22.3481 2.2099 L 23.2320 2.2099 L 23.2320 1.7680 L 25.8840 1.3260 L 25.8840 0.8840 L 30.3039 0.4420 L 30.3039 0.0000 L 42.2376 0.0000 L 42.2376 0.4420 L 44.4475 0.4420 L 44.4475 0.8840 L 46.2155 0.8840 L 46.2155 1.3260 L 47.5414 1.3260 L 47.5414 1.7680 L 48.4254 1.7680 L 48.4254 2.2099 L 49.7514 2.2099 L 49.7514 2.6519 L 50.6354 2.6519 L 50.6354 3.0939 L 52.4033 3.5359 L 52.4033 3.9779 L 53.2873 3.9779 L 53.2873 4.4199 L 54.1713 4.4199 L 54.6133 5.3039 L 55.4972 5.3039 L 55.9392 6.1878 L 56.8232 6.1878 L 56.8232 6.6298 L 57.7072 7.0718 L 57.7072 7.5138 L 58.1492 7.5138 L 58.1492 7.9558 L 59.0331 7.9558 L 59.4751 8.8398 L 59.9171 8.8398 L 59.9171 9.2818 L 60.3591 9.2818 L 60.8011 10.1657 L 61.2431 10.1657 L 61.6851 11.0497 L 62.1271 11.0497 L 62.1271 11.9337 L 62.5691 11.9337 L 63.0110 12.8177 L 63.4530 12.8177 L 63.4530 13.2597 L 63.8950 13.2597 L 63.8950 14.1436 L 64.7790 14.5856 L 64.7790 15.0276 L 65.2210 15.0276 L 65.2210 15.9116 L 65.6630 15.9116 L 65.6630 16.7956 L 66.1050 16.7956 L 66.1050 17.6796 L 66.5470 17.6796 L 66.5470 18.5635 L 66.9890 18.5635 L 66.9890 19.4475 L 67.4309 19.4475 L 67.8729 21.2155 L 68.3149 21.2155 L 68.7569 23.8674 L 69.1989 23.8674 L 69.1989 25.6354 L 69.6409 25.6354 L 69.6409 27.8453 L 70.0829 27.8453 L 70.0829 38.0110 L 69.6409 38.0110 L 69.6409 40.2210 L 69.1989 40.2210 L 69.1989 41.9890 L 68.7569 41.9890 L 68.7569 43.7569 L 68.3149 43.7569 L 68.3149 45.0829 L 67.8729 45.0829 L 67.8729 45.9669 L 67.4309 45.9669 L 67.4309 47.2928 L 66.9890 47.2928 L 66.9890 48.1768 L 66.5470 48.1768 L 66.1050 49.9448 L 65.2210 50.3867 L 64.7790 52.1547 L 64.3370 52.1547 L 63.8950 53.0387 L 63.4530 53.0387 L 63.4530 53.9227 L 63.0110 53.9227 L 62.5691 54.8066 L 62.1271 54.8066 L 62.1271 55.6906 L 61.6851 55.6906 L 61.6851 56.1326 L 60.8011 56.5746 L 60.8011 57.0166 L 60.3591 57.0166 L 60.3591 57.4586 L 59.9171 57.4586 L 59.9171 57.9006 L 59.4751 57.9006 L 59.4751 58.3425 L 58.5912 58.7845 L 58.5912 59.2265 L 57.7072 59.2265 L 57.7072 59.6685 L 56.8232 60.1105 L 56.8232 60.5525 L 56.3812 60.5525 L 56.3812 60.9945 L 55.4972 60.9945 L 55.0552 61.8785 L 54.1713 61.8785 L 53.7293 62.7624 L 52.8453 62.7624 L 52.8453 63.2044 L 51.9613 63.2044 L 51.9613 63.6464 L 51.0773 63.6464 L 51.0773 63.2044 L 50.6354 63.2044 L 51.0773 64.0884 L 49.3094 64.5304 L 49.3094 64.9724 L 48.4254 64.9724 L 48.4254 65.4144 L 45.7735 65.8564 L 45.7735 66.2983 L 44.4475 66.2983 L 44.4475 66.7403 L 42.6796 66.7403 L 42.6796 67.1823 L 40.0276 67.1823 L 40.0276 67.6243 L 29.8619 67.6243 L 29.8619 67.1823 L 27.6519 67.1823 L 27.6519 66.7403 L 25.8840 66.7403 L 25.8840 66.2983 L 24.5580 66.2983 L 24.5580 65.8564 L 21.9061 65.4144 L 21.9061 64.9724 L 21.0221 64.9724 L 21.0221 64.5304 L 19.6961 64.5304 L 19.6961 64.0884 L 18.8122 64.0884 L 18.8122 63.6464 L 17.9282 63.6464 L 17.4862 62.7624 L 16.6022 62.7624 L 16.1602 61.8785 L 15.7182 61.8785 L 15.7182 61.4365 L 14.8343 61.4365 L 14.3923 60.5525 L 13.5083 60.5525 L 13.0663 59.6685 L 12.6243 59.6685 L 12.6243 59.2265 L 11.7403 59.2265 L 11.2983 58.3425 L 10.8564 58.3425 L 10.8564 57.9006 L 10.4144 57.9006 L 10.4144 57.4586 L 9.9724 57.4586 L 9.9724 57.0166 L 9.5304 57.0166 L 9.0884 56.1326 L 8.6464 56.1326 L 8.6464 55.2486 L 8.2044 55.2486 L 8.2044 54.8066 L 7.3204 54.3646 L 7.3204 53.9227 L 6.8785 53.9227 L 6.8785 53.0387 L 5.9945 52.5967 L 5.9945 51.7127 L 5.5525 51.7127 L 5.5525 51.2707 L 5.1105 51.2707 L 5.1105 50.3867 L 4.2265 49.9448 L 3.7845 48.1768 L 3.3425 48.1768 L 3.3425 47.2928 L 2.9006 47.2928 L 2.9006 45.9669 L 2.4586 45.9669 L 2.4586 45.0829 L 2.0166 45.0829 L 2.0166 43.7569 L 1.5746 43.7569 L 1.5746 41.5470 L 1.1326 41.5470 L 1.1326 39.7790 L 0.6906 39.7790 L 0.6906 37.5691 L 0.2486 37.5691 Z',
    'right_gauge': 'M 0.1547 23.8232 L 0.5967 23.8232 L 0.5967 21.6133 L 1.0387 21.6133 L 1.0387 19.8453 L 1.4807 19.8453 L 1.4807 18.5193 L 1.9227 18.5193 L 1.9227 17.1934 L 2.3646 17.1934 L 2.8066 15.4254 L 3.6906 14.9834 L 3.6906 14.0994 L 4.5746 13.6575 L 4.5746 12.7735 L 5.4586 12.3315 L 5.4586 11.4475 L 5.9006 11.4475 L 6.3425 10.5635 L 6.7845 10.5635 L 7.2265 9.6796 L 8.1105 9.2376 L 8.1105 8.7956 L 8.9945 8.7956 L 9.4365 7.9116 L 10.3204 7.9116 L 10.7624 7.0276 L 11.6464 7.0276 L 11.6464 6.5856 L 13.4144 6.1436 L 13.4144 5.7017 L 14.7403 5.7017 L 14.7403 5.2597 L 16.0663 5.2597 L 16.0663 4.8177 L 16.5083 4.8177 L 16.5083 5.2597 L 17.3923 5.7017 L 17.3923 6.1436 L 18.2762 6.5856 L 18.2762 7.0276 L 18.7182 7.0276 L 18.7182 7.4696 L 19.6022 7.4696 L 19.6022 7.9116 L 20.0442 7.9116 L 20.0442 8.3536 L 20.9282 8.7956 L 20.9282 9.2376 L 21.3702 9.2376 L 21.3702 9.6796 L 21.8122 9.6796 L 21.8122 10.1215 L 22.2541 10.1215 L 22.6961 11.0055 L 23.1381 11.0055 L 23.1381 11.4475 L 23.5801 11.4475 L 23.5801 11.8895 L 24.0221 11.8895 L 24.0221 12.3315 L 24.4641 12.3315 L 24.9061 13.2155 L 25.3481 13.2155 L 25.3481 13.6575 L 25.7901 13.6575 L 25.7901 14.0994 L 26.2320 14.0994 L 26.2320 14.5414 L 26.6740 14.5414 L 27.1160 15.4254 L 27.5580 15.4254 L 27.5580 15.8674 L 28.4420 16.3094 L 28.4420 16.7514 L 28.8840 16.7514 L 29.3260 17.6354 L 29.7680 17.6354 L 29.7680 18.0773 L 30.2099 18.0773 L 30.2099 18.9613 L 30.6519 18.9613 L 30.6519 19.4033 L 31.5359 19.8453 L 31.5359 20.2873 L 31.9779 20.2873 L 31.9779 20.7293 L 32.4199 20.7293 L 32.4199 21.1713 L 32.8619 21.1713 L 32.8619 21.6133 L 33.3039 21.6133 L 33.3039 22.4972 L 34.1878 22.9392 L 34.1878 23.3812 L 34.6298 23.3812 L 34.6298 24.2652 L 35.5138 24.7072 L 35.5138 25.1492 L 36.3978 25.5912 L 36.3978 26.0331 L 36.8398 26.0331 L 36.8398 26.4751 L 37.2818 26.4751 L 37.2818 27.3591 L 38.1657 27.8011 L 38.1657 28.6851 L 39.0497 29.1271 L 39.0497 30.0110 L 39.4917 30.0110 L 39.4917 30.4530 L 40.3757 30.8950 L 40.3757 31.3370 L 40.8177 31.3370 L 40.8177 32.2210 L 41.2597 32.2210 L 41.2597 32.6630 L 41.7017 32.6630 L 41.7017 34.4309 L 41.2597 34.4309 L 41.2597 35.3149 L 40.8177 35.3149 L 40.8177 36.1989 L 40.3757 36.1989 L 40.3757 37.0829 L 39.4917 37.5249 L 39.4917 37.9669 L 39.0497 37.9669 L 38.6077 39.7348 L 38.1657 39.7348 L 37.7238 40.6188 L 37.2818 40.6188 L 37.2818 41.0608 L 36.8398 41.0608 L 36.8398 41.5028 L 35.9558 41.5028 L 35.9558 41.9448 L 35.0718 42.3867 L 35.0718 42.8287 L 34.6298 42.8287 L 34.6298 43.2707 L 34.1878 43.2707 L 34.1878 43.7127 L 33.3039 43.7127 L 33.3039 44.1547 L 32.4199 44.1547 L 32.4199 44.5967 L 31.5359 44.5967 L 31.5359 45.0387 L 30.6519 45.0387 L 30.6519 45.4807 L 29.7680 45.4807 L 29.7680 45.9227 L 28.4420 45.9227 L 28.4420 46.3646 L 26.2320 46.3646 L 26.2320 46.8066 L 25.3481 46.8066 L 25.3481 47.2486 L 19.1602 47.2486 L 19.1602 46.8066 L 17.8343 46.8066 L 17.8343 46.3646 L 15.1823 46.3646 L 15.1823 45.9227 L 14.2983 45.9227 L 14.2983 45.4807 L 12.9724 45.4807 L 12.9724 45.0387 L 11.2044 44.5967 L 10.7624 43.7127 L 9.8785 43.7127 L 9.8785 43.2707 L 9.4365 43.2707 L 8.9945 42.3867 L 8.1105 42.3867 L 7.6685 41.5028 L 6.7845 41.5028 L 6.3425 40.6188 L 5.9006 40.6188 L 5.9006 40.1768 L 5.4586 40.1768 L 5.4586 39.2928 L 4.5746 38.8508 L 4.5746 37.9669 L 3.6906 37.5249 L 3.6906 36.6409 L 2.8066 36.1989 L 2.3646 34.4309 L 1.9227 34.4309 L 1.9227 33.1050 L 1.4807 33.1050 L 1.4807 31.7790 L 1.0387 31.7790 L 1.0387 30.0110 L 1.4807 30.0110 L 1.4807 29.1271 L 1.0387 29.1271 L 1.0387 30.0110 L 0.5967 30.0110 L 0.5967 27.8011 L 0.1547 27.8011 Z',
}
WHEEL_PIVOT = (162.0, 127.0)
WHEEL_PIVOT_GLOBAL = (206.0, 475.0)
WHEEL_SOURCE_CANVAS = (330, 240)

# The outline follows measured original neutral bright-material anchors. It is
# an artistic high-resolution completion below the original y132 crop, not a
# claimed native CAD shape. Four holes plus the badge make five round elements.
SPOKE_OUTLINE = (
    "M 14 105 C 38 91 58 85 76 82 C 104 79 128 68 154 65 "
    "C 172 62 191 65 213 75 C 242 83 284 92 319 104 "
    "L 314 132 C 275 146 222 152 188 149 L 184 196 L 140 196 "
    "L 135 147 C 92 146 45 139 18 130 Z"
)
# Small-hole bounds are literal neutral native black-component bounds. Larger
# holes extend below the native crop: their completed ellipse is artwork.
SPOKE_HOLES = ((55.5, 117.0, 12.5, 11.0), (102.5, 120.0, 20.5, 22.0),
               (229.0, 120.0, 23.0, 22.0), (275.0, 117.0, 15.0, 11.0))


def _ellipse_path(cx, cy, rx, ry):
    return (f"M {cx-rx:g} {cy:g} A {rx:g} {ry:g} 0 1 0 {cx+rx:g} {cy:g} "
            f"A {rx:g} {ry:g} 0 1 0 {cx-rx:g} {cy:g} Z")


SPOKE_CLIP = "F0 " + SPOKE_OUTLINE + " " + " ".join(
    _ellipse_path(*hole) for hole in SPOKE_HOLES)


def _gradient(stops, *, start=(0, 0), end=(0, 1)):
    return {"kind": "linear_gradient", "start": list(start), "end": list(end),
            "stops": [[offset, color] for offset, color in stops]}


def _material(source, rect, *, rotation=0, pivot=(0, 0), clip=None):
    command = {"kind": "image", "source": source, "rect": list(rect),
               "rotation_degrees": rotation, "rotation_center": list(pivot)}
    if clip is not None:
        command["clip_path"] = clip
    return command


def _path(d, fill, stroke=None, width=0):
    return {"kind": "path", "d": d, "fill": fill,
            "stroke": stroke, "stroke_width": width}


def _ellipse(rect, fill, stroke=None, width=0):
    return {"kind": "ellipse", "rect": list(rect), "fill": fill,
            "stroke": stroke, "stroke_width": width}


def _rotate_command(command, angle):
    return dict(command, rotation_degrees=angle, rotation_center=list(WHEEL_PIVOT))


def spoke_commands(angle, mode="vector"):
    """Editable native-anchored material geometry, or clipped generated art.

    The complete source canvas extends below y132; rotating a previously
    clipped 330x132 picture would leave missing pixels at steering extremes.
    """
    if (type(angle) not in (int, float) or not math.isfinite(angle)
            or not -45 <= angle <= 45 or mode not in ("vector", "material")):
        raise ValueError("Ongeldig materiaalstuurcontract.")
    if mode == "material":
        return [_material("neutral_spokes", (0, 0, *WHEEL_SOURCE_CANVAS),
                          rotation=angle, pivot=WHEEL_PIVOT, clip=SPOKE_CLIP)]
    metal = _gradient(((0, "#FF777D80"), (.15, "#FFD0D2D0"), (.28, "#FF939A9D"),
                      (.53, "#FF52585B"), (.71, "#FFA3A8A9"), (1, "#FF343A3E")))
    commands = [
        _path(SPOKE_CLIP, metal, "#FF252B2E", 1.4),
        _path("M 17 105 C 68 83 110 81 154 67 C 176 63 192 67 214 77 "
              "C 249 86 285 94 317 104", "#00000000", "#FFE0E1DD", .8),
        _path("M 21 129 C 85 147 118 144 137 145 M 188 147 C 237 150 285 141 311 131",
              "#00000000", "#FF191F22", 1.2),
        _ellipse((130, 95, 64, 64), _gradient(((0, "#FF909694"), (.22, "#FFD2D2CB"),
                                           (.6, "#FF8D9594"), (1, "#FF525A5C"))),
                 "#FF3A4143", 1),
        _ellipse((135, 100, 54, 54), _gradient(((0, "#FF505657"), (.4, "#FF252C2F"),
                                             (1, "#FF101619"))), "#FFB2B8B5", .7),
        {"kind": "text", "text": "A2", "rect": [140, 107, 44, 31],
         "font_family": "Arial", "font_size": 17, "font_weight": "Bold",
         "fill": "#FFD0D3CE", "align": "center"},
    ]
    # All components, including badge and hole boundaries, rotate together.
    return [_rotate_command(command, angle) for command in commands]


def _gauge_scene(role, frame, variant="v1"):
    group = COCKPIT_BY_NAME[role]
    x, y, w, h = group.logical_rect
    previous = deepcopy(original.frame_scene(role, frame))
    # Original commands 0..5 are a flat-red rectangle plus five replacement
    # rim ellipses. They are deliberately omitted, preserving the material.
    commands = [_material("accepted_dashboard", (-x, -y, 640, 480))]
    face = previous["commands"][6:]
    if len(face) < 3 or face[0]["kind"] != "ellipse" or face[1]["kind"] != "ellipse":
        raise ValueError("Historisch metercommandcontract is veranderd.")
    face[0]["fill"] = _gradient(((0, "#FF4A5052"), (.3, "#FF161C1F"),
                                  (.75, "#FF343B3E"), (1, "#FF101619")))
    face[0]["stroke"] = "#FF080C0E"
    face[0]["stroke_width"] = .8
    face[1]["fill"] = _gradient(((0, "#FF1B2125"), (.25, "#FF11161B"),
                                  (.7, "#FF080D10"), (1, "#FF11171B")))
    face[1]["stroke"] = "#FF757F82"
    face[1]["stroke_width"] = .45
    # Keep original-style tick colors and native frame-derived needles. The
    # geometrical labels are still an artistic readable reconstruction.
    commands.extend(dict(c, clip_ref=role) if variant == "v2" else c
                    for c in face)
    return {"size": [w, h], "commands": commands, "transparent_rects": []}


def frame_scene(role, frame, *, spokes_mode="vector", variant="v1"):
    if (type(role) is not str or role not in COCKPIT_BY_NAME or type(frame) is not int
            or not 0 <= frame < len(COCKPIT_BY_NAME[role].resource_indices)
            or spokes_mode not in ("vector", "material") or type(variant) is not str
            or variant not in VARIANTS):
        raise ValueError("Ongeldige verfijnde cockpitframekeuze.")
    group = COCKPIT_BY_NAME[role]
    x, y, w, h = group.logical_rect
    if role == "dashboard_strip":
        return {"size": [w, h],
                "commands": [_material("accepted_dashboard", (-x, -y, 640, 480))],
                "coverage_mask": {"source": "native_dashboard", "logical_rect": [x, y, w, h]},
                "transparent_rects": []}
    if role == "steering_wheel":
        return {"size": [w, h],
                "commands": [_material("clean_plate", (-x, -y, 640, 480)),
                             *spoke_commands(original.WHEEL_ANGLES[frame], spokes_mode)],
                "transparent_rects": [[45, 0, 40, 26], [89, 41, 157, 18]]}
    return _gauge_scene(role, frame, variant)


def fixed_scene(patch):
    """Static left face based on the pinned top-PCX/lower-wheel82 composite.

    The two native gray features do not form one straight needle. Preserve
    them as separate fixed shapes; do not invent a telemetry value or pivot.
    """
    if patch not in (*FIXED_PATCHES, *FIXED_PATCHES_V2):
        raise ValueError("Onbekende vaste verfijnde cockpitpatch.")
    x, y, w, h = patch.logical_rect
    commands = [_material("accepted_dashboard", (-x, -y, 640, 480))]
    face = [_ellipse((2, 5, 36, 36), _gradient(((0, "#FF434B4E"), (.25, "#FF141B1F"),
                                              (.7, "#FF394246"), (1, "#FF151D21"))),
                     "#FF090E11", .7),
            _ellipse((3.2, 6.2, 33.6, 33.6), _gradient(((0, "#FF1A2227"), (.3, "#FF0D1418"),
                                                       (1, "#FF111A20"))), "#FF768083", .4)]
    for i in range(18):
        angle = 151 + i * 10
        color = "#FF367742" if angle < 280 else "#FFAA7435"
        a = math.radians(angle)
        x1, y1 = 20 + math.cos(a) * 13.1, 23 + math.sin(a) * 13.1
        x2, y2 = 20 + math.cos(a) * 15.8, 23 + math.sin(a) * 15.8
        face.append(_path(f"M {x1:.4f} {y1:.4f} L {x2:.4f} {y2:.4f}",
                          "#00000000", color, 1.35))
    # Fixed native upper-line and lower-stem/bulb are deliberately separate.
    face.extend((_path("M 25.5 15 L 22.5 18", "#00000000", "#FF9DA7AA", 1.0),
                 _path("M 17.5 19 L 17.5 22.5", "#00000000", "#FFE1E5E4", 1.6),
                 _ellipse((15.6, 22.1, 4.2, 4.2), "#FFC6CDCE", "#FF69757A", .4),
                 _ellipse((23.6, 35.7, 5.0, 5.0), "#FF501E18", "#FF6B3930", .35),
                 _ellipse((24.7, 36.8, 2.8, 2.8), "#FFE12C20")))
    commands.extend(dict(c, clip_ref="left_gauge") if patch in FIXED_PATCHES_V2
                    else dict(c, clip_path=LEFT_FACE_CLIP) for c in face)
    return {"size": [w, h], "commands": commands, "transparent_rects": [],
            "static_composite_sha256": LEFT_COMPOSITE_SHA256,
            "telemetry_angle": None}


def export_plan(*, spokes_mode="vector", variant="v1"):
    if (spokes_mode not in ("vector", "material") or type(variant) is not str
            or variant not in VARIANTS):
        raise ValueError("Onbekende materiaalstuurvariant.")
    atlases = ATLASES if variant == "v1" else ATLASES_V2
    patches = FIXED_PATCHES if variant == "v1" else FIXED_PATCHES_V2
    assets = [{"name": p.name, "cached_role": None, "fixed_rect": list(p.logical_rect),
               "scale": p.scale, "logical_size": list(p.logical_size),
               "texture_size": list(p.texture_size), "active_size": list(p.active_size),
               "bytes": p.byte_count,
               "frames": [{"animation_frame": None, "pixel_rect": [0, 0, *p.active_size],
                           "scene": fixed_scene(p)}]} for p in patches]
    for atlas in atlases:
        assets.append({"name": atlas.name, "cached_role": atlas.cached_role,
                       "scale": atlas.scale, "logical_size": list(atlas.logical_size),
                       "texture_size": list(atlas.texture_size), "active_size": list(atlas.active_size),
                       "animation_group": atlas.animation_group, "callers": list(atlas.callers),
                       "bytes": atlas.byte_count,
                       "frames": [{"animation_frame": f.animation_frame, "pixel_rect": list(f.pixel_rect),
                                   "scene": frame_scene(atlas.cached_role, f.animation_frame,
                                                        spokes_mode=spokes_mode, variant=variant)} for f in atlas.frames]})
    plan = {"schema": SCHEMA, "source_binary_sha256": SOURCE_SHA256,
            "asset_root": ASSET_ROOT if variant == "v1" else ASSET_ROOT_V2,
            "command_coordinates": "logical",
            "color_format": "#AARRGGBB", "game_executed": False,
            "spokes_mode": spokes_mode,
            "source_slots": [{"name": name, "path": path, "logical_size": list(size)}
                             for name, path, size in SOURCE_SLOTS],
            "material_contract": {"accepted_dashboard_sha256": ACCEPTED_DASHBOARD_SHA256,
                                  "clean_plate_allowed_edit_rect": [44, 348, 330, 132],
                                  "dashboard_pcx_zero_index_is_transparent": True,
                                  "spoke_canvas": list(WHEEL_SOURCE_CANVAS),
                                  "spoke_pivot": list(WHEEL_PIVOT),
                                  "unchanged_existing_fixed_dashboard": True},
            "assets": assets}
    if variant == "v2":
        plan["meter_clips"] = dict(METER_FACE_CLIPS)
        plan["meter_layering"] = {
            "source_sha256": ACCEPTED_DASHBOARD_SHA256,
            "source_size": [1448, 1086], "black_component_threshold_max_rgb": 8,
            "external_contour_only": True, "max_simplification_error_logical": .22,
            "generic_clip_applies_to_every_face_command": True,
            "native_order_unchanged": True, "new_face_only_clipped": True,
            "runtime_verified": False,
        }
    return plan


def encode_atlas(atlas, rgba_frames):
    """Use the unchanged historical pure pixel/crop encoder, with new names."""
    if atlas not in (*ATLASES, *ATLASES_V2):
        raise ValueError("Onbekende verfijnde materiaalatlas.")
    index = (ATLASES if atlas in ATLASES else ATLASES_V2).index(atlas)
    return original.encode_atlas(original.ATLASES[index], rgba_frames)


def encode_fixed(patch, rgba):
    """Pack only the declared static crop; opaque key collisions stay visible."""
    if patch not in (*FIXED_PATCHES, *FIXED_PATCHES_V2):
        raise ValueError("Onbekende vaste materiaalpatch.")
    w, h = patch.active_size
    tw, th = patch.texture_size
    if type(rgba) is not bytes or len(rgba) != w * h * 4:
        raise ValueError("Vaste materiaalpatch vereist exacte RGBA-bytes.")
    key = original.COLOR_KEY_RGB565
    result = bytearray(struct.pack("<H", key) * (tw * th))
    for row in range(h):
        for col in range(w):
            r, g, b, alpha = rgba[(row * w + col) * 4:(row * w + col) * 4 + 4]
            if alpha not in (0, 255):
                raise ValueError("Vaste materiaalpatch moet alfa0/255 gebruiken.")
            if alpha:
                value = (r >> 3) << 11 | (g >> 2) << 5 | b >> 3
                if value == key:
                    value ^= 1
                struct.pack_into("<H", result, (row * tw + col) * 2, value)
    return bytes(result)


original.validate_atlases(ATLASES)
