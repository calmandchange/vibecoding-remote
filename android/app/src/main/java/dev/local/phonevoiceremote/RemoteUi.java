package dev.local.phonevoiceremote;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.graphics.Canvas;
import android.content.res.ColorStateList;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.graphics.RadialGradient;
import android.graphics.Shader;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.HapticFeedbackConstants;
import android.view.MotionEvent;
import android.view.View;
import android.widget.FrameLayout;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

/** Warm, one-screen remote with Bluetooth state and tactile editing controls. */
final class RemoteUi {
    interface Listener {
        void onVoiceDown();
        void onVoiceUp();
        void onKey(int code);
        void onTakeoverChanged(boolean enabled);
        void onHotkeyChanged(String value);
    }

    private static final int INK = 0xFF1B1917;
    private static final int MUTED = 0xFF66635F;
    private static final int PAGE = 0xFFFDFCF7;
    private static final int SURFACE = 0xFFFFFEFA;
    private static final int EDGE = 0xFFE7E0D5;
    private static final int GREEN = 0xFF00A465;
    private static final int RED = 0xFFD85650;
    private static final long REPEAT_START_MS = 340;
    private static final long REPEAT_INTERVAL_MS = 105;

    private final Activity activity;
    private final Listener listener;
    private final Handler repeatHandler = new Handler(Looper.getMainLooper());
    private FrameLayout micButton;
    private FrameLayout micFace;
    private MicIcon micIcon;
    private DirectionPad directionPad;
    private TextView voiceTitle;
    private TextView voiceHint;
    private TextView connectionLabel;
    private View connectionDot;
    private Switch takeoverSwitch;
    private TextView hotkeyButton;
    private AlertDialog settingsDialog;
    private String hotkeyValue = "Ctrl+Win";
    private String connectionMessage = "正在检查连接";
    private boolean internalSwitchUpdate;
    private boolean takeoverRequested;
    private boolean takeoverActive;
    private boolean connected;
    private boolean selecting;
    private boolean recording;

    RemoteUi(Activity activity, Listener listener) {
        this.activity = activity;
        this.listener = listener;
        build();
        setConnection(false, "正在检查连接");
    }

    private int dp(float size) {
        return (int) (size * activity.getResources().getDisplayMetrics().density + 0.5f);
    }

    private GradientDrawable round(int fill, int radius, int border) {
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(fill);
        shape.setCornerRadius(dp(radius));
        if (border != 0) shape.setStroke(dp(1), border);
        return shape;
    }

    private TextView text(String value, float size, int color, boolean bold) {
        TextView label = new TextView(activity);
        label.setText(value);
        label.setTextSize(size);
        label.setTextColor(color);
        label.setIncludeFontPadding(false);
        if (bold) label.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return label;
    }

    private LinearLayout column() {
        LinearLayout result = new LinearLayout(activity);
        result.setOrientation(LinearLayout.VERTICAL);
        return result;
    }

    private void gap(LinearLayout parent, int height) {
        parent.addView(new View(activity), new LinearLayout.LayoutParams(1, dp(height)));
    }

    private GradientDrawable oval(int fill, int stroke, int strokeWidth) {
        GradientDrawable shape = new GradientDrawable();
        shape.setShape(GradientDrawable.OVAL);
        shape.setColor(fill);
        shape.setStroke(dp(strokeWidth), stroke);
        return shape;
    }

