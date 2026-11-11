"""Synthetic SDK archive shapes only; no account, filesystem or network access."""
import base64
from dataclasses import FrozenInstanceError, asdict
import json
import math
import plistlib

import pytest

from idoly_local.firebase_archive import (
    FirebaseArchiveError, parse_firebase_archive, select_candidate, summarize_candidates,
)
from idoly_local import firebase_archive as module


APP = '1:123456:ios:abcdef123456'
PROJECT = 'synthetic-idoly-project'
API_KEY = 'SYNTHETIC_PUBLIC_API_KEY'
UID = 'SYNTHETIC_PRIVATE_USER_ID'
REFRESH = 'SYNTHETIC_PRIVATE_REFRESH_TOKEN'
NOW = 1794350000
COCOA_EPOCH = 978307200


def jwt(uid=UID, issued=NOW - 100, expires=NOW + 3500, **changes):
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).decode().rstrip('=')
    claims = {'sub': uid, 'aud': PROJECT, 'iss': 'https://securetoken.google.com/' + PROJECT,
              'iat': issued, 'exp': expires, 'auth_time': issued - 1}
    claims.update(changes)
    # An inert signature is deliberate. The reader must NEVER claim verification.
    return encode({'alg': 'RS256', 'typ': 'JWT', 'kid': 'synthetic'}) + '.' + encode(claims) + '.' + \
        base64.urlsafe_b64encode(b'not-a-real-signature-at-all-123456').decode().rstrip('=')


def archive_document(*, uid=UID, issued=NOW - 100, expires=NOW + 3500, token=None, refresh=REFRESH):
    # The exact NSCoding keys/class names come from public SDK11.14.0 source.
    objects = ['$null']
    def add(value):
        objects.append(value)
        return plistlib.UID(len(objects) - 1)
    def cls(name):
        return add({'$classname': name, '$classes': [name, 'NSObject']})
    user_class, service_class, date_class = cls('FIRUser'), cls('FIRSecureTokenService'), cls('NSDate')
    date = add({'$class': date_class, 'NS.time': float(expires - COCOA_EPOCH)})
    service = add({'$class': service_class, 'accessToken': add(token or jwt(uid, issued, expires)),
                   'refreshToken': add(refresh), 'accessTokenExpirationDate': date,
                   'APIKey': add(API_KEY)})
    root = add({'$class': user_class, 'userID': add(uid), 'firebaseAppID': add(APP),
                'APIKey': add(API_KEY), 'tokenService': service, 'tenantID': plistlib.UID(0),
                # Irrelevant identity fields must not be retained or shown.
                'email': add('SYNTHETIC_PRIVATE_EMAIL@example.invalid'),
                'displayName': add('SYNTHETIC_PRIVATE_DISPLAY_NAME')})
    return {'$archiver': 'NSKeyedArchiver', '$version': 100000,
            '$objects': objects, '$top': {'root': root}}


def raw_archive(**kwargs):
    return plistlib.dumps(archive_document(**kwargs), fmt=plistlib.FMT_BINARY, sort_keys=False)


def parse(raw=None, **kwargs):
    return parse_firebase_archive(raw or raw_archive(), expected_app_id=APP,
        expected_project_id=PROJECT, expected_api_key=API_KEY, **kwargs)


def root(document):
    return document['$objects'][document['$top']['root'].data]


def service(document):
    return document['$objects'][root(document)['tokenService'].data]


def dump(document):
    return plistlib.dumps(document, fmt=plistlib.FMT_BINARY, sort_keys=False)


def test_exact_sdk_shape_returns_only_memory_credentials_with_redacted_repr(capsys):
    value = parse()
    assert value.firebase_uid == UID and value.app_id == value.google_app_id == APP
    assert value.api_key == API_KEY and value.project_id == PROJECT
    assert value.id_token == value.access_token == jwt() and value.refresh_token == REFRESH
    assert value.issued_at == NOW - 100 and value.expires_at_ms == (NOW + 3500) * 1000
    assert value.stored_expiration == NOW + 3500 and value.is_current(NOW)
    assert value.signature_verified is False
    for secret in (UID, REFRESH, value.id_token, 'SYNTHETIC_PRIVATE_EMAIL', 'SYNTHETIC_PRIVATE_DISPLAY_NAME'):
        assert secret not in repr(value) and secret not in str(value)
    assert 'email' not in value.__dataclass_fields__ and 'displayName' not in value.__dataclass_fields__
    assert capsys.readouterr() == ('', '')
    with pytest.raises(FrozenInstanceError):
        value.refresh_token = 'changed'


