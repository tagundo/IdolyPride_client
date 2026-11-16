"""Offline boundaries for the finite latest public-cohort compiler.

The positive original 202-pack/125-model/locale-cohort gate is performed by the
remote prep job. These units do not call the official services or mutate state.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('prepare_latest_data',ROOT/'tools/prepare_latest_server_data.py')
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)


def test_duplicate_nonfinite_and_path_inputs_rejected():
    for raw in (b'{"x":1,"x":2}',b'{"x":NaN}'):
        with pytest.raises((m.PreparationError,ValueError)):m.decode(raw)
    for name in ('data/../state.sqlite3','data/a/./b','/data/a','data/a\\b','data/a:b','data/x/'):
        assert not m.safe_name(name)
    assert m.safe_name('data/master-json/Card.json')


@pytest.mark.parametrize('name',('data/../secret','outside','data/file\\name'))
def test_archive_cannot_escape_public_root(tmp_path,name):
    path=tmp_path/'bad.zip'
    with ZipFile(path,'w') as archive:archive.writestr(name,b'x')
    with ZipFile(path) as archive,pytest.raises(m.PreparationError):m.archive_rows(archive)


def test_archive_duplicate_and_empty_members_rejected(tmp_path):
    for names in ((('data/a',b'x'),('data/a',b'y')),(('data/a',b''),)):
        path=tmp_path/str(len(list(tmp_path.iterdir())))
        with ZipFile(path,'w') as archive:
            for name,raw in names:archive.writestr(name,raw)
        with ZipFile(path) as archive,pytest.raises(m.PreparationError):m.archive_rows(archive)


def test_payload_member_inventory_and_fixed_metadata(tmp_path):
    public=tmp_path/'public';(public/'master-json').mkdir(parents=True)
    (public/'master-json/Card.json').write_bytes(b'[]')
    (public/'master-json/!version.txt').write_text(m.MASTER_VERSION)
    output=tmp_path/'ServerData.zip';m.write_payload(public,output)
    with ZipFile(output) as archive:
        assert m.archive_rows(archive)==m.file_rows(public)
        assert all(info.date_time==m.STAMP and not info.extra and not info.comment for info in archive.infolist())
    with pytest.raises(FileExistsError):m.write_payload(public,output)


def test_preservation_classifies_full_member_set_and_changed_bytes():
    def row(path,raw):return {'path':path,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    before=[row('data/keep',b'k'),row('data/change',b'o'),row('data/remove',b'r')]
    after=[row('data/keep',b'k'),row('data/change',b'n'),row('data/add',b'a')]
    assert m.preservation(before,after)=={'unchanged_paths':['data/keep'],'replaced_paths':['data/change'],
        'removed_paths':['data/remove'],'added_paths':['data/add']}


def test_sdk_request_is_application_only_and_decrypts_actual_cbc_wire():
    from Crypto.Cipher import AES
    key=bytes(range(32));iv=bytes(range(16));plain=b'original public protobuf bytes'
    count=16-len(plain)%16;wire=iv+AES.new(key,AES.MODE_CBC,iv).encrypt(plain+bytes([count])*count)
    observed=[]
    def fetch(url,headers,maximum):observed.append((url,headers,maximum));return wire
    settings={'application_id':212,'application_version':105051,'client_key':'PUBLIC-APPLICATION-KEY','aes_key_hex':key.hex()}
    value,backend=m.sdk_manifest(settings,fetch=fetch)
    assert value==plain
    assert observed==[('https://api.octo-cloud.com/v2/pub/a/212/v/105051/list/0',
        {'Accept':'application/x-protobuf,x-octo-app/212','X-OCTO-KEY':'PUBLIC-APPLICATION-KEY'},m.MAX_METADATA+1024)]
    assert backend(False,key,iv,wire[16:])==plain+bytes([count])*count


@pytest.mark.parametrize('wire',(b'',b'x'*17,b'x'*(m.MAX_METADATA+1025)))
def test_sdk_rejects_invalid_extents_and_padding(wire):
    settings={'application_id':212,'application_version':205051,'client_key':'public','aes_key_hex':'00'*32}
    with pytest.raises(ValueError):m.sdk_manifest(settings,fetch=lambda *_:wire)


def test_photography_projection_preserves_quest_order_and_owner():
    tables={'Area':[{'id':'area-main-002','type':1,'questIds':['q2','q1'],'unrelated':99}],
            'Quest':[{'id':'q1','areaId':'area-main-002','reward':'ignored'},{'id':'q2','areaId':'area-main-002'}]}
    assert m.photography_projection(tables)=={'schema':1,'area':{'id':'area-main-002','type':1,'questIds':['q2','q1']},
        'quests':[{'id':'q2','areaId':'area-main-002'},{'id':'q1','areaId':'area-main-002'}]}
    tables['Quest'].pop()
    with pytest.raises(m.PreparationError):m.photography_projection(tables)


def test_panorama_projection_uses_exact_fifteen_rule_order_and_cameras():
    from idoly_local.panorama_rules import PANORAMA_RULES,MASTER_PANORAMA_RULES
    rules=(*PANORAMA_RULES,*MASTER_PANORAMA_RULES)
    tables={'Music':[{'id':r.music_id,'assetId':r.music_id[6:],'is360LiveExist':True,'displayCharacterAmount':5,
                     'selectableStageIds':[r.stage_id],'releaseTime':'1788145200000'} for r in rules],
            'Stage':[{'id':name,'assetId':name[6:],'cameraPositions':[{'name':'first','index':0,'ignored':42},
                {'name':'second','index':1}]} for name in sorted({r.stage_id for r in rules})]}
    value=m.panorama_projection(tables)
    assert [row['id'] for row in value['musics']]==[r.music_id for r in rules]
    assert value['musics'][-1]['releaseTime']=='1788145200000'
    assert all('releaseTime' not in row for row in value['musics'][:-1])
    assert value['stages'][0]['cameraPositions']==[{'name':'first','index':0},{'name':'second','index':1}]


def schema_stub():
    fields={name:SimpleNamespace(number=number,type=kind,is_repeated=False)
            for name,number,kind in (('cardId',1,9),('displayType',2,14),('imageType',3,14))}
    return SimpleNamespace(pool=SimpleNamespace(FindMessageTypeByName=lambda _:SimpleNamespace(fields_by_name=fields)))


def image_database(asset,*,omit=None):
    rows=[SimpleNamespace(id=index+1,name='img_card_'+kind+'_1_'+asset,state=1,size=100,md5='a'*32)
          for index,kind in enumerate(('thumb','rect','full','upper')) if kind!=omit]
    return SimpleNamespace(assetBundleList=[],resourceList=rows)


def test_new_card_requires_original_image_signature_and_all_shared_families():
    audit=m.audit_module();before={'Card':[{'id':'old','assetId':'old-asset'}]}
    after={'Card':[*before['Card'],{'id':'new','assetId':'new-asset'}]}
    old=[{'cardId':'old','displayType':2,'imageType':3}];new=[*old,{'cardId':'new','displayType':2,'imageType':3}]
    db={'ios':(image_database('old-asset'),image_database('new-asset'))}
    receipt=m.card_image_requirements(schema_stub(),before,after,old,new,db,audit)
    assert receipt[0]['control_cards']==['old']
    assert len(receipt[0]['platforms']['ios']['records'])==4
    db['ios']=(image_database('old-asset'),image_database('new-asset',omit='full'))
    with pytest.raises(m.PreparationError,match='latest_added_card_image_family_missing'):
        m.card_image_requirements(schema_stub(),before,after,old,new,db,audit)
    with pytest.raises(m.PreparationError,match='latest_added_card_image_record_missing'):
        m.card_image_requirements(schema_stub(),before,after,old,old,db,audit)


def test_semantic_receipt_rejects_missing_feature_and_binds_exact_content():
    receipt={'schema':1,'projection_equal':True}
    value=m.semantic_envelope('media_access',receipt)
    assert value['receipt_sha256']==hashlib.sha256(m.canonical(receipt)).hexdigest()
    assert value['master_version']==m.MASTER_VERSION
    for key,body in (('unknown',receipt),('dream',{}),('dream',{'status':'FAIL'})):
        with pytest.raises(m.PreparationError):m.semantic_envelope(key,body)


def test_apply_checks_static_whole_blob_before_creating_output(tmp_path,monkeypatch):
    base=tmp_path/'base';base.write_bytes(b'base')
    source=tmp_path/'blob';source.write_bytes(b'blob')
    monkeypatch.setattr(m,'BASE_BYTES',4);monkeypatch.setattr(m,'BASE_SHA256',hashlib.sha256(b'base').hexdigest())
    class Pin:
        def load_pin(self):return {'upgrade_proof':{'proof':'fixed'}}
        def verify_overlay(self,path):raise ValueError('static_pin_differs')
    monkeypatch.setattr(m,'latest_pin_helper',lambda:Pin())
    output=tmp_path/'out'
    with pytest.raises(ValueError,match='static_pin_differs'):m.upgrade_server_data(base,output,overlay_zip=source)
    assert not output.exists() and source.read_bytes()==b'blob' and base.read_bytes()==b'base'


def test_apply_keeps_existing_output_and_calls_exact_proof(tmp_path,monkeypatch):
    base=tmp_path/'base';base.write_bytes(b'base');source=tmp_path/'source';source.write_bytes(b'blob')
    monkeypatch.setattr(m,'BASE_BYTES',4);monkeypatch.setattr(m,'BASE_SHA256',hashlib.sha256(b'base').hexdigest())
    calls=[]
    class Pin:
        def load_pin(self):return {'upgrade_proof':{'proof':'fixed'}}
        def verify_overlay(self,path):calls.append(('overlay',Path(path).read_bytes()))
        def verify_payload(self,path):calls.append(('payload',Path(path).read_bytes()))
        def verify_upgrade_proof(self,proof):calls.append(('proof',proof));return proof
    monkeypatch.setattr(m,'latest_pin_helper',lambda:Pin())
    output=tmp_path/'out';assert m.upgrade_server_data(base,output,overlay_zip=source)=={'proof':'fixed'}
    assert output.read_bytes()==b'blob' and calls==[('overlay',b'blob'),('payload',b'blob'),('proof',{'proof':'fixed'})]
    with pytest.raises(m.PreparationError):m.upgrade_server_data(base,output,overlay_zip=source)
    assert not list(tmp_path.glob('.latest-cohort-*'))


def test_artifact_admission_copies_partial_bounded_failure_without_modifying_source(tmp_path):
    source=tmp_path/'proof';source.mkdir();raw=b'{"status":"FAIL"}\n'
    (source/'latest-server-data.report.json').write_bytes(raw)
    destination=tmp_path/'artifact'
    assert m.admit_proof_artifact(source,destination) is True
    assert (destination/'latest-server-data.report.json').read_bytes()==raw
    assert (source/'latest-server-data.report.json').read_bytes()==raw


@pytest.mark.parametrize('kind',('oversize','aggregate','symlink','unexpected','missing'))
def test_artifact_admission_never_exports_unbounded_or_arbitrary_files(tmp_path,monkeypatch,kind):
    source=tmp_path/'proof'
    if kind!='missing':source.mkdir()
    if kind=='oversize':(source/'latest-server-data.report.json').write_bytes(b'x'*1025)
    elif kind=='aggregate':
        (source/'latest-server-data.report.json').write_bytes(b'{"padding":"'+b'x'*580+b'"}')
        (source/'latest-octo-proof.json').write_bytes(b'{"padding":"'+b'y'*580+b'"}')
    elif kind=='symlink':
        outside=tmp_path/'outside';outside.write_bytes(b'not-exported')
        (source/'latest-server-data.report.json').symlink_to(outside)
    elif kind=='unexpected':(source/'private-collection.log').write_bytes(b'not-exported')
    monkeypatch.setattr(m,'MAX_PROOF',1024)
    destination=tmp_path/'artifact'
    assert m.admit_proof_artifact(source,destination) is False
    assert {path.name for path in destination.iterdir()}=={'latest-server-data.report.json'}
    value=json.loads((destination/'latest-server-data.report.json').read_bytes())
    assert value=={'schema':1,'status':'FAIL','phase':'proof_artifact_admission','error_code':'latest_proof_artifact_rejected'}
    assert sum(path.stat().st_size for path in destination.iterdir())<1024


def test_explicit_no_base_copy_still_requires_static_blob_payload_and_proof(tmp_path,monkeypatch):
    source=tmp_path/'source';source.write_bytes(b'whole-new-cohort')
    calls=[]
    def forbidden_base(*args):raise AssertionError('No BASE file was supplied')
    monkeypatch.setattr(m,'pin_file',forbidden_base)
    class Pin:
        def load_pin(self):return {'upgrade_proof':{'historical_base':'fixed-prep-provenance'}}
        def verify_overlay(self,path):calls.append('blob')
        def verify_payload(self,path):
            assert Path(path).read_bytes()==b'whole-new-cohort';calls.append('payload')
        def verify_upgrade_proof(self,proof):calls.append('proof');return proof
    monkeypatch.setattr(m,'latest_pin_helper',lambda:Pin())
    output=tmp_path/'output'
    assert m.upgrade_server_data(None,output,overlay_zip=source)=={'historical_base':'fixed-prep-provenance'}
    assert calls==['blob','payload','proof']
    class BadPin(Pin):
        def verify_overlay(self,path):raise ValueError('static_blob_differs')
    monkeypatch.setattr(m,'latest_pin_helper',lambda:BadPin())
    with pytest.raises(ValueError,match='static_blob_differs'):
        m.upgrade_server_data(None,tmp_path/'bad-output',overlay_zip=source)
    assert not (tmp_path/'bad-output').exists()


def test_fixed_callback_failure_receipt_does_not_become_pass_or_export_raw_error(tmp_path,monkeypatch):
    import idoly_local.story_read_rules as story_rules
    import idoly_local.dream as dream
    import idoly_local.live_input as main_live
    monkeypatch.setattr(m,'table_rows',lambda *args,**kwargs:[{'id':'public'}])
    monkeypatch.setattr(m,'source_table_proofs',lambda *args,**kwargs:{'public':{'sha256':'a'*64}})
    monkeypatch.setattr(m,'photography_projection',lambda *_:{'schema':1,'original':True})
    monkeypatch.setattr(m,'panorama_projection',lambda *_:{'schema':1,'original':True})
    monkeypatch.setattr(m,'media_external_controls',lambda *args,**kwargs:{'unchanged':True})
    monkeypatch.setattr(story_rules,'audit_story_semantics',lambda *_:{'story_rewards_sha256':'b'*64})
    class Failure(ValueError):
        code='latest_dream_semantics_changed'
        receipt={'schema':1,'scope':'dream','status':'FAIL','reason_code':'secret token=value'}
    def reject(*args):raise Failure('raw remote/private details must not be exported')
    monkeypatch.setattr(dream,'audit_latest_dream_semantics',reject,raising=False)
    monkeypatch.setattr(main_live,'audit_latest_main_live_semantics',lambda *_:{'schema':1},raising=False)
    context={'schema':object(),'legacy':tmp_path/'legacy','audit_masters':tmp_path/'latest','work':tmp_path,
             'public':tmp_path/'public','octo_proof':{'platforms':{},'card_images':[],'adv_identity':{}}}
    with pytest.raises(m.PreparationError,match='latest_dream_semantics_changed'):
        m.prepare_semantic_controls(context,tmp_path/'proof')
    raw=(tmp_path/'proof/latest-semantic-controls.json').read_bytes()
    value=json.loads(raw)
    assert value['status']=='FAIL' and value['feature']=='dream'
    assert value['receipt']['reason_code']=='audited_master_semantics_changed'
    assert b'secret' not in raw and b'raw remote' not in raw
    assert not (tmp_path/'public/latest-semantic-controls.json').exists()
