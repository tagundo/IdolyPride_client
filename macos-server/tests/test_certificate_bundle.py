from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import hashlib
import shutil
import re
import ssl

import pytest

PATH=Path(__file__).parents[1]/'certificate_bundle.py'
SPEC=spec_from_file_location('mac_certificate_bundle',PATH)
bundle=module_from_spec(SPEC);SPEC.loader.exec_module(bundle)


def test_installed_public_bundle_parses_and_has_exact_original_roots(tmp_path):
    internal,licenses=tmp_path/'runtime',tmp_path/'licenses'
    report=bundle.install_certificate_bundle(internal,licenses)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    baseline=set(context.get_ca_certs(binary_form=True))
    context.load_verify_locations(cafile=str(internal/'cacert.pem'))
    assert context.verify_mode==ssl.CERT_REQUIRED and context.check_hostname
    pem=(internal/'cacert.pem').read_text()
    expected={ssl.PEM_cert_to_DER_cert(value) for value in re.findall(r'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----',pem,re.S)}
    assert len(expected)==report['certificates']==118
    assert set(context.get_ca_certs(binary_form=True))==baseline|expected
    assert hashlib.sha256((internal/'cacert.pem').read_bytes()).hexdigest()==report['cacert_sha256']
    assert (licenses/'LICENSE-certifi').read_bytes()==(bundle.CERTIFICATES/'LICENSE-certifi').read_bytes()
    assert report['cloud_or_user_ca_added'] is False


def test_rejects_modified_build_machine_ca_before_creating_destination(tmp_path,monkeypatch):
    inputs=tmp_path/'inputs';shutil.copytree(bundle.CERTIFICATES,inputs)
    (inputs/'cacert.pem').write_bytes((inputs/'cacert.pem').read_bytes()+b'\n')
    monkeypatch.setattr(bundle,'CERTIFICATES',inputs)
    with pytest.raises(ValueError,match='Pinned public CA input differs'):
        bundle.install_certificate_bundle(tmp_path/'runtime',tmp_path/'licenses')
    assert not (tmp_path/'runtime').exists()
