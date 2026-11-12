"""Install a pinned public CA store; never copy the build machine's trust store."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import shutil

CERTIFICATES=Path(__file__).resolve().parent/'certificates'
CERTIFICATE_FILES={
    'cacert.pem':'2ef52ad56b4803e264045c915e55c236cbfa045b84b81efefc218a19eb44bd2b',
    'LICENSE-certifi':'e93716da6b9c0d5a4a1df60fe695b370f0695603d21f6f83f053e42cfc10caf7',
}


def install_certificate_bundle(internal,licenses):
    """Give embedded urllib public roots in addition to configured default trust."""
    internal,licenses=Path(internal),Path(licenses)
    for name,expected in CERTIFICATE_FILES.items():
        path=CERTIFICATES/name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError('Pinned public CA input differs: '+name)
    provenance=json.loads((CERTIFICATES/'provenance.json').read_text())
    if (provenance.get('cacert_sha256')!=CERTIFICATE_FILES['cacert.pem']
            or provenance.get('wheel_sha256')!='e9b54de76e530bb6cf0ccd036787103acb58fd42ba930ea8bf948ddbaa2f61d1'
            or provenance.get('cloud_or_user_ca_added') is not False):
        raise ValueError('Public CA provenance differs')
    internal.mkdir(parents=True,exist_ok=True);licenses.mkdir(parents=True,exist_ok=True)
    destinations=((CERTIFICATES/'cacert.pem',internal/'cacert.pem'),
        (CERTIFICATES/'LICENSE-certifi',licenses/'LICENSE-certifi'),
        (CERTIFICATES/'provenance.json',licenses/'certifi-provenance.json'))
    for source,target in destinations:
        if target.exists() or target.is_symlink(): raise ValueError('CA destination already exists')
        shutil.copyfile(source,target)
    return {**provenance,'runtime_file':'runtime/_internal/cacert.pem',
        'license_directory':'licenses/tls','default_and_explicit_trust_preserved':True}
