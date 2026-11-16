"""Authenticated Application overlays cannot replay stale Love/account captures."""
import copy
from types import SimpleNamespace

import pytest

from idoly_local import codec
from idoly_local.application import Application
from idoly_local.catalog import FixtureStore
from idoly_local.love import ROUTES
from idoly_local.rpc import RpcCode,RpcFailure
from test_love import (game,schema,settings,invoke,register,progress,user,database,EV,E1,E2,NOW,UNKNOWN)


class Context:
    def __init__(self,token=None):self.token=token;self.aborts=[]
    def invocation_metadata(self):return (("x-auth-token",self.token),) if self.token else ()
    def abort(self,code,details):
        self.aborts.append((code,details))
        raise RpcFailure(code,details)


def app_for(game,tmp_path,*,enabled=True):
    store=FixtureStore(tmp_path/"fixtures",game.schema)
    app=Application(game.schema,game.state,store,profile="player",master_dir=game.master,
        event_settings=settings() if enabled else {"schema":1,"revision":0,"love_events":[]})
    app.love._prepared=game.plan;app.love.clock=lambda:game.clock[0]
    return app,store


def request(game,app,path,*,token=True,**fields):
    raw=game.schema.request_type(path)(**fields).SerializeToString()
    value=app.handle(path,codec.encode(raw),Context(game.token if token else None))
    # Application returns plaintext to its transport's codec serializer.
    return game.schema.response_type(path).FromString(value)


@pytest.mark.parametrize("path",sorted(ROUTES))
def test_every_original_love_route_requires_authentication_before_dispatch(game,tmp_path,path):
    app,store=app_for(game,tmp_path)
    hits=[]
    app.love.handle=lambda p,raw:hits.append(p)
    with pytest.raises(RpcFailure) as rejected:request(game,app,path,token=False)
    assert rejected.value.code==RpcCode.UNAUTHENTICATED and not hits


@pytest.mark.parametrize("path",sorted(ROUTES))
def test_every_original_love_route_dispatches_before_stale_capture_lookup(game,tmp_path,path):
    app,store=app_for(game,tmp_path)
    stale=game.schema.response_type(path)().SerializeToString()
    store._responses[(path,None)]=stale
    seen=[]
    def handle(route,raw):
        seen.append((route,raw))
        result=game.schema.response_type(route)()
        result.commonResponse.updatedData.SetInParent()
        return result.SerializeToString()
    app.love.handle=handle
    def forbidden(*_):raise AssertionError("A Love capture shadowed the authoritative local handler")
    store.get=forbidden
    response=request(game,app,path)
    assert seen==[(path,b"")] and response.HasField("commonResponse")


def stale_home(game):
    home=game.schema.response_type("/api.Home/Enter")()
    home.currentMainAreaId="area-main-002"
    home.loveInfo.isViewable=True;home.loveInfo.isUnlocked=True
    home.eventInfo.loveEventInfos.add(id="stale-event",name="Must not survive")
    home.bannerInfo.SetInParent()
    home.MergeFromString(UNKNOWN)
    return home.SerializeToString()


@pytest.mark.parametrize("captured",[True,False])
@pytest.mark.parametrize("enabled",[True,False])
def test_both_captured_and_constructed_home_replace_only_current_love_fields(game,tmp_path,captured,enabled):
    app,store=app_for(game,tmp_path,enabled=enabled)
    old=stale_home(game)
    if captured:store._responses[("/api.Home/Enter",None)]=old
    else:
        app.gameplay.handle=lambda path,raw:old if path=="/api.Home/Enter" else None
    before=database(game.state)
    result=request(game,app,"/api.Home/Enter")
    assert result.currentMainAreaId=="area-main-002" and result.HasField("bannerInfo")
    assert UNKNOWN in result.SerializeToString()
    assert result.loveInfo.isViewable is enabled
    assert [row.id for row in result.eventInfo.loveEventInfos]==([EV] if enabled else [])
    assert database(game.state)==before