    // The main screen follows the two controls in the approved concept art.
    @SuppressLint("ClickableViewAccessibility")
    private void build() {
        ScrollView scroll = new ScrollView(activity);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(PAGE);
        scroll.setVerticalScrollBarEnabled(false);
        LinearLayout page = column();
        page.setGravity(Gravity.CENTER_HORIZONTAL);
        page.setClipChildren(false);
        page.setPadding(dp(20), dp(13), dp(20), dp(24));
        scroll.addView(page, new ScrollView.LayoutParams(-1, -1));
        activity.setContentView(scroll);

        int screenWidth = activity.getResources().getConfiguration().screenWidthDp;
        int screenHeight = activity.getResources().getConfiguration().screenHeightDp;
        boolean compactHeight = screenHeight < 720;
        int micSize = Math.min(compactHeight ? 190 : 234, screenWidth - 64);
        int dpadSize = Math.min(compactHeight ? 232 : 274, screenWidth - 76);

        FrameLayout titleRow = new FrameLayout(activity);
        titleRow.setClipChildren(false);
        page.addView(titleRow, new LinearLayout.LayoutParams(-1, dp(42)));
        TextView brand = text("VibeCoding", 29, INK, true);
        brand.setGravity(Gravity.CENTER);
        brand.setTranslationY(dp(2));
        titleRow.addView(brand, new FrameLayout.LayoutParams(-1, -1, Gravity.CENTER));
        FrameLayout settingsButton = new FrameLayout(activity);
        settingsButton.setBackground(oval(SURFACE, EDGE, 1));
        settingsButton.setElevation(dp(2));
        settingsButton.setTranslationY(dp(6));
        settingsButton.setClickable(true);
        settingsButton.setContentDescription("设置，管理麦克风接管和语音快捷键");
        GearIcon gear = new GearIcon(activity);
        settingsButton.addView(gear, new FrameLayout.LayoutParams(dp(25), dp(25), Gravity.CENTER));
        settingsButton.setOnClickListener(view -> {
            view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY);
            showSettingsDialog();
        });
        titleRow.addView(settingsButton, new FrameLayout.LayoutParams(dp(42), dp(42), Gravity.END | Gravity.CENTER_VERTICAL));

        LinearLayout statusRow = new LinearLayout(activity);
        statusRow.setGravity(Gravity.CENTER);
        statusRow.setOrientation(LinearLayout.HORIZONTAL);
        connectionDot = new View(activity);
        connectionDot.setBackground(oval(RED, RED, 0));
        statusRow.addView(connectionDot, new LinearLayout.LayoutParams(dp(14), dp(14)));
        View statusGap = new View(activity);
        statusRow.addView(statusGap, new LinearLayout.LayoutParams(dp(12), dp(1)));
        connectionLabel = text("连接已断开", 16, INK, false);
        statusRow.addView(connectionLabel);
        page.addView(statusRow, new LinearLayout.LayoutParams(-1, dp(34)));
        gap(page, compactHeight ? 12 : 18);

