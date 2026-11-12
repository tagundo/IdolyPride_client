import copy
import hashlib
import json
from types import SimpleNamespace

from google.protobuf import descriptor_pb2, message_factory
import pytest

from idoly_local import master_translation_build as translation
from test_master_packs import _synthetic_schema


@pytest.fixture
def schema():
    base = _synthetic_schema()
    proto = descriptor_pb2.FileDescriptorProto(name="translation-test.proto", package="master", syntax="proto3")
    proto.dependency.append("test_master_options.proto")
    nested = proto.message_type.add(name="Choice")
    nested.field.add(name="text", number=1, type=9)
    nested.field.add(name="assetId", number=2, type=9)
    options = message_factory.GetMessageClass(base.pool.FindMessageTypeByName("google.protobuf.MessageOptions"))
    field_options = message_factory.GetMessageClass(base.pool.FindMessageTypeByName("google.protobuf.FieldOptions"))
    for name in ("Story", "PhotoQuestMusic", "Costume"):
        item = proto.message_type.add(name=name)
        table = options(); table.Extensions[base.pool.FindExtensionByName("master.table")] = True
        item.options.ParseFromString(table.SerializeToString())
        for number, field_name, kind in ((1, "id", 9), (2, "name", 9), (3, "description", 9),
                                        (4, "assetId", 9), (5, "order", 5), (6, "isUserUnavailable", 8)):
            field = item.field.add(name=field_name, number=number, type=kind)
            if field_name == "id":
                pk = field_options(); pk.Extensions[base.pool.FindExtensionByName("master.pk")] = True
                field.options.ParseFromString(pk.SerializeToString())
        item.field.add(name="branchChoices", number=7, type=11, label=3, type_name=".master.Choice")
        item.field.add(name="texts", number=8, type=9, label=3)
    table_file = base.pool.AddSerializedFile(proto.SerializeToString())
    api = descriptor_pb2.FileDescriptorProto(name="translation-api.proto", package="api", syntax="proto3")
    pack = api.message_type.add(name="Pack")
    for n, name, kind in ((1,"type",9),(2,"fileName",9),(3,"fileSize",5),(4,"cryptoKey",9),(5,"downloadUrl",9)):
        pack.field.add(name=name,number=n,type=kind)
    tag = api.message_type.add(name="Tag")
    tag.field.add(name="version",number=1,type=9)
    tag.field.add(name="masterTagPacks",number=2,type=11,label=3,type_name=".api.Pack")
    response = api.message_type.add(name="Response")
    response.field.add(name="masterTag",number=1,type=11,type_name=".api.Tag")
    base.pool.AddSerializedFile(api.SerializeToString())
    response_class = message_factory.GetMessageClass(base.pool.FindMessageTypeByName("api.Response"))
    return SimpleNamespace(pool=base.pool, files=[*base.files,table_file],
                           response_type=lambda _path: response_class,
                           fingerprint=hashlib.sha256(proto.SerializeToString()).hexdigest())


def test_exact_nested_translation_preserves_account_independent_nontext_fields_and_source(schema):
    rows = [{"id":"story-a","name":"日本語","assetId":"unchanged-body","order":7,
             "isUserUnavailable":True,"branchChoices":[{"text":"選択","assetId":"unchanged"}],
             "texts":["そのまま","元の文"]}, {"id":"story-b","name":"fallback"}]
    before = copy.deepcopy(rows)
    document = {"rule":["id|name","id|branchChoices.text","id|texts"],"data":{
        "story-a|name":"한국어", "story-a|branchChoices[0].text":"선택",
        "story-a|texts[1]":"번역", "story-a|branchChoices[9].text":"missing fallback",
        "missing-story|name":"do not create", "story-b|name":""}}
    out, counts = translation.translate_rows(schema,"Story",rows,document)
    assert rows == before
    assert out[0] == {**before[0],"name":"한국어", "branchChoices":[{"text":"선택","assetId":"unchanged"}],
                      "texts":["そのまま","번역"]}
    assert out[1] == before[1]
    assert counts == {"rows":2,"entries":6,"changed_fields":3,"missing_rows":1,
                      "empty_fallback":1,"unchanged_or_missing_path":1}


