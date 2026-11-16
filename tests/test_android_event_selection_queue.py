"""Run the real Android intent queue independently of Activity rendering on CI."""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / "android-server/app/src/main/java/game/qualiarts/idolypride/localserver"


def test_real_event_queue_keeps_rapid_edits_modes_and_cas_rebases(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    assert javac and java, "The Android queue contract requires the CI JDK"
    source = tmp_path / "game/qualiarts/idolypride/localserver"
    source.mkdir(parents=True)
    for name in ("EventWindow.java", "EventSelectionDraft.java"):
        (source / name).write_text((JAVA / name).read_text())
    harness = source / "EventSelectionHarness.java"
    harness.write_text(r"""
package game.qualiarts.idolypride.localserver;
import java.util.Map;
import java.util.TreeMap;
public final class EventSelectionHarness {
    static EventSelectionDraft.Window w(long a, long b) { return new EventSelectionDraft.Window(a,b); }
    static TreeMap<String, EventSelectionDraft.Window> rows(Object... pairs) {
        TreeMap<String, EventSelectionDraft.Window> map = new TreeMap<>();
        for(int i=0;i<pairs.length;i+=2)map.put((String)pairs[i], (EventSelectionDraft.Window)pairs[i+1]);
        return map;
    }
    static void check(boolean condition, String why) { if(!condition)throw new AssertionError(why); }
    interface Change { void run(); }
    static void rejected(Change change) {
        try { change.run(); throw new AssertionError("invalid change accepted"); }
        catch(IllegalArgumentException expected) { }
    }
    public static void main(String[] args) {
        EventSelectionDraft normal = new EventSelectionDraft(false);
        check(normal.prepare()==null&&!normal.loaded(), "unobserved save must not be sent");
        normal.observe(0, rows()); normal.edit("a",w(10,20));
        EventSelectionDraft.Save first = normal.prepare();
        normal.edit("b",w(30,40));
        normal.acknowledge(1, first.rows, first);
        check(normal.dirty()&&normal.rows().size()==2&&normal.pending().size()==1, "first ack lost a rapid second event");
        EventSelectionDraft.Save second=normal.prepare();
        check(second.revision==1, "second save used stale revision");
        normal.edit("a",null); normal.acknowledge(2,second.rows,second);
        check(normal.dirty()&&!normal.rows().containsKey("a")&&normal.rows().containsKey("b"), "later disable was lost by old ack");
        EventSelectionDraft.Save third=normal.prepare(); normal.acknowledge(3,third.rows,third);
        check(!normal.dirty()&&normal.rows().size()==1, "queue did not drain");
        normal.edit("a",w(10,20)); EventSelectionDraft.Save old=normal.prepare();
        normal.edit("a",null); normal.edit("a",w(50,60));
        normal.acknowledge(4,old.rows,old);
        check(normal.dirty()&&normal.rows().get("a").equals(w(50,60)), "same-event toggle generation lost");
        // An unrelated external writer changes the latest base after our CAS failed.
        normal.observe(8,rows("c",w(70,80)));
        check(!normal.rows().containsKey("b")&&normal.rows().containsKey("c")&&normal.rows().get("a").equals(w(50,60)), "rebase resurrected stale base or lost user intent");
        check(normal.prepare().revision==8, "rebase kept stale CAS token");
        EventSelectionDraft media=new EventSelectionDraft(true);
        media.observe(0,rows("a",w(0,0),"b",w(0,0)));media.edit("a",null);
        EventSelectionDraft.Save gallery=media.prepare();
        EventSelectionDraft.Save pendingNormal=normal.prepare();
        normal.acknowledge(9,pendingNormal.rows,pendingNormal);
        check(media.dirty()&&!media.rows().containsKey("a")&&media.rows().containsKey("b"), "old mode ack changed gallery draft");
        media.acknowledge(1,gallery.rows,gallery);
        check(!media.dirty()&&normal.rows().get("a").equals(w(50,60)), "gallery ack changed normal window");
        rejected(()->normal.edit("x",w(0,0)));rejected(()->media.edit("x",w(1,2)));
        Map<String,EventSelectionDraft.Window> before=normal.rows();
        rejected(()->normal.observe(8,rows()));
        check(normal.rows().equals(before), "stale observation mutated saved selections");
        normal.edit("x",w(100,200));EventSelectionDraft.Save sent=normal.prepare();
        rejected(()->normal.acknowledge(10,rows(),sent));
        check(normal.dirty()&&normal.rows().containsKey("x"), "wrong successful payload silently discarded intent");
        TreeMap<String,EventSelectionDraft.Window> malformed=rows("ok",w(1,2),"bad",w(2,1));
        rejected(()->normal.observe(10,malformed));
        check(normal.rows().containsKey("x"), "invalid observation partially updated state");
        try { sent.rows.clear(); throw new AssertionError("prepared save was mutable"); }
        catch(UnsupportedOperationException expected) { }
        System.out.println("event-selection-queue PASS");
    }
}
""")
    compile_result = subprocess.run([javac, "-d", str(tmp_path), *map(str, source.glob("*.java"))],
        capture_output=True, text=True, timeout=40)
    assert compile_result.returncode == 0, compile_result.stderr
    result = subprocess.run([java, "-cp", str(tmp_path), "game.qualiarts.idolypride.localserver.EventSelectionHarness"],
        capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "event-selection-queue PASS"
