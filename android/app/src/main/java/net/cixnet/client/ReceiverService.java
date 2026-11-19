package net.cixnet.client;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.net.wifi.WifiManager;
import android.os.*;
import android.util.Log;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** Owns reception independently of the WebView and its activity lifecycle. */
public final class ReceiverService extends Service {
  // A new channel also fixes installed previews: Android retains the original
  // channel's badge setting when an existing channel is registered again.
  private static final String RECEIVER = "receiver-status-v2";
  private static final String MESSAGES = "messages";
  private static final String STOP = "net.cixnet.client.STOP";
  private final AtomicBoolean running = new AtomicBoolean();
  private final Handler main = new Handler(Looper.getMainLooper());
  private PowerManager.WakeLock wakeLock;
  private WifiManager.MulticastLock multicastLock;
  private FallbackInternet fallbackInternet;

  @Override
  public void onCreate() {
    super.onCreate();
    fallbackInternet = new FallbackInternet(this);
    new File(getFilesDir(), "receiver-ready.json").delete();
    new File(getFilesDir(), "receiver-error.txt").delete();
    NotificationManager manager = getSystemService(NotificationManager.class);
    NotificationChannel receiverChannel =
        new NotificationChannel(
            RECEIVER, "Background receiver", NotificationManager.IMPORTANCE_LOW);
    // Foreground-service status must not create an unread-message launcher dot.
    receiverChannel.setShowBadge(false);
    manager.createNotificationChannel(receiverChannel);
    NotificationChannel messagesChannel =
        new NotificationChannel(
            MESSAGES, "Incoming messages", NotificationManager.IMPORTANCE_DEFAULT);
    messagesChannel.enableVibration(true);
    messagesChannel.setShowBadge(true);
    manager.createNotificationChannel(messagesChannel);
    startForeground(1, receiverNotification("Starting receiver…"));
  }

