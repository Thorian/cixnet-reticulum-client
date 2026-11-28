package net.cixnet.client;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ContentValues;
import android.content.pm.PackageManager;
import android.media.MediaScannerConnection;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import android.util.Base64;
import android.webkit.WebMessage;
import android.webkit.WebMessagePort;
import android.webkit.WebView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONObject;

/** One bounded, acknowledged save at a time; no bridge is installed in remote frames. */
final class DownloadStore {
  private final Activity activity;
  private final ExecutorService worker = Executors.newSingleThreadExecutor();
  private WebMessagePort port;
  private OutputStream output;
  private Uri pendingUri;
  private File pendingFile;
  private String activeId;
  private long expected;
  private long written;
  private volatile HttpURLConnection activeConnection;

  /** Content-Disposition downloads arrive here when no page script handled the link. */
  void download(String address, String name, String mime) {
    Uri target = Uri.parse(address);
    String host = target.getHost();
    if (!"http".equals(target.getScheme())
        || host == null
        || !host.matches("[a-f0-9]{32}\\.[a-f0-9]{32}\\.[a-f0-9]{32}\\.localhost")) {
      Toast.makeText(activity, "Open this download in your web browser", Toast.LENGTH_LONG).show();
      return;
    }
    AtomicBoolean cancelled = new AtomicBoolean();
    ProgressBar bar = new ProgressBar(activity, null, android.R.attr.progressBarStyleHorizontal);
    bar.setIndeterminate(true);
    TextView label = new TextView(activity);
    label.setText("Downloading " + name);
    LinearLayout layout = new LinearLayout(activity);
    layout.setOrientation(LinearLayout.VERTICAL);
    layout.setPadding(32, 20, 32, 20);
    layout.addView(label);
    layout.addView(bar);
    AlertDialog dialog =
        new AlertDialog.Builder(activity)
            .setTitle("Download")
            .setView(layout)
            .setNegativeButton(
                "Cancel",
                (unused, which) -> {
                  cancelled.set(true);
                  if (activeConnection != null) activeConnection.disconnect();
                })
            .create();
    dialog.setOnCancelListener(
        unused -> {
          cancelled.set(true);
          if (activeConnection != null) activeConnection.disconnect();
        });
    dialog.show();
    worker.execute(
        () -> {
          HttpURLConnection connection = null;
          boolean started = false;
          try {
            if (output != null) throw new IOException("Another file is being saved");
            // Java does not resolve Chromium's wildcard .localhost names. Keep the
            // validated Host header while connecting directly to the loopback server.
            URL local =
                new URL(
                    target
                        .buildUpon()
                        .encodedAuthority("127.0.0.1:" + target.getPort())
                        .build()
                        .toString());
            connection = (HttpURLConnection) local.openConnection();
            activeConnection = connection;
            connection.setRequestProperty("Host", target.getEncodedAuthority());
            connection.setConnectTimeout(15000);
            connection.setReadTimeout(600000);
            connection.setInstanceFollowRedirects(false);
            int status = connection.getResponseCode();
            if (status != 200) throw new IOException("Download failed (" + status + ")");
            long total = connection.getContentLengthLong();
            if (total > 512L * 1024 * 1024) throw new IOException("File is too large");
            activeId = UUID.randomUUID().toString();
            started = true;
            begin(name, mime == null ? "application/octet-stream" : mime);
            long count = 0;
            try (InputStream input = connection.getInputStream()) {
              byte[] bytes = new byte[32768];
              int length;
              while ((length = input.read(bytes)) != -1) {
                if (cancelled.get()) throw new IOException("Download cancelled");
                count += length;
                if (count > 512L * 1024 * 1024) throw new IOException("File is too large");
                output.write(bytes, 0, length);
                int percent = total > 0 ? (int) (100 * count / total) : 0;
                activity.runOnUiThread(
                    () -> {
                      bar.setIndeterminate(total <= 0);
                      bar.setProgress(percent);
                    });
              }
            }
            if (total >= 0 && count != total) throw new IOException("File transfer was incomplete");
            if (cancelled.get()) throw new IOException("Download cancelled");
            publish();
            activity.runOnUiThread(
                () ->
                    Toast.makeText(activity, "Saved to Downloads/ciXnet", Toast.LENGTH_LONG)
                        .show());
          } catch (Exception error) {
            if (started) discard();
            activity.runOnUiThread(
                () -> Toast.makeText(activity, error.getMessage(), Toast.LENGTH_LONG).show());
          } finally {
            if (connection != null) connection.disconnect();
            activeConnection = null;
            activity.runOnUiThread(dialog::dismiss);
          }
        });
  }

  DownloadStore(Activity activity) {
    this.activity = activity;
  }

