# Precomputed language catalogs

The server selects Japanese (`ja`), Korean (`ko`) or English (`en`) at startup.
It serves ordinary SQLCipher master packs to the original client. Translation
does not add a text hook or work to Unity's frame callbacks. Missing translation
rows, empty translations and unavailable nested entries retain the original
Japanese text. Coverage is recorded per table; selecting English or Korean does
not imply every screen has been translated.

`client-language.json` contains exactly:

```json
{"schema":1,"language":"ja"}
```

Japanese is the default. Invalid files retain the last valid setting in that
server process. Settings are saved atomically by the launcher. A change requires
a server restart and returning the game to the title screen. The selector uses
`original-master/languages/<locale>/master-tag.json` or the corresponding
`media-master-tag.json`. Japanese continues to use the original tags.

## Sources and attribution

The implementation reads the public data format; it does not copy Localify's
runtime translation hooks.

* [CyleAR/Hoshimi-localify](https://github.com/CyleAR/Hoshimi-localify) is GPL-3.0.
  Its `.gitmodules` links the Korean data repository, formerly named
  `IdolyprideTranslationDataKor`, now
  [CyleAR/ipr-translation-data-ko](https://github.com/CyleAR/ipr-translation-data-ko).
* [Project-Hoshimi/HoshimiLocalify-en](https://github.com/Project-Hoshimi/HoshimiLocalify-en)
  is a GPL-3.0 derivative. Its README identifies
  [ipr-translation-data-en](https://github.com/Project-Hoshimi/ipr-translation-data-en)
  as the English update feed. The feed describes itself as a sanitized mirror
  whose source of truth is private.
* [Project-Hoshimi/sumire-sr](https://github.com/Project-Hoshimi/sumire-sr) is
  AGPL-3.0 and attributes solis-server. Its separate game-data repository is
  useful protocol evidence, not an English translation license.

Neither inspected translation-data repository includes a root license file.
Their data provenance therefore records `NOASSERTION`, rather than treating the
module's GPL license as a license for every game text or translation. Repository,
commit, exact Git blob SHA-1, byte count and SHA-256 are retained for each input.
The pre-existing `tagundo/ipr-translation-data-ko` snapshot is a distinct fork;
it is reused for a current CyleAR build only when the pinned upstream Git blob
matches exactly. The producer does not relabel a fork as current upstream.

## Master-pack producer

`master_translation_build.translate_rows` reads the actual Localify shape:

```json
{"rule":["id|name","id|branchChoices.text"],"data":{"story-a|name":"Translated title","story-a|branchChoices[0].text":"Translated choice"}}
```

The supplied descriptor owns primary keys, scalar types, nested messages and
repeated-field indices. Only the explicit human-text leaf allowlist can change.
IDs, quantities, order, asset references, dates, visibility and unlock conditions
are not translation targets. Invalid/unsupported rule sets retain that table's
original pack and are reported as unsupported; malformed files and provenance
mismatches stop publication. Original inputs are never edited.

The producer requires a complete 202-entry input tag, replaces only changed
tables and roundtrips every generated pack through SQLCipher and protobuf. Its
public compatibility key derivation reuses `master_build` version 2. Pack names
and tag versions depend on locale, schema, source provenance and exact output
rows. SQLCipher's physical file bytes can include random salt, so byte hashes
are measured separately. Ordinary-to-media reuse verifies exact decoded rows
and preserves the same immutable pack bytes, avoiding duplicate unchanged packs.

Media translations start from the existing six-pack media overlay. Outfit
availability, visible flags and conditions remain intact. For the four cover
songs, the translated description supplies the distinct media label; an absent
description leaves the existing Japanese cover label instead of replacing it
with the indistinguishable original song name.

Example for one prebuilt variant:

```sh
python tools/build_master_translations.py \
  --schema data/protocol/idolypride-6.1.1.pb \
  --master-tag data/original-master/master-tag.json \
  --pack-root data/original-master/assets/master \
  --translations translations/ko/masterTrans \
  --source-manifest translations/ko-source.json \
  --language ko --output generated/ko-normal
```

Run media against the prepared media tag/pack root with `--media-mode`, using
`--reuse-overlay generated/ko-normal`. Generated files merge into the common
`original-master/assets/master` directory; the mode-specific tags live beside
the selected language catalogs. `coverage.json` records actual changed fields,
fallbacks, source hashes and generated pack hashes. No device-play result is
inferred from a successful build.

Sort variants are independent per-table packs built from the final localized
rows. `master-sort.json` and `media-master-sort.json` live beside their respective
tags. Runtime selection composes two entries; it does not rebuild SQLCipher or
enumerate every full-catalog combination.

## Coverage boundaries

The Korean and English feeds each contain 90 master translation JSON files.
Those can translate matching master titles, descriptions, card/character text,
messages and story catalog/choice text. They include nested repeated text fields.

ADV dialogue is different: `local-files/resource/adv` contains complete
Naninovel script replacements, including commands, asset references and timing.
`localization.json`, generic translation patterns, subtitles and image resources
also live outside the master tables. Serving translated masters alone does not
translate those resources. A separate precomputed, platform-correct asset layer
is required; the current master producer does not claim that coverage or modify
original SDK bundle hashes behind the SDK's back.
