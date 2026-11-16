#!/usr/bin/env python3
"""Compile a public latest cohort once; apply its frozen complete blob with stdlib.

Linux compilation needs locked SQLCipher/protobuf dependencies. Native builds
never rebuild encrypted packs: the source blob and final ServerData ZIP have
identical bytes. All data is public; no account/authentication/state operations
or release mutation occur. Large inputs and outputs belong on remote runners.
"""
from __future__ import annotations
import argparse
import base64
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path,PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler,Request,build_opener
from zipfile import ZipFile,ZipInfo,ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
POLICY='latest-cohort-overlay-v1'
BASE_BYTES=191343014
BASE_SHA256='37dbf0fb9bac5d860991753d2e41ff0c269684bfca673ba41e1bcb897651c223'
BASE_VERSION='961e456499039e31248a818a911c8d95f92461f86aff4674ba07e29c32afcf60'
MASTER_VERSION='6b77e0d8a64b26d5bebd09a7c19a47f2dfad2af914c5160418aa2e7292e13a11'
MASTER_TAG_SHA256='1433f99de2b5ca5c87765981a75e00e83d9176f124357e54f70121e1dd41ebb2'
DESCRIPTOR_SHA256='c82cee62abdca7144d11e710a6f773211464a89d2ddede207999a0a5e7aec8ad'
SCHEMA_SHA256='0fcf90596261dcd9bbed165bd93859dc30127e2a494e6529bafbd8885675edf3'
LEGACY_OVERLAY_BYTES=5702787
LEGACY_OVERLAY_SHA256='1095a0ec5a98a6f8781fb194b169ed6dfdb5940fb644aec8a220a5e703b70e0e'
LEGACY_RULESET_SHA256='876fab148d34d912213b3d8c6fb69b0b3c2bc86e81c75fef724636904a548b49'
SOURCE_COMPONENTS=(
 'tools/prepare_latest_server_data.py','tools/build_server_payload.py','tools/audit_public_master_freshness.py',
 'src/idoly_local/__init__.py','src/idoly_local/schema.py','src/idoly_local/master_build.py',
 'src/idoly_local/collect.py','src/idoly_local/codec.py','src/idoly_local/catalog.py','pyproject.toml','uv.lock',
 'src/idoly_local/media_master_build.py','src/idoly_local/media_outfit_policy.py',
 'src/idoly_local/master_translation_build.py','src/idoly_local/master_sort_build.py',
 'src/idoly_local/master_sort.py','src/idoly_local/media_settings.py','src/idoly_local/love_catalog.py',
 'src/idoly_local/tutorial_replay.py','src/idoly_local/story_catalog.py','src/idoly_local/story_read_rules.py',
 'src/idoly_local/gameplay.py','src/idoly_local/live_assets.py','src/idoly_local/rpc.py',
 'src/idoly_local/octo_manifest.py','src/idoly_local/panorama_rules.py',
 'src/idoly_local/dream.py','src/idoly_local/dream_capture.py','src/idoly_local/live_input.py',
 'src/idoly_local/card_progression.py','src/idoly_local/live_accessories.py','src/idoly_local/cli.py',
 '.github/workflows/prepare-latest-server-data.yml',
 'data/love-reference.json','data/love-adv-proof.json','data/love-reference-NOTICE.txt','LICENSE')
RAW_TABLES=tuple(sorted(('Character','CharacterActivityLevel','Costume','Hair','Card','Area','AreaGroup','Quest',
 'Setting','Tutorial','CardParameter','CardRarity','Accessory','HierarchyDetailGrade','HierarchyGrade','Reward',
 'Item','CardLevelRelease','Skill','Music','MusicChartPattern','Emblem','SkillEfficacy','SkillTrigger','SkillTarget',
 'Stage','ManagerLevel','CardLevel','Consumption','Message','MessageGroup','EventStory','ExtraStoryPart','ExtraStory',
 'Story','QuestPressure','QuestAudienceAdvantage','ComboAdvantage','QuestStaminaConsumption','Mission','StoryPart',
 'PhotoActivity','PhotoQuestMusic','PhotoQuestStage','PhotoExpression','CompanyGrade','CompanyTrustLevel',
 'CompanyEnjoyCharacterLevel','CompanyEnjoyCharacterLevelSetting','HomeTalk','PhotoPose','PhotoPoseMotion',
 'ExcursionGazeReaction','ExcursionPlace','ExcursionPlaceSetting','LoveHomeAction','LoveLevel','LoveStoryEpisode',
 'LoveColor','Condition','EventMission','CardImage','Decoration')))
MANIFEST='data/payload-manifest.json'
BLOB_NAME='data/latest-server-overlay.zip'
MAX_PROOF=512*1024
MAX_METADATA=8*1024*1024
MAX_FILE=64*1024*1024
MAX_EXPANDED=1024*1024*1024
MAX_BLOB=512*1024*1024
CHUNK=65536
STAMP=(2000,1,1,0,0,0)
PHASE='preflight'
PROOF_NAMES=frozenset(('latest-server-data.report.json','latest-server-data.readback.json',
 'latest-semantic-controls.json','latest-octo-proof.json'))


class PreparationError(ValueError):pass


def need(value,code):
    if not value:raise PreparationError(code)


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def pairs(items):
    result={}
    for key,value in items:
        need(key not in result,'latest_duplicate_json_key');result[key]=value
    return result


def decode(raw):
    return json.loads(raw,object_pairs_hook=pairs,
        parse_constant=lambda _:(_ for _ in ()).throw(PreparationError('latest_nonfinite_json')))


def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block:=stream.read(CHUNK):value.update(block)
    return value.hexdigest()


def read_json(path,maximum=MAX_METADATA):
    path=Path(path);info=path.lstat()
    need(stat.S_ISREG(info.st_mode) and not path.is_symlink() and 0<info.st_size<=maximum,'latest_json_file_invalid')
    return decode(path.read_bytes())


def write_json(path,value):
    raw=canonical(value)+b'\n';need(len(raw)<=MAX_FILE,'latest_generated_json_bound')
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as stream:stream.write(raw)
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def pin_file(path,size,sha):
    path=Path(path)
    need(path.is_file() and not path.is_symlink() and path.stat().st_size==size and digest(path)==sha,
         'latest_immutable_input_differs')


def source_pins():return {name:digest(ROOT/name) for name in sorted(SOURCE_COMPONENTS)}


def safe_name(name):
    path=PurePosixPath(name)
    return (type(name) is str and name.startswith('data/') and str(path)==name and not path.is_absolute()
        and all(part not in ('','.','..') for part in path.parts) and not any(ord(c)<32 or c in '\\:' for c in name))


def archive_rows(archive):
    infos=archive.infolist();need(0<len(infos)<=2048,'latest_member_count_bound')
    seen=set();rows=[];total=0
    for info in infos:
        need(safe_name(info.filename) and info.filename not in seen and not info.is_dir()
             and not info.flag_bits&1 and stat.S_IFMT(info.external_attr>>16) in (0,stat.S_IFREG),'latest_member_invalid')
        seen.add(info.filename);total+=info.file_size
        need(0<info.file_size<=MAX_FILE and total<=MAX_EXPANDED,'latest_member_extent')
        value=hashlib.sha256();size=0
        with archive.open(info) as stream:
            while block:=stream.read(CHUNK):
                size+=len(block);need(size<=info.file_size,'latest_member_extent');value.update(block)
        need(size==info.file_size,'latest_member_extent')
        rows.append({'path':info.filename,'bytes':size,'sha256':value.hexdigest()})
    return sorted(rows,key=lambda row:row['path'])


