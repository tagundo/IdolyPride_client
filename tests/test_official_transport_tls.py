"""Real, owned loopback TLS for the fixed official import transport.

Only socket connection routing and the test CA data are monkeypatched. Production
hostname checking, CERT_REQUIRED, ALPN, TLS, HTTP/2, HTTP/1.1 and SDK AES framing
all execute. No official destination is resolved or contacted by these tests.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import threading
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from h2.config import H2Configuration
from h2.connection import H2Connection
from h2.events import DataReceived, RequestReceived, StreamEnded, WindowUpdated

from idoly_local import codec
from idoly_local import official_transport as module

RPC_HOST = "api.game-idolypride.jp"
SEED_HOST = "id.qseed.jp"
FIREBASE_HOST = "identitytoolkit.googleapis.com"
SYNTHETIC_KEY = "AIzaSYNTHETIC_LOOPBACK_PUBLIC_CONFIGURATION"
SYNTHETIC_TOKEN = "SYNTHETIC_LOOPBACK_PRIVATE_TOKEN"


def openssl(*arguments):
    subprocess.run(["openssl",*map(str,arguments)],check=True,timeout=15,
                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


@pytest.fixture(scope="module")
def certificates(tmp_path_factory):
    # A missing test tool is a failed integration gate, not a silent skip.
    assert shutil.which("openssl"), "OpenSSL CLI is required for isolated transport TLS tests"
    root = tmp_path_factory.mktemp("official-owned-loopback-tls")
    root.chmod(0o700)
    ca_key, ca = root/"ca.key", root/"ca.pem"
    ca_config = root/"ca.cnf"
    ca_config.write_text("[req]\nprompt=no\ndistinguished_name=dn\nx509_extensions=ca\n"
        "[dn]\nCN=Owned Idoly Synthetic Test Root\n[ca]\nbasicConstraints=critical,CA:TRUE\n"
        "keyUsage=critical,keyCertSign,cRLSign\n",encoding="ascii")
    openssl("req","-x509","-newkey","rsa:2048","-nodes","-sha256","-days","1",
            "-config",ca_config,"-keyout",ca_key,"-out",ca)
    leaf_key, csr = root/"leaf.key", root/"leaf.csr"
    openssl("req","-new","-newkey","rsa:2048","-nodes","-subj","/CN=Owned Synthetic Leaf",
            "-keyout",leaf_key,"-out",csr)
    leaves = {}
    for label, names in (("valid",[RPC_HOST,SEED_HOST,FIREBASE_HOST]),
                         ("wrong",["unrelated-owned.invalid"])):
        ext, leaf = root/(label+".ext"), root/(label+".pem")
        ext.write_text("subjectAltName="+",".join("DNS:"+name for name in names)
            +"\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
             "extendedKeyUsage=serverAuth\n",encoding="ascii")
        openssl("x509","-req","-in",csr,"-CA",ca,"-CAkey",ca_key,"-CAcreateserial",
                "-days","1","-sha256","-extfile",ext,"-out",leaf)
        leaves[label] = leaf
    ca_key.chmod(0o600);leaf_key.chmod(0o600)
    return SimpleNamespace(ca=ca,key=leaf_key,valid=leaves["valid"],wrong=leaves["wrong"])


class LoopbackPeer:
    """Exactly one TLS connection, bounded I/O, and an always joined worker."""
    def __init__(self, certificates, handler, *, alpn="h2", wrong_host=False):
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2
        # No post-handshake session-ticket writes: the ALPN-negative client
        # deliberately closes immediately after its verified TLS handshake.
        self.context.num_tickets = 0
        self.context.set_alpn_protocols([alpn])
        self.context.load_cert_chain(certificates.wrong if wrong_host else certificates.valid, certificates.key)
        self.server_names = []
        self.context.set_servername_callback(lambda _,name,__ : self.server_names.append(name))
        self.listener = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1",0));self.listener.listen(1);self.listener.settimeout(5)
        self.port = self.listener.getsockname()[1]
        self.handler = handler
        self.accepted = 0
        self.error = None
        self.tls_error = None
        self.connection = None
        self.alpn = None
        self.record = {}
        self.thread = threading.Thread(target=self._run,name="idoly-owned-tls-peer",daemon=True)

    def _run(self):
        raw = None
        try:
            raw,_ = self.listener.accept();self.accepted += 1;raw.settimeout(5)
            self.connection = self.context.wrap_socket(raw,server_side=True)
            self.alpn = self.connection.selected_alpn_protocol()
            self.handler(self.connection,self.record)
        except ssl.SSLError as error:
            self.tls_error = type(error).__name__
        except BaseException as error:
            self.error = error
        finally:
            if self.connection is not None:self.connection.close()
            elif raw is not None:raw.close()

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self,kind,value,traceback):
        # Give the peer time to consume the client's final close/flow update.
        self.thread.join(timeout=6)
        if self.thread.is_alive():
            if self.connection is not None:self.connection.close()
            self.listener.close()
            self.thread.join(timeout=2)
        self.listener.close()
        assert not self.thread.is_alive(), "Owned TLS peer worker was not joined"
        if kind is None and self.error is not None:
            raise self.error


def connect_only_to_owned_peer(monkeypatch,peer,expected_host):
    original = socket.create_connection
    attempts = []
    def connect(address,timeout=socket._GLOBAL_DEFAULT_TIMEOUT,source_address=None,*,all_errors=False):
        attempts.append(address)
        # Check before the real socket call: an unexpected endpoint cannot
        # escape this test through DNS, a proxy or a production host.
        assert address == (expected_host,443), "Unexpected non-owned transport destination"
        return original(("127.0.0.1",peer.port),timeout=timeout,source_address=source_address,
                        all_errors=all_errors)
    monkeypatch.setattr(module.socket,"create_connection",connect)
    return attempts


def trusted_transport(monkeypatch,certificates):
    monkeypatch.setattr(module,"ROOTS_PEM",certificates.ca.read_text(encoding="ascii"))
    client = module.OfficialTransport()
    for context in (client._context,client._http_context):
        assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
        assert context.minimum_version >= ssl.TLSVersion.TLSv1_2
    return client


def h2_handler(reply):
    encoded = codec.encode(reply)
    response = b"\0" + len(encoded).to_bytes(4,"big") + encoded
    def handle(connection,record):
        peer = H2Connection(H2Configuration(client_side=False,header_encoding="ascii"))
        peer.initiate_connection()
        # Exercise a real connection-level WINDOW_UPDATE in addition to the
        # client updates needed to receive a response larger than 65535 bytes.
        peer.increment_flow_control_window(1024*1024)
        connection.sendall(peer.data_to_send())
        request = bytearray()
        ready = trailers = False
        offset = 0
        window_updates = 0
        window_waits = 0
        while True:
            data = connection.recv(65536)
            if not data:
                break
            for event in peer.receive_data(data):
                if isinstance(event,RequestReceived):
                    record["headers"] = dict(event.headers)
                elif isinstance(event,DataReceived):
                    assert event.stream_id == 1
                    request.extend(event.data)
                    peer.acknowledge_received_data(event.flow_controlled_length,event.stream_id)
                elif isinstance(event,StreamEnded):
                    assert event.stream_id == 1 and not ready
                    ready = True
                    peer.send_headers(1,[(":status","200"),("content-type","application/grpc+proto"),
                                         ("x-error-code","0")])
                elif isinstance(event,WindowUpdated):
                    window_updates += 1
            if ready:
                while offset < len(response):
                    amount = min(len(response)-offset,peer.local_flow_control_window(1),peer.max_outbound_frame_size)
                    if not amount:
                        window_waits += 1
                        break
                    peer.send_data(1,response[offset:offset+amount]);offset += amount
                if offset == len(response) and not trailers:
                    peer.send_headers(1,[("grpc-status","0")],end_stream=True)
                    trailers = True
            pending = peer.data_to_send()
            if pending:connection.sendall(pending)
        record.update(request=bytes(request),response_bytes=offset,trailers=trailers,
                      window_updates=window_updates,window_waits=window_waits)
    return handle


def http_handler(body,status=200,extra_headers=()):
    def handle(connection,record):
        stream = connection.makefile("rb")
        try:
            first = stream.readline(8193)
            assert first.endswith(b"\r\n") and len(first) <= 8192
            method,path,version = first[:-2].decode("ascii").split(" ")
            headers = {}
            while True:
                line = stream.readline(8193)
                assert line and len(line) <= 8192
                if line == b"\r\n":break
                key,value = line[:-2].decode("ascii").split(":",1)
                assert key.lower() not in headers
                headers[key.lower()] = value.strip()
            length = int(headers.get("content-length","0"));assert 0 <= length <= 32768
            request = stream.read(length)
            assert len(request) == length
            record.update(method=method,path=path,version=version,headers=headers,body=request)
            head = [("Content-Length",str(len(body))),("Content-Type","application/json"),
                    ("Connection","close"),*extra_headers]
            response = "HTTP/1.1 "+str(status)+" Synthetic\r\n"+"".join(k+": "+v+"\r\n" for k,v in head)+"\r\n"
            connection.sendall(response.encode("ascii")+body)
        finally:
            stream.close()
    return handle


def seed_headers():
    return {"X-Device":"synthetic-device","X-Ad":"synthetic-ad","X-App":"game.qualiarts.idolypride",
            "X-AppVersion":"6.1.1","X-SeedVersion":"1"}


def test_actual_tls_h2_unary_crypto_fixed_hostname_and_flow_control(monkeypatch,certificates):
    plain = bytes(range(256))*1024
    request = b"synthetic-protobuf-request"
    client = trusted_transport(monkeypatch,certificates)
    with LoopbackPeer(certificates,h2_handler(plain)) as peer:
        attempts = connect_only_to_owned_peer(monkeypatch,peer,RPC_HOST)
        assert client.rpc("/api.User/Get",request,{"x-auth-token":SYNTHETIC_TOKEN},timeout=5) == plain
    assert attempts == [(RPC_HOST,443)] and peer.accepted == 1
    assert peer.alpn == "h2" and peer.server_names == [RPC_HOST]
    record = peer.record
    assert record["trailers"] and record["response_bytes"] > 65535
    assert record["window_updates"] > 0 and record["window_waits"] > 0
    headers,framed = record["headers"],record["request"]
    assert headers[":authority"] == RPC_HOST and headers[":scheme"] == "https"
    assert headers[":path"] == "/api.User/Get" and headers["x-auth-token"] == SYNTHETIC_TOKEN
    assert framed[0] == 0 and int.from_bytes(framed[1:5],"big") == len(framed)-5
    assert codec.decode(framed[5:]) == request
    assert not peer.tls_error and not peer.error


@pytest.mark.parametrize("operation",["seed","signin","lookup"])
def test_actual_https_seed_firebase_fixed_scope_and_http1_alpn(monkeypatch,certificates,operation):
    expected_host = SEED_HOST if operation == "seed" else FIREBASE_HOST
    response = b"synthetic-seed" if operation == "seed" else (
        b'{"idToken":"synthetic-id-token"}' if operation == "signin" else b'{"users":[{"localId":"synthetic-uid"}]}')
    client = trusted_transport(monkeypatch,certificates)
    # These deliberately unusable proxy variables must not redirect the direct
    # verified HTTPS transport. No real proxy or external DNS is available.
    for key in ("HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","http_proxy","https_proxy","all_proxy"):
        monkeypatch.setenv(key,"http://non-owned-proxy.invalid:9")
    with LoopbackPeer(certificates,http_handler(response),alpn="http/1.1") as peer:
        attempts = connect_only_to_owned_peer(monkeypatch,peer,expected_host)
        if operation == "seed":
            assert client.seed(seed_headers()) == "synthetic-seed"
        else:
            payload = {"token":SYNTHETIC_TOKEN,"returnSecureToken":True} if operation == "signin" else {"idToken":SYNTHETIC_TOKEN}
            value = client.firebase(operation,SYNTHETIC_KEY,payload,
                {"X-Ios-Bundle-Identifier":"game.qualiarts.idolypride"})
            assert value == json.loads(response)
    assert attempts == [(expected_host,443)] and peer.accepted == 1
    assert peer.alpn == "http/1.1" and peer.server_names == [expected_host]
    record = peer.record
    assert record["headers"]["host"] == expected_host and record["version"] == "HTTP/1.1"
    if operation == "seed":
        assert record["method"] == "GET" and record["path"] == "/getId" and record["body"] == b""
        assert record["headers"]["x-app"] == "game.qualiarts.idolypride"
    else:
        url = urlsplit(record["path"])
        assert record["method"] == "POST" and parse_qs(url.query) == {"key":[SYNTHETIC_KEY]}
        assert url.path == ("/v1/accounts:signInWithCustomToken" if operation == "signin" else "/v1/accounts:lookup")
        assert json.loads(record["body"]) == payload
        assert record["headers"]["x-ios-bundle-identifier"] == "game.qualiarts.idolypride"
    assert not peer.tls_error and not peer.error


@pytest.mark.parametrize("operation",["rpc","seed"])
@pytest.mark.parametrize("failure",["hostname","untrusted"])
def test_actual_tls_rejects_wrong_hostname_or_untrusted_root_without_retry(monkeypatch,certificates,operation,failure):
    client = trusted_transport(monkeypatch,certificates) if failure == "hostname" else module.OfficialTransport()
    expected_host = RPC_HOST if operation == "rpc" else SEED_HOST
    alpn = "h2" if operation == "rpc" else "http/1.1"
    with LoopbackPeer(certificates,lambda connection,record: record.update(unexpected_request=True),
                      alpn=alpn,wrong_host=failure == "hostname") as peer:
        attempts = connect_only_to_owned_peer(monkeypatch,peer,expected_host)
        with pytest.raises(module.OfficialTransportError) as stopped:
            if operation == "rpc":client.rpc("/api.User/Get",b"",{},timeout=5)
            else:client.seed(seed_headers())
        assert stopped.value.code == "tls_failed"
        assert SYNTHETIC_TOKEN not in str(stopped.value) and expected_host not in str(stopped.value)
    assert attempts == [(expected_host,443)] and peer.accepted == 1
    assert peer.server_names == [expected_host] and peer.tls_error
    assert "unexpected_request" not in peer.record and not peer.error


def test_actual_tls_h2_requires_negotiated_h2_alpn(monkeypatch,certificates):
    client = trusted_transport(monkeypatch,certificates)
    with LoopbackPeer(certificates,lambda connection,record: record.update(after_handshake=connection.recv(1)),
                      alpn="http/1.1") as peer:
        attempts = connect_only_to_owned_peer(monkeypatch,peer,RPC_HOST)
        with pytest.raises(module.OfficialTransportError) as stopped:
            client.rpc("/api.User/Get",b"",{},timeout=5)
        assert stopped.value.code == "tls_alpn_invalid"
    assert attempts == [(RPC_HOST,443)] and peer.alpn is None
    assert peer.record["after_handshake"] == b"" and not peer.error


def test_actual_https_rejects_redirect_without_second_connection(monkeypatch,certificates):
    client = trusted_transport(monkeypatch,certificates)
    with LoopbackPeer(certificates,http_handler(b"",302,[("Location","https://non-owned.invalid/secret")]),
                      alpn="http/1.1") as peer:
        attempts = connect_only_to_owned_peer(monkeypatch,peer,SEED_HOST)
        with pytest.raises(module.OfficialTransportError) as stopped:
            client.seed(seed_headers())
        assert stopped.value.code == "http_redirect_rejected" and "non-owned" not in str(stopped.value)
    assert attempts == [(SEED_HOST,443)] and peer.accepted == 1
    assert peer.record["path"] == "/getId" and not peer.error
