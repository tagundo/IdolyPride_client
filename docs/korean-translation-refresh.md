# Pinned Korean translation refresh

The unified APK and IPA compile Korean ADV and text catalogs from the same
immutable public archive identified by
`data/latest-korean-translations-pin.json`. The current source is
[`CyleAR/ipr-translation-data-ko` at `11ecceb451833b81c614f666a3667be0d08e0281`](https://github.com/CyleAR/ipr-translation-data-ko/tree/11ecceb451833b81c614f666a3667be0d08e0281).
Its archive is 160873732 bytes with SHA256
`9a52f6a05c460f7fd22146ebd5076a20b43c7a992edf9143e5ab70c3a7eb95ea`.
The upstream archive has no root license or attribution document; provenance
therefore retains `data_terms: NOASSERTION`.

`tools/refresh_korean_translation_bundle.py` verifies the source archive, original
platform manifest and previous translation bundle before producing a fresh
archive. Each output must match its fixed size, SHA256 and package-manifest
SHA256. Both platforms now include all 3114 available ADV scripts, including the
23 added scripts; the remaining 401 ADV resources retain their Japanese source.

All 667 existing translated image bundles and their proofs are checked and
preserved. No image is drawn or re-encoded. English bundle members retain their
exact bytes. Existing static startup UI images keep their separately pinned
source. The new Korean text catalog supplies generic display strings, including
`サキュ×まほ` → `서큐×마법`. Phone subtitles are retained in the catalog, but this
change does not introduce a phone subtitle renderer.

The Android input stage downloads the pinned archive next to its unchanged
donor APK. The packager applies the separate frozen Korean master overlay,
builds ADV/text, regenerates the startup receipt, compiles the corresponding
asset pins into BuildConfig, and checks the final three APK assets again.
The iOS input stage preserves the old donor translation bundle as
`bundledTranslations.base.zip`; its build stage produces the refreshed bundle
after preparing server data. Original cohort and Korean master proofs remain
separate.

Prepared resource revisions advance to Android 1099 and iOS 1171. Runtime SDK
revision selection also fingerprints manifest contents, so a Korean-to-Korean
update invalidates the previous translated manifest while retaining accounts and
unrelated cached resources.

The separate frozen `korean-master-refresh-v1` layer updates Korean ordinary and
viewing-mode master packs and all 18 sort variants. Compared with the previous
Korean packs, 14 tables, 161 rows and 284 text fields change in each mode. These
include Mana's `card-mna-05-casl-04` name, description and obtain message, and
newly translated costume names. Non-text fields and 566 existing payload members
retain their bytes. The original latest-cohort proof remains separate from the
Korean refresh proof. Compiled SQLCipher packs are frozen; the application copies
their compressed streams and does not recompile or recompress them.

The Home Event banners `img_banner_l_event-love-23-1215` (Rei) and
`img_banner_l_event-love-25-0426` (Succu × Magic) have no Korean PNG in either the
previous or current upstream source. They intentionally retain their original
images; this refresh does not generate missing banner artwork.
