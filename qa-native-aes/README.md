# Emulator-only software AES dispatch

The API30 Google APIs x86_64 native bridge (`libndk_translation` 0.2.2) crashed
on ARM64 `AESIMC` in the game's `AES_CBC_decrypt_Native`, before game RPCs. This
QA adaptation changes four branch instructions in the original `libFastAES.so`
to call its existing software `_C` functions. It performs real AES encryption
and decryption. Key expansion, CBC chaining, ECB, padding and exports remain the
original implementation. It is not the exact production client.

The patch requires original SHA-256
`f8f64ab5424b6f692464e23cf47af9d399c4072b700c196e7b321e670b93fcc4`.
It verifies that the software functions and their AES helper range contain no
AES/SHA/PMULL instructions. The output APK receives an embedded QA marker and an
ephemeral signing key. Install it only on disposable emulator data. Production
client packaging and release APKs do not use this tool.

The ARM64 P/Invoke ABI, recovered from `FastAES.dll` metadata and IL2CPP stubs:

```c
int32_t AES_CBC_decrypt_Native(uint8_t *output, const uint8_t *input,
    uint32_t length, const uint8_t *key, uint32_t keyLength,
    const uint8_t *iv, int32_t padding);
int32_t AES_CBC_encrypt_Native(uint8_t *output, uint32_t outputCapacity,
    const uint8_t *input, uint32_t inputLength, const uint8_t *key,
    uint32_t keyLength, const uint8_t *iv, int32_t padding);
```

ECB has the same respective signatures, including its unused IV argument. The
managed padding argument is a `System.Security.Cryptography.PaddingMode`; its
low byte is consumed natively. Tested modes are `1=None`, `2=PKCS7`, with
16/24/32-byte keys. No malformed-input behavior is changed or advertised.

Before packaging, Unicorn executes both the original software exports and the
patched Native exports against NIST SP800-38A known ciphertexts and an independent
PyCryptodome oracle. Cases include both directions, one/multiple blocks, empty
PKCS7 input, and partial/full padding blocks. Inputs, keys, IVs, stack and
callee-saved register preservation are checked. The verifier hooks only libc
memory operations; it does not replace or skip cryptography.

```sh
uv run --locked --all-extras python tools/package_qa_aes_client.py \
  data/ci-input/Game-local-r2.apk \
  --output data/dist/Game-QA-software-AES.apk \
  --build-tools "$ANDROID_HOME/build-tools/34.0.0" \
  --report data/android-game-debug/qa-aes-report.json
```

For a separately built diagnostic APK, pass its explicitly verified SHA-256 using
`--expected-source-sha256`. The FastAES library checksum remains mandatory. Game
UI capture still requires an actual home screen review; an emulator process or
successful RPC does not establish that the home screen loaded.

## Optional no-store initialization for emulator QA

The translated emulator has no Play account. Its real billing initializer
reported `BillingUnavailable` and the game returned to its title screen before
Home RPCs. `--emulator-no-store` enables a separate, explicit QA adaptation:
only the first 32 bytes of `UnityPurchaseManager.InitializeAsync` at
`0x87b61ac` change. The replacement calls the original managed
`PurchaseInitResult.CreateSuccessResult` factory at `0x87b520c` and returns its
object in a completed 24-byte `UniTask`. It does not initialize a store, set
`IsInitializeSucceeded`, or modify purchase, receipt, pricing or grant code.
Later code depending on an actual store remains unverified.

This option requires the audited local-bootstrap IL2CPP SHA-256
`4517381b0dbeae559d79832797f0c57c78ba6f37cf7d3544a58d0f31f2b8def3`,
its exact initializer prologue and original factory/getter instructions.
Unicorn executes the replacement and both original factory initialization
paths, with hooks only for IL2CPP metadata initialization, managed allocation
and `System.Object.ctor`. It checks the genuine factory object's original
`IsSuccess` getter, hidden x8 return buffer, x19 through x29, x30, stack
alignment/restoration and the return buffer boundary. The APK marker records
both the AES and IAP QA adaptations; production packaging never calls this code.

The debug workflow additionally uses `--prepare-restarted-tutorial`: after
readiness it makes local `Auth.Login`, `Tutorial.Init(name="QAManager")` and
read-only `User.Get` calls. It requires completed main tutorial step10 and an
uncleared profile, and calls no tutorial progress/skip or purchase/grant RPC.
The client derives its next step100 from stored step10; this preparation does
not prove that the corresponding game screen appeared. `profile-fixture.json`
records these fixture calls separately without authentication tokens. The debug
workflow permits at most two fresh OCR-observed title taps. A second tap requires
two stable, non-loading title observations at least three seconds apart and at
least twenty seconds after the first. It addresses the normal title-background
reload path; no other game UI is operated.

```sh
uv run --locked --all-extras pytest -q qa-native-aes android-server/ci
uv run --locked --all-extras python tools/package_qa_aes_client.py \
  data/ci-input/Game-local-r2.apk \
  --output data/dist/Game-QA-no-store.apk \
  --build-tools "$ANDROID_HOME/build-tools/34.0.0" \
  --emulator-no-store --report data/android-game-debug/qa-aes-report.json
```