def extract_archive(archive,destination,*,merge=False):
    for info in archive.infolist():
        target=Path(destination)/PurePosixPath(info.filename).relative_to('data')
        if target.exists():
            need(merge and target.is_file() and not target.is_symlink() and target.stat().st_size==info.file_size,
                 'latest_legacy_merge_differs')
            with archive.open(info) as source:need(hashlib.sha256(source.read()).hexdigest()==digest(target),'latest_legacy_merge_differs')
            continue
        target.parent.mkdir(parents=True,exist_ok=True)
        with archive.open(info) as incoming,target.open('xb') as outgoing:shutil.copyfileobj(incoming,outgoing,CHUNK)


def file_rows(directory):
    rows=[]
    for path in sorted(Path(directory).rglob('*')):
        if path.is_dir():continue
        need(path.is_file() and not path.is_symlink(),'latest_generated_member_invalid')
        name='data/'+path.relative_to(directory).as_posix()
        need(safe_name(name) and 0<path.stat().st_size<=MAX_FILE,'latest_generated_member_invalid')
        rows.append({'path':name,'bytes':path.stat().st_size,'sha256':digest(path)})
    need(len(rows)<=2048 and sum(row['bytes'] for row in rows)<=MAX_EXPANDED,'latest_generated_extent')
    return rows


def runtime():
    sys.path.insert(0,str(ROOT/'src'))
    from idoly_local.schema import Schema
    from idoly_local.master_build import _annotated_tables,_sqlcipher_driver
    from idoly_local.master_translation_build import read_master_rows
    return Schema,_annotated_tables,_sqlcipher_driver,read_master_rows


def prepare_inputs(base,latest,work):
    global PHASE
    PHASE='immutable_inputs'
    pin_file(base,BASE_BYTES,BASE_SHA256)
    legacy=work/'legacy';legacy.mkdir()
    with ZipFile(base) as archive:
        old_rows=archive_rows(archive);extract_archive(archive,legacy)
    pin_file(ROOT/'data/love-server-overlay.zip',LEGACY_OVERLAY_BYTES,LEGACY_OVERLAY_SHA256)
    with ZipFile(ROOT/'data/love-server-overlay.zip') as overlay:
        old_overlay_rows=archive_rows(overlay)
        need(len(old_overlay_rows)==11,'latest_legacy_overlay_differs');extract_archive(overlay,legacy,merge=True)
    legacy_catalog=read_json(legacy/'master-json/LoveCatalog.json')
    need(legacy_catalog['ruleset_sha256']==LEGACY_RULESET_SHA256,'latest_legacy_ruleset_differs')
    for name,sha in legacy_catalog['source_files'].items():
        need('/' not in name and digest(legacy/'master-json'/name)==sha,'latest_legacy_source_differs')
    need((legacy/'master-json/!version.txt').read_text().strip()==BASE_VERSION,'latest_legacy_version_differs')
    Schema,annotated,driver_loader,read_rows=runtime()
    descriptor=legacy/'protocol/idolypride-6.1.1.pb'
    need(digest(descriptor)==DESCRIPTOR_SHA256,'latest_descriptor_differs')
    schema=Schema.from_descriptor_set(descriptor)
    need(schema.fingerprint==SCHEMA_SHA256,'latest_schema_differs')
    driver,_=driver_loader()
    public=work/'public';public.mkdir()
    for row in old_rows:
        relative=PurePosixPath(row['path']).relative_to('data')
        if row['path']==MANIFEST or relative.parts[0] in ('master-json','original-master'):continue
        source=legacy/relative;target=public/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    original=public/'original-master';pool=original/'assets/master';pool.mkdir(parents=True)
    tag=read_json(latest/'master-tag.json');report=read_json(latest/'archive-report.json')
    need(digest(latest/'master-tag.json')==MASTER_TAG_SHA256,'latest_observed_master_tag_differs')
    from google.protobuf.json_format import ParseDict
    response_type=schema.response_type('/api.Master/Get')
    response=response_type.FromString((latest/'response.pb').read_bytes())
    clean=response_type();clean.CopyFrom(response);clean.DiscardUnknownFields()
    expected_tag=type(response.masterTag)();ParseDict(tag,expected_tag)
    need(response.HasField('masterTag') and response.masterTag.SerializeToString(deterministic=True)==expected_tag.SerializeToString(deterministic=True)
         and clean.SerializeToString(deterministic=True)==response.SerializeToString(deterministic=True),'latest_master_response_differs')
    need(type(tag) is dict and set(tag)=={'version','masterTagPacks'} and tag['version']==MASTER_VERSION
         and len(tag['masterTagPacks'])==202 and report.get('complete') is True
         and report.get('master_version')==MASTER_VERSION and report.get('completed_packs')==202
         and report.get('expected_packs')==202,'latest_archive_cohort_differs')
    packs={pack['type']:pack for pack in tag['masterTagPacks']}
    need(len(packs)==202 and set(packs)==set(annotated(schema)) and set(report.get('packs',{}))==set(packs),
         'latest_archive_schema_inventory_differs')
    need(set(RAW_TABLES)<=set(packs) and len(RAW_TABLES)==63,'latest_raw_table_inventory_differs')
    names=set();active=[]
    for table,pack in sorted(packs.items()):
        name=pack['fileName'];record=report['packs'][table]
        need(type(name) is str and name not in names and re.fullmatch(r'[A-Za-z0-9_.-]{1,200}',name)
             and name not in ('.','..') and type(pack['fileSize']) is int and 0<pack['fileSize']<=MAX_FILE
             and record.get('file_name')==name and record.get('size')==pack['fileSize'], 'latest_pack_identity_differs')
        names.add(name);source=latest/'assets/master'/name;pin_file(source,pack['fileSize'],record['sha256'])
        shutil.copyfile(source,pool/name)
        active.append({'type':table,'file_name':name,'bytes':pack['fileSize'],'sha256':record['sha256']})
    for name in ('master-tag.json','archive-report.json','response.pb'):shutil.copyfile(latest/name,original/name)
    PHASE='decode_202_original_packs'
    masters=public/'master-json';masters.mkdir();audit={};counts={}
    audit_masters=work/'latest-all-master-json';audit_masters.mkdir()
    for table,pack in sorted(packs.items()):
        rows=read_rows(schema,driver,pool,pack)
        raw=canonical(rows)
        audit[table]={'rows':len(rows),'known_rows_sha256':hashlib.sha256(raw).hexdigest(),
                      'protobuf_unknown_fields_absent':True,'pack_sha256':report['packs'][table]['sha256']}
        with (audit_masters/(table+'.json')).open('xb') as target:target.write(raw)
        if table in RAW_TABLES:
            os.link(audit_masters/(table+'.json'),masters/(table+'.json'))
            counts[table]=len(rows)
    (masters/'!version.txt').write_text(MASTER_VERSION,encoding='ascii')
    (audit_masters/'!version.txt').write_text(MASTER_VERSION,encoding='ascii')
    PHASE='existing_account_reference_controls'
    for table in ('Card','Character','Costume','Hair','Item','Accessory','Music','Area','Quest'):
        before=read_json(legacy/'master-json'/(table+'.json'),MAX_FILE)
        after=read_json(masters/(table+'.json'),MAX_FILE)
        need({row['id'] for row in before}<={row['id'] for row in after},'latest_existing_reference_removed')
    old_mission=next(row for row in read_json(legacy/'master-json/Mission.json',MAX_FILE) if row['id']=='ms-normal-card_level_achievement')
    new_mission=next(row for row in read_json(masters/'Mission.json',MAX_FILE) if row['id']=='ms-normal-card_level_achievement')
    need(old_mission==new_mission,'latest_card_level_mission_control_changed')
    for source_name,target_name in (('data/love-reference.json','love-reference.json'),('data/love-adv-proof.json','love-adv-proof.json'),
        ('data/love-reference-NOTICE.txt','licenses/love-reference-NOTICE.txt'),('LICENSE','licenses/love-reference-AGPL-3.0.txt')):
        target=public/target_name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/source_name,target)
    return {'schema':schema,'driver':driver,'read_rows':read_rows,'legacy':legacy,'public':public,
            'tag':tag,'packs':packs,'active_packs':active,'counts':counts,'record_audit':audit,'old_rows':old_rows,'audit_masters':audit_masters,'work':work}


