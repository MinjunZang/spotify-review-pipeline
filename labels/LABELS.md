# Shared label definitions — `labels-v1`

These are the course's common labels (GRADING_CONTRACT.md) plus our worked examples and optional
subtopics. The enricher, the verifier and the human golden-set labeler all use this document.
Examples come from the **development** sample (`analysis_10000.csv`, rows after the first 500) —
never from the golden 50. Classify the **text only**; star rating and other metadata are not inputs.

## Topic (exactly one)

| topic | Covers | Subtopics (optional, ours) |
|---|---|---|
| `access` | Login, signup, password, account access, being logged out, lost/hacked account | `login_failure`, `logged_out`, `account_lost_or_hacked`, `signup` |
| `usability` | Navigation, controls, layout, queue/playlist management, ad interruptions, unwanted UI changes | `ads`, `ui_navigation`, `queue_shuffle_controls`, `library_playlist_management`, `ui_change` |
| `playback` | Playback failure, crashes, freezes, lag, connection errors, audio quality, battery/data/storage use, device/Bluetooth/car/cast | `crash_freeze`, `playback_stops_or_skips`, `connection_error`, `audio_quality`, `performance_resources`, `device_integration` |
| `downloads` | Downloading, saved music, offline listening, disappearing downloads | `downloads_missing`, `offline_mode`, `download_fails` |
| `catalog` | Missing songs/artists, search/discovery, recommendations, lyrics availability, podcasts content | `missing_content`, `search`, `recommendations`, `lyrics`, `podcasts` |
| `billing` | Price, charges, refunds, subscriptions, paywalls, premium entitlement; **explicitly premium-only controls** (skip limits, forced shuffle on free, "pay for basic features") | `price`, `premium_paywall`, `charges_refund`, `subscription_entitlement` |
| `support` | Contacting support and the support response | `support_response` |
| `other` | General praise/criticism, unrelated content, no supported specific topic | `general`, `unrelated` |

**Rules**
1. Pick the problem with the **highest supported severity**; on a tie, the **first specific problem mentioned**.
2. Positive review → the **first specific praised feature**; generic praise ("Good", "Love it") → `other`.
3. Mentioning a paid plan alone is not `billing`. A subscription failing to activate *is* billing; music
   crashing for a paying customer is `playback`.
4. "Bad app", "worst app" with no specific defect → `other` (do not invent a defect).

## Intent (precedence order — the first that applies wins)

1. `cancellation` — explicitly leaving, uninstalling, cancelling, switching away, or threatening to.
2. `complaint` — a negative experience, including mixed praise + criticism.
3. `request` — asks for a change/feature without reporting a failure.
4. `praise` — positive only.
5. `unclear` — meaningless, unrelated, unsupported language, or bare boycott slogans with no product
   complaint and no personal departure.

## Severity (integer 1–5)

| | Meaning |
|---|---|
| 1 | No reported problem: praise, neutral/unclear content, or a pure feature request |
| 2 | Dislike, generic criticism, minor annoyance, cosmetic issue; no supported functional loss |
| 3 | Degraded or restricted function; some use or a workaround remains (too many ads, forced shuffle, buggy lyrics) |
| 4 | A clearly blocked core task (cannot log in, cannot play music, app crashes on every use, downloads unusable) |
| 5 | Explicit serious financial, privacy or data harm (unauthorized charges, hacked account, lost paid-for data) |

Stars, angry language, an expensive plan, or cancellation intent **alone** do not raise severity.

## Sentiment

A number from −1 (very negative) to 1 (very positive) with one decimal; 0 = neutral/unclear.
Golden-set tolerance (declared in advance): a prediction agrees if |pred − human| ≤ 0.5.

## Evidence quote, entities, needs_review

* `evidence_quote` — an **exact substring** of the review text (checked by code) that supports the topic
  and intent. For a short review, the full text may be the quote.
* `entities` — product features named in the text (e.g. `shuffle`, `lyrics`, `ads`, `premium`,
  `download`, `podcast`). Extracted by **code** from a fixed term list, so nothing is invented.
* `needs_review` — true when the text is ambiguous, non-English/unsupported, sarcastic, mixed,
  or lacks context to decide severity. Missing context → `needs_review`, never invented impact.

## Worked examples (development sample)

| dev ID | Text (abridged) | topic / subtopic | intent | sev | Why |
|---|---|---|---|---|---|
| 15ff50dc | "I can't log into my account even though I uninstalled it and reinstalled it…" | access / login_failure | complaint | 4 | Core task blocked. Reinstalling is troubleshooting, not departure. |
| 7142ad2b | "…my account automatically Log out and then all my favourite songs are gone… I'm also uninstalling this." | access / logged_out | cancellation | 4 | Explicit uninstall → cancellation. Logged out + library lost blocks use; first problem mentioned. |
| 305c3fe1 | "Why am I paying for this? Unable to login, can not reach tech support. Looks like the account was hacked." | access / account_lost_or_hacked | complaint | 5 | Explicit privacy/security harm outranks the support problem. |
| 8cf70f3f | "It always crashing down; unable to play and just stop working everytime I use it" | playback / crash_freeze | complaint | 4 | Playback blocked on every use. |
| 9397488c | "Why does it constantly need internet to open up downloaded playlists?…" | downloads / offline_mode | complaint | 4 | Offline listening, the core purpose of downloads, is blocked. |
| b06534cf | "It keeps saying that I'm trying to use premium features… meanwhile… I have a premium account" | billing / subscription_entitlement | complaint | 4 | A paid entitlement isn't honoured. |
| 9291c867 | "…way too many ads and… we now have to pay for BASIC features like skip, view lyrics, shuffle…" | usability / ads | complaint | 3 | Ads and paywalled controls are both severity 3; the tie rule picks the first mentioned (ads). `billing / premium_paywall` is an accepted alternative. |
| f99f2c70 | "Very good app for music But 4 ads for 30 min songs very bad" | usability / ads | complaint | 3 | Mixed praise + criticism → complaint. Ad load degrades use. |
| 3940ad58 | "Give us the option to permanently turn off smart shuffle…" | usability / queue_shuffle_controls | request | 1 | Desired change, no failure reported → request, severity 1. |
| d7f0416d | "Your customer service members seriously need retraining… Half an hour being ignored…" | support / support_response | complaint | 3 | Support contact is degraded, not a blocked core listening task. |
| 2c2fefc7 | "Always great! Even the support team is amazing!" | support / support_response | praise | 1 | First specific praised feature is support. |
| d804411c | "Its alright without premium, but its AWESOME with premium" | other / general | praise | 1 | A paid-plan mention alone isn't billing; no problem reported. |
| (typical) | "Good", "Nice app", "Love it" | other / general | praise | 1 | Generic praise. |
| (typical) | "Worst app" | other / general | complaint | 2 | Generic criticism; no specific defect inferred. |

**Note on 9291c867:** the paywall is arguably the review's main point, but the shared tie rule says the
*first* specific problem wins, so prompts keep the strict rule. In disagreement analysis we record
such multi-problem ties as ambiguous with several accepted labels.
