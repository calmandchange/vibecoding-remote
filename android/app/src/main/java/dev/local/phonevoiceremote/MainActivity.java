package dev.local.phonevoiceremote;

import android.Manifest;
import android.app.Activity;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothServerSocket;
import android.bluetooth.BluetoothSocket;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Android end of the Bluetooth SPP microphone and shortcut bridge. */
public class MainActivity extends Activity {
    private static final UUID SPP_UUID = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB");
    private static final int SAMPLE_RATE = 16000;
    private static final int FRAME_BYTES = 640; // 20 ms, PCM16 mono
    private static final int FIRST_FRAME_BYTES = 160; // 5 ms for prompt audio onset
    private static final byte AUDIO = 1;
    private static final byte HOTKEY = 2;
    private static final byte HEARTBEAT = 3;
    private static final byte KEY = 4;
    private static final byte TAKEOVER = 5;
    private static final byte CONFIG_HOTKEY = 6;
    private static final byte ACK = 7;

    private final Object socketLock = new Object();
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService controls = Executors.newSingleThreadExecutor();
    private volatile boolean running = true;
    private volatile boolean recording = false;
    private volatile boolean connected = false;
    private volatile boolean takeoverRequested = false;
    private volatile boolean takeoverActive = false;
    private volatile String hotkeySetting = "Ctrl+Win";
    private volatile boolean serverStarting = false;
    private BluetoothServerSocket server;
    private BluetoothSocket client;
    private OutputStream output;
    private volatile Thread recordingThread;
    private AudioRecord cachedRecorder;
    private RemoteUi screen;
    private final Runnable heartbeat = new Runnable() {
        @Override public void run() {
            if (!running) return;
            if (connected && !controls.isShutdown()) {
                controls.execute(() -> sendFrame(HEARTBEAT, new byte[0], 0));
            }
            ui.postDelayed(this, 2000);
        }
    };
    private final Runnable retryServer = new Runnable() {
        @Override public void run() {
            if (running && !serverStarting && !connected) startServer();
        }
    };

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        getWindow().setStatusBarColor(0xFFFDFCF7);
        getWindow().setNavigationBarColor(0xFFFDFCF7);
        applySystemBars();
        SharedPreferences settings = getSharedPreferences("remote-settings", MODE_PRIVATE);
        hotkeySetting = settings.getString("voice-hotkey", "Ctrl+Win");
        screen = new RemoteUi(this, new RemoteUi.Listener() {
            @Override public void onVoiceDown() { startRecording(); }
            @Override public void onVoiceUp() { stopRecording(); }
            @Override public void onKey(int code) { sendKey(code); }
            @Override public void onTakeoverChanged(boolean enabled) { setTakeoverRequested(enabled); }
            @Override public void onHotkeyChanged(String value) {
                hotkeySetting = value;
                settings.edit().putString("voice-hotkey", value).apply();
                sendHotkeySetting();
            }
        });
        screen.setHotkey(hotkeySetting);
        ui.postDelayed(heartbeat, 2000);
    }

    private void applySystemBars() {
        if (Build.VERSION.SDK_INT >= 30) {
            WindowInsetsController controller = getWindow().getInsetsController();
            if (controller != null) {
                controller.setSystemBarsAppearance(WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS,
                        WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS);
                controller.setSystemBarsBehavior(
                        WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
                controller.hide(WindowInsets.Type.navigationBars());
            }
        } else {
            getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR |
                    View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
        }
    }

    @Override public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) applySystemBars();
    }

    @Override
    protected void onResume() {
        super.onResume();
        requestPermissionsIfNeeded();
        if (connected && takeoverRequested && !controls.isShutdown()) {
            controls.execute(() -> sendFrame(TAKEOVER, new byte[]{1}, 1));
        }
    }

    private void requestPermissionsIfNeeded() {
        boolean needsMic = checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED;
        boolean needsBluetooth = Build.VERSION.SDK_INT >= 31 &&
                checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED;
        if (needsMic || needsBluetooth) {
            if (Build.VERSION.SDK_INT >= 31) {
                requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO, Manifest.permission.BLUETOOTH_CONNECT}, 1);
            } else {
                requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 1);
            }
        } else {
            startServer();
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results);
        if (requestCode == 1) {
            boolean granted = true;
            for (int result : results) granted &= result == PackageManager.PERMISSION_GRANTED;
            if (granted && results.length > 0) startServer();
            else screen.setConnection(false, "需要麦克风和附近设备权限，请在系统设置中授权");
        }
    }

    private void startServer() {
        if (serverStarting) return;
        BluetoothManager manager = getSystemService(BluetoothManager.class);
        BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
        if (adapter == null || !adapter.isEnabled()) {
            screen.setConnection(false, "请先开启手机蓝牙，然后返回本页面");
            ui.removeCallbacks(retryServer);
            ui.postDelayed(retryServer, 3000);
            return;
        }
        serverStarting = true;
        ui.removeCallbacks(retryServer);
        screen.setConnection(false, "正在等待电脑连接…");
        new Thread(() -> {
            try {
                server = adapter.listenUsingRfcommWithServiceRecord("PhoneVoiceRemote", SPP_UUID);
                while (running) {
                    BluetoothSocket accepted = server.accept();
                    synchronized (socketLock) {
                        client = accepted;
                        output = accepted.getOutputStream();
                        connected = true;
                        takeoverActive = false;
                    }
                    Log.i("PhoneVoiceRemote", "电脑已连接");
                    showStatus("电脑已连接，可开启麦克风接管");
                    controls.execute(() -> {
                        sendHotkeySettingNow();
                        sendFrame(TAKEOVER, new byte[]{(byte) (takeoverRequested ? 1 : 0)}, 1);
                    });
                    try {
                        readComputerMessages(accepted.getInputStream());
                    } catch (IOException ignored) {
                        // A broken RFCOMM link is normal when the PC disconnects.
                        Log.w("PhoneVoiceRemote", "蓝牙读取中断", ignored);
                    } finally {
                        stopRecording();
                        synchronized (socketLock) {
                            connected = false;
                            takeoverActive = false;
                            output = null;
                            client = null;
                        }
                        try { accepted.close(); } catch (IOException ignored) { }
                        Log.i("PhoneVoiceRemote", "电脑连接已断开，等待重连");
                        if (running) showStatus("连接断开，正在等待电脑重连…");
                    }
                }
            } catch (IOException | SecurityException e) {
                Log.w("PhoneVoiceRemote", "蓝牙服务中断，将重试", e);
                if (running) showStatus("蓝牙服务失败：" + e.getMessage());
            } finally {
                try { if (server != null) server.close(); } catch (IOException ignored) { }
                serverStarting = false;
                server = null;
                if (running) ui.postDelayed(retryServer, 1500);
            }
        }, "bluetooth-server").start();
    }

    private void setTakeoverRequested(boolean enabled) {
        takeoverRequested = enabled;
        if (!enabled) {
            takeoverActive = false;
            stopRecording();
        }
        screen.setTakeoverStatus(enabled, false, enabled ? "正在切换电脑麦克风…" : "已关闭接管");
        if (connected && !controls.isShutdown()) {
            controls.execute(() -> sendFrame(TAKEOVER, new byte[]{(byte) (enabled ? 1 : 0)}, 1));
        }
    }

    private void sendHotkeySetting() {
        if (connected && !controls.isShutdown()) controls.execute(this::sendHotkeySettingNow);
    }

    private void sendHotkeySettingNow() {
        byte[] bytes = hotkeySetting.getBytes(StandardCharsets.UTF_8);
        if (bytes.length > 0 && bytes.length <= 64) sendFrame(CONFIG_HOTKEY, bytes, bytes.length);
    }

    private static int readRequired(InputStream input) throws IOException {
        int value = input.read();
        if (value < 0) throw new IOException("电脑蓝牙连接已关闭");
        return value;
    }

    private void readComputerMessages(InputStream input) throws IOException {
        while (running) {
            if (readRequired(input) != 'P') continue;
            if (readRequired(input) != 'M') continue;
            int kind = readRequired(input);
            int length = readRequired(input) | (readRequired(input) << 8);
            if (length > 512) throw new IOException("电脑消息长度无效");
            byte[] payload = new byte[length];
            int offset = 0;
            while (offset < length) {
                int read = input.read(payload, offset, length - offset);
                if (read < 0) throw new IOException("电脑蓝牙连接已关闭");
                offset += read;
            }
            if (kind == ACK && length >= 3) {
                byte acknowledged = payload[0];
                boolean success = payload[1] == 1;
                boolean active = payload[2] == 1;
                String message = new String(Arrays.copyOfRange(payload, 3, length), StandardCharsets.UTF_8);
                if (acknowledged == TAKEOVER) {
                    takeoverActive = success && active && takeoverRequested && connected;
                    if (!success) takeoverRequested = false;
                    ui.post(() -> screen.setTakeoverStatus(takeoverRequested, takeoverActive, message));
                    if (!success) ui.post(() -> screen.showTakeoverError(message));
                } else if (acknowledged == CONFIG_HOTKEY && !success) {
                    ui.post(() -> screen.showHotkeyError(message));
                }
            }
        }
    }

    private void startRecording() {
        if (!connected || !takeoverActive || recording ||
                (recordingThread != null && recordingThread.isAlive())) return;
        long pressedAt = SystemClock.elapsedRealtimeNanos();
        recording = true;
        screen.setRecording(true);
        recordingThread = new Thread(() -> {
            AudioRecord recorder = null;
            boolean hotkeyPressed = false;
            boolean recorderFailed = false;
            try {
                // The shortcut must lead the stream; waiting for audio initialization used to add
                // at least three 20 ms frames to every press.
                hotkeyPressed = sendFrame(HOTKEY, new byte[]{1}, 1);
                if (!hotkeyPressed) return;
                long hotkeySentAt = SystemClock.elapsedRealtimeNanos();
                recorder = getOrCreateRecorder();
                long recordStartAt = SystemClock.elapsedRealtimeNanos();
                recorder.startRecording();
                long recorderStartedAt = SystemClock.elapsedRealtimeNanos();
                byte[] frame = new byte[FRAME_BYTES];
                int filled = 0;
                boolean firstFrame = true;
                while (running && recording && connected && takeoverActive) {
                    int target = firstFrame ? FIRST_FRAME_BYTES : FRAME_BYTES;
                    int count = recorder.read(frame, filled, target - filled);
                    if (count <= 0) throw new IllegalStateException("读取麦克风失败：" + count);
                    filled += count;
                    if (filled == target) {
                        if (!sendFrame(AUDIO, frame, filled)) break;
                        if (firstFrame) {
                            Log.i("PhoneVoiceRemote", "快捷键 " +
                                    (hotkeySentAt - pressedAt) / 1_000_000 + " ms；录音启动 " +
                                    (recorderStartedAt - recordStartAt) / 1_000_000 +
                                    " ms；首帧音频 " +
                                    (SystemClock.elapsedRealtimeNanos() - pressedAt) / 1_000_000 + " ms");
                            firstFrame = false;
                        }
                        filled = 0;
                    }
                }
            } catch (SecurityException | IllegalStateException | IllegalArgumentException e) {
                recorderFailed = true;
                showStatus("录音失败：" + e.getMessage());
            } finally {
                // Keep press and release on this thread so a quick touch cannot reverse their order.
                if (hotkeyPressed) sendFrame(HOTKEY, new byte[]{2}, 1);
                if (recorder != null) {
                    try {
                        if (recorder.getRecordingState() == AudioRecord.RECORDSTATE_RECORDING) recorder.stop();
                    } catch (IllegalStateException e) {
                        recorderFailed = true;
                    }
                    if (recorderFailed || !running) releaseCachedRecorder();
                }
                stopRecording();
                recordingThread = null;
                ui.post(() -> screen.updateKeys(connected));
            }
        }, "microphone-stream");
        recordingThread.start();
    }

    private AudioRecord getOrCreateRecorder() {
        if (cachedRecorder != null && cachedRecorder.getState() == AudioRecord.STATE_INITIALIZED) {
            return cachedRecorder;
        }
        releaseCachedRecorder();
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            throw new SecurityException("麦克风权限未授权");
        }
        int minimum = AudioRecord.getMinBufferSize(SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        if (minimum <= 0) throw new IllegalStateException("设备不支持 16 kHz 单声道录音");
        AudioRecord recorder = new AudioRecord(MediaRecorder.AudioSource.MIC, SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
                Math.max(minimum, FRAME_BYTES * 2));
        if (recorder.getState() != AudioRecord.STATE_INITIALIZED) {
            recorder.release();
            throw new IllegalStateException("麦克风初始化失败");
        }
        cachedRecorder = recorder;
        return recorder;
    }

    private void releaseCachedRecorder() {
        if (cachedRecorder != null) {
            cachedRecorder.release();
            cachedRecorder = null;
        }
    }

    private boolean sendFrame(byte kind, byte[] payload, int length) {
        synchronized (socketLock) {
            if (output == null) return false;
            try {
                byte[] frame = new byte[5 + length];
                frame[0] = 'P';
                frame[1] = 'M';
                frame[2] = kind;
                frame[3] = (byte)(length & 0xff);
                frame[4] = (byte)((length >>> 8) & 0xff);
                System.arraycopy(payload, 0, frame, 5, length);
                output.write(frame);
                return true;
            } catch (IOException e) {
                showStatus("发送失败，请检查蓝牙连接：" + e.getMessage());
                try { if (client != null) client.close(); } catch (IOException ignored) { }
                return false;
            }
        }
    }

    private void stopRecording() {
        boolean threadActive = recordingThread != null && recordingThread.isAlive();
        recording = false;
        ui.post(() -> {
            screen.setRecording(false);
            screen.updateKeys(connected && !threadActive);
        });
    }

    private void sendKey(int code) {
        if (!connected || recording || recordingThread != null || controls.isShutdown()) return;
        controls.execute(() -> sendFrame(KEY, new byte[]{(byte) code}, 1));
    }

    private void showStatus(String text) {
        ui.post(() -> {
            screen.setConnection(connected, text);
        });
    }

    @Override
    protected void onPause() {
        stopRecording();
        takeoverActive = false;
        if (connected && !controls.isShutdown()) {
            controls.execute(() -> sendFrame(TAKEOVER, new byte[]{0}, 1));
        }
        screen.setTakeoverStatus(takeoverRequested, false, "已暂停接管");
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        running = false;
        ui.removeCallbacks(heartbeat);
        ui.removeCallbacks(retryServer);
        stopRecording();
        controls.shutdownNow();
        try { if (server != null) server.close(); } catch (IOException ignored) { }
        try { if (client != null) client.close(); } catch (IOException ignored) { }
        if (recordingThread == null || !recordingThread.isAlive()) releaseCachedRecorder();
        super.onDestroy();
    }
}