def test_positive_starter_stale_userget_stops_shadowing_after_first_love_transaction(game,tmp_path):
    app,store=app_for(game,tmp_path)
    stale=game.schema.response_type("/api.User/Get").FromString(game.original)
    stale.user.name="Stale fixture"
    store._responses[("/api.User/Get",None)]=stale.SerializeToString()
    assert game.state.starter_version("player")==7 and not game.state.has_love_progress("player")
    assert request(game,app,"/api.User/Get").user.name=="Stale fixture"
    result=request(game,app,"/api.Love/Register",loveId=EV,name="Manager")
    assert result.commonResponse.updatedData.loves[0].loveId==EV
    assert game.state.has_love_progress("player") and game.state.starter_version("player")==7
    current=request(game,app,"/api.User/Get")
    assert current.user.name=="QA" and current.loves[0].loveId==EV
    assert current.SerializeToString()==game.state.snapshot("player")[0]
    assert UNKNOWN in current.SerializeToString() and game.state.authenticated(game.token,"player")
    assert store.get("/api.User/Get",b"")==stale.SerializeToString()


def test_real_application_love_flow_changes_userget_but_unrelated_stale_routes_stay_untouched(game,tmp_path):
    app,store=app_for(game,tmp_path)
    unrelated="/api.Notice/List"
    old=game.schema.response_type(unrelated)();old.commonResponse.SetInParent()
    store._responses[(unrelated,None)]=old.SerializeToString()
    request(game,app,"/api.Love/Register",loveId=EV,name="Manager")
    request(game,app,"/api.Love/Start",storyEpisodeId=E1,hintLevel=0)
    response=request(game,app,"/api.Love/Finish",storyEpisodeId=E1,hintLevel=0,
        selectStoryChoiceInfos=[{"groupIndex":1,"index":2,"isValid":True},
                               {"groupIndex":2,"index":1,"isValid":True}])
    assert response.commonResponse.updatedData.loves[0].isReadingStory is False
    top=request(game,app,"/api.Love/Top",loveId=EV)
    assert list(top.storyEpisodeIds)==[E1,E2]
    assert request(game,app,"/api.User/Get").loves[0].hiddenFavorability==5
    assert request(game,app,unrelated).SerializeToString()==old.SerializeToString()


def test_application_default_disabled_never_loads_love_catalog_on_home(game,tmp_path,monkeypatch):
    app,store=app_for(game,tmp_path,enabled=False)
    app.love._prepared=None
    def forbidden():raise AssertionError("Disabled Love tried to load a catalog")
    monkeypatch.setattr(app.love,"_load",forbidden)
    store._responses[("/api.Home/Enter",None)]=stale_home(game)
    result=request(game,app,"/api.Home/Enter")
    assert not result.loveInfo.isViewable and not result.eventInfo.loveEventInfos


@pytest.mark.parametrize("failure",["catalog","value","captured_bytes"])
def test_captured_home_invalid_love_uses_transport_abort_and_never_leaks_exception(game,tmp_path,monkeypatch,failure):
    app,store=app_for(game,tmp_path)
    store._responses[("/api.Home/Enter",None)]=b"\x0a\x80" if failure=="captured_bytes" else stale_home(game)
    def stop(*_):
        if failure=="catalog":raise RpcFailure(RpcCode.FAILED_PRECONDITION,"Local Moshi Koi: catalog_unavailable")
        raise ValueError("SYNTHETIC_PRIVATE_EXCEPTION_PAYLOAD")
    if failure!="captured_bytes":monkeypatch.setattr(app.love,"home_info",stop)
    context=Context(game.token)
    with pytest.raises(RpcFailure) as rejected:
        app.handle("/api.Home/Enter",codec.encode(b""),context)
    assert rejected.value.code==RpcCode.FAILED_PRECONDITION
    assert len(context.aborts)==1 and context.aborts[0][0]==RpcCode.FAILED_PRECONDITION
    assert "SYNTHETIC_PRIVATE_EXCEPTION_PAYLOAD" not in context.aborts[0][1]
