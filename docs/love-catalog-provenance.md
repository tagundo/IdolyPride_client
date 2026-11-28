# Love catalog sources and preparation

The default server payload includes LoveHomeAction, LoveLevel, LoveStoryEpisode and LoveColor, together with their original Story/Setting/Item/Character/Costume/Area/Condition/EventMission prerequisites. Packaging these tables does not enable an event. Events remain disabled until an explicit local schedule is saved; the local schedule does not alter the global game clock or establish an official event end date.

## Original master evidence

The original master version is `961e456499039e31248a818a911c8d95f92461f86aff4674ba07e29c32afcf60`. `tools/build_server_payload.py` verifies each original encrypted master pack before decoding. `love_catalog.LOVE_MASTER_PINS` additionally fixes the four Love pack hashes and counts: 243 home actions, 57 levels, 72 story episodes and one color definition. The resulting runtime catalog records the hashes of every decoded prerequisite file; a changed file invalidates the cached catalog.

The original descriptor file SHA-256 is `c82cee62abdca7144d11e710a6f773211464a89d2ddede207999a0a5e7aec8ad`; the runtime Schema's normalized fingerprint is separately `0fcf90596261dcd9bbed165bd93859dc30127e2a494e6529bafbd8885675edf3`. These are intentionally different identities. Story episode assets are joined through original Story.advAssetIds, not the similarly named LoveStoryEpisode.assetId. All 72 original Love story rows have empty rewardId; an unrelated story reader's stone reward must not be reused.

## Reference routing and limits