  void attach(WebView view, String origin) {
    if (port != null) port.close();
    worker.execute(this::discard);
    WebMessagePort[] channel = view.createWebMessageChannel();
    port = channel[0];
    WebMessagePort replies = port;
    port.setWebMessageCallback(
        new WebMessagePort.WebMessageCallback() {
          @Override
          public void onMessage(WebMessagePort unused, WebMessage message) {
            worker.execute(() -> receive(message.getData(), replies));
          }
        });
    String token = UUID.randomUUID().toString();
    view.evaluateJavascript(
        "document.documentElement.dataset.downloadToken=" + JSONObject.quote(token),
        ignored ->
            view.postWebMessage(
                new WebMessage(token, new WebMessagePort[] {channel[1]}), Uri.parse(origin)));
  }

  private void receive(String data, WebMessagePort replies) {
    JSONObject reply = new JSONObject();
    try {
      if (data == null || data.length() > 50000) throw new IOException("Invalid download chunk");
      JSONObject request = new JSONObject(data);
      reply.put("request", request.getString("request"));
      String id = request.getString("id");
      switch (request.getString("action")) {
        case "begin":
          if (output != null) throw new IOException("Another file is being saved");
          expected = request.getLong("size");
          if (expected < 0 || expected > 512L * 1024 * 1024)
            throw new IOException("File is too large");
          activeId = id;
          written = 0;
          begin(request.getString("name"), request.optString("mime", "application/octet-stream"));
          break;
        case "chunk":
          requireActive(id);
          byte[] bytes = Base64.decode(request.getString("data"), Base64.DEFAULT);
          if (bytes.length > 32768 || written + bytes.length > expected)
            throw new IOException("Invalid file size");
          output.write(bytes);
          written += bytes.length;
          break;
        case "finish":
          requireActive(id);
          if (written != expected) throw new IOException("File transfer was incomplete");
          publish();
          break;
        case "cancel":
          if (id.equals(activeId)) discard();
          break;
        default:
          throw new IOException("Unknown download action");
      }
      reply.put("ok", true);
    } catch (Exception error) {
      try {
        reply.put("error", error.getMessage() == null ? "Could not save file" : error.getMessage());
      } catch (Exception ignored) {
      }
    }
    activity.runOnUiThread(
        () -> {
          try {
            replies.postMessage(new WebMessage(reply.toString()));
          } catch (IllegalStateException closed) {
            /* The client page has closed. */
          }
        });
  }

  private void requireActive(String id) throws IOException {
    if (!id.equals(activeId) || output == null)
      throw new IOException("Download is no longer active");
  }

  private void publish() throws IOException {
    output.close();
    output = null;
    if (pendingUri != null) {
      ContentValues values = new ContentValues();
      values.put(MediaStore.Downloads.IS_PENDING, 0);
      if (activity.getContentResolver().update(pendingUri, values, null, null) != 1)
        throw new IOException("Could not publish file in Downloads");
    } else if (pendingFile != null) {
      MediaScannerConnection.scanFile(activity, new String[] {pendingFile.toString()}, null, null);
    }
    pendingUri = null;
    pendingFile = null;
    activeId = null;
  }

  private void begin(String originalName, String mime) throws IOException {
    String name = originalName.replaceAll("[\\\\/\\p{Cntrl}]", "_").trim();
    if (name.isEmpty() || name.equals(".") || name.equals("..")) name = "download";
    if (name.length() > 180) name = name.substring(0, 180);
    if (!mime.matches("[a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+")) mime = "application/octet-stream";
    if (Build.VERSION.SDK_INT >= 29) {
      ContentValues values = new ContentValues();
      values.put(MediaStore.Downloads.DISPLAY_NAME, name);
      values.put(MediaStore.Downloads.MIME_TYPE, mime);
      values.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/ciXnet");
      values.put(MediaStore.Downloads.IS_PENDING, 1);
      pendingUri =
          activity.getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
      if (pendingUri == null) throw new IOException("Downloads storage is unavailable");
      output = activity.getContentResolver().openOutputStream(pendingUri);
    } else {
      if (activity.checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE)
          != PackageManager.PERMISSION_GRANTED) {
        activity.runOnUiThread(
            () ->
                activity.requestPermissions(
                    new String[] {Manifest.permission.WRITE_EXTERNAL_STORAGE}, 13));
        throw new IOException("Allow storage access, then try saving again");
      }
      File directory =
          new File(
              Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
              "ciXnet");
      if (!directory.isDirectory() && !directory.mkdirs())
        throw new IOException("Could not create Downloads/ciXnet");
      File target = new File(directory, name);
      for (int i = 1; target.exists(); i++) target = new File(directory, i + "-" + name);
      pendingFile = target;
      output = new FileOutputStream(target);
    }
    if (output == null) throw new IOException("Could not open Downloads storage");
  }

  private void discard() {
    try {
      if (output != null) output.close();
    } catch (IOException ignored) {
    }
    output = null;
    if (pendingUri != null) activity.getContentResolver().delete(pendingUri, null, null);
    if (pendingFile != null) pendingFile.delete();
    pendingUri = null;
    pendingFile = null;
    activeId = null;
  }

  void close() {
    if (activeConnection != null) activeConnection.disconnect();
    if (port != null) port.close();
    worker.execute(this::discard);
    worker.shutdown();
  }
}
