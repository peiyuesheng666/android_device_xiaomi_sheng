// SPDX-License-Identifier: Apache-2.0
package org.lineageos.sheng.pen;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.pm.LauncherActivityInfo;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.os.UserHandle;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.DragEvent;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.accessibility.AccessibilityNodeInfo;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import org.lineageos.sheng.pen.controls.PenControls;
import org.lineageos.sheng.pen.controls.PenControlsSettings;
import org.lineageos.sheng.pen.controls.PenMenuApps;
import org.lineageos.sheng.pen.controls.PenMenuEntry;

/** Explicit edit mode with a selected row and a bottom add/remove toolbar. */
final class PenMenuEditor {
    private final Activity activity;
    private final boolean zh;
    private final int user=UserHandle.myUserId(),ink,muted,accent;
    private final Runnable changed;
    private final List<PenMenuEntry> items;
    private LinearLayout rows;
    private ScrollView scroll;
    private TextView help,count,edit,add,remove,save;
    private AlertDialog dialog;
    private boolean editing;
    private PenMenuEntry dragged,selected;
    private float dragY;
    private int scrollDirection;
    private final Runnable autoScroll=new Runnable(){
        @Override public void run(){
            if(dragged==null || scrollDirection==0)return;
            int before=scroll.getScrollY();scroll.scrollBy(0,scrollDirection*dp(8));
            dragY+=scroll.getScrollY()-before;moveAt(dragY);
            scroll.postDelayed(this,24);
        }
    };
    PenMenuEditor(Activity activity,boolean zh,Runnable changed){
        this.activity=activity;this.zh=zh;this.changed=changed;
        boolean dark=(activity.getResources().getConfiguration().uiMode & 0x30)==0x20;
        ink=activity.getColor(dark?android.R.color.system_neutral1_50:android.R.color.system_neutral1_900);
        muted=activity.getColor(dark?android.R.color.system_neutral2_200:android.R.color.system_neutral2_600);
        accent=activity.getColor(dark?android.R.color.system_accent1_200:android.R.color.system_accent1_600);
        items=new ArrayList<>(Arrays.asList(PenMenuEntry.read(PenControlsSettings.read(activity,PenControls.MENU,user))));
    }
    void show(){
        LinearLayout body=column();body.setPadding(dp(20),dp(4),dp(20),dp(8));
        help=text("",13,muted);body.addView(help);
        count=text("",13,muted);count.setPadding(0,dp(10),0,dp(6));body.addView(count);
        scroll=new ScrollView(activity);rows=column();scroll.addView(rows);
        rows.setOnDragListener((view,event)->drag(event));
        body.addView(scroll,new LinearLayout.LayoutParams(-1,Math.min(dp(440),(int)(activity.getResources().getDisplayMetrics().heightPixels*.45f))));
        LinearLayout footer=new LinearLayout(activity);footer.setGravity(Gravity.CENTER_VERTICAL);
        // Keep the editing tools on the left and the draft actions on the right.
        edit=button(zh?"编辑":"Edit",()->{editing=true;refresh();});
        add=button("＋",this::chooseType);add.setTextSize(18);
        add.setContentDescription(zh?"添加应用或系统操作":"Add app or system action");
        remove=button("−",this::removeSelected);remove.setTextSize(20);
        footer.addView(edit,new LinearLayout.LayoutParams(dp(64),dp(48)));
        footer.addView(add,new LinearLayout.LayoutParams(dp(48),dp(48)));
        footer.addView(remove,new LinearLayout.LayoutParams(dp(48),dp(48)));
        footer.addView(new View(activity),new LinearLayout.LayoutParams(0,1,1));
        footer.addView(button(zh?"取消":"Cancel",()->dialog.dismiss()),new LinearLayout.LayoutParams(dp(72),dp(48)));
        save=button(zh?"保存":"Save",this::save);
        footer.addView(save,new LinearLayout.LayoutParams(dp(72),dp(48)));
        LinearLayout.LayoutParams footerSize=new LinearLayout.LayoutParams(-1,-2);footerSize.topMargin=dp(12);body.addView(footer,footerSize);
        dialog=new AlertDialog.Builder(activity).setTitle(zh?"自定义快捷菜单":"Customize pen menu").setView(body).create();
        dialog.setOnShowListener(ignored->{
            dialog.getWindow().setLayout(Math.min(dp(560),activity.getResources().getDisplayMetrics().widthPixels-dp(40)),-2);
            refresh();
        });
        dialog.setOnDismissListener(ignored->{dragged=null;scroll.removeCallbacks(autoScroll);});
        dialog.show();
    }
    private void refresh(){
        rows.removeAllViews();
        help.setText(editing?(zh?"拖动手柄排序；选中一项后点 − 移除，点 ＋ 添加。":"Drag a handle to reorder. Select an item and tap − to remove; tap + to add.")
                :(zh?"点下方“编辑”添加应用、排序或移除。":"Tap Edit below to add, reorder or remove items."));
        int remaining=PenMenuEntry.MAX_ITEMS-items.size();
        count.setText(zh?("已添加 "+items.size()+" / 6 项"+(editing&&remaining==0?" · 移除后可继续添加":items.isEmpty()?" · 至少保留一项":""))
                :(items.size()+" / 6 items"+(editing&&remaining==0?" · Remove an item to add more":items.isEmpty()?" · Keep at least one item":"")));
        edit.setVisibility(editing?View.GONE:View.VISIBLE);
        add.setVisibility(editing?View.VISIBLE:View.GONE);remove.setVisibility(editing?View.VISIBLE:View.GONE);
        if(!items.contains(selected))selected=null;
        for(PenMenuEntry entry:items){
            String title=PenMenuApps.title(activity,entry,user,zh);
            LinearLayout row=new LinearLayout(activity);row.setGravity(Gravity.CENTER_VERTICAL);row.setMinimumHeight(dp(68));
            row.setTag(entry);row.setPadding(0,0,dp(10),0);
            if(editing){
                row.setFocusable(true);row.setOnClickListener(view->{selected=entry;updateSelection();});
                TextView handle=text("≡",24,muted);handle.setGravity(Gravity.CENTER);handle.setFocusable(true);
                handle.setContentDescription((zh?"拖动排序 ":"Drag to reorder ")+title);
                handle.setOnTouchListener((view,event)->{
                    if(event.getActionMasked()!=MotionEvent.ACTION_DOWN)return true;
                    selected=entry;updateSelection();dragged=entry;row.setAlpha(.45f);
                    boolean started=view.startDragAndDrop(ClipData.newPlainText("pen-menu-item",""),
                            new View.DragShadowBuilder(row),entry,0);
                    if(!started){dragged=null;row.setAlpha(1);}
                    return true;
                });
                handle.setAccessibilityDelegate(new View.AccessibilityDelegate(){
                    @Override public void onInitializeAccessibilityNodeInfo(View host,AccessibilityNodeInfo info){
                        super.onInitializeAccessibilityNodeInfo(host,info);
                        int index=items.indexOf(entry);
                        if(index>0)info.addAction(new AccessibilityNodeInfo.AccessibilityAction(AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD,zh?"上移":"Move up"));
                        if(index+1<items.size())info.addAction(new AccessibilityNodeInfo.AccessibilityAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD,zh?"下移":"Move down"));
                    }
                    @Override public boolean performAccessibilityAction(View host,int action,android.os.Bundle args){
                        int index=items.indexOf(entry),next=index+(action==AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD?-1:1);
                        if((action==AccessibilityNodeInfo.ACTION_SCROLL_FORWARD || action==AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD)
                                && index>=0 && next>=0 && next<items.size()){
                            java.util.Collections.swap(items,index,next);refresh();return true;
                        }
                        return super.performAccessibilityAction(host,action,args);
                    }
                });
                row.addView(handle,new LinearLayout.LayoutParams(dp(48),dp(48)));
            }
            if(entry.component!=null){
                LauncherActivityInfo app=PenMenuApps.resolve(activity,entry,user);
                ImageView icon=new ImageView(activity);icon.setImageDrawable(app==null?activity.getPackageManager().getDefaultActivityIcon():app.getBadgedIcon(0));
                icon.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
                LinearLayout.LayoutParams size=new LinearLayout.LayoutParams(dp(28),dp(28));size.rightMargin=dp(10);row.addView(icon,size);
            }
            TextView name=text(title,14,ink);name.setMaxLines(2);row.addView(name,new LinearLayout.LayoutParams(0,-2,1));
            rows.addView(row);
        }
        if(items.isEmpty()){TextView empty=text(zh?"从下方添加应用或系统操作。":"Add an app or action below.",14,muted);empty.setPadding(0,dp(24),0,dp(24));rows.addView(empty);}
        enabled(add,remaining>0);enabled(save,editing&&!items.isEmpty());updateSelection();
    }
    private void updateSelection(){
        for(int i=0;i<rows.getChildCount();i++){
            View row=rows.getChildAt(i);boolean active=selected!=null&&selected.equals(row.getTag());
            row.setSelected(active);
            GradientDrawable shape=new GradientDrawable();shape.setCornerRadius(dp(12));
            shape.setColor(active?(accent&0xffffff)|0x18000000:0);
            if(active)shape.setStroke(dp(1),(accent&0xffffff)|0x70000000);
            row.setBackground(shape);
        }
        enabled(remove,selected!=null);
        remove.setContentDescription(selected==null?(zh?"移除所选项目":"Remove selected item")
                :(zh?"移除 ":"Remove ")+PenMenuApps.title(activity,selected,user,zh));
    }
    private void removeSelected(){
        if(selected==null)return;
        int index=items.indexOf(selected);if(index<0)return;
        items.remove(index);
        selected=items.isEmpty()?null:items.get(Math.min(index,items.size()-1));refresh();
    }
    private void save(){
        if(!editing||items.isEmpty())return;
        try{
            if(!PenControlsSettings.write(activity,PenControls.MENU,PenMenuEntry.write(items)))throw new IllegalStateException("Setting rejected");
            changed.run();dialog.dismiss();
        }catch(RuntimeException failure){message(zh?"暂时无法保存":"Could not save menu");}
    }
    private void chooseType(){
        if(!editing||items.size()>=PenMenuEntry.MAX_ITEMS)return;
        new AlertDialog.Builder(activity).setTitle(zh?"添加到快捷菜单":"Add to pen menu")
                .setItems(zh?new String[]{"应用","系统操作"}:new String[]{"App","System action"},
                        (owner,index)->{if(index==0)chooseApp();else chooseAction();})
                .setNegativeButton(android.R.string.cancel,null).show();
    }
    private boolean drag(DragEvent event){
        if(!editing || event.getLocalState()!=dragged || dragged==null)return false;
        switch(event.getAction()){
            case DragEvent.ACTION_DRAG_STARTED:return true;
            case DragEvent.ACTION_DRAG_LOCATION:
                dragY=event.getY();moveAt(dragY);
                float visible=dragY-scroll.getScrollY();
                int next=visible<dp(40)?-1:visible>scroll.getHeight()-dp(40)?1:0;
                if(next!=scrollDirection){scrollDirection=next;scroll.removeCallbacks(autoScroll);if(next!=0)scroll.post(autoScroll);}
                return true;
            case DragEvent.ACTION_DRAG_EXITED:scrollDirection=0;scroll.removeCallbacks(autoScroll);return true;
            case DragEvent.ACTION_DROP:return true;
            case DragEvent.ACTION_DRAG_ENDED:
                dragged=null;scrollDirection=0;scroll.removeCallbacks(autoScroll);refresh();return true;
            default:return true;
        }
    }
    private void moveAt(float y){
        int from=items.indexOf(dragged);if(from<0)return;
        int to=0;
        for(int i=0;i<rows.getChildCount();i++){View child=rows.getChildAt(i);if(y>child.getTop()+child.getHeight()/2f)to=i+1;}
        if(to>from)to--;to=Math.max(0,Math.min(to,items.size()-1));if(to==from)return;
        PenMenuEntry item=items.remove(from);items.add(to,item);
        View row=rows.getChildAt(from);rows.removeViewAt(from);rows.addView(row,to);
    }
    private void chooseApp(){
        try{
            List<LauncherActivityInfo> apps=new ArrayList<>();
            for(LauncherActivityInfo info:PenMenuApps.list(activity,user))if(!items.contains(PenMenuEntry.application(info.getComponentName().flattenToString())))apps.add(info);
            if(apps.isEmpty()){message(zh?"没有其他可添加的应用":"No more apps to add");return;}
            LinearLayout body=column();body.setPadding(dp(20),0,dp(20),0);
            EditText search=new EditText(activity);search.setSingleLine(true);search.setHint(zh?"搜索应用":"Search apps");body.addView(search);
            List<LauncherActivityInfo> filtered=new ArrayList<>();
            ArrayAdapter<String> labels=new ArrayAdapter<>(activity,android.R.layout.simple_list_item_1,new ArrayList<>());
            ListView list=new ListView(activity);list.setAdapter(labels);body.addView(list,new LinearLayout.LayoutParams(-1,Math.min(dp(360),(int)(activity.getResources().getDisplayMetrics().heightPixels*.35f))));
            Runnable filter=()->{
                String query=search.getText().toString().trim().toLowerCase(Locale.ROOT);filtered.clear();labels.clear();
                for(LauncherActivityInfo app:apps)if(app.getLabel().toString().toLowerCase(Locale.ROOT).contains(query)){filtered.add(app);labels.add(app.getLabel().toString());}
                labels.notifyDataSetChanged();
            };
            search.addTextChangedListener(new TextWatcher(){
                public void beforeTextChanged(CharSequence s,int start,int count,int after){}
                public void onTextChanged(CharSequence s,int start,int before,int count){filter.run();}
                public void afterTextChanged(Editable s){}
            });
            AlertDialog picker=new AlertDialog.Builder(activity).setTitle(zh?"添加应用":"Add app").setView(body).setNegativeButton(android.R.string.cancel,null).create();
            list.setOnItemClickListener((parent,view,index,id)->{add(PenMenuEntry.application(filtered.get(index).getComponentName().flattenToString()));picker.dismiss();});
            filter.run();picker.show();picker.getWindow().setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_HIDDEN);
        }catch(RuntimeException failure){message(zh?"暂时无法读取应用":"Could not load apps");}
    }
    private void chooseAction(){
        List<PenMenuEntry> choices=new ArrayList<>();List<String> labels=new ArrayList<>();
        for(PenControls.Action action:PenControls.Action.values())if(action!=PenControls.Action.NONE && action!=PenControls.Action.MENU){
            PenMenuEntry entry=PenMenuEntry.operation(action);if(!items.contains(entry)){choices.add(entry);labels.add(action.title(zh));}
        }
        new AlertDialog.Builder(activity).setTitle(zh?"添加系统操作":"Add system action").setItems(labels.toArray(new String[0]),(owner,index)->add(choices.get(index))).setNegativeButton(android.R.string.cancel,null).show();
    }
    private void add(PenMenuEntry item){if(!items.contains(item) && items.size()<PenMenuEntry.MAX_ITEMS){items.add(item);selected=item;refresh();}}
    private LinearLayout column(){LinearLayout view=new LinearLayout(activity);view.setOrientation(LinearLayout.VERTICAL);return view;}
    private TextView text(String value,int size,int color){TextView view=new TextView(activity);view.setText(value);view.setTextSize(size);view.setTextColor(color);view.setIncludeFontPadding(false);return view;}
    private TextView button(String title,Runnable action){
        TextView view=text(title,13,accent);view.setGravity(Gravity.CENTER);view.setFocusable(true);
        StateListDrawable states=new StateListDrawable();
        for(int state:new int[]{android.R.attr.state_pressed,android.R.attr.state_focused,0}){
            GradientDrawable shape=new GradientDrawable();shape.setCornerRadius(dp(10));shape.setColor((accent&0xffffff)|(state==0?0:0x18000000));
            states.addState(state==0?new int[]{}:new int[]{state},shape);
        }
        states.setExitFadeDuration(140);view.setBackground(states);view.setOnClickListener(v->action.run());return view;
    }
    private void enabled(TextView view,boolean value){view.setEnabled(value);view.setAlpha(value?1f:.35f);}
    private void message(String text){Toast.makeText(activity,text,Toast.LENGTH_SHORT).show();}
    private int dp(float value){return Math.round(value*activity.getResources().getDisplayMetrics().density);}
}