def test_optional_sdk_token_date_may_be_absent():
    document = archive_document()
    service(document)['accessTokenExpirationDate'] = plistlib.UID(0)
    assert parse(dump(document)).stored_expiration is None


@pytest.mark.parametrize('kind', ('other_app', 'other_key', 'other_service_key', 'tenant', 'uid_mismatch',
                                   'aud', 'issuer', 'wrong_user_class', 'wrong_service_class'))
def test_scope_and_sdk_class_mismatches_fail_without_exposing_fields(kind):
    document = archive_document()
    user, token_service = root(document), service(document)
    if kind == 'other_app': user['firebaseAppID'] = '1:99999:ios:abcdef'
    elif kind == 'other_key': user['APIKey'] = 'WRONG_PRIVATE_KEY'
    elif kind == 'other_service_key': token_service['APIKey'] = 'WRONG_PRIVATE_KEY'
    elif kind == 'tenant': user['tenantID'] = 'SYNTHETIC_PRIVATE_TENANT'
    elif kind == 'uid_mismatch': user['userID'] = 'OTHER_PRIVATE_UID'
    elif kind == 'aud': token_service['accessToken'] = jwt(aud='other-project')
    elif kind == 'issuer': token_service['accessToken'] = jwt(iss='https://example.invalid/')
    elif kind == 'wrong_user_class': document['$objects'][user['$class'].data]['$classname'] = 'ArbitraryClass'
    elif kind == 'wrong_service_class': document['$objects'][token_service['$class'].data]['$classname'] = 'ArbitraryClass'
    with pytest.raises(FirebaseArchiveError) as error:
        parse(dump(document))
    for secret in (UID, REFRESH, 'WRONG_PRIVATE_KEY', 'SYNTHETIC_PRIVATE_TENANT', 'OTHER_PRIVATE_UID'):
        assert secret not in str(error.value)


@pytest.mark.parametrize('field', ('userID', 'firebaseAppID', 'APIKey', 'tokenService'))
def test_missing_required_user_fields_fail_closed(field):
    document = archive_document()
    del root(document)[field]
    with pytest.raises(FirebaseArchiveError): parse(dump(document))


@pytest.mark.parametrize('field', ('accessToken', 'refreshToken'))
def test_missing_required_token_fields_fail_closed(field):
    document = archive_document()
    del service(document)[field]
    with pytest.raises(FirebaseArchiveError): parse(dump(document))


@pytest.mark.parametrize('mutation', ('cycle', 'unreachable_cycle', 'bad_ref', 'huge_ref', 'extra_root',
                                    'object_limit', 'deep_container', 'nan_date', 'wrong_date'))
def test_archive_graph_and_date_bounds(mutation):
    document = archive_document()
    if mutation == 'cycle': root(document)['email'] = document['$top']['root']
    elif mutation == 'unreachable_cycle':
        document['$objects'].append({'cycle': plistlib.UID(len(document['$objects']))})
    elif mutation == 'bad_ref': root(document)['tokenService'] = plistlib.UID(len(document['$objects']))
    elif mutation == 'huge_ref': root(document)['tokenService'] = plistlib.UID((1 << 63) - 1)
    elif mutation == 'extra_root': document['$top']['other'] = document['$top']['root']
    elif mutation == 'object_limit': document['$objects'].extend('x' for _ in range(4100))
    elif mutation == 'deep_container':
        nested = []
        for _ in range(70): nested = [nested]
        document['unused'] = nested
    elif mutation == 'nan_date':
        document['$objects'][service(document)['accessTokenExpirationDate'].data]['NS.time'] = math.nan
    elif mutation == 'wrong_date':
        document['$objects'][service(document)['accessTokenExpirationDate'].data]['NS.time'] = 'PRIVATE_DATE'
    with pytest.raises(FirebaseArchiveError): parse(dump(document))


@pytest.mark.parametrize('raw', (b'', b'x' * 100, b'x' * (2 * 1024 * 1024 + 1),
                               plistlib.dumps({'x': 'secret'}, fmt=plistlib.FMT_XML)))
def test_nonbinary_oversize_and_malformed_inputs(raw):
    with pytest.raises(FirebaseArchiveError): parse_firebase_archive(raw, expected_app_id=APP, expected_project_id=PROJECT)


def test_malicious_binary_trailer_is_rejected_before_plist_allocation(monkeypatch):
    raw = bytearray(raw_archive())
    raw[-24:-16] = ((1 << 64) - 1).to_bytes(8, 'big')
    monkeypatch.setattr(plistlib, 'loads', lambda _: pytest.fail('must reject before allocation'))
    with pytest.raises(FirebaseArchiveError, match='invalid_archive_table'):
        parse(bytes(raw))