@pytest.mark.parametrize("path", ["id", "assetId", "order", "isUserUnavailable", "missing", "branchChoices.assetId"])
def test_rules_cannot_rewrite_ids_assets_numeric_gates_or_unknown_fields(schema, path):
    with pytest.raises(ValueError):
        translation.translate_rows(schema,"Story",[{"id":"a"}],{"rule":["id|"+path],"data":{}})


@pytest.mark.parametrize("key", ["a|description", "a|branchChoices.text", "a|name[0]", "a|branchChoices[-1].text", "a|name|extra"])
def test_undeclared_paths_malformed_indices_and_ambiguous_keys_fail_closed(schema, key):
    with pytest.raises(ValueError):
        translation.translate_rows(schema,"Story",[{"id":"a"}],{"rule":["id|name","id|branchChoices.text"],"data":{key:"text"}})


def test_composite_primary_key_mismatch_and_duplicate_original_ids_are_rejected(schema):
    for rows,document in [([{"id":"a"}],{"rule":["assetId|name"],"data":{}}),
                          ([{"id":"a"},{"id":"a"}],{"rule":["id|name"],"data":{}}),
                          ([{"id":"a|b"}],{"rule":["id|name"],"data":{}})]:
        with pytest.raises(ValueError):
            translation.translate_rows(schema,"Story",rows,document)


def test_explicit_rule_indices_are_constraints_and_unindexed_rules_are_wildcards(schema):
    rows=[{'id':'a','branchChoices':[{'text':'一'},{'text':'二'}]}]
    with pytest.raises(ValueError,match='matching declared'):
        translation.translate_rows(schema,'Story',rows,{'rule':['id|branchChoices[0].text'],
            'data':{'a|branchChoices[1].text':'wrong index'}})
    out,_=translation.translate_rows(schema,'Story',rows,
        {'rule':['id|branchChoices[0].text','id|branchChoices[1].text'],
         'data':{'a|branchChoices[0].text':'one','a|branchChoices[1].text':'two'}})
    assert out[0]['branchChoices']==[{'text':'one'},{'text':'two'}]


def test_media_cover_label_uses_actual_translated_description_and_preserves_missing_fallback(schema):
    identity="music-thrx-001-unit"
    rows=[{"id":identity,"name":"日本語カバー","description":"日本語カバー","isUserUnavailable":False}]
    doc={"rule":["id|name","id|description"],"data":{identity+"|name":"Bang Bang",
         identity+"|description":"Bang Bang (Suzu, Saki, Shizuku ver.)  "}}
    ordinary,_=translation.translate_rows(schema,"PhotoQuestMusic",rows,doc)
    media,_=translation.translate_rows(schema,"PhotoQuestMusic",rows,doc,media_mode=True)
    assert ordinary[0]["name"]=="Bang Bang"
    assert media[0]["name"]=="Bang Bang (Suzu, Saki, Shizuku ver.)"
    assert media[0]["isUserUnavailable"] is False
    doc["data"].pop(identity+"|description")
    fallback,_=translation.translate_rows(schema,"PhotoQuestMusic",rows,doc,media_mode=True)
    assert fallback[0]["name"]=="日本語カバー"


def test_input_reader_rejects_duplicate_oversized_and_symlink_files(tmp_path):
    p=tmp_path/"Story.json";p.write_text('{"rule":[],"rule":[],"data":{}}')
    with pytest.raises(ValueError):translation.read_translation(p)
    p.write_bytes(b" "*(translation.MAX_DOCUMENT_BYTES+1))
    with pytest.raises(ValueError):translation.read_translation(p)
    p.unlink();target=tmp_path/"target";target.write_text('{}');p.symlink_to(target)
    with pytest.raises(ValueError):translation.read_translation(p)