def audit_module():
    spec=importlib.util.spec_from_file_location('latest_public_asset_audit',ROOT/'tools/audit_public_master_freshness.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def table_rows(context,table,*,legacy=False):
    directory=context['legacy']/'master-json' if legacy else context['audit_masters']
    path=directory/(table+'.json')
    if path.is_file():return read_json(path,MAX_FILE)
    need(legacy,'latest_audit_table_missing')
    tag=read_json(context['legacy']/'original-master/master-tag.json')
    need(tag['version']==BASE_VERSION,'latest_legacy_tag_differs')
    packs={row['type']:row for row in tag['masterTagPacks']}
    need(table in packs,'latest_legacy_audit_pack_missing')
    rows=context['read_rows'](context['schema'],context['driver'],context['legacy']/'original-master/assets/master',packs[table])
    extra=context['work']/'legacy-audit-extra';extra.mkdir(exist_ok=True)
    path=extra/(table+'.json')
    if not path.exists():write_json(path,rows)
    return rows


def sdk_manifest(settings,*,fetch=None):
    """Read the public application SDK catalog; never a player API/token."""
    from Crypto.Cipher import AES
    from idoly_local.octo_manifest import decrypt_manifest
    version=settings['application_version']
    need(version in (205051,105051) and settings['application_id']==212,'latest_octo_platform_invalid')
    url=f'https://api.octo-cloud.com/v2/pub/a/212/v/{version}/list/0'
    headers={'Accept':'application/x-protobuf,x-octo-app/212','X-OCTO-KEY':settings['client_key']}
    if fetch is None:
        opener=build_opener(NoRedirect())
        try:
            with opener.open(Request(url,headers=headers),timeout=45) as response:
                need(response.status==200 and response.geturl()==url,'latest_octo_endpoint_rejected')
                raw=response.read(MAX_METADATA+1025)
        except (HTTPError,OSError):raise PreparationError('latest_octo_endpoint_rejected') from None
    else:raw=fetch(url,headers,MAX_METADATA+1024)
    need(type(raw) is bytes and 16<len(raw)<=MAX_METADATA+1024,'latest_octo_response_invalid')
    def aes(encrypt,key,iv,data):
        cipher=AES.new(key,AES.MODE_CBC,iv)
        return cipher.encrypt(data) if encrypt else cipher.decrypt(data)
    return decrypt_manifest(raw,aes_key=bytes.fromhex(settings['aes_key_hex']),aes_cbc=aes),aes


def database_records(database):
    nodes={};by_name={};all_records=[]
    for row in database.assetBundleList:
        record={'id':row.id,'name':row.name,'state':row.state,'size':row.size,'md5':row.md5,
                'dependencies':sorted(row.dependencie)}
        nodes[row.id]=record;by_name[row.name]=record
    for kind,rows in (('assetbundle',database.assetBundleList),('resources',database.resourceList)):
        all_records.extend({'kind':kind,'id':row.id,'name':row.name,'state':row.state,'bytes':row.size,'md5':row.md5}
                           for row in rows)
    return nodes,by_name,all_records


def card_image_requirements(schema,before,after,old_images,new_images,databases,audit):
    """Require the shared observed families of original cards with the same
    CardImage display/image-type signature. This is a metadata compatibility
    control, not a claim that all runtime image request code was reconstructed.
    """
    descriptor=schema.pool.FindMessageTypeByName('master.CardImage')
    for name,number,kind in (('cardId',1,9),('displayType',2,14),('imageType',3,14)):
        field=descriptor.fields_by_name.get(name)
        need(field is not None and field.number==number and field.type==kind and not field.is_repeated,
             'latest_card_image_schema_differs')
    def signatures(rows):
        result={}
        for row in rows:
            identity=row.get('cardId');display=row.get('displayType');image=row.get('imageType')
            need(type(identity) is str and type(display) is int and display in (1,2,3)
                 and type(image) is int and image in (1,2,3),'latest_card_image_record_invalid')
            result.setdefault(identity,[]).append((display,image))
        need(all(len(values)==len(set(values)) for values in result.values()),'latest_card_image_duplicate')
        return {key:sorted(value) for key,value in result.items()}
    old_signature,new_signature=signatures(old_images),signatures(new_images)
    prior={row['id']:row for row in before['Card']};current={row['id']:row for row in after['Card']}
    output=[]
    for identity in sorted(current.keys()-prior.keys()):
        signature=new_signature.get(identity);need(signature,'latest_added_card_image_record_missing')
        controls=sorted(key for key in prior if old_signature.get(key)==signature)
        need(controls,'latest_card_image_original_controls_missing')
        card={'card_id':identity,'card_image_signature':[list(value) for value in signature],
              'control_cards':controls,'platforms':{},'scope':'shared-original-card-image-family-metadata'}
        for platform,(old_database,new_database) in databases.items():
            old_records=database_records(old_database)[2]
            new_nodes,new_names,new_records=database_records(new_database)
            pattern_sets=[];complete_controls=[]
            for control in controls:
                asset=prior[control]['assetId'];family=audit.card_family(asset,old_records)
                patterns={row['name'][:-len(asset)] for row in family['matched_records'] if row['state']!=4}
                if all(any(value.startswith('img_card_'+kind+'_') for value in patterns) for kind in ('thumb','rect','full','upper')):
                    pattern_sets.append(patterns);complete_controls.append(control)
            need(pattern_sets,'latest_card_image_original_controls_missing')
            required=set.intersection(*pattern_sets)
            need(required and all(any(value.startswith('img_card_'+kind+'_') for value in required)
                 for kind in ('thumb','rect','full','upper')),'latest_card_image_control_family_incomplete')
            names={row['name']:row for row in new_records}
            matches=[names.get(prefix+current[identity]['assetId']) for prefix in sorted(required)]
            need(all(row is not None and row['state']!=4 for row in matches),'latest_added_card_image_family_missing')
            for record in matches:
                if record['kind']=='assetbundle':
                    closure=audit.dependency_closure(record['name'],new_nodes,new_names)
                    need(closure['present'] and closure['dependency_metadata_complete'],'latest_card_image_dependency_missing')
                    record['dependency_closure']=closure
            card['platforms'][platform]={'control_cards':complete_controls,'excluded_incomplete_original_controls':len(controls)-len(complete_controls),
                                         'required_patterns':sorted(required),'records':matches}
        output.append(card)
    return output


def prepare_octo(context):
    global PHASE
    from idoly_local.octo_manifest import Database,OctoManifest
    PHASE='anonymous_public_octo_catalogs'
    audit=audit_module();audit.validate_model_fields(context['schema'])
    before={table:table_rows(context,table,legacy=True) for table in audit.TABLES}
    after={table:table_rows(context,table) for table in audit.TABLES}
    selection=audit.model_selection(before,after)
    need(not selection['invalid_references'],'latest_appearance_reference_invalid')
    evidence=read_json(ROOT/'data/love-adv-proof.json')
    adv_names=sorted('adv_'+name+'.txt' for name in evidence['assets'])
    need(len(adv_names)==68,'latest_adv_source_inventory_differs')
    identities={'schema':1,'platforms':{}};databases={};platforms={};roots=[]
    for platform,(folder,version,revision,old_sha) in audit.OCTO_PINS.items():
        directory=context['legacy']/folder;settings=read_json(directory/'settings.json',16384)
        old_raw=(directory/'manifest.pb').read_bytes()
        need(hashlib.sha256(old_raw).hexdigest()==old_sha and settings['manifest_sha256']==old_sha
             and settings['revision']==revision and settings['application_version']==version,'latest_legacy_octo_differs')
        new_raw,aes=sdk_manifest(settings)
        validated_old=OctoManifest(old_raw,aes_key=bytes.fromhex(settings['aes_key_hex']),client_key=settings['client_key'],
            base_url='http://127.0.0.1:8080',aes_cbc=aes,application_version=version)
        validated=OctoManifest(new_raw,aes_key=bytes.fromhex(settings['aes_key_hex']),client_key=settings['client_key'],
            base_url='http://127.0.0.1:8080',aes_cbc=aes,application_version=version)
        need(validated_old.revision==revision and validated.revision>=revision,'latest_octo_revision_regressed')
        old_database,new_database=Database.FromString(old_raw),Database.FromString(new_raw)
        databases[platform]=(old_database,new_database)
        old_resources={row.name:row for row in old_database.resourceList}
        new_resources={row.name:row for row in new_database.resourceList}
        records=[]
        def identity(row):return {'md5':row.md5,'size':row.size,'generation':row.generation,'objectName':row.objectName}
        for name in adv_names:
            old,new=old_resources.get(name),new_resources.get(name)
            need(old is not None and new is not None and old.state!=4 and new.state!=4,'latest_love_adv_missing')
            records.append({'name':name,'baseline':identity(old),'candidate':identity(new)})
        new_sha=hashlib.sha256(new_raw).hexdigest()
        identities['platforms'][platform]={'baseline_manifest_sha256':old_sha,'candidate_manifest_sha256':new_sha,'records':records}
        nodes,names,all_records=database_records(new_database)
        checks=[]
        for name,sources in selection['roots'].items():
            result=audit.dependency_closure(name,nodes,names)
            need(result['present'] and not result['deleted'] and result['dependency_metadata_complete'],
                 'latest_required_model_catalog_missing')
            checks.append({'name':name,'sources':sources,**result})
        platforms[platform]={'application_id':212,'application_version':version,'baseline_revision':revision,
            'revision':validated.revision,'baseline_manifest_sha256':old_sha,'manifest_sha256':new_sha,
            'baseline_manifest_bytes':len(old_raw),'manifest_bytes':len(new_raw),
            'object_count':len(all_records),'model_roots':len(checks),'missing_model_roots':0,
            'incomplete_dependency_closures':0,'models':checks}
        target=context['public']/folder
        for name in ('settings.json','manifest.pb'):(target/name).unlink()
        shutil.copyfile(directory/'manifest.pb',target/'legacy-manifest.pb')
        with (target/'manifest.pb').open('xb') as stream:stream.write(new_raw)
        changed=deepcopy(settings);changed.update(revision=validated.revision,manifest_sha256=new_sha)
        write_json(target/'settings.json',changed)
    images=card_image_requirements(context['schema'],before,after,
        table_rows(context,'CardImage',legacy=True),table_rows(context,'CardImage'),databases,audit)
    proof={'schema':1,'status':'PASS','scope':'latest-public-sdk-catalog-metadata-only',
        'master_version':MASTER_VERSION,'selection':{key:value for key,value in selection.items() if key!='roots'},
        'platforms':platforms,'card_images':images,'adv_identity':identities,
        'cdn_asset_bytes_downloaded':False,'unity_playback_verified':False}
    need(len(canonical(proof))<=MAX_PROOF,'latest_octo_proof_bound')
    context['adv_identity_proof']=identities;context['octo_proof']=proof
    return proof


def row_index(rows):
    need(type(rows) is list and rows and all(type(row) is dict and type(row.get('id')) is str for row in rows),
         'latest_semantic_table_invalid')
    indexed={row['id']:row for row in rows}
    need(len(indexed)==len(rows),'latest_semantic_duplicate_identity')
    return indexed


def source_table_proofs(context,tables,*,legacy=False):
    result={}
    for table in tables:
        rows=table_rows(context,table,legacy=legacy)
        directory=context['legacy']/'master-json' if legacy else context['audit_masters']
        path=directory/(table+'.json')
        if not path.exists():path=context['work']/'legacy-audit-extra'/(table+'.json')
        result[table]={'bytes':path.stat().st_size,'sha256':digest(path),
            'canonical_rows_sha256':hashlib.sha256(canonical(rows)).hexdigest(),'rows':len(rows)}
    return result


def photography_projection(tables):
    areas=row_index(tables['Area']);quests=row_index(tables['Quest'])
    area=areas.get('area-main-002');need(area is not None,'latest_media_area_missing')
    selected=area.get('questIds')
    need(type(selected) is list and selected and len(set(selected))==len(selected)
         and all(identity in quests for identity in selected),'latest_media_quest_missing')
    return {'schema':1,'area':{key:area.get(key) for key in ('id','type','questIds')},
            'quests':[{key:quests[identity].get(key) for key in ('id','areaId')} for identity in selected]}


def panorama_projection(tables):
    from idoly_local.panorama_rules import PANORAMA_RULES,MASTER_PANORAMA_RULES
    music=row_index(tables['Music']);stage=row_index(tables['Stage'])
    rules=(*PANORAMA_RULES,*MASTER_PANORAMA_RULES);need(len(rules)==15,'latest_panorama_facts_differ')
    musics=[]
    for rule in rules:
        row=music.get(rule.music_id);need(row is not None,'latest_panorama_music_missing')
        value={key:row.get(key) for key in ('id','assetId','is360LiveExist','displayCharacterAmount')}
        if rule in MASTER_PANORAMA_RULES:
            value.update(selectableStageIds=row.get('selectableStageIds'),releaseTime=str(row.get('releaseTime')))
        musics.append(value)
    stages=[]
    for identity in sorted({rule.stage_id for rule in rules}):
        row=stage.get(identity);need(row is not None and type(row.get('cameraPositions')) is list,
                                    'latest_panorama_stage_missing')
        stages.append({'id':row['id'],'assetId':row.get('assetId'),
            'cameraPositions':[{key:position.get(key) for key in ('name','index')} for position in row['cameraPositions']]})
    return {'schema':1,'musics':musics,'stages':stages}


def media_external_controls(context,*,legacy=False):
    function=table_rows(context,'FunctionLock',legacy=legacy)
    selected=sorted((row for row in function if row.get('type') in (16,49)),key=lambda row:row['type'])
    need([row['type'] for row in selected]==[16,49],'latest_media_function_control_missing')
    conditions=row_index(table_rows(context,'Condition',legacy=legacy))
    descriptions=row_index(table_rows(context,'ConditionDescription',legacy=legacy))
    names=('cd-clear-area-main-002','cd-photo_panorama_music-start')
    need(all(name in conditions for name in names),'latest_media_condition_control_missing')
    description=descriptions.get('cd-tutorial-finish-photo-create-shooting')
    need(description is not None and description.get('description')=='フォト撮影チュートリアル突破',
         'latest_media_description_control_changed')
    return {'function_locks':selected,'conditions':[conditions[name] for name in names],'description':description}


def semantic_envelope(scope,receipt):
    need(scope in ('story_reads','media_access','panorama','dream','main_live','octo')
         and type(receipt) is dict and receipt and receipt.get('status') in (None,'PASS'),'latest_semantic_receipt_invalid')
    need(len(canonical(receipt))<=MAX_PROOF,'latest_semantic_receipt_bound')
    return {'status':'PASS','scope':scope,'master_version':MASTER_VERSION,'schema_sha256':SCHEMA_SHA256,
            'receipt':receipt,'receipt_sha256':hashlib.sha256(canonical(receipt)).hexdigest()}


def prepare_semantic_controls(context,proof_directory,*,partial=False):
    global PHASE
    from idoly_local.story_read_rules import audit_story_semantics
    from idoly_local.panorama_rules import SOURCE_SHA256
    PHASE='cohort_semantic_controls'
    proof_directory=Path(proof_directory);proof_directory.mkdir(parents=True,exist_ok=True)
    needed=('Story','Condition','Message','Telephone','Item','Area','Quest','Music','Stage')
    before={table:table_rows(context,table,legacy=True) for table in needed}
    after={table:table_rows(context,table) for table in needed}
    old_story=audit_story_semantics(*(before[table] for table in ('Story','Condition','Message','Telephone','Item')))
    new_story=audit_story_semantics(*(after[table] for table in ('Story','Condition','Message','Telephone','Item')))
    need(old_story['story_rewards_sha256']==new_story['story_rewards_sha256'],'latest_story_reward_semantics_changed')
    story={'baseline':old_story,'candidate':new_story,'reward_scope_equal':True,'whole_condition_graph_equality_claim':False,
           'source_tables':{'baseline':source_table_proofs(context,needed[:5],legacy=True),
                            'candidate':source_table_proofs(context,needed[:5])}}
    old_external=media_external_controls(context,legacy=True);new_external=media_external_controls(context)
    controls={}
    for key,projection,tables in (('media_access',photography_projection,('Area','Quest')),
                                  ('panorama',panorama_projection,('Music','Stage'))):
        old,new=projection(before),projection(after)
        receipt={'baseline_projection':old,'candidate_projection':new,
                 'baseline_projection_sha256':hashlib.sha256(canonical(old)).hexdigest(),
                 'candidate_projection_sha256':hashlib.sha256(canonical(new)).hexdigest(),
                 'projection_equal':old==new,'baseline_external_controls':old_external,
                 'candidate_external_controls':new_external,'external_controls_equal':old_external==new_external,
                 'source_tables':{'baseline':source_table_proofs(context,tables,legacy=True),
                                  'candidate':source_table_proofs(context,tables)}}
        if key=='panorama':receipt['fourteen_factual_rules_sha256']=SOURCE_SHA256
        controls[key]=semantic_envelope(key,receipt)
    # Save bounded original projections before rejecting a change; this makes a
    # failed candidate auditable without pretending it passed the semantic gate.
    raw_controls={'schema':1,'master_version':MASTER_VERSION,'features':controls}
    need(len(canonical(raw_controls))<=64*1024,'latest_media_projection_proof_bound')
    write_json(proof_directory/'latest-semantic-controls.json',raw_controls)
    need(all(row['receipt']['projection_equal'] and row['receipt']['external_controls_equal']
             for row in controls.values()),'latest_media_semantics_changed')
    controls['story_reads']=semantic_envelope('story_reads',story)
    octo=context['octo_proof']
    controls['octo']=semantic_envelope('octo',{'schema':1,'proof_sha256':hashlib.sha256(canonical(octo)+b'\n').hexdigest(),
        'platforms':{key:{name:value for name,value in row.items() if name!='models'} for key,row in octo['platforms'].items()},
        'required_card_images':len(octo['card_images']),'card_images_sha256':hashlib.sha256(canonical(octo['card_images'])).hexdigest(),
        'adv_identity_sha256':hashlib.sha256(canonical(octo['adv_identity'])).hexdigest(),
        'cdn_asset_bytes_downloaded':False,'unity_playback_verified':False})
    if not partial:
        # Pure original-data callbacks are supplied by their feature owners.
        # Missing callbacks fail closed and never produce an empty PASS receipt.
        from idoly_local.dream import audit_latest_dream_semantics
        from idoly_local.live_input import audit_latest_main_live_semantics
        for key,callback in (('dream',audit_latest_dream_semantics),('main_live',audit_latest_main_live_semantics)):
            PHASE='semantic_'+key
            try:
                receipt=callback(context['schema'],context['legacy']/'master-json',context['audit_masters'])
            except ValueError as error:
                code='latest_'+key+'_semantics_changed'
                if getattr(error,'code',None)!=code:raise
                # Only the callback's fixed public identifier is admitted;
                # raw exceptions, rows, paths and remote bodies are never used.
                failure={'schema':1,'scope':key,'status':'FAIL','reason_code':'audited_master_semantics_changed'}
                candidate=getattr(error,'receipt',None)
                if (type(candidate) is dict and set(candidate)==set(failure)
                        and type(candidate.get('schema')) is int and candidate['schema']==1
                        and candidate.get('scope')==key and candidate.get('status')=='FAIL'
                        and type(candidate.get('reason_code')) is str
                        and re.fullmatch(r'[a-z][a-z0-9_]{0,79}',candidate['reason_code'])):
                    failure=deepcopy(candidate)
                (proof_directory/'latest-semantic-controls.json').unlink()
                write_json(proof_directory/'latest-semantic-controls.json',{'schema':1,'master_version':MASTER_VERSION,
                    'status':'FAIL','feature':key,'error_code':code,'receipt':failure})
                raise PreparationError(code) from None
            controls[key]=semantic_envelope(key,receipt)
        need(set(controls)=={'story_reads','media_access','panorama','dream','main_live','octo'},'latest_semantic_feature_missing')
    (proof_directory/'latest-semantic-controls.json').unlink()
    write_json(proof_directory/'latest-semantic-controls.json',{'schema':1,'master_version':MASTER_VERSION,'features':controls})
    need((proof_directory/'latest-semantic-controls.json').stat().st_size<=MAX_PROOF,'latest_semantic_controls_bound')
    if not partial:
        shutil.copyfile(proof_directory/'latest-semantic-controls.json',context['public']/'latest-semantic-controls.json')
    container={'schema':1,'master_version':MASTER_VERSION,'features':controls}
    context['semantic_controls']=container
    return container


def prepare_love(context):
    global PHASE
    PHASE='love_semantic_compatibility'
    from idoly_local.love_catalog import prepare_latest_love_catalog
    public,legacy=context['public'],context['legacy']
    proofs={table:next(row['sha256'] for row in context['active_packs'] if row['type']==table)
            for table in ('LoveHomeAction','LoveLevel','LoveStoryEpisode','LoveColor')}
    return prepare_latest_love_catalog(context['schema'],public/'master-json',latest_pack_proofs=proofs,
        legacy_master_dir=legacy/'master-json',legacy_catalog_path=legacy/'master-json/LoveCatalog.json',
        output_path=public/'master-json/LoveCatalog.json',compatibility_path=public/'love-compatibility.json',
        legacy_rules_path=public/'love-legacy-rules.json',adv_identity_proof=context['adv_identity_proof'])


def revalidate_public_templates(context):
    global PHASE
    public=context['public'];schema=context['schema'];masters=public/'master-json'
    from idoly_local.tutorial_replay import validate_replays
    from idoly_local.story_catalog import validate_story_catalog
    PHASE='public_template_revalidation'
    for folder in ('public-tutorial','public-story'):
        path=public/folder/'manifest.json';value=read_json(path)
        need(value.get('master_version')==BASE_VERSION,'latest_public_template_source_differs')
        value['master_version']=MASTER_VERSION
        path.unlink();write_json(path,value)
    # Only version binding changes; the existing exact PB/source digest and
    # every referenced latest master row are revalidated by their producers.
    tutorial=validate_replays(schema,masters,public/'public-tutorial')
    story=validate_story_catalog(schema,masters,public/'public-story')
    return tutorial,story


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def public_get(url,maximum,*,github_api=False):
    parsed=urlsplit(url)
    need(parsed.scheme=='https' and parsed.hostname in ('api.github.com','raw.githubusercontent.com')
         and parsed.port in (None,443) and not parsed.username and not parsed.password and not parsed.fragment,
         'latest_translation_origin_invalid')
    headers={'Accept-Encoding':'identity','User-Agent':'idoly-public-cohort-preparer'}
    token=os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if github_api and token:headers['Authorization']='Bearer '+token
    opener=build_opener(NoRedirect())
    with opener.open(Request(url,headers=headers),timeout=45) as response:
        need(response.status==200,'latest_translation_source_unavailable')
        raw=response.read(maximum+1)
    need(len(raw)<=maximum,'latest_translation_source_bound')
    return raw


def translation_sources(legacy,work,language):
    coverage=read_json(legacy/'original-master/languages'/language/'coverage.json')
    source=deepcopy(coverage['source']);files=coverage['source_files']
    match=re.fullmatch(r'https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)',source.get('repository',''))
    need(match and re.fullmatch(r'[0-9a-f]{40}',source.get('revision','')) and isinstance(files,dict)
         and 0<len(files)<=202,'latest_translation_provenance_invalid')
    owner,repo=match.groups();revision=source['revision']
    tree=decode(public_get(f'https://api.github.com/repos/{owner}/{repo}/git/trees/{revision}?recursive=1',16*1024*1024,github_api=True))
    need(type(tree) is dict and tree.get('truncated') is False and isinstance(tree.get('tree'),list),
         'latest_translation_tree_invalid')
    entries=tree['tree'];destination=work/'translation-sources'/language/'masterTrans';destination.mkdir(parents=True)
    total=0
    for name,expected in sorted(files.items()):
        need(re.fullmatch(r'[A-Za-z0-9_]{1,128}\.json',name) and type(expected) is dict
             and set(expected)=={'bytes','sha256','git_blob_sha1'} and type(expected['bytes']) is int
             and 0<expected['bytes']<=8*1024*1024,'latest_translation_file_invalid')
        candidates=[row for row in entries if row.get('type')=='blob' and row.get('sha')==expected['git_blob_sha1']
                    and PurePosixPath(row.get('path','')).name==name]
        need(candidates,'latest_translation_blob_missing')
        chosen=sorted(candidates,key=lambda row:row['path'])[0];path=PurePosixPath(chosen['path'])
        need(not path.is_absolute() and str(path)==chosen['path'] and all(part not in ('','.','..') for part in path.parts)
             and re.fullmatch(r'[A-Za-z0-9_./-]{1,512}',chosen['path']),'latest_translation_path_invalid')
        raw=public_get(f'https://raw.githubusercontent.com/{owner}/{repo}/{revision}/{path.as_posix()}',expected['bytes'])
        total+=len(raw);need(total<=64*1024*1024,'latest_translation_source_bound')
        blob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        need(len(raw)==expected['bytes'] and hashlib.sha256(raw).hexdigest()==expected['sha256']
             and blob==expected['git_blob_sha1'],'latest_translation_blob_differs')
        with (destination/name).open('xb') as stream:stream.write(raw)
    source['files']=files
    return destination,source


def merge_pack_files(source,destination):
    for path in sorted((Path(source)/'assets/master').iterdir()):
        need(path.is_file() and not path.is_symlink() and re.fullmatch(r'[A-Za-z0-9_.-]{1,220}',path.name),
             'latest_generated_pack_invalid')
        target=Path(destination)/path.name
        if target.exists():
            need(target.is_file() and target.stat().st_size==path.stat().st_size and digest(target)==digest(path),
                 'latest_generated_pack_collision')
        else:shutil.copyfile(path,target)


def prior_translation_overlay(legacy,work,language):
    target=work/'reuse-translations'/language;(target/'assets/master').mkdir(parents=True)
    for filename in ('master-tag.json','coverage.json'):
        shutil.copyfile(legacy/'original-master/languages'/language/filename,target/filename)
    for path in (legacy/'original-master/assets/master').iterdir():
        if path.is_file():os.link(path,target/'assets/master'/path.name)
    return target


def sorted_variant(context,tag,language,mode,work):
    from idoly_local.master_sort_build import build_sort_master_overlays
    public=context['public'];pool=public/'original-master/assets/master';packs={pack['type']:pack for pack in tag['masterTagPacks']}
    rows={table:context['read_rows'](context['schema'],context['driver'],pool,packs[table])
          for table in ('Music','Costume','PhotoQuestMusic')}
    stage=work/('sort-'+language+'-'+mode)
    result=build_sort_master_overlays(context['schema'],tag,rows,stage,language=language,source=mode)
    merge_pack_files(stage,pool)
    return stage/'sort-manifest.json',result


def prepare_locales(context,work):
    global PHASE
    from idoly_local.media_master_build import build_media_master_overlay
    from idoly_local.master_translation_build import build_translation_master_overlay
    public,legacy=context['public'],context['legacy'];original=public/'original-master';pool=original/'assets/master'
    schema=context['schema'];PHASE='gallery_eight_pack_generation'
    media=work/'gallery-master'
    gallery=build_media_master_overlay(schema,original/'master-tag.json',pool,public/'master-json',media)
    merge_pack_files(media,pool);shutil.copyfile(media/'media-master-tag.json',original/'media-master-tag.json')
    tags={'ja':{'normal':context['tag'],'media':read_json(original/'media-master-tag.json')}}
    for language in ('ko','en'):
        PHASE='language_'+language+'_source_and_normal'
        translations,source=translation_sources(legacy,work,language)
        reuse=prior_translation_overlay(legacy,work,language)
        normal=work/('language-'+language+'-normal')
        normal_report=build_translation_master_overlay(schema,context['tag'],pool,translations,normal,
            language=language,source=source,reuse_overlay=reuse)
        merge_pack_files(normal,pool)
        directory=original/'languages'/language;directory.mkdir(parents=True)
        for filename in ('master-tag.json','coverage.json'):shutil.copyfile(normal/filename,directory/filename)
        PHASE='language_'+language+'_media'
        translated_media=work/('language-'+language+'-media')
        media_report=build_translation_master_overlay(schema,tags['ja']['media'],pool,translations,translated_media,
            language=language,source=source,media_mode=True,reuse_overlay=normal)
        merge_pack_files(translated_media,pool)
        shutil.copyfile(translated_media/'master-tag.json',directory/'media-master-tag.json')
        shutil.copyfile(translated_media/'coverage.json',directory/'media-coverage.json')
        tags[language]={'normal':read_json(directory/'master-tag.json'),'media':read_json(directory/'media-master-tag.json')}
        need(normal_report['source_version']==MASTER_VERSION and media_report['source_version']==tags['ja']['media']['version'],
             'latest_language_source_cohort_differs')
    locales={}
    for language,modes in tags.items():
        locales[language]={}
        directory=original if language=='ja' else original/'languages'/language
        for mode,tag in modes.items():
            PHASE='sort_'+language+'_'+mode
            path,sort=sorted_variant(context,tag,language,mode,work)
            stem='' if mode=='normal' else 'media-'
            target=directory/(stem+'master-sort.json');shutil.copyfile(path,target)
            tagpath=directory/(stem+'master-tag.json')
            need(len(tag['masterTagPacks'])==202 and {row['type'] for row in tag['masterTagPacks']}==set(context['packs'])
                 and sort['base_version']==tag['version'],'latest_locale_inventory_differs')
            for pack in tag['masterTagPacks']:
                path=pool/pack['fileName']
                need(path.is_file() and path.stat().st_size==pack['fileSize'],'latest_locale_pack_missing')
            locales[language][mode]={'tag_version':tag['version'],'tag_sha256':digest(tagpath),'pack_count':202,
                'table_names':sorted(context['packs']),'sort_manifest_sha256':digest(target)}
    return locales,gallery


def source_overlay(pins):
    return {'schema':1,'operation':POLICY,'derivation':'complete-public-member-replacement',
        'base_sha256':BASE_SHA256,'base_bytes':BASE_BYTES,'master_version':MASTER_VERSION,
        'component_sources':pins,'component_sources_sha256':hashlib.sha256(canonical(pins)).hexdigest()}


def write_payload(public,output):
    need(not Path(output).exists() and not Path(output).is_symlink(),'latest_fresh_output_required')
    with ZipFile(output,'x',compression=ZIP_DEFLATED,compresslevel=6) as archive:
        for path in sorted(Path(public).rglob('*')):
            if path.is_dir():continue
            need(path.is_file() and not path.is_symlink(),'latest_generated_member_invalid')
            name='data/'+path.relative_to(public).as_posix();need(safe_name(name),'latest_generated_member_invalid')
            info=ZipInfo(name,STAMP);info.compress_type=ZIP_DEFLATED;info.create_system=3
            info.external_attr=0o100644<<16;info.extra=info.comment=b''
            with path.open('rb') as incoming,archive.open(info,'w') as outgoing:shutil.copyfileobj(incoming,outgoing,CHUNK)
    need(Path(output).stat().st_size<=MAX_BLOB,'latest_payload_bound')


def preservation(old_rows,new_rows):
    old={row['path']:row for row in old_rows};new={row['path']:row for row in new_rows}
    shared=old.keys() & new.keys()
    return {'unchanged_paths':sorted(key for key in shared if old[key]==new[key]),
        'replaced_paths':sorted(key for key in shared if old[key]!=new[key]),
        'removed_paths':sorted(old.keys()-new.keys()),'added_paths':sorted(new.keys()-old.keys())}


def compile_latest_server_data(base,latest,output,*,source_blob_path,report_path,work,compatibility_only=False):
    global PHASE
    base,latest,output,report_path,work=map(Path,(base,latest,output,report_path,work))
    need(not work.exists() and not output.exists() and not report_path.exists(),'latest_fresh_work_required')
    if not compatibility_only:
        need(source_blob_path is not None,'latest_source_blob_required')
        need(not Path(source_blob_path).exists() and not Path(source_blob_path).resolve().is_relative_to(ROOT),'latest_fresh_blob_required')
    need(all(not path.resolve().is_relative_to(ROOT) for path in (output,report_path,work)),
         'latest_outputs_must_be_remote_owned_paths')
    work.mkdir(mode=0o700);pins=source_pins()
    context=prepare_inputs(base,latest,work)
    octo=prepare_octo(context)
    proof_directory=report_path.parent
    proof_directory.mkdir(parents=True,exist_ok=True)
    write_json(proof_directory/'latest-octo-proof.json',octo)
    love_report=prepare_love(context)
    semantic=prepare_semantic_controls(context,proof_directory,partial=compatibility_only)
    if compatibility_only:
        proof={'schema':1,'status':'PASS','operation':'latest-cohort-compatibility-audit-v1',
            'base_master_version':BASE_VERSION,'master_version':MASTER_VERSION,'component_sources':pins,
            'love':love_report,'record_audit':context['record_audit'],'tables':context['counts'],'semantic_controls':semantic}
        need(len(canonical(proof))<=MAX_PROOF,'latest_small_proof_bound');write_json(report_path,proof)
        return proof
    need(love_report['equivalent'] is True,'latest_love_semantics_changed')
    PHASE='public_templates';tutorial,story=revalidate_public_templates(context)
    locales,gallery=prepare_locales(context,work)
    public=context['public'];original=public/'original-master';catalog=read_json(public/'master-json/LoveCatalog.json')
    love={'master_version':MASTER_VERSION,'schema_sha256':SCHEMA_SHA256,'ruleset_sha256':catalog['ruleset_sha256'],
        'events':len(catalog['events']),'episodes':sum(len(row['episodes']) for row in catalog['events'].values()),
        'compatibility':{'path':'data/love-compatibility.json','sha256':digest(public/'love-compatibility.json'),
            'legacy_ruleset_sha256':LEGACY_RULESET_SHA256,'legacy_rules_path':'data/love-legacy-rules.json',
            'legacy_rules_sha256':digest(public/'love-legacy-rules.json')}}
    need(love['events']==6 and love['episodes']==72,'latest_love_catalog_count_differs')
    PHASE='managed_manifest'
    members=file_rows(public)
    need(MANIFEST not in {row['path'] for row in members},'latest_manifest_already_present')
    summary={'schema':1,'master_version':MASTER_VERSION,'schema_sha256':SCHEMA_SHA256,'tables':context['counts'],
        'tutorial_replays':tutorial,'story_catalog':story,'love_catalog':love,'locales':locales,
        'record_audit':context['record_audit'],'semantic_controls':semantic,'source_overlay':source_overlay(pins),'files':members}
    manifest_raw=canonical(summary)+b'\n';need(len(manifest_raw)<=2*1024*1024,'latest_manifest_bound')
    with (public/'payload-manifest.json').open('xb') as stream:stream.write(manifest_raw)
    PHASE='freeze_complete_public_blob'
    output.parent.mkdir(parents=True,exist_ok=True);write_payload(public,output)
    with ZipFile(output) as archive:verified=archive_rows(archive)
    need(verified==file_rows(public),'latest_output_inventory_differs')
    blob=Path(source_blob_path);blob.parent.mkdir(parents=True,exist_ok=True)
    with output.open('rb') as incoming,blob.open('xb') as outgoing:shutil.copyfileobj(incoming,outgoing,CHUNK)
    names=[row['path'] for row in verified]
    tables=sorted(PurePosixPath(name).stem for name in names if name.startswith('data/master-json/') and name.endswith('.json'))
    need(tables==sorted((*RAW_TABLES,'LoveCatalog')) and len(tables)==64,'latest_final_table_inventory_differs')
    size=output.stat().st_size;whole=digest(output)
    need(blob.stat().st_size==size and digest(blob)==whole and source_pins()==pins,'latest_source_or_blob_changed')
    result={'schema':1,'status':'PASS','operation':POLICY,
        'base':{'bytes':BASE_BYTES,'sha256':BASE_SHA256,'entries':len(context['old_rows']),'master_json_tables':55},
        'component_sources':pins,'component_sources_sha256':hashlib.sha256(canonical(pins)).hexdigest(),
        'source_blob':{'path':BLOB_NAME,'bytes':size,'sha256':whole},
        'output':{'bytes':size,'sha256':whole,'entries':len(verified),'master_json_tables':64,
            'payload_manifest_sha256':hashlib.sha256(manifest_raw).hexdigest(),
            'member_inventory_sha256':hashlib.sha256(canonical(members)).hexdigest(),
            'member_names':names,'master_json_table_names':tables,'members':members},
        'original_master':{'version':MASTER_VERSION,'schema_sha256':SCHEMA_SHA256,'descriptor_sha256':DESCRIPTOR_SHA256,
            'tag_sha256':digest(original/'master-tag.json'),'archive_report_sha256':digest(original/'archive-report.json'),
            'pack_count':202,'packs':context['active_packs']},'love':love,'locales':locales,
        'preservation':preservation(context['old_rows'],verified),'semantic_controls':semantic,
        'derivation':{'kind':'complete-public-member-replacement','native_apply':'verified-copy',
            'sqlcipher_bytes_frozen':True,'raw_compile_repeat_byte_identity_claim':False}}
    need(len(canonical(result))<=MAX_PROOF,'latest_small_proof_bound');write_json(report_path,result)
    PHASE='complete'
    return result


def admit_proof_artifact(source,destination):
    """Always-run artifact boundary: copy only bounded fixed-name metadata.

    Failed or overlarge private compiler output remains on the disposable
    runner. Only a new small fixed failure document may leave that runner.
    """
    source,destination=Path(source),Path(destination)
    need(not destination.exists() and not destination.is_symlink(),'latest_fresh_proof_destination_required')
    destination.mkdir(mode=0o700)
    copies={};valid=False
    try:
        need(source.is_dir() and not source.is_symlink(),'latest_proof_source_invalid')
        paths=list(source.iterdir())
        need(0<len(paths)<=4 and {path.name for path in paths}<=PROOF_NAMES,'latest_proof_source_invalid')
        total=0
        for path in paths:
            fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
            with os.fdopen(fd,'rb') as stream:
                before=os.fstat(stream.fileno());outer=path.lstat()
                need(stat.S_ISREG(before.st_mode) and not stat.S_ISLNK(outer.st_mode)
                     and (before.st_dev,before.st_ino)==(outer.st_dev,outer.st_ino)
                     and 0<before.st_size<=MAX_PROOF,'latest_proof_source_invalid')
                total+=before.st_size;need(total<=MAX_PROOF,'latest_proof_artifact_bound')
                raw=stream.read(before.st_size+1);after=os.fstat(stream.fileno())
                need(len(raw)==before.st_size and all(getattr(before,key)==getattr(after,key)
                     for key in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')),'latest_proof_source_changed')
            need(type(decode(raw)) is dict,'latest_proof_source_invalid')
            copies[path.name]=raw
        valid=True
    except (OSError,ValueError,TypeError):
        copies={'latest-server-data.report.json':canonical({'schema':1,'status':'FAIL','phase':'proof_artifact_admission',
                'error_code':'latest_proof_artifact_rejected'})+b'\n'}
    for name,raw in sorted(copies.items()):
        with (destination/name).open('xb') as stream:stream.write(raw)
    return valid


def latest_pin_helper():
    spec=importlib.util.spec_from_file_location('idoly_latest_data_pin',ROOT/'tools/latest_server_data_pin.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def upgrade_server_data(base_zip,output_zip,*,overlay_zip,report_path=None):
    """Apply a full fixed source blob without SQLCipher/runtime imports.

    ``None`` explicitly means this copy caller supplies no historical BASE
    input. The static preparation proof still binds its verified original BASE
    provenance; the complete current blob/payload/proof checks remain mandatory.
    A supplied BASE is always checked, never treated as another payload cohort.
    """
    if base_zip is not None:pin_file(base_zip,BASE_BYTES,BASE_SHA256)
    output=Path(output_zip);need(not output.exists() and not output.is_symlink(),'latest_fresh_output_required')
    if report_path is not None:need(not Path(report_path).exists(),'latest_fresh_report_required')
    helper=latest_pin_helper();pin=helper.load_pin();helper.verify_overlay(overlay_zip)
    output.parent.mkdir(parents=True,exist_ok=True)
    descriptor,temporary=tempfile.mkstemp(prefix='.latest-cohort-',dir=output.parent);partial=Path(temporary)
    try:
        with os.fdopen(descriptor,'wb') as outgoing,Path(overlay_zip).open('rb') as incoming:
            shutil.copyfileobj(incoming,outgoing,CHUNK);outgoing.flush();os.fsync(outgoing.fileno())
        helper.verify_payload(partial)
        proof=helper.verify_upgrade_proof(deepcopy(pin['upgrade_proof']))
        need(not output.exists() and not output.is_symlink(),'latest_output_appeared')
        os.link(partial,output);partial.unlink()
        if report_path is not None:write_json(report_path,proof)
        return proof
    finally:
        partial.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-zip',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--overlay-zip',type=Path)
    mode.add_argument('--compile',action='store_true')
    mode.add_argument('--compatibility-only',action='store_true')
    parser.add_argument('--latest-archive',type=Path)
    parser.add_argument('--source-blob',type=Path)
    parser.add_argument('--work',type=Path)
    args=parser.parse_args()
    try:
        if args.overlay_zip is not None:
            value=upgrade_server_data(args.base_zip,args.output,overlay_zip=args.overlay_zip,report_path=args.report)
        else:
            need(args.latest_archive is not None and args.work is not None,'latest_compile_inputs_required')
            value=compile_latest_server_data(args.base_zip,args.latest_archive,args.output,
                source_blob_path=args.source_blob,report_path=args.report,work=args.work,compatibility_only=args.compatibility_only)
        print(json.dumps({'status':'PASS','operation':value['operation'],'report_bytes':args.report.stat().st_size,
            'report_sha256':digest(args.report),'output':value.get('source_blob')}))
        return 0
    except Exception as error:
        failure={'schema':1,'status':'FAIL','phase':PHASE,
            'error_code':str(error) if isinstance(error,PreparationError) else 'latest_preparation_failed',
            'error_class':type(error).__name__ if type(error).__name__ in ('ValueError','OSError','ImportError','KeyError','HTTPError') else 'Exception'}
        if not args.report.exists():write_json(args.report,failure)
        print(json.dumps(failure))
        return 1


if __name__=='__main__':raise SystemExit(main())
