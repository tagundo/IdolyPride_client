#!/usr/bin/env python3
"""Publish pinned, separately downloadable build artifacts through private Git LFS.

Useful when release uploads are unavailable. Every object is downloaded and
checked before a new pointer-only download branch becomes visible. Credentials
and temporary signed URLs are never written to the publication report.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import tempfile
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

ROOT=Path(__file__).resolve().parents[1]
REMOTE='https://github.com/tagundo/IdolyPride_client.git'
BATCH=REMOTE+'/info/lfs/objects/batch'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): raise ValueError('Unexpected LFS redirect')


def git(arguments,*,env=None,data=None):
    return subprocess.run(['git',*arguments],cwd=ROOT,env=env,input=data,
        check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout.decode().strip()


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--readme',type=Path,required=True)
    parser.add_argument('--branch',required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args()
    manifest=json.loads(args.manifest.read_text())
    if not re.fullmatch(r'downloads/[a-z0-9][a-z0-9._/-]{0,100}',args.branch): raise ValueError('Expected a new downloads branch')
    if git(['ls-remote','--heads',REMOTE,'refs/heads/'+args.branch]): raise ValueError('Download branch already exists')
    if not re.fullmatch('[a-f0-9]{40}',manifest['source_commit']): raise ValueError('Expected a frozen source commit')
    files=manifest['artifacts']
    if not isinstance(files,list) or not 1<=len(files)<=8: raise ValueError('Invalid artifact count')
    names=set()
    for item in files:
        path=Path(item['path']).resolve(strict=True); name=item['name']
        if (path.name!=name or name in names or not re.fullmatch('[A-Za-z0-9._-]+',name)
                or not name.endswith(('.apk','.ipa','.app.zip')) or type(item['bytes']) is not int
                or not 0<item['bytes']<=2*1024**3 or path.stat().st_size!=item['bytes']
                or not re.fullmatch('[a-f0-9]{64}',item['sha256'])): raise ValueError('Artifact identity differs')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=item['sha256']: raise ValueError('Artifact hash differs')
        names.add(name)
    args.evidence.mkdir(parents=True,exist_ok=False)
    state={'schema':1,'source_commit':manifest['source_commit'],'branch':args.branch,'published':False,'artifacts':[]}
    def save(): (args.evidence/'publication.json').write_text(json.dumps(state,indent=2)+'\n')
    save()
    authorization='Basic '+base64.b64encode(('x-access-token:'+os.environ['GH_TOKEN']).encode()).decode()
    opener=build_opener(NoRedirect(),HTTPSHandler(context=ssl.create_default_context()))
    def batch(operation,item):
        data=json.dumps({'operation':operation,'transfers':['basic'],'objects':[{'oid':item['sha256'],'size':item['bytes']}]}).encode()
        request=Request(BATCH,data=data,method='POST',headers={'Authorization':authorization,
            'Accept':'application/vnd.git-lfs+json','Content-Type':'application/vnd.git-lfs+json'})
        with opener.open(request,timeout=30) as response: result=json.loads(response.read(65536))
        objects=result['objects']
        if len(objects)!=1 or objects[0].get('error') or objects[0]['oid']!=item['sha256'] or objects[0]['size']!=item['bytes']:
            raise ValueError('LFS object identity differs')
        return objects[0].get('actions',{})
    def request(action,*,method='GET',data=None,headers=None):
        target=urlsplit(action['href']); host=target.hostname or ''
        if target.scheme!='https' or not (host in ('github.com','lfs.github.com')
                or host.endswith('.githubusercontent.com') or host.endswith('.amazonaws.com')):
            raise ValueError('Unexpected LFS action host')
        return Request(action['href'],data=data,method=method,headers={**action.get('header',{}),**(headers or {})})
    objects=None
    try:
        for item in files:
            receipt={'name':item['name'],'sha256':item['sha256'],'bytes':item['bytes'],'stage':'upload'}
            state['artifacts'].append(receipt); save()
            actions=batch('upload',item)
            if 'upload' in actions:
                with Path(item['path']).open('rb') as stream:
                    with opener.open(request(actions['upload'],method='PUT',data=stream,headers={
                            'Content-Length':str(item['bytes']),'Content-Type':'application/octet-stream',
                            'Content-Disposition':'attachment; filename="'+item['name']+'"'}),timeout=120) as response:
                        if response.status not in (200,201,202,204): raise ValueError('LFS upload refused')
                        response.read(65536)
            if 'verify' in actions:
                body=json.dumps({'oid':item['sha256'],'size':item['bytes']}).encode()
                with opener.open(request(actions['verify'],method='POST',data=body,headers={
                        'Content-Type':'application/vnd.git-lfs+json'}),timeout=30) as response:
                    if response.status not in (200,201,202,204): raise ValueError('LFS verification refused')
                    response.read(65536)
            receipt['stage']='full_download_verify'; save()
            action=batch('download',item)['download']; digest=hashlib.sha256(); total=0
            for begin in range(0,item['bytes'],8*1024*1024):
                end=min(item['bytes'],begin+8*1024*1024)-1; count=0
                with opener.open(request(action,headers={'Range':f'bytes={begin}-{end}','Accept-Encoding':'identity'}),timeout=60) as response:
                    if response.status!=206 or response.headers.get('Content-Range')!=f'bytes {begin}-{end}/{item["bytes"]}':
                        raise ValueError('Invalid download byte range')
                    while block:=response.read(128*1024):
                        count+=len(block)
                        if count>end-begin+1: raise ValueError('Overlong download range')
                        digest.update(block)
                if count!=end-begin+1: raise ValueError('Truncated download range')
                total+=count
            if total!=item['bytes'] or digest.hexdigest()!=item['sha256']: raise ValueError('Complete download differs')
            receipt.update(stage='verified',complete_download_verified=True); save()
        env={key:value for key,value in os.environ.items() if not key.startswith('GIT_TRACE') and key not in ('GIT_CURL_VERBOSE','GH_DEBUG')}
        objects=Path(tempfile.mkdtemp(prefix='idoly-bundle-pointers-',dir='/dev/shm'))
        env.update(GIT_OBJECT_DIRECTORY=str(objects),GIT_ALTERNATE_OBJECT_DIRECTORIES=str(ROOT/'.git/objects'),GIT_LFS_SKIP_PUSH='1')
        tree_files={'.gitattributes':b'*.apk filter=lfs diff=lfs merge=lfs -text\n*.ipa filter=lfs diff=lfs merge=lfs -text\n*.app.zip filter=lfs diff=lfs merge=lfs -text\n',
            'README.md':args.readme.read_bytes(),
            'SHA256SUMS':''.join(f'{item["sha256"]}  {item["name"]}\n' for item in files).encode(),
            'RELEASE-VERIFICATION.json':json.dumps({**manifest,'artifacts':[{k:v for k,v in item.items() if k!='path'} for item in files]},indent=2).encode()+b'\n'}
        for item in files: tree_files[item['name']]=f'version https://git-lfs.github.com/spec/v1\noid sha256:{item["sha256"]}\nsize {item["bytes"]}\n'.encode()
        blobs={name:git(['hash-object','-w','--stdin'],env=env,data=data) for name,data in tree_files.items()}
        tree=git(['mktree'],env=env,data=''.join(f'100644 blob {blobs[name]}\t{name}\n' for name in sorted(blobs)).encode())
        commit=git(['commit-tree',tree],env=env,data=b'Publish separately verified local client and server binaries\n')
        git(['-c','pack.threads=1','push',REMOTE,commit+':refs/heads/'+args.branch],env=env)
        state.update(published=True,commit=commit,tree=tree); save()
        print(json.dumps(state))
    except Exception as error:
        state.update(error_type=type(error).__name__,http_status=getattr(error,'code',None)); save()
        raise SystemExit('Publication stopped; sanitized evidence saved') from None
    finally:
        if objects is not None: shutil.rmtree(objects)


if __name__=='__main__': main()
