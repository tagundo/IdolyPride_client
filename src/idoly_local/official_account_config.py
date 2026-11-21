"""Public Firebase settings extracted from pinned original Japanese apps.

App configuration only: no account passwords or tokens. Extraction Actions
43815222197, commit 92ba3ab395d8aed25d049211cc33a5241533ded6. Artifact
14201399992 SHA256 5e8a2bf5a628e565a1425bbe0936ccae6fc37185d669e307c87cfbef8016c7f9.
Exact original/member provenance below. No official authentication performed.
"""
import re

PUBLIC_CONFIG = {'android': {'api_key': 'AIzaSyCabjC7_mOU21qkcNobnhN1khTi1-1F-kA', 'app_version': '6.1.1', 'bundle_id': 'game.qualiarts.idolypride', 'certificate_sha1': '381D8CBA5B5B5DAA048B4495EEF678E87FCAE3A6', 'google_app_id': '1:543065248020:android:05fdc14eecbd124aab3201', 'project_id': 'solis-firebase', 'project_number': '543065248020'}, 'ios': {'api_key': 'AIzaSyCp8JNTXIXLdpm7WG0YE3DKQ-JiXLqezZc', 'app_version': '6.1.1', 'bundle_id': 'game.qualiarts.idolypride', 'google_app_id': '1:543065248020:ios:babf05d967621a37ab3201', 'project_id': 'solis-firebase', 'project_number': '543065248020'}}

SOURCE_PROVENANCE = {'android': {'android_build_tools': '34.0.0', 'app_executed': False, 'identity_scope_verified': True, 'members': [{'badging_sha256': '721523158350fee0810aace0086e2787818e60fbe1c96e08b82450601b717702', 'bytes': 110914967, 'certificate_sha1': '381D8CBA5B5B5DAA048B4495EEF678E87FCAE3A6', 'certificate_sha256': '06cede031cd36c1986928fb5a9339c859253c07e06aff6137503d8385d3291b5', 'member': 'game.qualiarts.idolypride.apk', 'resources_dump_sha256': '613e03a000e0f025fe0186432fd189349a73e555cefc153b4af36d7a50826742', 'sha256': '3d54e05f897bfb54716a0ad645562955ceb0081cead696cb29595941ac08faa9', 'signature_output_sha256': '854733870caa1daa7174fc0336dc2e458af06994c865a47dd1371c37962519e6'}, {'badging_sha256': 'caaa139adadafb5fed4b16fe1b3eb9abd488381920cd8b5a5aab01adc07c702e', 'bytes': 56780923, 'certificate_sha1': '381D8CBA5B5B5DAA048B4495EEF678E87FCAE3A6', 'certificate_sha256': '06cede031cd36c1986928fb5a9339c859253c07e06aff6137503d8385d3291b5', 'member': 'config.arm64_v8a.apk', 'sha256': 'b91a53316f230b48e290145f9625ca5caf5d40180c3de6ab1dce5171912aba67', 'signature_output_sha256': '428d3ed0bdb769dabd14abd38f53faa01cf9ceed0202eabbe69b048afdd885a0'}], 'source': {'asset_id': 725772331, 'bytes': 167699540, 'sha256': 'ab3bd9186ccc2659f91fcf2a48e25b591e94b4209c505f2ca401be8b22e5de36'}}, 'ios': {'app_executed': False, 'identity_scope_verified': True, 'members': [{'bytes': 729, 'member': 'Payload/IDOLY PRIDE.app/GoogleService-Info.plist', 'sha256': 'e4f3ad5aa7e6ef3538e8e1cd5cf5be8e03bfb57cc22e3543dd4b10276818aa48'}, {'bytes': 24329, 'member': 'Payload/IDOLY PRIDE.app/Info.plist', 'sha256': 'd3d7cdede947002ffb6d23be2415046e6fcf11d827aab7685bcebc9e2df8403b'}], 'source': {'asset_id': 725761399, 'bytes': 146438450, 'sha256': '33197938a0990b267af2d67c09e9d1123694e28695fc39d9650ca4f6aa661848'}}}

_SOURCE_PINS = {
    "ios": (146438450, "33197938a0990b267af2d67c09e9d1123694e28695fc39d9650ca4f6aa661848"),
    "android": (167699540, "ab3bd9186ccc2659f91fcf2a48e25b591e94b4209c505f2ca401be8b22e5de36"),
}
_APP_IDS = {
    "ios": "1:543065248020:ios:babf05d967621a37ab3201",
    "android": "1:543065248020:android:05fdc14eecbd124aab3201",
}


def load_public_config(platform):
    """Return an independent scope-checked copy; never read user files/env."""
    try:
        if type(platform) is not str or platform not in _SOURCE_PINS:
            raise ValueError()
        value = PUBLIC_CONFIG[platform]
        required = {"api_key", "project_id", "project_number", "google_app_id", "bundle_id", "app_version"}
        if platform == "android": required.add("certificate_sha1")
        proof = SOURCE_PROVENANCE[platform]
        pin = _SOURCE_PINS[platform]
        if (type(value) is not dict or set(value) != required
                or not all(type(item) is str for item in value.values())
                or value["project_id"] != "solis-firebase" or value["project_number"] != "543065248020"
                or value["google_app_id"] != _APP_IDS[platform]
                or value["bundle_id"] != "game.qualiarts.idolypride" or value["app_version"] != "6.1.1"
                or re.fullmatch(r"AIza[A-Za-z0-9_-]{20,80}", value["api_key"]) is None
                or proof["source"]["bytes"] != pin[0] or proof["source"]["sha256"] != pin[1]
                or proof["identity_scope_verified"] is not True or proof["app_executed"] is not False):
            raise ValueError()
        if platform == "android" and re.fullmatch(r"[A-F0-9]{40}",value["certificate_sha1"]) is None:
            raise ValueError()
        return dict(value)
    except Exception:
        raise ValueError("official_config_unavailable") from None
