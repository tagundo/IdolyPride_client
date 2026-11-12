"""Real synthetic loopback TLS: no user keys or live CDN calls."""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch
from urllib.error import URLError

import pytest
from idoly_local import octo_cache as cache


def command(*args):
    subprocess.run(['openssl',*map(str,args)],check=True,stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL,timeout=10)


def root_certificate(directory,label):
    key=directory/(label+'.key');cert=directory/(label+'.pem')
    command('req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=Synthetic Idoly Test '+label,
            '-addext','basicConstraints=critical,CA:TRUE','-addext','keyUsage=critical,keyCertSign,cRLSign',
            '-keyout',key,'-out',cert)
    key.chmod(0o600)
    return key,cert


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        data=b'verified-local-tls'
        self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def log_message(self,*args):pass


@pytest.mark.skipif(shutil.which('openssl') is None, reason='OpenSSL CLI needed for synthetic TLS certificates')
def test_frozen_https_keeps_verification_and_appends_public_roots():
    with tempfile.TemporaryDirectory(prefix='idoly-owned-tls-probe-') as directory:
        directory=Path(directory);directory.chmod(0o700)
        ca_key,ca=root_certificate(directory,'trusted-root')
        other_key,other=root_certificate(directory,'other-root')
        leaf_key=directory/'leaf.key';csr=directory/'leaf.csr';leaf=directory/'leaf.pem'
        command('req','-new','-newkey','rsa:2048','-nodes','-subj','/CN=localhost','-keyout',leaf_key,'-out',csr)
        leaf_key.chmod(0o600)
        ext=directory/'leaf-extensions';ext.write_text('subjectAltName=DNS:localhost\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n')
        command('x509','-req','-in',csr,'-CA',ca,'-CAkey',ca_key,'-CAcreateserial','-days','1','-extfile',ext,'-out',leaf)
        server=HTTPServer(('127.0.0.1',0),Handler)
        server_context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);server_context.load_cert_chain(leaf,leaf_key)
        server.socket=server_context.wrap_socket(server.socket,server_side=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        bundle_dir=directory/'bundle';bundle_dir.mkdir();bundle=bundle_dir/'cacert.pem';shutil.copyfile(ca,bundle)
        missing=str(directory/'absent-default')
        environment={'SSL_CERT_FILE':missing,'SSL_CERT_DIR':missing,'NO_PROXY':'localhost,127.0.0.1','no_proxy':'localhost,127.0.0.1',
                     'HTTP_PROXY':'','HTTPS_PROXY':'','ALL_PROXY':'','http_proxy':'','https_proxy':'','all_proxy':''}
        statuses={}
        try:
            with patch.dict(os.environ,environment),patch.object(sys,'frozen',True,create=True),patch.object(sys,'_MEIPASS',str(bundle_dir),create=True),patch.object(cache,'_cdn_origin',return_value=True):
                good='https://localhost:'+str(server.server_port)+'/object'
                wrong_host='https://127.0.0.1:'+str(server.server_port)+'/object'
                # This fixed synthetic server has no system/default CA available.
                try:
                    from urllib.request import HTTPSHandler,ProxyHandler,build_opener
                    build_opener(ProxyHandler({}),HTTPSHandler(context=ssl.create_default_context())).open(good,timeout=3)
                    raise AssertionError('Missing default trust unexpectedly succeeded')
                except URLError as error:
                    assert isinstance(error.reason,ssl.SSLCertVerificationError),type(error.reason)
                    statuses['missing_default_trust_fails_verification']=True
                context=cache._frozen_tls_context()
                assert context.verify_mode==ssl.CERT_REQUIRED and context.check_hostname
                statuses['normal_certificate_and_hostname_verification_retained']=True
                with cache.open_upstream(good,timeout=3) as response:
                    assert response.status==200 and response.read()==b'verified-local-tls'
                statuses['appended_bundled_ca_allows_exact_local_leaf']=True
                try:
                    cache.open_upstream(wrong_host,timeout=3)
                    raise AssertionError('Wrong hostname unexpectedly succeeded')
                except URLError as error:
                    assert isinstance(error.reason,ssl.SSLCertVerificationError),type(error.reason)
                    statuses['wrong_hostname_still_rejected']=True
                shutil.copyfile(other,bundle)
                try:
                    cache.open_upstream(good,timeout=3)
                    raise AssertionError('Untrusted root unexpectedly succeeded')
                except URLError as error:
                    assert isinstance(error.reason,ssl.SSLCertVerificationError),type(error.reason)
                    statuses['untrusted_issuer_still_rejected']=True
                with patch.dict(os.environ,{'SSL_CERT_FILE':str(ca)}):
                    with cache.open_upstream(good,timeout=3) as response:
                        assert response.read()==b'verified-local-tls'
                statuses['explicit_environment_ca_trust_preserved_when_bundle_differs']=True
                bundle.unlink()
                try:
                    cache._frozen_tls_context()
                    raise AssertionError('Missing frozen bundle unexpectedly succeeded')
                except cache.OctoCacheError as error:
                    assert error.code=='upstream_tls'
                statuses['missing_packaged_ca_fails_closed_with_tls_code']=True
        finally:
            server.shutdown();server.server_close();thread.join(timeout=3)
        result={'status':'PASS','checks':statuses,'checks_count':len(statuses),'network_scope':'owned loopback HTTPS server only','native_platform':'Linux CPython synthetic transport proof','actual_macos_execution':False,'private_synthetic_keys_removed_by_temporary_directory':True}
    assert result['checks_count'] == 7 and all(result['checks'].values())
