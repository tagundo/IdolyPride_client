package game.qualiarts.idolypride.presentation;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** Strict media endpoint validation and native-default retention, no JNI. */
public final class MediaHarness {
    private static int checks;
    private static final String CONFIG="{\"schema\":1,\"revision\":9,\"hide_video_mv\":false,\"mv_sort\":\"recent\",\"outfit_sort\":\"title\"}";
    private static void check(boolean ok) { ++checks;if(!ok)throw new AssertionError("media boundary "+checks); }
    private static void reject(String raw) throws Exception {
        try { PresentationClient.parseMedia(raw); } catch(IOException expected) { ++checks;return; }
        throw new AssertionError("Invalid media message accepted");
    }
    private static final class Fake extends HttpURLConnection {
        String body=CONFIG;int status=200;
        Fake() throws Exception {super(new URL("http://127.0.0.1:8080"));}
        @Override public void connect(){connected=true;}
        @Override public void disconnect(){connected=false;}
        @Override public boolean usingProxy(){return false;}
        @Override public int getResponseCode(){return status;}
        @Override public long getContentLengthLong(){return body.getBytes(StandardCharsets.UTF_8).length;}
        @Override public InputStream getInputStream(){return new ByteArrayInputStream(body.getBytes(StandardCharsets.UTF_8));}
    }
    private static final class Receiver implements PresentationClient.MediaNative {
        int calls;boolean useOrder=false,accept=true;long revision;
        @Override public boolean configure(int schema,long next,boolean value){
            check(schema==1);++calls;if(!accept)return false;useOrder=value;revision=next;return true;
        }
    }
    public static void main(String[] args) throws Exception {
        PresentationClient.MediaConfig value=PresentationClient.parseMedia(CONFIG);
        check(value.revision==9 && !value.hideVideoMv && value.mvSort.equals("recent") && value.useMasterCostumeOrder());
        check(!PresentationClient.parseMedia(CONFIG.replace("\"title\"","\"original\"")).useMasterCostumeOrder());
        for(String mv:new String[]{"recent","old","title","id"})for(String outfit:new String[]{"original","recent","old","title","id"}){
            value=PresentationClient.parseMedia(CONFIG.replace("\"mv_sort\":\"recent\"","\"mv_sort\":\""+mv+"\"")
                .replace("\"outfit_sort\":\"title\"","\"outfit_sort\":\""+outfit+"\""));
            check(value.mvSort.equals(mv)&&value.outfitSort.equals(outfit));
        }
        for(int at=0;at<CONFIG.length();++at)reject(CONFIG.substring(0,at));
        for(String raw:new String[]{CONFIG.replace("\"schema\":1","\"schema\":1.0"),CONFIG.replace("\"schema\":1","\"schema\":true"),
            CONFIG.replace("\"schema\":1","\"schema\":2"),CONFIG.replace("\"revision\":9","\"revision\":-1"),
            CONFIG.replace("\"revision\":9","\"revision\":9.0"),CONFIG.replace("\"revision\":9","\"revision\":9e0"),
            CONFIG.replace("\"revision\":9","\"revision\":9223372036854775808"),CONFIG.replace("false","\"false\""),
            CONFIG.replace("false","0"),CONFIG.replace("false","null"),CONFIG.replace("\"recent\"","\"original\""),
            CONFIG.replace("\"title\"","\"unknown\""),CONFIG.replace("\"schema\":1","\"schema\":1,\"schema\":1"),
            CONFIG.replace("\"schema\"","\"account\""),CONFIG+"{}","[]","null",""})reject(raw);
        final Fake fake=new Fake();
        PresentationClient client=new PresentationClient(new PresentationClient.Connections(){
            @Override public HttpURLConnection open(URL url){check(url.toString().equals("http://127.0.0.1:8080/client/media"));return fake;}
        });
        Receiver receiver=new Receiver();
        check(client.pollMedia(receiver)&&receiver.useOrder&&receiver.revision==9);
        int calls=receiver.calls;
        fake.body=CONFIG.replace("\"title\"","\"old\"");check(!client.pollMedia(receiver)&&receiver.calls==calls);
        fake.body=CONFIG.replace("\"revision\":9","\"revision\":8");check(!client.pollMedia(receiver)&&receiver.calls==calls);
        fake.status=404;
        try{client.pollMedia(receiver);throw new AssertionError("404 accepted");}catch(IOException expected){++checks;}
        check(receiver.useOrder&&receiver.calls==calls);
        fake.status=200;fake.body="{}";
        try{client.pollMedia(receiver);throw new AssertionError("Malformed accepted");}catch(IOException expected){++checks;}
        check(receiver.useOrder&&receiver.calls==calls);
        fake.body=CONFIG.replace("\"revision\":9","\"revision\":10").replace("\"title\"","\"original\"");
        check(client.pollMedia(receiver)&&!receiver.useOrder&&receiver.revision==10);
        receiver.accept=false;fake.body=CONFIG.replace("\"revision\":9","\"revision\":11");
        check(!client.pollMedia(receiver)&&!receiver.useOrder);
        System.out.println("PASS "+checks);
    }
}
