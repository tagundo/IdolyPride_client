"""Build the Docker context that adds genuine Google Play services to the pinned redroid image.

The game's own play-services-basement check (GooglePlayServicesUtilLight) needs three
Google-signed system packages with one signing lineage: GmsCore, Google Services
Framework (shares GmsCore's UID) and the Play Store. Without the Play Store it reports
SERVICE_INVALID and Firebase messaging refuses to start, so all three are required.

Input is the official MindTheGapps zip whose SHA-256 the workflow pins. Only the
allowlisted regular files below are read out of it; its installer (update-binary,
toybox, addon.d) is never executed, and the setup wizard and optional Google apps are
left out so AOSP Provision and the AOSP keyboard stay as they are. Files land in a
context `system/` tree with 0644 files and 0755 directories. The Dockerfile copies
that tree over the image's /system as root (redroid's /product and /system_ext are
symlinks into /system) and keeps the base image's own entrypoint. The game is not
changed.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import zipfile

# The three packages the game's availability check reads, pinned inside the zip as well.
PACKAGE_APKS = {
    "system/product/priv-app/GmsCore/GmsCore.apk":
        ("com.google.android.gms", "38eb121872076788b3e2cba8006032ca4eaee569514403cf159d49f47a526d4d", 168192577),
    "system/product/priv-app/Phonesky/Phonesky.apk":
        ("com.android.vending", "63192a372c0f5ff74219872a472371fb0d2eb5f7bf719d890bb8213d2ade6a9f", 79449783),
    "system/system_ext/priv-app/GoogleServicesFramework/GoogleServicesFramework.apk":
        ("com.google.android.gsf", "748a7b1eb1edf2ca7928fe9f1e1f69df16f913755da7b657e62f38a55f0bbff7", 5335582),
}

# Configuration that ships with those packages on a phone. GmsOverlay makes the Play
# Store and GMS force-queryable (package visibility); the sysconfig, permission and
# default-permission files are the ones MindTheGapps installs for them. The setup-wizard
# overlay, SetupWizard, GooglePartnerSetup, GoogleRestore, Velvet, Speech, TalkBack,
# Wellbeing and the Google keyboard library are deliberately not taken.
SUPPORT_FILES = (
    "system/product/overlay/GmsOverlay.apk",
    "system/product/overlay/GmsSettingsOverlay.apk",
    "system/product/overlay/GmsSettingsProviderOverlay.apk",
    "system/product/etc/permissions/privapp-permissions-google-product.xml",
    "system/product/etc/permissions/privapp-permissions-mtg.xml",
    "system/product/etc/permissions/com.google.android.dialer.support.xml",
    "system/product/framework/com.google.android.dialer.support.jar",
    "system/product/etc/default-permissions/default-permissions-google.xml",
    "system/product/etc/default-permissions/default-permissions-mtg.xml",
    "system/product/etc/sysconfig/google.xml",
    "system/product/etc/sysconfig/google_build.xml",
    "system/product/etc/sysconfig/google-hiddenapi-package-allowlist.xml",
    "system/product/etc/sysconfig/d2d_cable_migration_feature.xml",
    "system/product/etc/sysconfig/sysconfig_contextual_search.xml",
    "system/product/etc/sysconfig/wellbeing.xml",
    "system/product/etc/init/gapps.rc",
    "system/product/etc/security/fsverity/gms_fsverity_cert.der",
    "system/system_ext/etc/permissions/privapp-permissions-google-system-ext.xml",
)

# Android 11 image (the only redroid image whose software AVC encoder needs no YUV graphic
# buffers): the last official MindTheGapps 11 arm64 release, same three packages.
PACKAGE_APKS_11 = {
    "system/product/priv-app/PrebuiltGmsCore/PrebuiltGmsCore.apk":
        ("com.google.android.gms", "0b4e47b1e53d8d035fda2f5d8369f67de6f9985ed49001c207aac329d563b56f", 96849165),
    "system/product/priv-app/Phonesky/Phonesky.apk":
        ("com.android.vending", "2d4f714099b1e74b26246aec794e51a3c09181e6a9a315261774cf13c4e7ccdd", 22290178),
    "system/system_ext/priv-app/GoogleServicesFramework/GoogleServicesFramework.apk":
        ("com.google.android.gsf", "482798ab45ae314ae8084ee15295d0acb7da4ea9cdc3c2701a75ab2dbc10f252", 6555284),
}
SUPPORT_FILES_11 = (
    "system/product/etc/permissions/privapp-permissions-google-p.xml",
    "system/product/etc/permissions/com.google.android.dialer.support.xml",
    "system/product/framework/com.google.android.dialer.support.jar",
    "system/product/etc/sysconfig/google.xml",
    "system/product/etc/sysconfig/google_build.xml",
    "system/product/etc/sysconfig/google-hiddenapi-package-whitelist.xml",
    "system/system_ext/etc/permissions/privapp-permissions-google-se.xml",
)
PROFILES = {"15": None, "11": (PACKAGE_APKS_11, SUPPORT_FILES_11)}

# Android 15 redroid scans new system packages as stopped on first boot
# (config_stopSystemPackagesByDefault); let the Google packages receive BOOT_COMPLETED.
INITIAL_STATE_FILE = "system/etc/sysconfig/qa-google-initial-package-state.xml"
PINNED_BASE = re.compile(r"redroid/redroid:[A-Za-z0-9_.-]+@sha256:[0-9a-f]{64}")
CHUNK = 1 << 20


def fail(message):
    raise SystemExit("redroid GApps context: " + message)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def initial_state_xml(packages):
    rows = "".join('    <initial-package-state package="%s" stopped="false"/>\n' % name for name in packages)
    return '<?xml version="1.0" encoding="utf-8"?>\n<config>\n' + rows + "</config>\n"


def dockerfile(base_image):
    # No "# syntax=" line: that would pull a BuildKit frontend image from Docker Hub.
    return "FROM %s\nCOPY --chown=0:0 system/ /system/\n" % base_image


def make_dirs(root, relative):
    current = root
    for part in PurePosixPath(relative).parent.parts:
        current = current / part
        if not current.is_dir():
            current.mkdir()
        os.chmod(current, 0o755)
    return current


def extract(archive, info, target, expected=None):
    digest, size = hashlib.sha256(), 0
    with archive.open(info) as source, open(target, "xb") as sink:
        for block in iter(lambda: source.read(CHUNK), b""):
            digest.update(block)
            size += len(block)
            sink.write(block)
    os.chmod(target, 0o644)
    if size != info.file_size:
        fail("%s: extracted %d bytes, zip says %d" % (info.filename, size, info.file_size))
    if expected and (digest.hexdigest(), size) != expected:
        fail("%s: sha256 %s size %d, pinned %s size %d" % (info.filename, digest.hexdigest(), size, *expected))
    return digest.hexdigest(), size


def prepare(zip_path, expected_sha256, base_image, context, apk_pins=None, support_files=SUPPORT_FILES):
    apk_pins = PACKAGE_APKS if apk_pins is None else apk_pins
    zip_path, context = Path(zip_path), Path(context)
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256 or ""):
        fail("expected SHA-256 must be 64 lowercase hex characters")
    actual = sha256_file(zip_path)
    if actual != expected_sha256:
        fail("zip SHA-256 %s differs from the pinned %s" % (actual, expected_sha256))
    if not PINNED_BASE.fullmatch(base_image or ""):
        fail("base image must be a digest-pinned redroid/redroid:<tag>@sha256:<digest> reference")
    if context.exists() and any(context.iterdir()):
        fail("context directory %s is not empty" % context)
    context.mkdir(parents=True, exist_ok=True)
    os.chmod(context, 0o755)
    wanted = list(apk_pins) + list(support_files)
    for name in wanted:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or path.parts[0] != "system" or len(path.parts) < 3:
            fail("refusing allowlist entry %s" % name)
    files, packages = [], {}
    with zipfile.ZipFile(zip_path) as archive:
        counts = Counter(info.filename for info in archive.infolist())
        entries = {info.filename: info for info in archive.infolist()}
        for name in wanted:
            info = entries.get(name)
            if info is None:
                fail("zip has no %s" % name)
            if counts[name] != 1:
                fail("zip has %d entries named %s" % (counts[name], name))
            kind = stat.S_IFMT(info.external_attr >> 16)
            if info.is_dir() or kind not in (0, stat.S_IFREG):
                fail("%s is not a regular file in the zip" % name)
            target = make_dirs(context, name) / PurePosixPath(name).name
            pin = apk_pins.get(name)
            digest, size = extract(archive, info, target, pin[1:] if pin else None)
            files.append({"path": "/" + name, "sha256": digest, "size": size, "mode": "0644"})
            if pin:
                packages[pin[0]] = {"path": "/" + name, "sha256": digest, "size": size}
    state = context / INITIAL_STATE_FILE
    make_dirs(context, INITIAL_STATE_FILE)
    state.write_text(initial_state_xml(sorted(packages)))
    os.chmod(state, 0o644)
    files.append({"path": "/" + INITIAL_STATE_FILE, "sha256": sha256_file(state),
                  "size": state.stat().st_size, "mode": "0644"})
    for directory, subdirectories, names in os.walk(context / "system"):
        os.chmod(directory, 0o755)
        for name in names:
            os.chmod(os.path.join(directory, name), 0o644)
    (context / "Dockerfile").write_text(dockerfile(base_image))
    os.chmod(context / "Dockerfile", 0o644)
    return {"schema": 1, "zip_sha256": actual, "base_image": base_image, "dockerfile": dockerfile(base_image),
            "packages": packages, "files": sorted(files, key=lambda row: row["path"]),
            "initial_non_stopped_packages": sorted(packages), "total_bytes": sum(row["size"] for row in files)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--zip", required=True, help="downloaded MindTheGapps zip")
    parser.add_argument("--sha256", required=True, help="pinned SHA-256 of that zip")
    parser.add_argument("--base-image", required=True, help="digest-pinned redroid image reference")
    parser.add_argument("--context", required=True, help="new or empty Docker build context directory")
    parser.add_argument("--android", choices=sorted(PROFILES), default="15", help="guest Android release")
    args = parser.parse_args(argv)
    profile = PROFILES[args.android]
    if profile is None:
        receipt = prepare(args.zip, args.sha256, args.base_image, args.context)
    else:
        receipt = prepare(args.zip, args.sha256, args.base_image, args.context,
                          apk_pins=profile[0], support_files=profile[1])
    json.dump(receipt, sys.stdout, indent=1, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
