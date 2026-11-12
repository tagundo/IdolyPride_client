package game.qualiarts.idolypride.presentation;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** Host-only lifecycle trace schema/transport boundaries; no Android or JNI. */
public final class WardrobeHarness {
    private static int checks;
    private static final String IDLE="{\"schema\":1,\"phase\":\"idle\",\"show_failures\":0,\"released_waits\":0,\"sequence\":0,\"sample_age_ms\":null}";
    private static final String EVENT="{\"schema\":1,\"phase\":\"show_begin\",\"show_failures\":0,\"released_waits\":0,\"sequence\":1,\"sample_age_ms\":0}";
    private static final String CONFIG="{\"schema\":1,\"revision\":0,\"custom_graphics\":false,\"quality\":0,\"target_fps\":0,\"render_scale\":1,\"max_buffer_pixel\":4096,\"anti_aliasing\":-1,\"shadow_resolution\":0,\"expand_photography\":false}";
    private static final String MEDIA="{\"schema\":1,\"revision\":0,\"hide_video_mv\":false,\"mv_sort\":\"recent\",\"outfit_sort\":\"original\"}";
    private static final String PLAYBACK="{\"schema\":1,\"revision\":0,\"wait_for_orientation\":true}";
    private static final String PLAYBACK_STATUS="{\"schema\":1,\"bridge_version\":1,\"revision\":0,\"wait_for_orientation\":true,\"supported\":true,\"applied\":true}";
    private static final String RENDER="{\"schema\":1,\"state\":\"waiting\",\"actual_mode\":null,\"graphics_api\":null,\"callback_tid\":null,\"observations\":0,\"sample_age_ms\":null,\"cpu_frame_ms\":null,\"gpu_frame_ms\":null,\"timing_age_ms\":null}";
    private static void check(boolean ok) { ++checks;if(!ok)throw new AssertionError("wardrobe boundary "+checks); }
    private static String field(String source,String key,String value) {
        int start=source.indexOf("\""+key+"\":")+key.length()+3,end=source.indexOf(',',start);
        if(end<0)end=source.lastIndexOf('}');return source.substring(0,start)+value+source.substring(end);
    }
    private static void accept(String raw) throws Exception { PresentationClient.validateWardrobe(raw);++checks; }
    private static void reject(String raw) throws Exception {
        try{PresentationClient.validateWardrobe(raw);}catch(IOException expected){++checks;return;}
        throw new AssertionError("Invalid wardrobe trace accepted");
    }
    private static final class Fake extends HttpURLConnection {
        byte[] body="{}".getBytes(StandardCharsets.UTF_8);int code=200;long declared=-1;String encoding,contentType;
        boolean closed,disconnected,slow;final ByteArrayOutputStream posted=new ByteArrayOutputStream();
        Fake()throws Exception{super(new URL("http://127.0.0.1:8080"));}
        @Override public void connect(){connected=true;}
        @Override public void disconnect(){disconnected=true;}
        @Override public boolean usingProxy(){return false;}
        @Override public int getResponseCode(){
            if(slow){long end=System.nanoTime()+1500000000L;while(System.nanoTime()<end)try{Thread.sleep(5);}catch(InterruptedException ignored){}}
            return code;
        }
        @Override public long getContentLengthLong(){return declared;}
        @Override public String getContentEncoding(){return encoding;}
        @Override public void setRequestProperty(String key,String value){super.setRequestProperty(key,value);if(key.equals("Content-Type"))contentType=value;}
        @Override public java.io.OutputStream getOutputStream(){return posted;}
        @Override public InputStream getInputStream(){return new ByteArrayInputStream(body){
            @Override public void close()throws IOException{closed=true;super.close();}
        };}
    }
    private static final class Router implements PresentationClient.Connections {
        Fake wardrobe;int calls;
        Router(Fake value){wardrobe=value;}
        @Override public HttpURLConnection open(URL url)throws IOException {
            ++calls;check(url.getProtocol().equals("http")&&url.getHost().equals("127.0.0.1")&&url.getPort()==8080
                &&url.getUserInfo()==null&&url.getQuery()==null&&url.getRef()==null);
            if(url.getPath().equals("/client/wardrobe"))return wardrobe;
            try{
                Fake value=new Fake();String raw="{}";
                if(url.getPath().equals("/client/presentation"))raw=CONFIG;
                else if(url.getPath().equals("/client/playback"))raw=PLAYBACK;
                else if(url.getPath().equals("/client/media"))raw=MEDIA;
                else check(url.getPath().equals("/client/presentation/status")||url.getPath().equals("/client/playback/status")||url.getPath().equals("/client/render-probe"));
                value.body=raw.getBytes(StandardCharsets.UTF_8);return value;
            }catch(Exception failure){throw new IOException(failure);}
        }
    }
    public static void main(String[] args)throws Exception {
        accept(IDLE);accept(EVENT);
        for(String phase:new String[]{"show_begin","show_failed","hide_wait_released","owner_closed"})accept(field(EVENT,"phase","\""+phase+"\""));
        for(String key:new String[]{"show_failures","released_waits","sequence","sample_age_ms"}) {
            accept(field(EVENT,key,"9223372036854775807"));
            for(String wrong:new String[]{"true","1.0","1e0","\"1\"","-1","9223372036854775808"})reject(field(EVENT,key,wrong));
        }
        for(String wrong:new String[]{"true","1.0","1e0","null","\"1\"","2"})reject(field(EVENT,"schema",wrong));
        for(String wrong:new String[]{"null","true","0","[]","{}","\"waiting\""})reject(field(EVENT,"phase",wrong));
        reject(field(EVENT,"sequence","0"));reject(field(EVENT,"sample_age_ms","null"));
        for(String key:new String[]{"show_failures","released_waits","sequence"})reject(field(IDLE,key,"1"));
        reject(field(IDLE,"sample_age_ms","0"));
        for(String wrong:new String[]{"{}","[]","null",EVENT+"{}",EVENT+"x",EVENT.replace("\"schema\":1","\"schema\":1,\"schema\":1"),
            EVENT.replace("\"schema\":1","\"schema\":1,\"\\u0073chema\":1"),EVENT.replace("\"schema\"","\"account\""),EVENT.replace("\"show_failures\":0,","")})reject(wrong);
        for(int i=0;i<EVENT.length();++i)reject(EVENT.substring(0,i));
        StringBuilder oversized=new StringBuilder(EVENT);while(oversized.length()<=PresentationClient.MAX_WARDROBE_BYTES)oversized.append(' ');reject(oversized.toString());
        StringBuilder exact=new StringBuilder(EVENT);while(exact.length()<PresentationClient.MAX_WARDROBE_BYTES)exact.append(' ');accept(exact.toString());
        Fake good=new Fake();Router router=new Router(good);PresentationClient client=new PresentationClient(router);client.postWardrobe(EVENT);
        check(good.getRequestMethod().equals("POST")&&!good.getInstanceFollowRedirects()&&!good.getUseCaches());
        check(good.getConnectTimeout()==1000&&good.getReadTimeout()>0&&good.getReadTimeout()<=1000);
        check(good.closed&&good.disconnected&&new String(good.posted.toByteArray(),StandardCharsets.UTF_8).equals(EVENT));
        check("application/json; charset=utf-8".equals(good.contentType));
        int calls=router.calls;try{client.postWardrobe(oversized.toString());throw new AssertionError();}catch(IOException expected){check(router.calls==calls);}
        Fake missing=new Fake();missing.code=404;router.wardrobe=missing;
        try{client.postWardrobe(EVENT);throw new AssertionError();}catch(IOException expected){check(missing.disconnected);}
        check(client.fetch().revision==0&&client.fetchPlayback().waitForOrientation&&client.fetchMedia().outfitSort.equals("original"));
        client.postStatus(PresentationClient.startupFailureStatus());client.postPlaybackStatus(PLAYBACK_STATUS);client.postRenderProbe(RENDER);++checks;
        for(int scenario=0;scenario<5;++scenario){
            Fake bad=new Fake();router.wardrobe=bad;
            if(scenario==0)bad.code=302;
            if(scenario==1)bad.body=new byte[PresentationClient.MAX_BYTES+1];
            if(scenario==2)bad.declared=PresentationClient.MAX_BYTES+1;
            if(scenario==3)bad.encoding="gzip";
            if(scenario==4)bad.body=new byte[]{(byte)0xc3,(byte)0x28};
            try{client.postWardrobe(EVENT);throw new AssertionError();}catch(IOException expected){check(bad.disconnected);}
        }
        Fake slow=new Fake();slow.slow=true;router.wardrobe=slow;long began=System.nanoTime();
        try{client.postWardrobe(EVENT);throw new AssertionError();}catch(IOException expected){check((System.nanoTime()-began)/1000000<1400);}
        System.out.println("PASS "+checks);
    }
}
