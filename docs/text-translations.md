# Prepared UI and story text

Japanese, Korean and English use prepared language data. The game does not run
a translation engine, read translation files or replace every displayed string
in a frame callback. The fixed UI language belongs to the installed client;
the server language selects the corresponding master packs and story scripts.
Use the matching client and server language.

## Built-in UI

The original 6.1.1 I18n configuration resolves a built-in TextAsset. Android
stores it separately in `assets/bin/Data/dc5a3280fad6542929a0daf3a3736d29`;
iOS stores TextAsset 377 inside `Data/resources.assets`. Both contain exactly
the same encoded CSV. The original reader supports a plaintext CSV beginning
with `KEY,`, so a prepared language table can use that existing reader without
new text setter hooks. Serialized object identity, name and references remain
unchanged; the asset writer owns size/alignment changes.

The stock CSV parser handles quoted fields, commas, doubled quotes and leading
whitespace. Its caller converts literal `\n` to a newline. Translated values
therefore encode actual CR/LF as `\n` and quote changed fields; the original
header, comments and untranslated logical records retain their source bytes.
The original parser does not support literal newlines inside a quoted field.

The stock table has 4,199 keys. The pinned Korean source supplies 4,198 nonempty
translations with one original fallback; the English source matches 4,185
stock keys, with 17 empty or missing fallbacks. Equal source and translation
values do not require a rewrite. These counts describe the keyed UI table,
not every prefab, image or string in the game. Generic Localify dictionaries
remain build input: a matching metadata literal can also be a comparison
operand, so only independently audited display literal indexes may be patched.
There is no implicit patch-all mode.

## Story scripts

ADV scripts are UTF-8 Octo `resources` objects, not Unity asset bundles.
`resource_translation_build` prepares the script bytes and their complete
platform manifest together. Each changed script receives a distinct local
object identity, generation, size and MD5. Original resource files and manifests
remain immutable. `ResourceTranslation` checks that only the six authorized
ADV integrity fields changed and rejects unrelated resource, bundle, dependency
or gameplay changes.

The optional platform package installs under the selected resource library,
normally `Downloads/IdolyPride/translations`. It contains Korean and English
platform directories with `manifest.pb`, `manifest.json` and `objects.zip`.
The installer validates the complete package and file hashes before atomically
selecting an immutable version through its platform pointer. Original Japanese
resources and the ordinary resource cache are preserved.

At server preparation the selected language manifest and compressed archive
are opened once. A requested translated script enters the existing guarded
cache seed path, which verifies its complete size and MD5 before atomic
publication. It works when public resource downloads are disabled. Missing or
corrupt local language objects cannot fall through to the public CDN. The
client receives the normal encrypted manifest and verifies the declared object
hash; no SDK checksum check is skipped.

Language changes, including returning to Japanese, advance a small persistent
resource revision. An authenticated request for an older revision receives a
complete updated snapshot. Reopening the same prepared language reuses its
revision. This avoids retaining a previous language through the SDK cache.

The current platform archive contains 3,492 ADV records. Korean changes 3,091
scripts and leaves 401 missing scripts in Japanese. English changes 3,093;
398 source scripts are byte-identical to the original and one is absent.
Source coverage does not imply that every line within every supplied script
has been translated. The manifest records the exact source revision and output
hashes.

## Sources and limits

Korean data comes from the CyleAR-linked translation repository at
`f6e5689bcd6878d962996edfd390c1442b926c0f`. English comes from
`Project-Hoshimi/ipr-translation-data-en` at
`aa0993d34843bd8fad503a84ee75392ec6058246`. Repository identity, immutable
revision, input/output hashes and `NOASSERTION` data terms are retained. The
runtime module license is not used to invent a license for all translation data.

The separate phone subtitle feed is preserved as source/provenance. It requires
an additional display feature because the original telephone voice has no
corresponding built-in subtitle asset. Prepared phone data is not reported as
connected subtitles. ADV story text uses the game's existing story display.

Host tests verify CSV semantics, manifest consistency, offline cache import,
corrupt-data rejection and language revision changes. They do not establish
physical device rendering or complete visual translation coverage.
