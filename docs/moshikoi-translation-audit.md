# Moshi Koi translation audit, 2026-11-16

The selected game language applies the existing prepared story, UI and master
translations in both ordinary and viewing mode. This is file and source
coverage evidence, not a claim that every line or image is translated.
Missing translations retain Japanese; no replacement scripts or images are
invented.

## Story coverage

The mapping uses the original `LoveStoryEpisode.storyId`, the corresponding
original `Story.advAssetIds[0]`, and the exact Octo resource name
`adv_<assetId>.txt`. It does not infer filenames from an event date.

| Love ID | Original story episodes | Unique ADV | Korean changed ADV | English changed ADV |
|---|---:|---:|---:|---:|
| love-23-0514 | 11 | 10 | 10 | 10 |
| love-23-1114 | 11 | 10 | 10 | 10 |
| love-24-0517 | 11 | 10 | 10 | 10 |
| love-24-1114 | 11 | 11 | 10 | 10 |
| love-26-0313 | 10 | 10 | 10 | 10 |
| love-extra-25-0426 | 18 | 18 | 18 | 18 |
| Total | 72 | 69 | 68 | 68 |

The same unavailable node is absent in both translation sources:
`st-love-24-1114-004-bad` / `love_2411_04_02` /
`love-event-story-love-24-1114-004-bad`. Its original ADV and verified branch
route are also unavailable in the pinned recovery inputs, so the restored
feature explicitly refuses this node. The other 71 episode references share
68 supplied translated ADV objects. Byte differences do not prove that every
text line in a supplied script was translated.

Korean source is `CyleAR/ipr-translation-data-ko` at
`f6e5689bcd6878d962996edfd390c1442b926c0f`; the audited local Love files have
no working tree modifications. Each of the 68 source files is present, differs
from the original Japanese SHA-256 and contains Hangul. English source is
`Project-Hoshimi/ipr-translation-data-en` at
`aa0993d34843bd8fad503a84ee75392ec6058246`. Its exact Git tree was read as
bounded public metadata, without downloading or writing an archive: 1,091,334
bytes, SHA-256
`521f2f758dccd5e5769a55dc6efeccfdee93172b3dad4aed772ff7e538095c45`.
All 68 relevant English Git blob hashes differ from the original Japanese
`blob <length>\0<bytes>` identity. This metadata establishes source object
coverage, not a new end-to-end device rendering claim.

`resource_translation_build.NAME` accepts all of these `adv_love_*.txt` names.
All 68 exact resource names are also present in the current original Octo
manifest; the unavailable node is absent there. Changed script bytes and
size/MD5/object-generation metadata are prepared together. `app_runtime` passes the same effective game language to
`create_octo_gateway` in both ordinary and viewing mode; the media profile does
not select a separate untranslated gateway. The currently pinned translation
bundles are reused, rather than rebuilding scripts during gameplay.

## Master text, UI and server labels

Both fixed translation sources contain nonempty name and description entries
for all 72 original Love Story rows: 144 fields per language. The English
`masterTrans/Story.json` is 725,737 bytes with SHA-256
`fd1bb4871322382046969c8e7cbf157e61ebd4b7bb078ee85a536c1a3e0507d2`,
matching the existing prepared-master source receipt. Existing prepared
ordinary and media master receipts report all 243 `LoveHomeAction` text fields
changed in each language. These master assets use the normal prebuilt game
language selection.

The built-in `love.*` UI namespace has 102 nonempty mappings in both Korean
and English. The English `love.episode` value is still the original `話`; the
other 101 values have no Japanese kana/CJK characters. Nonempty mappings are
not automatically full translations. Hint explanations and interface labels
come from this UI data; actual choice/dialogue text comes from the ADV scripts.
The restored server sends choice indices and hint flags, not alternate dialogue.

New server responses originally read event names, descriptions, short names and
ending labels directly from the raw Love catalog. Display now uses an optional
frozen exact-string map from the selected bundle's existing `text.json`
`generic` table. Missing or empty entries keep the exact original. The optional
pack is bounded and verified against its text manifest; wrong language, bad
hash/schema, duplicate keys and unsafe files fail with a fixed code.

Most raw event and ending names have no existing generic translation. Korean
currently supplies the Extra description and short-name mappings; English
supplies the Rei description mapping. None of the 55 ending-label references
has a generic mapping in either source, so those labels remain Japanese. No
claim of complete translated titles, endings or images is made.

This lookup is restricted to display labels. It never rewrites IDs, assets,
choices, player/save names, ruleset fingerprints, progress, account data or
master definitions. A language switch cannot change route compatibility or
award inventory. Existing original-language labels remain valid fallback.

## Verification boundary

Source and AST checks were performed locally without importing the project,
running tests, native builds or a VM. `tests/test_love_translation.py` provides
remote-only checks for both platforms and both local modes, optional fallback,
pack integrity, input safety, exact output lookup and unchanged game state.
Source coverage alone does not prove every delivered package or physical-device
screen; the enclosing source-bound remote build and device QA remain separate.
