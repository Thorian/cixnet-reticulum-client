package net.cixnet.client;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.os.SystemClock;
import android.provider.MediaStore;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONObject;

/** Exercise the real WebView port, public Downloads storage and HTTP fallback. */
public final class DownloadsInstrumentation extends Instrumentation {
  private Uri saved;
  private DownloadStore store;

  @Override
  public void onCreate(Bundle arguments) {
    super.onCreate(arguments);
    start();
  }

  @Override
  public void onStart() {
    Bundle result = new Bundle();
    try {
      Activity activity =
          startActivitySync(
              new Intent(getTargetContext(), MainActivity.class)
                  .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
      java.io.File ready =
          new java.io.File(getTargetContext().getFilesDir(), "receiver-ready.json");
      for (int i = 0; i < 120 && !ready.exists(); i++) SystemClock.sleep(500);
      JSONObject receiver =
          new JSONObject(new String(Files.readAllBytes(ready.toPath()), StandardCharsets.UTF_8));
      String origin = "http://127.0.0.1:" + receiver.getInt("port");
      String name = "cixnet-download-test-" + System.currentTimeMillis() + ".bin";
      AtomicReference<WebView> view = new AtomicReference<>();
      AtomicReference<String> state = new AtomicReference<>("");
      runOnMainSync(
          () -> {
            WebView page = new WebView(activity);
            page.getSettings().setJavaScriptEnabled(true);
            view.set(page);
            store = new DownloadStore(activity);
            page.setWebViewClient(
                new WebViewClient() {
                  @Override
                  public void onPageFinished(WebView web, String url) {
                    store.attach(web, origin);
                  }
                });
            activity.setContentView(page);
            String html =
                "<div id='toast'></div><script type='module'>import {initDownloads,saveBlob} from"
                    + " '/downloads.js';initDownloads();setTimeout(async()=>{try{await saveBlob(new"
                    + " Blob([Uint8Array.from({length:70000},(_,i)=>i%251)]),"
                    + JSONObject.quote(name)
                    + ");document.body.dataset.test='saved'}catch(e){document.body.dataset.test='error:'+e.message}},1000)</script>";
            page.loadDataWithBaseURL(origin + "/", html, "text/html", "utf-8", null);
          });
      for (int i = 0; i < 180 && !state.get().equals("\"saved\""); i++) {
        SystemClock.sleep(500);
        runOnMainSync(
            () -> view.get().evaluateJavascript("document.body.dataset.test||''", state::set));
        if (state.get().contains("error:")) throw new AssertionError(state.get());
      }
      if (!state.get().equals("\"saved\""))
        throw new AssertionError("WebView save timed out: " + state.get());
      byte[] expected = new byte[70000];
      for (int i = 0; i < expected.length; i++) expected[i] = (byte) (i % 251);
      verifyFile(name, expected);
      result.putString("webViewSave", "70000 bytes published in Downloads/ciXnet");
      getTargetContext().getContentResolver().delete(saved, null, null);
      saved = null;

      try (ServerSocket server =
          new ServerSocket(0, 1, java.net.InetAddress.getByName("127.0.0.1"))) {
        String host =
            "a".repeat(32)
                + "."
                + "b".repeat(32)
                + "."
                + "c".repeat(32)
                + ".localhost:"
                + server.getLocalPort();
        AtomicReference<Throwable> failure = new AtomicReference<>();
        Thread sender =
            new Thread(
                () -> {
                  try (Socket socket = server.accept()) {
                    BufferedReader input =
                        new BufferedReader(
                            new InputStreamReader(
                                socket.getInputStream(), StandardCharsets.US_ASCII));
                    String line;
                    boolean correctHost = false;
                    while ((line = input.readLine()) != null && !line.isEmpty())
                      if (line.equalsIgnoreCase("Host: " + host)) correctHost = true;
                    if (!correctHost) throw new AssertionError("Canonical Host header was lost");
                    socket
                        .getOutputStream()
                        .write(
                            "HTTP/1.1 200 OK\r\nContent-Length: 3\r\nConnection: close\r\n\r\nabc"
                                .getBytes(StandardCharsets.US_ASCII));
                  } catch (Throwable error) {
                    failure.set(error);
                  }
                });
        sender.start();
        String httpName = name + ".http";
        runOnMainSync(
            () -> store.download("http://" + host + "/file", httpName, "application/octet-stream"));
        for (int i = 0; i < 60; i++) {
          SystemClock.sleep(500);
          try {
            verifyFile(httpName, new byte[] {97, 98, 99});
            break;
          } catch (AssertionError notReady) {
            if (i == 59) throw notReady;
          }
        }
        sender.join(2000);
        if (failure.get() != null) throw new AssertionError(failure.get());
        result.putString("httpSave", "Loopback file published with canonical Host header");
      }
      result.putString("result", "PASS");
      finish(Activity.RESULT_OK, result);
    } catch (Throwable error) {
      result.putString("result", "FAIL: " + error);
      finish(Activity.RESULT_CANCELED, result);
    } finally {
      if (saved != null) getTargetContext().getContentResolver().delete(saved, null, null);
      if (store != null) runOnMainSync(store::close);
    }
  }

  private void verifyFile(String name, byte[] expected) throws Exception {
    try (Cursor cursor =
        getTargetContext()
            .getContentResolver()
            .query(
                MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                new String[] {"_id", "relative_path", "is_pending"},
                "_display_name=?",
                new String[] {name},
                null)) {
      if (cursor == null || !cursor.moveToFirst())
        throw new AssertionError("Download is not visible");
      if (!cursor.getString(1).equals("Download/ciXnet/") || cursor.getInt(2) != 0)
        throw new AssertionError("Download is not published in the public folder");
      saved = Uri.withAppendedPath(MediaStore.Downloads.EXTERNAL_CONTENT_URI, cursor.getString(0));
    }
    try (java.io.InputStream input =
        getTargetContext().getContentResolver().openInputStream(saved)) {
      if (!Arrays.equals(expected, input.readAllBytes()))
        throw new AssertionError("Saved file differs from transferred bytes");
    }
  }
}
