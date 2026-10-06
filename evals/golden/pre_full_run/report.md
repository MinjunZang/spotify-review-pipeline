# Golden-set comparison (pre_full_run)

Predictions: `gpt-6-luna|effort=none|enrich_v1@60e05ad9d03f|schema-v1` · human labels: {'human_confirmed': 43, 'human_edited': 7}

| metric | value |
|---|---|
| topic agreement (strict / with human alternatives) | 88% / 94% |
| intent agreement (strict / with alternatives) | 96% / 98% |
| severity exact / with alternatives / MAE | 72% / 80% / 0.46 |
| sentiment within ±0.5 / MAE | 90% / 0.13 |
| quote exact substring | 100% |
| needs_review precision / recall | 0.857 / 0.5 |
| ambiguous cases (human) | 24 |
| valid predictions | 50/50 |

## Topic confusion (rows = human, columns = model)

| human \ model | usability | playback | downloads | catalog | billing | support | other |
|---|---|---|---|---|---|---|---|
| **usability** | 8 | 1 |  |  |  |  | 1 |
| **playback** |  | 4 |  |  |  |  |  |
| **downloads** |  |  | 1 |  |  |  |  |
| **catalog** |  |  |  | 6 |  |  |  |
| **billing** | 1 |  |  |  | 2 |  |  |
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
| 10 | Duo Premium .... No ads at all! | usability/praise/1 | other/praise/1 | human_confirmed | topic: billing |
| 11 | Very good but wen I play my song it o ly plays a little bit then it st | playback/complaint/4 | playback/complaint/3 | human_confirmed | severity: 3 |
| 17 | Lhat ng song nasa spotify | catalog/praise/1 | catalog/complaint/3 | human_confirmed | topic: other; intent: unclear |
| 19 | asem, lirik nya kdang gaada kek mana?? | catalog/complaint/3 | catalog/complaint/2 | human_confirmed | severity: 2 |
| 20 | Hate This application 👎 | other/complaint/4 | other/complaint/2 | human_edited |  |
| 24 | Please ye ads ko thoda kumm Karo harr ek song ke baad ad 🙏🙄 | usability/complaint/3 | usability/request/1 | human_confirmed | intent: request; severity: 2 |
| 29 | Deleting this App. The new update suck, we can't choose our fvrt songs | billing/cancellation/3 | usability/cancellation/3 | human_confirmed | topic: usability |
| 31 | I hate this app and sweden .I love islam | other/unclear/2 | other/unclear/1 | human_edited | intent: complaint; severity: 2 |
| 33 | Are you out of your mind? This is dangerous! Listening to music in a n | usability/complaint/3 | playback/complaint/5 | human_confirmed | topic: playback; severity: 2,4 |
| 46 | Worst app ever too much ad | usability/complaint/3 | usability/complaint/2 | human_confirmed | severity: 2 |
| 48 | This update very bad for everyone.old Spotify. we all want. | usability/complaint/4 | usability/complaint/2 | human_edited | intent: request |