@pytest.mark.parametrize('claims', ({'iat': True}, {'exp': 0}, {'exp': NOW + 1000000},
                                   {'auth_time': NOW + 100}, {'exp': 'PRIVATE_EXP'}))
def test_invalid_jwt_times_are_not_accepted(claims):
    token = jwt(**claims)
    with pytest.raises(FirebaseArchiveError): parse(raw_archive(token=token))


def test_jwt_duplicate_claims_and_non_rs256_are_rejected():
    token = jwt()
    header, payload, signature = token.split('.')
    duplicate = base64.urlsafe_b64encode(b'{"aud":"one","aud":"two"}').decode().rstrip('=')
    none_header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip('=')
    for bad in (header + '.' + duplicate + '.' + signature, none_header + '.' + payload + '.' + signature):
        with pytest.raises(FirebaseArchiveError): parse(raw_archive(token=bad))


@pytest.mark.parametrize('firebase', ({'tenant': 'SYNTHETIC_PRIVATE_TENANT'},
                                     'PRIVATE_NOT_A_DICTIONARY', None, []))
def test_token_tenant_cannot_bypass_absent_archive_tenant(firebase):
    with pytest.raises(FirebaseArchiveError) as failure:
        parse(raw_archive(token=jwt(firebase=firebase)))
    assert 'SYNTHETIC_PRIVATE_TENANT' not in str(failure.value)


def test_extreme_integer_date_never_escapes_as_overflow():
    reader = object.__new__(module._Archive)
    reader.objects = ['$null', {'$classname': 'NSDate', '$classes': ['NSDate', 'NSObject']},
                      {'$class': plistlib.UID(1), 'NS.time': 1 << 100000}]
    with pytest.raises(FirebaseArchiveError, match='invalid_archive_date'):
        reader.date(plistlib.UID(2))


def test_same_account_128_archives_choose_newest_current_claims_not_first_row():
    candidates = [parse(raw_archive(issued=NOW - 1000 + index, expires=NOW + 1000 + index))
                  for index in range(128)]
    summaries = summarize_candidates(candidates, now=NOW)
    assert len(summaries) == 1 and summaries[0].candidate_count == summaries[0].current_candidate_count == 128
    assert summaries[0].group_number == 1 and summaries[0].latest_issued_at == NOW - 873
    assert select_candidate(candidates, now=NOW) is candidates[-1]
    encoded = json.dumps([asdict(row) for row in summaries])
    assert UID not in encoded and REFRESH not in encoded and 'SYNTHETIC_PRIVATE' not in encoded


def test_multiple_accounts_never_autochoose_even_when_latest_is_newer():
    first = parse(raw_archive())
    other = parse(raw_archive(uid='SYNTHETIC_OTHER_PRIVATE_USER', issued=NOW - 1))
    candidates = [first, other]
    assert [row.group_number for row in summarize_candidates(candidates, now=NOW)] == [1, 2]
    with pytest.raises(FirebaseArchiveError, match='multiple_accounts_require_selection'):
        select_candidate(candidates, now=NOW)
    assert select_candidate(candidates, now=NOW, group_number=2) is other


def test_expired_credentials_require_explicit_offline_refresh_selection():
    old = parse(raw_archive(issued=NOW - 5000, expires=NOW - 1000))
    assert not old.is_current(NOW) and summarize_candidates([old], now=NOW)[0].current_candidate_count == 0
    with pytest.raises(FirebaseArchiveError, match='no_current_candidate'):
        select_candidate([old], now=NOW)
    assert select_candidate([old], now=NOW, require_current=False) is old
    assert old.signature_verified is False


def test_same_time_different_credential_pairs_are_ambiguous():
    first = parse(raw_archive())
    second = parse(raw_archive(refresh='ANOTHER_PRIVATE_REFRESH'))
    with pytest.raises(FirebaseArchiveError, match='ambiguous_same_time_candidates'):
        select_candidate([first, second], now=NOW)
    assert select_candidate([first, first], now=NOW) is first


def test_future_archives_do_not_override_eligible_current_archive():
    first = parse(raw_archive())
    future = parse(raw_archive(issued=NOW + 3600, expires=NOW + 7200))
    assert select_candidate([future, first], now=NOW) is first


@pytest.mark.parametrize('group', (0, -1, True, '1', 2))
def test_invalid_opaque_group_numbers_fail(group):
    with pytest.raises(FirebaseArchiveError): select_candidate([parse()], now=NOW, group_number=group)