`data/love-reference.json` is canonical JSON prepared remotely with PyYAML 6.0.3 from exactly twelve byte/hash-pinned public YAML files at [vertesan/solis-server 9b67c06939403d7035e1795745f791340a775868](https://github.com/vertesan/solis-server/tree/9b67c06939403d7035e1795745f791340a775868/internal/makino/moshikoi). Its 44,247 bytes have SHA-256 `3f1f8e30a499c630a23dfca8e9216e165a2086d3c031b52aba39dc76d05438ec`. The original source hashes, capture claims, and inference comments remain inside the canonical file. The preparation downloads no account, media, or original ADV script data and performs no official authentication.

The six event IDs are love-23-0514, love-23-1114, love-24-0517, love-24-1114, love-26-0313 and love-extra-25-0426. Reference settings describe server captures; this project has not independently authenticated those captures. Numeric route weights, branch associations and ending bonuses identified as inferred remain compatibility metadata. They are not verified official awards. `score_bonus_grants` and the stone-grant policy are false; merely carrying a reference favorability number does not authorize crediting an official account statistic.

`data/love-adv-proof.json` contains 10,239 bytes (SHA-256 `1000ef777c5a95212a48be4d7294f741c1d41bb24ac132589b1711a07bcfded6`). It records only file hashes, byte counts, choice alternative counts and condition-branch counts observed by streaming existing original resource exports; no dialogue or media is copied. The original 72 story records refer to 69 distinct ADV assets. Exactly 68 resource exports were available. All 71 reference route definitions have choice alternative counts matching their observed original ADV scripts.

The remaining node, love-event-story-love-24-1114-004-bad, refers to love_2411_04_02. Both its preserved original ADV source and a reference route definition are unavailable. The exact object is also absent from the pinned original Android and iOS manifests inspected for this task. No neighboring object ID or missing branch count is guessed. The catalog marks this episode's advEvidence.available=false so the game handler can reject entry before mutation. This is partial support, not a claim that all 72 story paths were restored or that a future upstream resource could never exist.

## Runtime and distribution

`build_love_catalog` runs in the CI payload staging directory, combining verified original master inputs and the small canonical reference/proof. It emits master-json/LoveCatalog.json with a content-derived ruleset hash and explicit source/inference grades. Runtime loading checks the supported schema, original version, reference/proof pins, ruleset digest and prerequisite file hashes. Its cache also binds inode, size, modification time and change time; settings polling does not repeatedly parse large master tables. Returned game catalogs are private copies, while `event_catalog(data_dir)` exposes only bounded titles, IDs, support/source grades and dates. Missing or damaged data returns available=false without creating files.

Captured start dates are reference evidence. Official end times and durations are unknown and remain null. User-selected local windows are a separate local policy, with the common settings layer enforcing its stated bounds. The catalog itself grants no currency, items, progress, ownership, account selection or schedule changes.

The server payload includes the canonical reference/proof, `data/licenses/love-reference-NOTICE.txt`, and the complete AGPL license text as `data/licenses/love-reference-AGPL-3.0.txt`. The public upstream source/license URL and exact source pin are retained. The reference's licensing does not relicense original game text, artwork, audio or other game assets, which remain owned by their respective right holders. The proof contains no original dialogue bytes or user account data.

Portable tests cover pinned metadata, the original descriptor identity, source tampering, cache invalidation, safe unavailable behavior and package table contracts. Actual original-pack preparation is validated by the remote payload build. No local project imports, test execution or official authentication were used while preparing this source change. Public release remains subject to the wider native/runtime validation gates.


## Finite latest-cohort progress compatibility

The legacy runtime uses master
`961e456499039e31248a818a911c8d95f92461f86aff4674ba07e29c32afcf60`
and the prepared catalog fingerprint
`876fab148d34d912213b3d8c6fb69b0b3c2bc86e81c75fef724636904a548b49`.
The candidate master is
`6b77e0d8a64b26d5bebd09a7c19a47f2dfad2af914c5160418aa2e7292e13a11`.
A different whole-data fingerprint is expected. It must retain its truthful
master version and complete source-file hashes; no latest catalog is relabeled
as the old master to satisfy saved progress.

`prepare_latest_love_catalog` is a build-only operation on exact public inputs.
Its legacy directory comes directly from the pinned original base plus the
existing old Love overlay, without rerunning or changing the old generator.
It validates the exact legacy catalog fingerprint and all twelve raw source
JSON hashes. The latest catalog independently validates the fixed original
Love packs, original reference/ADV proof and all latest source hashes.

Compatibility compares the full six event definitions, 72 Story rows,
choice/branch graphs, story costs, levels, endings and withheld-bonus policy.
External comparison includes referenced Item definitions, three consumed Love
Setting fields, recursively referenced unlock/ending/EventMission Conditions,
the referenced Area quest lists, selected Costume definitions and Character
identity/model asset references. Unrelated new cards, outfits, character
biographies and costume rosters are excluded from this semantic projection;
their entire current source files still remain covered by catalog integrity.
Original inferred reference routes remain inferred. A separate required
`adv_identity_proof` contains both platforms' baseline/latest manifest SHA-256
and all 68 exact logical script names with MD5, size, generation and object name.
The generator validates this complete set against the pinned original ADV
proof. Every identity must remain equal; any difference stops preparation before
publishing compatibility outputs. These normalized identities also enter both
semantic digests and the complete small report is retained in the compatibility
proof (bounded to 256 KiB). An equal logical asset name alone is insufficient.
The one missing ADV is not repaired by this comparison.

The generator emits `master-json/LoveCatalog.json`, `love-compatibility.json`
and `love-legacy-rules.json`. The last file preserves the original legacy
catalog bytes as base64, their SHA-256 and the original external rule subset.
The small proof binds both real master versions, both full catalog hashes and
fingerprints, both twelve-file source maps, the semantic hashes and the exact
legacy-rules archive hash. A non-equivalent comparison emits no aliases and
retains the old rules for recovery; it never fabricates a progress migration.

A proven catalog may contain exactly one accepted old progress fingerprint.
Runtime requires an independently read-back, source-pinned proof for this
finite old/latest pair, and still verifies the full current catalog, source
files and legacy-rules archive. Its generated pin lives in
`love_compatibility_pins.py`, excluded from compiler inputs to avoid a
source/output hash cycle. The compiler never imports or consumes that runtime
pin. Until actual remote evidence is frozen, the pin is `None` and the latest
runtime catalog is intentionally unavailable.

No State or account ZIP migration is performed. Existing normal/viewing
`profile_love_progress` rows retain their exact old fingerprint and JSON bytes;
new registrations use the actual new fingerprint. Existing rows are passed to
the unchanged atomic State API using their original validated fingerprint.
Read-only Love responses preserve incoming snapshot/progress bytes when their
meaning did not change, including allowed JSON whitespace and unknown protobuf
fields. An explicit gameplay mutation may change its intended fields but does
not silently re-pin the row, reset a run, advance time or grant a reward.

Remote-only tests cover recursive dependency changes, unrelated additions,
missing/forged evidence, complete integrity checks, exact original rule archive
retention, normal/viewing raw progress and account ZIP preservation, old backup
restoration, new registration pins and fail-closed incompatible progress. Local
verification is source/AST only. Actual latest compatibility is not claimed
until the owned remote generator and small-artifact read-back complete.