def test_real_sqlcipher_overlay_roundtrip_preserves_other_packs_and_original_bytes(schema,tmp_path):
    pytest.importorskip("sqlcipher3")
    from idoly_local.master_build import build_master_packs,_sqlcipher_driver
    catalog=tmp_path/"original-json";catalog.mkdir()
    for table,rows in (("Story",[{"id":"a","name":"日本語","assetId":"same","order":3}]),
                       ("Costume",[{"id":"c","name":"unchanged","isUserUnavailable":True}])):
        (catalog/(table+".json")).write_text(json.dumps(rows))
    original=tmp_path/"original";build_master_packs(schema,catalog,original,tables=["Story","Costume"])
    tag=json.loads((original/"master-tag.json").read_text())
    tag['masterTagPacks'].extend({'type':'Unchanged%03d'%n,'fileName':'untouched%03d.db'%n,
        'fileSize':4096,'cryptoKey':'b'*64,'downloadUrl':'https://public.invalid/unchanged'} for n in range(200))
    before={p.relative_to(original):p.read_bytes() for p in original.rglob('*') if p.is_file()}
    translations=tmp_path/"translations";translations.mkdir()
    (translations/"Story.json").write_text(json.dumps({"rule":["id|name"],"data":{"a|name":"번역"}}))
    raw=(translations/'Story.json').read_bytes()
    source={"repository":"https://github.com/example/public","revision":"a"*40,"license":"NOASSERTION",
        "files":{'Story.json':{'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob_sha1':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}}}
    output=tmp_path/"translated"
    report=translation.build_translation_master_overlay(schema,tag,original/"assets/master",translations,output,
        language="ko",source=source)
    assert report["changed_pack_count"]==1 and not report["device_verified"]
    changed=json.loads((output/"master-tag.json").read_text())
    by_type={p['type']:p for p in changed['masterTagPacks']}
    original_types={p['type']:p for p in tag['masterTagPacks']}
    assert by_type['Story']!=original_types['Story']
    assert by_type['Costume']==original_types['Costume']
    assert changed['masterTagPacks'][2:]==tag['masterTagPacks'][2:]
    assert report['pack_count']==202
    driver,_=_sqlcipher_driver()
    result=translation.read_master_rows(schema,driver,output/"assets/master",by_type['Story'])
    assert result[0]["name"]=="번역" and result[0]["assetId"]=="same" and result[0]["order"]==3
    assert translation.read_master_rows(schema,driver,[original/'assets/master',output/'assets/master'],by_type['Story'])==result
    with pytest.raises(ValueError,match='ambiguous'):
        translation.read_master_rows(schema,driver,[output/'assets/master',output/'assets/master'],by_type['Story'])
    assert before=={p.relative_to(original):p.read_bytes() for p in original.rglob('*') if p.is_file()}
    reused=tmp_path/'media-reused'
    report2=translation.build_translation_master_overlay(schema,tag,original/'assets/master',translations,reused,
        language='ko',source=source,media_mode=True,reuse_overlay=output)
    assert report2['tables']['Story']['reused_pack'] is True
    assert (reused/'assets/master'/by_type['Story']['fileName']).read_bytes()==(output/'assets/master'/by_type['Story']['fileName']).read_bytes()
    bad=copy.deepcopy(source);bad['files']['Story.json']['git_blob_sha1']='0'*40
    rejected=tmp_path/'bad-provenance'
    with pytest.raises(ValueError,match='pinned public file'):
        translation.build_translation_master_overlay(schema,tag,original/'assets/master',translations,rejected,
            language='ko',source=bad)
    assert not rejected.exists()
    assert before=={p.relative_to(original):p.read_bytes() for p in original.rglob('*') if p.is_file()}
    with pytest.raises(ValueError,match="unused"):
        translation.build_translation_master_overlay(schema,tag,original/"assets/master",translations,output,
            language="ko",source=source)
