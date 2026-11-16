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
