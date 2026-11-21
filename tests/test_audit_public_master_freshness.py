"""Anonymous audit exports bounded IDs/names/hashes, never raw masters."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('public_master_audit', ROOT / 'tools/audit_public_master_freshness.py')
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_known_rows_add_remove_change_and_order_independent_hash():
    before = [{'id':'old', 'name':'旧衣装'}, {'id':'shared', 'name':'旧名称', 'unknown':{'value':1}},
              {'id':'same', 'name':'そのまま'}]
    after = [{'id':'same', 'name':'そのまま'}, {'id':'new', 'name':'新衣装'},
             {'id':'shared', 'name':'新名称', 'unknown':{'value':2}}]
    result = audit.compare_rows(before, after, [audit.DETAIL_BUDGET])
    assert (result['added_count'],result['removed_count'],result['changed_count'],result['unchanged_count'])==(1,1,1,1)
    assert result['added'][0]['id']=='new' and result['added'][0]['name']=='新衣装'
    assert result['removed'][0]['id']=='old'
    assert result['changed'][0]['baseline_name']=='旧名称'
    assert result['changed'][0]['candidate_name']=='新名称'
    assert result['changed'][0]['baseline_row_sha256'] != result['changed'][0]['candidate_row_sha256']
    assert audit.compare_rows(before[::-1], after[::-1], [audit.DETAIL_BUDGET]) == result
    assert 'unknown' not in json.dumps(result)
    assert result['known_schema_fields_only'] is True


def test_truncation_preserves_complete_counts_and_hashes():
    before=[]
    after=[{'id':str(i),'name':'新規'*700} for i in range(1000)]
    result=audit.compare_rows(before,after,[2000])
    assert result['candidate_count']==result['added_count']==1000
    assert result['details_truncated'] and len(result['added'])<1000
    assert len(audit.canonical(result))<8192
    assert result['candidate_rows_sha256']==audit.compare_rows(before,after,[audit.DETAIL_BUDGET])['candidate_rows_sha256']


@pytest.mark.parametrize('rows', ([{'name':'no-id'}],[{'id':'same'},{'id':'same'}],
    [{'id':'bad\nidentity'}],[{'id':'id','name':False}],[1],{}))
def test_ambiguous_or_invalid_rows_fail_closed(rows):
    with pytest.raises(audit.AuditError,match='^row_contract_invalid$'):
        audit.row_index(rows)


def test_pack_change_does_not_count_version_only_source_identity():
    old={'packs':{'Card':{'file_name':'a.db','size':1,'sha256':'a'*64,'source_sha256':'a'*64},
                  'Costume':{'file_name':'b.db','size':2,'sha256':'b'*64}}}
    new={'packs':{'Card':{'file_name':'a.db','size':1,'sha256':'a'*64,'source_sha256':'c'*64},
                  'Costume':{'file_name':'b.db','size':3,'sha256':'c'*64},
                  'Hair':{'file_name':'c.db','size':4,'sha256':'d'*64}}}
    result=audit.compare_packs(old,new)
    assert result['unchanged_count']==1 and result['changed_count']==1
    assert result['added_types']==['Hair'] and result['removed_types']==[]
    assert result['changed'][0]['type']=='Costume'
    assert set(result['changed'][0])=={'type','baseline_bytes','candidate_bytes','baseline_sha256','candidate_sha256'}


def test_collection_failure_always_writes_fixed_small_proof_without_project_imports(tmp_path,monkeypatch):
    source=tmp_path/'source'
    names=['tools/audit_public_master_freshness.py','.github/workflows/audit-public-master-freshness.yml','src/idoly_local/collect.py']
    for name in names:
        path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixed-source')
    monkeypatch.setattr(audit,'ROOT',source)
    output=tmp_path/'proof.json'
    monkeypatch.setattr('sys.argv',['audit','--base-zip',str(tmp_path/'missing-base'),
        '--candidate-root',str(tmp_path/'missing-candidate'),'--descriptor',str(tmp_path/'missing-schema'),
        '--output',str(output),'--source-commit','a'*40,'--collection-failed'])
    assert audit.main()==1
    result=json.loads(output.read_bytes())
    assert result['status']=='FAIL' and result['error_code']=='anonymous_public_master_unavailable'
    assert result['production_data_changed'] is False and result['account_authentication_performed'] is False
    assert result['raw_packs_uploaded'] is False and result['tables_requested']==list(audit.TABLES)
    assert len(output.read_bytes())<audit.MAX_PROOF
    assert set(result['source_files'])==set(names)
    with pytest.raises(audit.AuditError):audit.main()


def test_workflow_has_no_authentication_release_or_raw_artifact_path():
    text=(ROOT/'.github/workflows/audit-public-master-freshness.yml').read_text()
    assert 'contents: read' in text and 'contents: write' not in text
    assert 'archive-master --app-version 6.1.1' in text
    assert 'umask 077' in text and 'collection.log" 2>&1; then' in text
    assert 'collect-session' not in text and 'official_account' not in text
    assert 'gh release' not in text
    artifact=text.split('uses: actions/upload-artifact@v4')[1]
    assert 'proof/master-freshness.json' in artifact and '*.zip' not in artifact and '**' not in artifact



def test_model_selection_uses_actual_fields_and_includes_reward_and_changed_default_refs():
    before={'Card':[{'id':'old-card','name':'old','assetId':'old'}],
        'Costume':[{'id':'old-cos','name':'old','characterId':'owner','bodyAssetId':'old-body','defaultHairId':'old-hair'}],
        'Hair':[{'id':'old-hair','name':'old','characterId':'owner','hairAssetId':'old-hair-asset','faceAssetId':'old-face'}],
        'Character':[{'id':'owner','name':'old','defaultCostumeId':'old-cos','defaultLiveCostumeId':''}]}
    after={name:[dict(row) for row in rows] for name,rows in before.items()}
    after['Card'].append({'id':'new-card','name':'new','assetId':'card-exact','characterId':'owner',
        'rewardCostumeId':'new-cos','rewardHairIds':['new-hair'],'rewardHairId':'new-hair'})
    after['Costume'].append({'id':'new-cos','name':'new','characterId':'owner','bodyAssetId':'opaque-body-asset',
        'defaultHairId':'new-hair'})
    after['Hair'].append({'id':'new-hair','name':'new','characterId':'owner','hairAssetId':'opaque-hair-asset',
        'faceAssetId':'opaque-face-asset'})
    after['Character'][0]['name']='changed'
    result=audit.model_selection(before,after)
    assert result['added_card_ids']==['new-card'] and result['added_costume_ids']==['new-cos']
    assert result['added_hair_ids']==['new-hair'] and result['changed_character_ids']==['owner']
    assert not result['invalid_references']
    assert 'mdl_chr_opaque-body-asset_body' in result['roots']
    assert 'mdl_chr_opaque-hair-asset_hair' in result['roots']
    assert 'mdl_chr_opaque-face-asset_face' in result['roots']
    assert 'mdl_chr_new-cos_body' not in result['roots']
    assert any('addedCard:new-card.rewardCostumeId' in source for source in result['roots']['mdl_chr_opaque-body-asset_body'])
    assert any('changedCharacter:owner.defaultLiveCostumeId' in source for source in result['roots']['mdl_chr_old-body_body'])


def test_dependency_metadata_closure_handles_cycles_missing_and_deleted_without_io():
    def row(identity,name,state,size,dependencies):
        return {'id':identity,'name':name,'state':state,'size':size,'md5':'a'*32,'dependencies':dependencies}
    root=row(1,'model',1,10,[2,3,4]);shared=row(2,'texture',3,20,[1]);deleted=row(3,'gone',4,0,[])
    nodes={1:root,2:shared,3:deleted};names={v['name']:v for v in nodes.values()}
    result=audit.dependency_closure('model',nodes,names)
    assert result['present'] and not result['dependency_metadata_complete']
    assert result['closure_nodes']==2 and result['closure_bytes']==30
    assert result['missing_dependency_count']==2 and result['missing_dependency_ids']==[3,4]
    assert result['root_bytes']==10 and result['root_md5']=='a'*32
    absent=audit.dependency_closure('unknown',nodes,names)
    assert not absent['present'] and not absent['deleted']
    removed=audit.dependency_closure('gone',nodes,names)
    assert not removed['present'] and removed['deleted']
    root['dependencies']=[2]
    complete=audit.dependency_closure('model',nodes,names)
    assert complete['dependency_metadata_complete'] and complete['closure_nodes']==2
    assert complete['closure_sha256'] != result['closure_sha256']


def test_card_image_family_is_exact_observed_pattern_with_deleted_rows_separate():
    rows=[{'kind':'assetbundle','id':1,'name':'img_card_thumb_1_exact-asset','state':3,'bytes':20,'md5':'a'*32},
          {'kind':'assetbundle','id':2,'name':'img_card_full_0_exact-asset','state':4,'bytes':0,'md5':''},
          {'kind':'assetbundle','id':3,'name':'img_card_thumb_1_exact-asset-neighbor','state':3,'bytes':30,'md5':'b'*32}]
    result=audit.card_family('exact-asset',rows)
    assert result['active_count']==1 and result['deleted_count']==1
    assert [row['id'] for row in result['matched_records']]==[1,2]
    with pytest.raises(audit.AuditError):audit.card_family('unsafe/../asset',rows)