  @Override
  public int onStartCommand(Intent intent, int flags, int startId) {
    if (intent != null && STOP.equals(intent.getAction())) {
      stopSelf();
      return START_NOT_STICKY;
    }
    if (running.compareAndSet(false, true)) {
      wakeLock =
          getSystemService(PowerManager.class)
              .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "ciXnet:receiver");
      wakeLock.acquire();
      WifiManager wifi = (WifiManager) getApplicationContext().getSystemService(WIFI_SERVICE);
      multicastLock = wifi.createMulticastLock("ciXnet:discovery");
      multicastLock.acquire();
      new Thread(this::runReceiver, "ciXnet receiver").start();
    }
    return START_STICKY;
  }

  private void runReceiver() {
    try {
      File ui = new File(getFilesDir(), "ui");
      copyAssets("ui", ui);
      if (!Python.isStarted()) Python.start(new AndroidPlatform(this));
      Python.getInstance()
          .getModule("android_receiver")
          .callAttr(
              "run",
              this,
              new File(getFilesDir(), "cixnet").getAbsolutePath(),
              ui.getAbsolutePath());
    } catch (Exception error) {
      Log.e("ciXnet", "Receiver stopped", error);
      new File(getFilesDir(), "receiver-ready.json").delete();
      try {
        Files.write(
            new File(getFilesDir(), "receiver-error.txt").toPath(),
            "Receiver could not start. Check the Android diagnostic log."
                .getBytes(StandardCharsets.UTF_8));
      } catch (IOException ignored) {
        /* The notification still reports failure. */
      }
      getSystemService(NotificationManager.class)
          .notify(1, receiverNotification("Receiver stopped · reopen ciXnet"));
      main.post(this::stopSelf);
    }
  }

  /** Called only after the Python listener and all persisted identities are ready. */
  public void receiverReady(int port, String accessKey) throws IOException {
    File temporary = new File(getFilesDir(), "receiver-ready.tmp");
    Files.write(
        temporary.toPath(),
        ("{\"port\":" + port + ",\"accessKey\":\"" + accessKey + "\"}")
            .getBytes(StandardCharsets.UTF_8));
    Files.move(
        temporary.toPath(),
        new File(getFilesDir(), "receiver-ready.json").toPath(),
        StandardCopyOption.REPLACE_EXISTING);
    getSystemService(NotificationManager.class)
        .notify(1, receiverNotification("Receiver running · waiting for messages"));
  }

  /** No message body or attachment names are exposed on the lock screen. */
  public void messageReceived(String owner, String peer, String message) {
    if (Build.VERSION.SDK_INT >= 33
        && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED) return;
    Intent intent =
        new Intent(this, MainActivity.class)
            .putExtra("owner", owner)
            .putExtra("peer", peer)
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
    PendingIntent open =
        PendingIntent.getActivity(
            this,
            (owner + peer).hashCode(),
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    Notification notification =
        new Notification.Builder(this, MESSAGES)
            .setSmallIcon(R.drawable.ic_cixnet)
            .setContentTitle("ciXnet")
            .setContentText("New message received")
            .setVisibility(Notification.VISIBILITY_PRIVATE)
            .setContentIntent(open)
            .setAutoCancel(true)
            .setCategory(Notification.CATEGORY_MESSAGE)
            .build();
    getSystemService(NotificationManager.class).notify(owner + ":" + peer, 2, notification);
  }

  /** The authenticated local API supplies only a generated loopback bridge URL. */
  public boolean openBrowser(String value) {
    Uri uri = Uri.parse(value);
    String host = uri.getHost();
    if (!"http".equals(uri.getScheme())
        || host == null
        || !host.endsWith(".localhost")
        || uri.getUserInfo() != null) return false;
    try {
      startActivity(
          new Intent(Intent.ACTION_VIEW, uri)
              .addCategory(Intent.CATEGORY_BROWSABLE)
              .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
      return true;
    } catch (ActivityNotFoundException unavailable) {
      return false;
    }
  }

  private Notification receiverNotification(String text) {
    PendingIntent open =
        PendingIntent.getActivity(
            this,
            0,
            new Intent(this, MainActivity.class),
            PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
    PendingIntent stop =
        PendingIntent.getService(
            this,
            1,
            new Intent(this, ReceiverService.class).setAction(STOP),
            PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
    return new Notification.Builder(this, RECEIVER)
        .setSmallIcon(R.drawable.ic_cixnet)
        .setContentTitle("ciXnet receiver")
        .setContentText(text)
        .setContentIntent(open)
        // Updating service status must never sound like an incoming message.
        .setOnlyAlertOnce(true)
        .setCategory(Notification.CATEGORY_SERVICE)
        .setBadgeIconType(Notification.BADGE_ICON_NONE)
        .setOngoing(true)
        .addAction(new Notification.Action.Builder(null, "Stop receiver", stop).build())
        .build();
  }

  private void copyAssets(String source, File target) throws IOException {
    String[] children = getAssets().list(source);
    if (children != null && children.length > 0) {
      if (!target.isDirectory() && !target.mkdirs())
        throw new IOException("Cannot create UI directory");
      for (String child : children) copyAssets(source + "/" + child, new File(target, child));
    } else {
      try (InputStream input = getAssets().open(source);
          OutputStream output = new FileOutputStream(target)) {
        byte[] buffer = new byte[65536];
        int count;
        while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
      }
    }
  }

  public FallbackInternet fallbackInternet() {
    return fallbackInternet;
  }

  @Override
  public void onDestroy() {
    if (fallbackInternet != null) fallbackInternet.release();
    new File(getFilesDir(), "receiver-ready.json").delete();
    if (Python.isStarted()) Python.getInstance().getModule("android_receiver").callAttr("stop");
    if (multicastLock != null && multicastLock.isHeld()) multicastLock.release();
    if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
    // Only the private receiver process exits; the activity belongs to another process.
    main.postDelayed(() -> android.os.Process.killProcess(android.os.Process.myPid()), 1500);
    super.onDestroy();
  }

  @Override
  public IBinder onBind(Intent intent) {
    return null;
  }
}
