"""Compile the actual compact header helpers without an Android runtime.

The owned emulator gate checks real layout, usable body and editable controls;
this JVM seam protects row ownership, readable status and unchanged portrait.
"""
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
ACTIVITY = ROOT / "android-server/app/src/main/java/game/qualiarts/idolypride/localserver/MainActivity.java"


def method(source, marker):
    begin = source.index(marker)
    cursor = source.index("{", begin) + 1
    depth = 1
    while depth:
        depth += (source[cursor] == "{") - (source[cursor] == "}")
        cursor += 1
    return source[begin:cursor]


def test_compact_header_is_limited_to_short_landscape_and_preserves_graphics_and_picker():
    source = ACTIVITY.read_text()
    create = method(source, "    @Override public void onCreate(")
    assert ("compactHeader = compact && getResources().getConfiguration().screenWidthDp\n"
            "                > getResources().getConfiguration().screenHeightDp;") in create
    assert "screenHeightDp < 520" in create
    assert "compactHeaderAction(start, 12); compactHeaderAction(stop, 12);" in create
    assert "primaryButton(launch); compactHeaderAction(launch, 12);" in create
    assert "compactHeaderAction(control, 3);" in method(source, "    private void addCategoryButton(")
    assert "customGraphics" in method(source, "    private void addPresentationControls(")
    assert 'state.putInt("account_picker", pendingAccountPicker);' in source
    assert "pendingAccountPicker == 0 && !ServerService.isManagingAccounts()" in source


def test_actual_header_keeps_two_live_labels_and_accessible_actions_without_changing_portrait(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    assert javac and java, "The required compact header harness needs a JDK"
    production = ACTIVITY.read_text()
    actual = "\n".join(method(production, marker) for marker in (
        "    private void addNativeHeading(", "    private void compactHeaderAction("))
    source = r'''
import java.util.*;
public final class CompactHeaderHarness {
 boolean compactHeader;TextView status;
 static final int TEXT_PRIMARY=1,STATUS_BACKGROUND=2;
 static final class R { static final class string { static final int app_name=1,status_stopped=2; } }
 static final class BuildConfig { static final String VERSION_NAME="test-version"; }
 static final class Typeface { static final Object DEFAULT=new Object();static final int BOLD=1; }
 static final class TextUtils { static final class TruncateAt { static final Object END=new Object(); } }
 static final class android { static final class view { static final class Gravity {static final int CENTER_VERTICAL=16;} } }
 static class View {
  int minimumHeight,gravity;int[] padding={0,0,0,0};
  void setMinimumHeight(int value){minimumHeight=value;}
  void setPadding(int left,int top,int right,int bottom){padding=new int[]{left,top,right,bottom};}
  void setGravity(int value){gravity=value;}
 }
 static class TextView extends View {
  int font,minHeight,maxLines=Integer.MAX_VALUE;String value;Object ellipsize;
  void setText(String text){value=text;}void setTypeface(Object face,int style){}
  void setMinHeight(int height){minHeight=height;}void setMaxLines(int lines){maxLines=lines;}
  void setEllipsize(Object value){ellipsize=value;}void setBackground(Object background){}
 }
 static final class Button extends TextView { boolean enabled=true; }
 static final class GradientDrawable {void setColor(int value){}void setCornerRadius(int value){}}
 static final class LinearLayout extends View {
  static final int HORIZONTAL=0;int orientation=-1;
  final List<View> children=new ArrayList<>();final List<LayoutParams> placements=new ArrayList<>();
  LinearLayout(Object context){}void setOrientation(int value){orientation=value;}
  void addView(View child){children.add(child);placements.add(null);}
  void addView(View child,LayoutParams params){children.add(child);placements.add(params);}
  static final class LayoutParams {
   final int width,height;final float weight;int[] margins;
   LayoutParams(int width,int height){this(width,height,0);}
   LayoutParams(int width,int height,float weight){this.width=width;this.height=height;this.weight=weight;}
   void setMargins(int left,int top,int right,int bottom){margins=new int[]{left,top,right,bottom};}
  }
 }
 int dp(int value){return value;}String getString(int resource){return resource==1?"Long translated app title":"Stopped";}
 TextView text(int resource,int size,int color){TextView v=new TextView();v.value=getString(resource);v.font=size;return v;}
 static void check(boolean value,String code){if(!value)throw new AssertionError(code);}
 __ACTUAL__
 public static void main(String[] args){
  for(boolean shortPortrait:new boolean[]{false,true}){
   CompactHeaderHarness h=new CompactHeaderHarness();LinearLayout parent=new LinearLayout(h);
   h.addNativeHeading(parent,shortPortrait);
   check(parent.children.size()==2,"portrait header structure changed");
   check(((TextView)parent.children.get(0)).font==(shortPortrait?20:25),"portrait title size changed");
   check(parent.children.get(1)==h.status&&h.status.font==21,"portrait status ownership/size changed");
   check(Arrays.equals(h.status.padding,new int[]{14,8,14,8}),"portrait status spacing changed");
   Button action=new Button();action.minHeight=52;action.minimumHeight=52;action.setPadding(12,8,12,8);
   h.compactHeaderAction(action,3);
   check(action.minHeight==52&&action.minimumHeight==52&&Arrays.equals(action.padding,new int[]{12,8,12,8}),
      "portrait action changed");
  }
  CompactHeaderHarness h=new CompactHeaderHarness();h.compactHeader=true;LinearLayout parent=new LinearLayout(h);
  h.addNativeHeading(parent,true);
  check(parent.children.size()==1&&parent.children.get(0) instanceof LinearLayout,"landscape labels did not share a row");
  LinearLayout row=(LinearLayout)parent.children.get(0);
  check(row.orientation==LinearLayout.HORIZONTAL&&row.minimumHeight>=36,"landscape row structure");
  check(row.children.size()==2&&row.children.get(1)==h.status,"live status was replaced or reordered");
  TextView title=(TextView)row.children.get(0);
  check(title.font>=18&&h.status.font>=16,"unreadable compact font");
  check(row.placements.get(0).width==0&&row.placements.get(0).weight==1,"title did not yield width to status");
  check(h.status.maxLines==Integer.MAX_VALUE&&h.status.ellipsize==null,"status/error was truncated");
  h.status.setText("Long status error still belongs to the same live TextView");
  check(((TextView)row.children.get(1)).value.startsWith("Long status"),"status updates lost");
  for(int padding:new int[]{3,12}){
   Button action=new Button();action.enabled=false;
   h.compactHeaderAction(action,padding);
   check(action.minHeight>=44&&action.minimumHeight>=44,"compact action smaller than44dp");
   check(!action.enabled,"layout changed action availability");
   check(Arrays.equals(action.padding,new int[]{padding,4,padding,4}),"compact action spacing");
  }
  System.out.println("PASS compact header");
 }
}
'''.replace("__ACTUAL__", actual)
    path = tmp_path / "CompactHeaderHarness.java"
    path.write_text(source)
    subprocess.run([javac, str(path)], check=True, capture_output=True, text=True, timeout=30)
    result = subprocess.run([java, "-cp", str(tmp_path), "CompactHeaderHarness"],
                            check=True, capture_output=True, text=True, timeout=30)
    assert result.stdout.strip() == "PASS compact header"
