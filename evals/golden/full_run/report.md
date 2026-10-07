# Golden-set comparison (full_run)

Predictions: `gpt-6-luna|effort=none|enrich_v1@60e05ad9d03f|schema-v1` · human labels: {'human_confirmed': 43, 'human_edited': 7}

| metric | value |
|---|---|
| topic agreement (strict / with human alternatives) | 86% / 96% |
| intent agreement (strict / with alternatives) | 92% / 100% |
| severity exact / with alternatives / MAE | 82% / 88% / 0.3 |
| sentiment within ±0.5 / MAE | 86% / 0.146 |
| quote exact substring | 100% |
| needs_review precision / recall | 0.727 / 0.667 |
| ambiguous cases (human) | 24 |
| valid predictions | 50/50 |

## Topic confusion (rows = human, columns = model)

| human \ model | usability | playback | downloads | catalog | billing | support | other |
|---|---|---|---|---|---|---|---|
| **usability** | 8 | 1 |  |  | 1 |  |  |
| **playback** |  | 4 |  |  |  |  |  |
| **downloads** |  |  | 1 |  |  |  |  |
| **catalog** | 1 |  |  | 4 |  |  | 1 |
| **billing** |  |  |  |  | 3 |  |  |
| **support** |  |  |  |  |  |  | 3 |
| **other** |  |  |  |  |  |  | 23 |

## Disagreements (topic, intent or severity differs)

| # | review (abridged) | human | model | source | human alternatives |
|---|---|---|---|---|---|
| 1 | Staff must be full of mentally ill kool-aid heads. Banning conservativ | catalog/complaint/2 | catalog/complaint/3 | human_confirmed | topic: other; intent: unclear; severity: 3 |
| 5 | I just loved it | support/praise/2 | other/praise/1 | human_edited |  |
| 6 | Hate this application 🤮🤮🤮🤮🤮🤮 | other/complaint/5 | other/complaint/2 | human_edited |  |
| 7 | Excellent | support/praise/2 | other/praise/1 | human_edited |  |
| 9 | Spotify is awesome and and very diverse :) | support/praise/4 | other/praise/1 | human_edited | topic: other |
| 11 | Very good but wen I play my song it o ly plays a little bit then it st | playback/complaint/4 | playback/complaint/3 | human_confirmed | severity: 3 |
| 17 | Lhat ng song nasa spotify | catalog/praise/1 | other/unclear/1 | human_confirmed | topic: other; intent: unclear |
| 20 | Hate This application 👎 | other/complaint/4 | other/complaint/2 | human_edited |  |
| 28 | Unconditional love, Stoli Canales | other/praise/1 | other/unclear/1 | human_confirmed | intent: unclear |
| 31 | I hate this app and sweden .I love islam | other/unclear/2 | other/complaint/2 | human_edited | intent: complaint; severity: 2 |
| 33 | Are you out of your mind? This is dangerous! Listening to music in a n | usability/complaint/3 | playback/complaint/3 | human_confirmed | topic: playback; severity: 2,4 |
| 38 | 1-Lyrics not getting loaded, 2-can't go back to or start song where to | catalog/complaint/3 | usability/complaint/3 | human_confirmed | topic: usability |
| 43 | I gave one star because I can't give any less than that. the new updat | usability/complaint/3 | billing/complaint/3 | human_confirmed | topic: playback,billing; severity: 4 |
| 46 | Worst app ever too much ad | usability/complaint/3 | usability/complaint/2 | human_confirmed | severity: 2 |
| 47 | Too expensive and the free version is pretty much unusable with consta | usability/complaint/3 | usability/cancellation/3 | human_confirmed | topic: billing; intent: cancellation; severity: 2 |
| 48 | This update very bad for everyone.old Spotify. we all want. | usability/complaint/4 | usability/complaint/2 | human_edited | intent: request |
