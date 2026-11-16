"""Disposable WK navigation uses the same visible controls as a user."""
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "ios-unified/probe/main.m"


def script():
    source = SOURCE.read_text()
    match = re.search(r"static NSString \*const ProbeSettingsNavigationScript =\s*(.*?);\n\n//", source, re.S)
    assert match
    return "".join(json.loads(raw) for raw in re.findall(r'@?("(?:[^"\\]|\\.)*")', match.group(1)))


def test_native_actions_reveal_categories_without_mutating_visibility_or_skipping_existing_gates():
    source = SOURCE.read_text(); reveal = script()
    assert ".click()" in reveal and "summary.click()" in reveal
    assert not re.search(r"\.(?:hidden|open)\s*=(?!=)", reveal)
    assert "dataWithJSONObject:@[identifier]" in source
    for control in ("diagnostics-copy", "language", "resources-import", "accounts-refresh", "official-inspect"):
        assert '@"' + control + '") completionHandler:' in source or '@"' + control + '"),' in source
    assert "account_ui_control_hidden" in source
    assert "120*NSEC_PER_SEC" in source and "15*NSEC_PER_SEC" in source


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for actual probe navigation semantics")
def test_probe_activates_observed_category_then_outer_and_inner_summaries():
    program = "const reveal=" + script() + r""";
const assert=require('node:assert/strict');const actions=[];
class Element {
 constructor(id,tag,parent=null){this.id=id;this.tagName=tag;this.parentElement=parent;this.children=[];this.hidden=false;this.open=true;this.attrs={};this.disabled=false;if(parent)parent.children.push(this);}
 getAttribute(k){return this.attrs[k]||null;}
 closest(selector){assert.equal(selector,'[role="tabpanel"]');for(let e=this;e;e=e.parentElement)if(e.attrs.role==='tabpanel')return e;return null;}
 scrollIntoView(){actions.push('scroll:'+this.id);}
 getBoundingClientRect(){for(let e=this;e;e=e.parentElement){if(e.hidden)return {width:0,height:0};const p=e.parentElement;if(p&&p.tagName==='DETAILS'&&!p.open&&p.children[0]!==e)return {width:0,height:0};}return {width:100,height:40};}
 click(){actions.push('click:'+this.id);if(this.onClick)this.onClick();}
}
const root=new Element('root','MAIN');const page=new Element('category-panel-users','DIV',root);page.attrs.role='tabpanel';page.hidden=true;
const outer=new Element('panel-accounts','DETAILS',page);outer.open=false;const first=new Element('outer-summary','SUMMARY',outer);
const inner=new Element('inner','DETAILS',outer);inner.open=false;const second=new Element('inner-summary','SUMMARY',inner);
const target=new Element('accounts-clone','BUTTON',inner);const nav=new Element('category-users','BUTTON',root);nav.attrs['aria-controls']=page.id;
nav.onClick=()=>{page.hidden=false;};first.onClick=()=>{outer.open=!outer.open;};second.onClick=()=>{inner.open=!inner.open;};
const all=[root,page,outer,first,inner,second,target,nav];global.document={getElementById:id=>all.find(e=>e.id===id)||null};global.getComputedStyle=e=>({display:e.hidden?'none':'block',visibility:'visible'});
assert.equal(reveal(target.id),true);assert.deepEqual(actions.filter(a=>a.startsWith('click:')),['click:category-users','click:outer-summary','click:inner-summary']);
assert(!actions.includes('click:'+target.id));actions.length=0;assert.equal(reveal(target.id),true);assert(!actions.some(a=>a.startsWith('click:')));
page.hidden=true;nav.attrs['aria-controls']='unrelated';actions.length=0;assert.equal(reveal(target.id),false);assert(!actions.some(a=>a.startsWith('click:')));
nav.attrs['aria-controls']=page.id;nav.hidden=true;assert.equal(reveal(target.id),false);assert(!actions.some(a=>a.startsWith('click:')));
nav.hidden=false;nav.disabled=true;assert.equal(reveal(target.id),false);assert(!actions.some(a=>a.startsWith('click:')));
nav.disabled=false;outer.open=false;first.onClick=()=>{};actions.length=0;assert.equal(reveal(target.id),false);assert(!actions.includes('click:'+target.id));
assert.equal(reveal('missing'),false);
"""
    result = subprocess.run([shutil.which("node"), "-e", program], capture_output=True, text=True, timeout=8)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for actual DOM layout observations")
@pytest.mark.parametrize("overflow", (False, True))
def test_dom_observation_measures_every_expanded_category_and_restores_user_ui_state(overflow):
    source = SOURCE.read_text()
    expression = re.search(r"static NSString \*const ProbeSettingsDOMScript =\s*(.*?)\nstatic void ProbeSettingsDOMAttempt", source, re.S)
    observed_script = "".join(json.loads(raw) for raw in re.findall(r'@?("(?:[^"\\]|\\.)*")', expression.group(1))).rstrip(";")
    program = "const overflow=" + json.dumps(overflow) + r""";
const assert=require('node:assert/strict'),keys=['console','server','users','content','graphics'],seen=[],opened=[];
let active='console';const nodes={};
function element(id,tag){return {id,tagName:tag,hidden:false,open:false,disabled:false,attrs:{},children:[],getAttribute(k){return this.attrs[k]||null;},scrollIntoView(){},getBoundingClientRect(){return {width:100,height:40,right:100,left:0};}};}
for(const key of keys){const nav=element('category-'+key,'BUTTON'),page=element('category-panel-'+key,'DIV'),details=element('panel-'+key,'DETAILS'),summary=element('summary-'+key,'SUMMARY');
 nav.attrs={role:'tab','aria-controls':page.id,'aria-selected':String(key==='console')};page.hidden=key!=='console';details.children=[summary];
 summary.click=()=>{details.open=!details.open;opened.push(key+':'+details.open);};page.querySelectorAll=selector=>{assert.equal(selector,'details.card-panel');return [details];};
 nav.click=()=>{active=key;seen.push(key);for(const k of keys){nodes['category-'+k].attrs['aria-selected']=String(k===key);nodes['category-panel-'+k].hidden=k!==key;}};
 Object.assign(nodes,{[nav.id]:nav,[page.id]:page,[details.id]:details});}
const width=()=>overflow&&active==='graphics'&&nodes['panel-graphics'].open?860:844;
const fields={disabled:false},presets={options:[{value:'2'},{value:'4096'}]};
const document={documentElement:{clientWidth:844,get scrollWidth(){return width();}},body:{get scrollWidth(){return width();},querySelectorAll(){return [];}},readyState:'complete',
 getElementById(id){return nodes[id]||(id.endsWith('-fields')?fields:presets);},querySelectorAll(){return [];}};
const window={idolyServerReply(){}};const getComputedStyle=e=>({display:e.hidden?'none':'block',visibility:'visible'});
""" + "const result=" + observed_script + r""";
assert.equal(result.no_horizontal_overflow,!overflow);assert.equal(result.content_width,overflow?860:844);
assert.deepEqual(seen.slice(0,5),keys);assert.equal(seen.at(-1),'console');assert.equal(active,'console');
assert.equal(opened.length,10);for(const key of keys)assert.equal(nodes['panel-'+key].open,false);
"""
    result = subprocess.run([shutil.which("node"), "-e", program], capture_output=True, text=True, timeout=8)
    assert result.returncode == 0, result.stdout + result.stderr