        micButton = new FrameLayout(activity);
        micButton.setBackground(oval(SURFACE, EDGE, 1));
        micButton.setElevation(dp(11));
        micButton.setClickable(true);
        micFace = new FrameLayout(activity);
        micFace.setBackground(micBackground(false));
        FrameLayout.LayoutParams faceParams = new FrameLayout.LayoutParams(-1, -1);
        int faceInset = dp(9);
        faceParams.setMargins(faceInset, faceInset, faceInset, faceInset);
        micButton.addView(micFace, faceParams);
        LinearLayout micContents = column();
        micContents.setGravity(Gravity.CENTER);
        micIcon = new MicIcon(activity, RED);
        micContents.addView(micIcon, new LinearLayout.LayoutParams(dp(80), dp(80)));
        gap(micContents, 12);
        voiceTitle = text("等待连接", 22, INK, true);
        voiceTitle.setGravity(Gravity.CENTER);
        micContents.addView(voiceTitle);
        micFace.addView(micContents, new FrameLayout.LayoutParams(-1, -1, Gravity.CENTER));
        micButton.setOnTouchListener((view, event) -> {
            if (!view.isEnabled()) return false;
            int action = event.getActionMasked();
            if (!takeoverActive) {
                if (action == MotionEvent.ACTION_UP) {
                    view.performClick();
                }
                return true;
            }
            if (action == MotionEvent.ACTION_DOWN) {
                listener.onVoiceDown();
                view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY);
                view.animate().scaleX(0.97f).scaleY(0.97f).setDuration(90).start();
                return true;
            }
            if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {
                listener.onVoiceUp();
                view.animate().scaleX(1f).scaleY(1f).setDuration(100).start();
                if (action == MotionEvent.ACTION_UP) view.performClick();
                return true;
            }
            return true;
        });
        micButton.setOnClickListener(view -> {
            if (connected && !takeoverActive) showSettingsDialog();
        });
        page.addView(micButton, new LinearLayout.LayoutParams(dp(micSize), dp(micSize)));
        gap(page, 0);
        voiceHint = text("请检查蓝牙连接", 14, MUTED, false);
        voiceHint.setGravity(Gravity.CENTER);
        voiceHint.setMaxLines(2);
        page.addView(voiceHint, new LinearLayout.LayoutParams(-1, dp(compactHeight ? 30 : 32)));
        gap(page, 0);

        directionPad = new DirectionPad(activity);
        LinearLayout.LayoutParams padParams = new LinearLayout.LayoutParams(
                dp(dpadSize + 44), dp(dpadSize + 44));
        padParams.topMargin = -dp(compactHeight ? 19 : 18);
        page.addView(directionPad, padParams);
    }

    private GradientDrawable micBackground(boolean active) {
        int stateColor = connected ? GREEN : RED;
        return oval(active ? 0xFFF4FCF6 : SURFACE, stateColor, active ? 3 : 2);
    }

    private void updateSelection() {
        directionPad.setContentDescription(selecting ? "选字模式。按住方向可连续选中文字；长按中心上半圆退出" :
                "方向遥控盘。中心上半圆轻点回车，长按切换选字；下半圆删除，按住连续删除");
        directionPad.invalidate();
    }

    private void showSettingsDialog() {
        if (settingsDialog != null && settingsDialog.isShowing()) return;
        LinearLayout panel = column();
        panel.setPadding(dp(24), dp(8), dp(24), dp(10));

        takeoverSwitch = new Switch(activity);
        takeoverSwitch.setText("接管电脑麦克风");
        takeoverSwitch.setTextSize(16);
        takeoverSwitch.setTextColor(INK);
        takeoverSwitch.setChecked(takeoverRequested);
        takeoverSwitch.setThumbTintList(new ColorStateList(
                new int[][]{new int[]{android.R.attr.state_checked}, new int[]{}},
                new int[]{GREEN, 0xFFB7A99F}));
        takeoverSwitch.setTrackTintList(new ColorStateList(
                new int[][]{new int[]{android.R.attr.state_checked}, new int[]{}},
                new int[]{0xFFB8DFC8, 0xFFE4D9D0}));
        takeoverSwitch.setOnCheckedChangeListener((button, checked) -> {
            if (!internalSwitchUpdate) listener.onTakeoverChanged(checked);
        });
        panel.addView(takeoverSwitch, new LinearLayout.LayoutParams(-1, dp(56)));

        TextView takeoverHelp = text("开启后，按住首页麦克风按钮即可向电脑输入语音。", 13, MUTED, false);
        takeoverHelp.setLineSpacing(dp(2), 1f);
        panel.addView(takeoverHelp, new LinearLayout.LayoutParams(-1, -2));
        gap(panel, 18);

        hotkeyButton = text("语音快捷键  " + hotkeyValue + "   ›", 15, INK, false);
        hotkeyButton.setGravity(Gravity.CENTER_VERTICAL);
        hotkeyButton.setPadding(dp(12), 0, dp(12), 0);
        hotkeyButton.setBackground(round(SURFACE, 12, EDGE));
        hotkeyButton.setClickable(true);
        hotkeyButton.setContentDescription("设置语音输入快捷键，当前" + hotkeyValue);
        hotkeyButton.setOnClickListener(view -> showHotkeyDialog());
        panel.addView(hotkeyButton, new LinearLayout.LayoutParams(-1, dp(52)));
        gap(panel, 16);

        TextView connectionHelp = text(connected ? "电脑已连接" : connectionMessage, 13, MUTED, false);
        connectionHelp.setLineSpacing(dp(2), 1f);
        panel.addView(connectionHelp, new LinearLayout.LayoutParams(-1, -2));
        settingsDialog = new AlertDialog.Builder(activity)
                .setTitle("设置")
                .setView(panel)
                .setPositiveButton("完成", null)
                .create();
        settingsDialog.setOnDismissListener(dialog -> {
            settingsDialog = null;
            takeoverSwitch = null;
            hotkeyButton = null;
        });
        settingsDialog.show();
    }

    private void showHotkeyDialog() {
        EditText input = new EditText(activity);
        input.setSingleLine(true);
        input.setText(hotkeyValue);
        input.setSelection(input.length());
        int margin = dp(22);
        FrameLayout box = new FrameLayout(activity);
        box.setPadding(margin, 0, margin, 0);
        box.addView(input, new FrameLayout.LayoutParams(-1, -2));
        AlertDialog dialog = new AlertDialog.Builder(activity)
                .setTitle("语音输入快捷键")
                .setMessage("输入法使用的组合键，例如 Ctrl+Win 或 Ctrl+Shift+V")
                .setView(box)
                .setNegativeButton("取消", null)
                .setPositiveButton("保存", null)
                .create();
        dialog.setOnShowListener(unused -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(view -> {
            String value = input.getText().toString().trim();
            if (!validHotkey(value)) {
                input.setError("请输入有效的组合键，如 Ctrl+Win、Alt+V、F8");
                return;
            }
            setHotkey(value);
            listener.onHotkeyChanged(value);
            dialog.dismiss();
        }));
        dialog.show();
    }

    private boolean validHotkey(String value) {
        if (value.isEmpty() || value.getBytes(java.nio.charset.StandardCharsets.UTF_8).length > 64) return false;
        String[] parts = value.toUpperCase(java.util.Locale.ROOT).split("\\+", -1);
        if (parts.length < 1) return false;
        java.util.HashSet<String> seen = new java.util.HashSet<>();
        for (String raw : parts) {
            String part = raw.trim();
            if (part.equals("CONTROL")) part = "CTRL";
            if (part.equals("WINDOWS")) part = "WIN";
            if (part.equals("RETURN")) part = "ENTER";
            if (part.equals("ESC")) part = "ESCAPE";
            if (!seen.add(part)) return false;
            if (part.matches("CTRL|ALT|SHIFT|WIN|SPACE|ENTER|TAB|ESCAPE|[A-Z0-9]|F([1-9]|1[0-2])")) continue;
            return false;
        }
        return !(seen.size() == 1 && seen.iterator().next().matches("CTRL|ALT|SHIFT|WIN"));
    }

    void setHotkey(String value) {
        hotkeyValue = value;
        if (hotkeyButton != null) {
            hotkeyButton.setText("语音快捷键  " + value + "   ›");
            hotkeyButton.setContentDescription("设置语音输入快捷键，当前" + value);
        }
    }

    void showHotkeyError(String message) {
        Toast.makeText(activity, "快捷键设置失败：" + message, Toast.LENGTH_LONG).show();
    }

    void showTakeoverError(String message) {
        Toast.makeText(activity, "接管电脑麦克风失败：" + message, Toast.LENGTH_LONG).show();
    }

    void setTakeoverStatus(boolean requested, boolean active, String message) {
        takeoverRequested = requested;
        takeoverActive = active;
        if (takeoverSwitch != null) {
            internalSwitchUpdate = true;
            takeoverSwitch.setChecked(requested);
            internalSwitchUpdate = false;
        }
        refreshVoice();
    }

    private void refreshVoice() {
        voiceTitle.setText(recording ? "正在聆听" : !connected ? "等待连接" :
                takeoverActive ? "按住说话" : takeoverRequested ? "正在接管" : "开启接管");
        voiceHint.setText(recording ? "松开后输入" : !connected ? "请检查蓝牙连接" :
                takeoverActive ? "松开后输入" : takeoverRequested ?
                        "正在等待电脑确认麦克风接管" : "点击麦克风，在设置中开启接管");
        micButton.setEnabled(connected);
        micButton.setContentDescription(!connected ? "电脑未连接，" + connectionMessage :
                takeoverActive ? "按住说话，松开后输入到电脑" : "打开设置，开启电脑麦克风接管");
        micFace.setBackground(micBackground(recording));
    }

    void setConnection(boolean isConnected, String message) {
        connected = isConnected;
        connectionMessage = message;
        if (!isConnected) takeoverActive = false;
        connectionLabel.setText(isConnected ? "已连接到 Windows" : "连接已断开");
        connectionDot.setBackground(oval(isConnected ? GREEN : RED, isConnected ? GREEN : RED, 0));
        micIcon.setIconColor(isConnected ? GREEN : RED);
        refreshVoice();
        micButton.setAlpha(1f);
        if (!isConnected) {
            selecting = false;
            updateSelection();
        }
        updateKeys(isConnected && !recording);
    }

    void setRecording(boolean active) {
        recording = active;
        refreshVoice();
        if (active) updateKeys(false);
    }

    void updateKeys(boolean enabled) {
        directionPad.setEnabled(enabled);
        directionPad.setAlpha(1f);
    }

    /** Four held directions around a center split into Enter and Delete. */
    private final class DirectionPad extends View {
        private static final int CENTER_ENTER = 4;
        private static final int CENTER_DELETE = 5;
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final RectF outer = new RectF(6, 6, 212, 212);
        private final RectF inner = new RectF(61, 61, 157, 157);
        private final RectF centerHalves = new RectF(60, 60, 158, 158);
        private final Path sector = new Path();
        private final Path symbol = new Path();
        private int pressed = -1;
        private boolean centerHeld;
        private boolean gestureCancelled;
        private final Runnable repeat = new Runnable() {
            @Override public void run() {
                if (isEnabled() && pressed >= 0 && pressed < CENTER_ENTER) {
                    sendDirection(pressed);
                    repeatHandler.postDelayed(this, REPEAT_INTERVAL_MS);
                }
            }
        };
        private final Runnable repeatDelete = new Runnable() {
            @Override public void run() {
                if (isEnabled() && pressed == CENTER_DELETE) {
                    listener.onKey(2);
                    repeatHandler.postDelayed(this, REPEAT_INTERVAL_MS);
                }
            }
        };
        private final Runnable selectOnHold = new Runnable() {
            @Override public void run() {
                if (isEnabled() && pressed == CENTER_ENTER) {
                    centerHeld = true;
                    performClick();
                    Toast.makeText(activity, selecting ? "选字模式已开启" : "选字模式已关闭",
                            Toast.LENGTH_SHORT).show();
                }
            }
        };

        DirectionPad(Activity context) {
            super(context);
            setLayerType(View.LAYER_TYPE_SOFTWARE, null);
            setClickable(true);
            setContentDescription("方向遥控盘。中心上半圆轻点回车，长按切换选字；下半圆删除，按住连续删除");
        }

        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            float scale = (Math.min(getWidth(), getHeight()) - dp(44)) / 218f;
            canvas.save();
            canvas.translate((getWidth() - 218f * scale) / 2f, (getHeight() - 218f * scale) / 2f);
            canvas.scale(scale, scale);

            paint.setStyle(Paint.Style.FILL);
            paint.setColor(0xFFF7F4ED);
            paint.setShadowLayer(9f, 0, 6f, 0x3B000000);
            canvas.drawCircle(109, 109, 109, paint);
            paint.clearShadowLayer();
            paint.setColor(0xFFE6DDD1);
            canvas.drawCircle(109, 109, 105, paint);

            for (int direction = 0; direction < 4; direction++) {
                float start = -133.75f + direction * 90;
                buildRoundedSector(start, start + 87.5f);
                paint.setColor(SURFACE);
                paint.setShader(new RadialGradient(83, 65, 170,
                        new int[]{0xFFFFFFFF, 0xFFFFFEFB, 0xFFF9F5EF},
                        new float[]{0f, 0.58f, 1f}, Shader.TileMode.CLAMP));
                paint.setShadowLayer(5f, 0, 2.5f, 0x48746250);
                canvas.drawPath(sector, paint);
                paint.clearShadowLayer();
                paint.setShader(null);
                if (pressed == direction) {
                    paint.setColor(0x3300A465);
                    canvas.drawPath(sector, paint);
                }
                paint.setColor(0xFFCFC3B5);
                paint.setStrokeWidth(0.9f);
                paint.setStyle(Paint.Style.STROKE);
                canvas.drawPath(sector, paint);
                paint.setColor(0x66FFFFFF);
                paint.setStrokeWidth(0.45f);
                canvas.drawPath(sector, paint);
                paint.setStyle(Paint.Style.FILL);
            }
            paint.setColor(isEnabled() ? INK : 0xFF999999);
            drawArrow(canvas, 109, 37, 0);
            drawArrow(canvas, 181, 109, 1);
            drawArrow(canvas, 109, 181, 2);
            drawArrow(canvas, 37, 109, 3);

            paint.setStyle(Paint.Style.FILL);
            paint.setColor(selecting ? GREEN : 0xFFE3DACE);
            paint.setShadowLayer(4f, 0, 2.5f, 0x38000000);
            canvas.drawCircle(109, 109, 50, paint);
            paint.clearShadowLayer();
            paint.setColor(pressed == CENTER_ENTER ? 0xFFEBF3EB : SURFACE);
            paint.setShadowLayer(1.5f, 0, 1f, 0x26000000);
            canvas.drawArc(centerHalves, 180, 180, true, paint);
            paint.setColor(pressed == CENTER_DELETE ? 0xFFEFE7DC : SURFACE);
            canvas.drawArc(centerHalves, 0, 180, true, paint);
            paint.clearShadowLayer();
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(1.1f);
            paint.setColor(0xFFD8CEC1);
            canvas.drawArc(centerHalves, 180, 180, true, paint);
            canvas.drawArc(centerHalves, 0, 180, true, paint);
            canvas.drawLine(61, 109, 157, 109, paint);
            drawEnterSymbol(canvas);
            drawDeleteSymbol(canvas);
            paint.setStyle(Paint.Style.FILL);
            paint.setColor(isEnabled() ? INK : 0xFF999999);
            paint.setTextAlign(Paint.Align.CENTER);
            paint.setTypeface(Typeface.create(Typeface.DEFAULT, Typeface.BOLD));
            paint.setTextSize(13f);
            canvas.drawText("回车", 109, 101, paint);
            canvas.drawText("删除", 109, 151, paint);
            canvas.restore();
        }

        private void buildRoundedSector(float start, float end) {
            final float outerRadius = 103f;
            final float innerRadius = 48f;
            final float cornerInset = 7f;
            final float outerAngle = 4f;
            final float innerAngle = 8f;
            sector.reset();
            sector.moveTo(polarX(outerRadius, start + outerAngle),
                    polarY(outerRadius, start + outerAngle));
            sector.arcTo(outer, start + outerAngle,
                    end - start - outerAngle * 2f, false);
            sector.quadTo(polarX(outerRadius, end), polarY(outerRadius, end),
                    polarX(outerRadius - cornerInset, end),
                    polarY(outerRadius - cornerInset, end));
            sector.lineTo(polarX(innerRadius + cornerInset, end),
                    polarY(innerRadius + cornerInset, end));
            sector.quadTo(polarX(innerRadius, end), polarY(innerRadius, end),
                    polarX(innerRadius, end - innerAngle),
                    polarY(innerRadius, end - innerAngle));
            sector.arcTo(inner, end - innerAngle,
                    -(end - start - innerAngle * 2f), false);
            sector.quadTo(polarX(innerRadius, start), polarY(innerRadius, start),
                    polarX(innerRadius + cornerInset, start),
                    polarY(innerRadius + cornerInset, start));
            sector.lineTo(polarX(outerRadius - cornerInset, start),
                    polarY(outerRadius - cornerInset, start));
            sector.quadTo(polarX(outerRadius, start), polarY(outerRadius, start),
                    polarX(outerRadius, start + outerAngle),
                    polarY(outerRadius, start + outerAngle));
            sector.close();
        }

        private float polarX(float radius, float degrees) {
            return 109f + radius * (float) Math.cos(Math.toRadians(degrees));
        }

        private float polarY(float radius, float degrees) {
            return 109f + radius * (float) Math.sin(Math.toRadians(degrees));
        }

        private void drawArrow(Canvas canvas, float x, float y, int direction) {
            symbol.reset();
            if (direction == 0) {
                symbol.moveTo(x, y - 11); symbol.lineTo(x + 11, y + 7); symbol.lineTo(x - 11, y + 7);
            } else if (direction == 1) {
                symbol.moveTo(x + 11, y); symbol.lineTo(x - 7, y + 11); symbol.lineTo(x - 7, y - 11);
            } else if (direction == 2) {
                symbol.moveTo(x, y + 11); symbol.lineTo(x - 11, y - 7); symbol.lineTo(x + 11, y - 7);
            } else {
                symbol.moveTo(x - 11, y); symbol.lineTo(x + 7, y - 11); symbol.lineTo(x + 7, y + 11);
            }
            symbol.close();
            canvas.drawPath(symbol, paint);
        }

        private void drawEnterSymbol(Canvas canvas) {
            paint.setColor(isEnabled() ? INK : 0xFF999999);
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(2.6f);
            paint.setStrokeCap(Paint.Cap.ROUND);
            paint.setStrokeJoin(Paint.Join.ROUND);
            symbol.reset();
            symbol.moveTo(120, 72);
            symbol.lineTo(120, 78);
            symbol.quadTo(120, 83, 115, 83);
            symbol.lineTo(100, 83);
            canvas.drawPath(symbol, paint);
            symbol.reset();
            symbol.moveTo(105, 78); symbol.lineTo(100, 83); symbol.lineTo(105, 88);
            canvas.drawPath(symbol, paint);
        }

        private void drawDeleteSymbol(Canvas canvas) {
            paint.setColor(isEnabled() ? INK : 0xFF999999);
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(2.3f);
            paint.setStrokeCap(Paint.Cap.ROUND);
            paint.setStrokeJoin(Paint.Join.ROUND);
            symbol.reset();
            symbol.moveTo(101, 120); symbol.lineTo(119, 120);
            symbol.lineTo(119, 135); symbol.lineTo(101, 135);
            symbol.lineTo(93, 127.5f); symbol.close();
            canvas.drawPath(symbol, paint);
            canvas.drawLine(106, 124, 114, 132, paint);
            canvas.drawLine(114, 124, 106, 132, paint);
        }

        private int directionAt(float x, float y) {
            float scale = (Math.min(getWidth(), getHeight()) - dp(44)) / 218f;
            float dx = (x - getWidth() / 2f) / scale;
            float dy = (y - getHeight() / 2f) / scale;
            float radius = (float) Math.hypot(dx, dy);
            if (radius < 50) return dy < 0 ? CENTER_ENTER : CENTER_DELETE;
            if (radius > 109) return -1;
            if (Math.abs(dx) > Math.abs(dy)) return dx > 0 ? 1 : 3;
            return dy > 0 ? 2 : 0;
        }

        private void sendDirection(int direction) {
            int[] codes = {5, 4, 6, 3};
            listener.onKey(codes[direction] + (selecting ? 4 : 0));
        }

        @Override public boolean onTouchEvent(MotionEvent event) {
            if (!isEnabled()) return false;
            int action = event.getActionMasked();
            if (action == MotionEvent.ACTION_DOWN) {
                pressed = directionAt(event.getX(), event.getY());
                gestureCancelled = false;
                centerHeld = false;
                invalidate();
                if (pressed >= 0 && pressed < CENTER_ENTER) {
                    performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP);
                    sendDirection(pressed);
                    repeatHandler.postDelayed(repeat, REPEAT_START_MS);
                } else if (pressed == CENTER_DELETE) {
                    performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP);
                    listener.onKey(2);
                    repeatHandler.postDelayed(repeatDelete, REPEAT_START_MS);
                } else if (pressed == CENTER_ENTER) {
                    repeatHandler.postDelayed(selectOnHold, 520);
                }
                return true;
            }
            if (action == MotionEvent.ACTION_MOVE) {
                if (!gestureCancelled && directionAt(event.getX(), event.getY()) != pressed) {
                    gestureCancelled = true;
                    repeatHandler.removeCallbacks(repeat);
                    repeatHandler.removeCallbacks(repeatDelete);
                    repeatHandler.removeCallbacks(selectOnHold);
                    pressed = -1;
                    invalidate();
                }
                return true;
            }
            if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {
                int released = pressed;
                repeatHandler.removeCallbacks(repeat);
                repeatHandler.removeCallbacks(repeatDelete);
                repeatHandler.removeCallbacks(selectOnHold);
                pressed = -1;
                invalidate();
                if (action == MotionEvent.ACTION_UP && released == CENTER_ENTER && !centerHeld && !gestureCancelled &&
                        directionAt(event.getX(), event.getY()) == CENTER_ENTER) {
                    performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP);
                    listener.onKey(1);
                }
                return true;
            }
            return true;
        }

        @Override public boolean performClick() {
            super.performClick();
            if (!isEnabled()) return false;
            selecting = !selecting;
            performHapticFeedback(HapticFeedbackConstants.LONG_PRESS);
            updateSelection();
            return true;
        }

        @Override public void setEnabled(boolean enabled) {
            super.setEnabled(enabled);
            if (!enabled) {
                repeatHandler.removeCallbacks(repeat);
                repeatHandler.removeCallbacks(repeatDelete);
                repeatHandler.removeCallbacks(selectOnHold);
                pressed = -1;
                invalidate();
            }
        }
    }

    private static final class GearIcon extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Path outline = new Path();

        GearIcon(Activity activity) { super(activity); }

        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            float scale = Math.min(getWidth(), getHeight()) / 32f;
            canvas.save();
            canvas.translate((getWidth() - 32 * scale) / 2f, (getHeight() - 32 * scale) / 2f);
            canvas.scale(scale, scale);
            outline.reset();
            for (int i = 0; i < 48; i++) {
                float phase = i % 6;
                float radius = phase == 0 || phase == 5 ? 11.3f : 14.2f;
                double angle = (i * 7.5 - 90) * Math.PI / 180;
                float x = 16 + radius * (float) Math.cos(angle);
                float y = 16 + radius * (float) Math.sin(angle);
                if (i == 0) outline.moveTo(x, y);
                else outline.lineTo(x, y);
            }
            outline.close();
            paint.setColor(INK);
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(2.2f);
            paint.setStrokeJoin(Paint.Join.ROUND);
            canvas.drawPath(outline, paint);
            canvas.drawCircle(16, 16, 4.3f, paint);
            canvas.restore();
        }
    }

    private static final class MicIcon extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final RectF capsule = new RectF(18, 7, 30, 31);
        private final RectF arc = new RectF(12, 15, 36, 38);
        private int color;

        MicIcon(Activity activity, int color) {
            super(activity);
            this.color = color;
        }

        void setIconColor(int color) {
            this.color = color;
            invalidate();
        }

        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            float scale = Math.min(getWidth(), getHeight()) / 48f;
            canvas.save();
            canvas.translate((getWidth() - scale * 48) / 2f, (getHeight() - scale * 48) / 2f);
            canvas.scale(scale, scale);
            paint.setColor(color);
            paint.setStyle(Paint.Style.FILL);
            canvas.drawRoundRect(capsule, 6, 6, paint);
            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeWidth(3.2f);
            paint.setStrokeCap(Paint.Cap.ROUND);
            canvas.drawArc(arc, 0, 180, false, paint);
            canvas.drawLine(24, 38, 24, 43, paint);
            canvas.drawLine(17, 43, 31, 43, paint);
            canvas.restore();
        }
    }
}
