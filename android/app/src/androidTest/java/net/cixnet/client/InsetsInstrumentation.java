package net.cixnet.client;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.ContentValues;
import android.content.Intent;
import android.database.sqlite.SQLiteDatabase;
import android.graphics.Insets;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.webkit.WebView;
import android.widget.FrameLayout;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONObject;

/** Real-window regression for the startup ordering and Android 15 safe area. */
public final class InsetsInstrumentation extends Instrumentation {
  private Activity target;
  private boolean guideScreenshots;

  @Override
  public void onCreate(Bundle arguments) {
    super.onCreate(arguments);
    guideScreenshots =
        arguments != null && arguments.getString("screenshots", "false").equals("true");
    start();
  }

  @Override
  public void onStart() {
    Bundle report = new Bundle();
    try {
      Activity activity =
          startActivitySync(
              new Intent(getTargetContext(), MainActivity.class)
                  .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
      target = activity;
      AtomicReference<Throwable> failure = new AtomicReference<>();
      AtomicReference<Boolean> ready = new AtomicReference<>(false);
      AtomicReference<WebView> page = new AtomicReference<>();
      for (int attempt = 0; attempt < 120 && !ready.get(); attempt++) {
        SystemClock.sleep(500);
        runOnMainSync(
            () -> {
              try {
                ViewGroup host = activity.findViewById(android.R.id.content);
                FrameLayout root = (FrameLayout) host.getChildAt(0);
                if (!(root.getChildAt(0) instanceof WebView)) return;
                if (!root.isLaidOut()
                    || root.isLayoutRequested()
                    || !root.getChildAt(0).isLaidOut()
                    || root.getChildAt(0).isLayoutRequested()) return;
                WindowInsets window = root.getRootWindowInsets();
                if (window == null) return;
                Insets safe =
                    window.getInsets(
                        WindowInsets.Type.systemBars()
                            | WindowInsets.Type.displayCutout()
                            | WindowInsets.Type.ime());
                if (root.getPaddingTop() != safe.top
                    || root.getPaddingBottom() != safe.bottom
                    || root.getPaddingLeft() != safe.left
                    || root.getPaddingRight() != safe.right)
                  throw new AssertionError("Content padding does not reserve the system safe area");
                View browser = root.getChildAt(0);
                if (browser.getTop() < safe.top
                    || browser.getBottom() > root.getHeight() - safe.bottom)
                  throw new AssertionError("WebView overlaps a system bar");
                page.set((WebView) browser);
                report.putInt("safeTop", safe.top);
                report.putInt("safeBottom", safe.bottom);
                report.putInt("webViewTop", browser.getTop());
                report.putInt("webViewBottom", browser.getBottom());
                ready.set(true);
              } catch (Throwable error) {
                failure.set(error);
                ready.set(true);
              }
            });
      }
      if (failure.get() != null) throw new AssertionError("Layout regression", failure.get());
      if (!ready.get()) throw new AssertionError("Client window did not load");
      if (guideScreenshots) {
        captureGuide(page.get());
        report.putString("result", "PASS: guide screenshots captured from actual demo client UI");
        finish(Activity.RESULT_OK, report);
        return;
      }
      for (int attempt = 0; attempt < 60; attempt++) {
        String selected =
            evaluate(
                page.get(),
                "(() => { const client = document.getElementById('client');if (!client ||"
                    + " client.classList.contains('hidden')) { document.querySelector('#profiles"
                    + " .profile')?.click(); return false; } return true; })()");
        if ("true".equals(selected)) break;
        SystemClock.sleep(500);
      }
      String tabs =
          evaluate(
              page.get(),
              "(() => { document.querySelector('.mobile-tabs [data-tab=browse]').click();return"
                  + " document.querySelector('.mobile-tabs').getBoundingClientRect().height > 0;"
                  + " })()");
      if (!"true".equals(tabs)) throw new AssertionError("Mobile tabs disappeared in Browse");
      String settings =
          evaluate(
              page.get(),
              "(() => { const button = document.getElementById('mobile-settings-open');if"
                  + " (button.getBoundingClientRect().height < 32) return false; button.click();"
                  + " return document.getElementById('settings-dialog').open; })()");
      if (!"true".equals(settings)) throw new AssertionError("Mobile Settings is not accessible");
      sendKeyDownUpSync(KeyEvent.KEYCODE_BACK);
      SystemClock.sleep(500);
      if (!"false".equals(evaluate(page.get(), "document.getElementById('settings-dialog').open")))
        throw new AssertionError("Back did not close Settings");
      if (activity.isFinishing())
        throw new AssertionError("Back closed the client instead of its popup");
      seedSearchFixture();
      evaluate(
          page.get(),
          "document.querySelector('.mobile-tabs"
              + " [data-tab=contacts]').click();document.getElementById('search').value='archived"
              + " rendezvous';document.getElementById('search').dispatchEvent(new Event('input',"
              + " {bubbles:true}));");
      boolean found = false;
      for (int attempt = 0; attempt < 60; attempt++) {
        if ("true"
            .equals(
                evaluate(
                    page.get(),
                    "(() => { const row = document.querySelector('.conversation-item');if (!row ||"
                        + " !row.textContent.includes('archived rendezvous')) return false;"
                        + " row.click(); return true; })()"))) {
          found = true;
          break;
        }
        SystemClock.sleep(500);
      }
      if (!found) throw new AssertionError("Search did not find the older message");
      boolean focused = false;
      for (int attempt = 0; attempt < 60; attempt++) {
        if ("true"
            .equals(
                evaluate(
                    page.get(),
                    "!!document.querySelector('.bubble.search-match')?.textContent.includes('archived"
                        + " rendezvous')"))) {
          focused = true;
          break;
        }
        SystemClock.sleep(500);
      }
      if (!focused) throw new AssertionError("Search result did not open its matching message");
      evaluate(page.get(), "document.getElementById('settings-pairing').click()");
      String pairing =
          evaluate(
              page.get(),
              "(() => { document.getElementById('settings-pairing').click(); const"
                  + " dialog=document.getElementById('pairing-dialog'); const"
                  + " code=document.getElementById('pairing-code');"
                  + " code.value=JSON.stringify({cixnet:1,name:'Test"
                  + " desktop',public:'ab',host:'192.168.50.12',port:4242,destination:'cd'});code.dispatchEvent(new"
                  + " Event('input'));return dialog.open &&"
                  + " !document.getElementById('pairing-approve').disabled &&"
                  + " document.getElementById('pairing-review').textContent.includes('Test"
                  + " desktop') && !!document.querySelector('#pairing-owners input'); })()");
      if (!"true".equals(pairing))
        throw new AssertionError("Phone pairing review or identity selection is unavailable");
      SystemClock.sleep(2000);
      android.graphics.Bitmap screenshot = getUiAutomation().takeScreenshot();
      if (screenshot != null) {
        try (java.io.FileOutputStream image =
            new java.io.FileOutputStream(
                new File(getTargetContext().getFilesDir(), "pairing-dialog.png"))) {
          screenshot.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, image);
        }
        screenshot.recycle();
      }
      evaluate(page.get(), "document.getElementById('pairing-dialog').close()");
      report.putString(
          "result",
          "PASS: safe area, tabs, popup Back, and saved-text search opens the matching message;"
              + " pairing review and identity selection");
      finish(Activity.RESULT_OK, report);
    } catch (Throwable error) {
      report.putString("result", "FAIL: " + error.toString() + " / " + error.getCause());
      finish(Activity.RESULT_CANCELED, report);
    }
  }

  /** Curated screenshots use only disposable emulator data, never real conversations. */
  private void captureGuide(WebView page) throws Exception {
    File directory = new File(getTargetContext().getFilesDir(), "cixnet");
    File profilesFile = new File(directory, "profiles.json");
    JSONObject profiles =
        new JSONObject(
            new String(Files.readAllBytes(profilesFile.toPath()), StandardCharsets.UTF_8));
    JSONObject profile = profiles.getJSONArray("profiles").getJSONObject(0);
    String owner = profile.getString("id");
    profile.put("nickname", "Alex");
    profile.put("display_name", "Alex");
    Files.write(profilesFile.toPath(), profiles.toString().getBytes(StandardCharsets.UTF_8));
    String[] peers = {
      "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "cccccccccccccccccccccccccccccccc"
    };
    String[] names = {"Morgan", "Casey", "River team"};
    String[] text = {
      "The new relay is ready. I’ll send the build notes this evening.",
      "The photo came through clearly. Thanks!",
      "Meet at the workshop at 10 tomorrow?",
      "Yes, see you there.",
      "Testing the local link from the trailhead."
    };
    try (SQLiteDatabase db =
        SQLiteDatabase.openDatabase(
            new File(directory, "messages.sqlite").getAbsolutePath(),
            null,
            SQLiteDatabase.OPEN_READWRITE)) {
      db.delete("outbox", "owner=?", new String[] {owner});
      db.delete("messages", "owner=?", new String[] {owner});
      for (int index = 0; index < peers.length; index++) {
        ContentValues name = new ContentValues();
        name.put("peer", peers[index]);
        name.put("name", names[index]);
        db.insertWithOnConflict("peer_names", null, name, SQLiteDatabase.CONFLICT_REPLACE);
      }
      for (int index = 0; index < text.length; index++) {
        int contact = index < 2 ? 0 : index < 4 ? 1 : 2;
        ContentValues message = new ContentValues();
        message.put("id", "guide-message-" + index);
        message.put("owner", owner);
        message.put("peer", peers[contact]);
        message.put("direction", index == 1 || index == 3 ? "out" : "in");
        message.put("content", text[index]);
        message.put("timestamp", System.currentTimeMillis() / 1000.0 - 60 * (index + 1));
        message.put("status", index == 1 || index == 3 ? "delivered" : "received");
        db.insert("messages", null, message);
      }
    }
    evaluate(page, "location.reload();true");
    SystemClock.sleep(2000);
    for (int attempt = 0; attempt < 60; attempt++) {
      if ("true"
          .equals(
              evaluate(
                  page,
                  "(() => { if(document.getElementById('client')?.classList.contains('hidden'))"
                      + " {document.querySelector('#profiles .profile')?.click();return"
                      + " false;}return !!document.querySelector('.conversation-item');})()")))
        break;
      SystemClock.sleep(500);
    }
    evaluate(
        page,
        "document.querySelector('.mobile-tabs"
            + " [data-tab=contacts]').click();document.getElementById('search').value='';document.getElementById('search').dispatchEvent(new"
            + " Event('input'))");
    saveGuide("01-conversations");
    evaluate(page, "document.querySelector('.conversation-item')?.click()");
    saveGuide("02-conversation");
    evaluate(page, "document.getElementById('settings-pairing').click()");
    saveGuide("03-phone-pairing");
    evaluate(
        page,
        "document.getElementById('pairing-dialog').close();document.getElementById('mobile-settings-open').click()");
    evaluate(page, "document.getElementById('fallback').scrollIntoView({block:'center'})");
    saveGuide("04-automatic-gateway-settings");
    evaluate(page, "document.getElementById('settings-dialog').close()");
  }

  private void saveGuide(String name) throws Exception {
    SystemClock.sleep(2000);
    android.graphics.Bitmap bitmap = getUiAutomation().takeScreenshot();
    if (bitmap == null) throw new AssertionError("Screenshot unavailable");
    File folder = new File(getTargetContext().getFilesDir(), "guide-screenshots");
    folder.mkdirs();
    try (java.io.FileOutputStream output =
        new java.io.FileOutputStream(new File(folder, name + ".png"))) {
      bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, output);
    }
    bitmap.recycle();
  }

  /** Fixture data belongs only to the disposable emulator, never a physical phone. */
  private void seedSearchFixture() throws Exception {
    File directory = new File(getTargetContext().getFilesDir(), "cixnet");
    JSONObject profiles =
        new JSONObject(
            new String(
                Files.readAllBytes(new File(directory, "profiles.json").toPath()),
                StandardCharsets.UTF_8));
    String owner = profiles.getJSONArray("profiles").getJSONObject(0).getString("id");
    try (SQLiteDatabase database =
        SQLiteDatabase.openDatabase(
            new File(directory, "messages.sqlite").getAbsolutePath(),
            null,
            SQLiteDatabase.OPEN_READWRITE)) {
      for (int index = 0; index < 2; index++) {
        ContentValues values = new ContentValues();
        values.put("id", "native-search-" + index);
        values.put("owner", owner);
        values.put("peer", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
        values.put("direction", "in");
        values.put(
            "content", index == 0 ? "archived rendezvous test" : "A newer unrelated message");
        values.put("timestamp", 1 + index);
        values.put("status", "received");
        database.insertWithOnConflict("messages", null, values, SQLiteDatabase.CONFLICT_REPLACE);
      }
    }
  }

  private String evaluate(WebView view, String script) {
    // Receiver startup can replace a stale WebView. Resolve the current view for
    // each attempt rather than retaining a detached renderer across the test.
    for (int retry = 0; retry < 3; retry++) {
      AtomicReference<String> result = new AtomicReference<>();
      runOnMainSync(
          () -> {
            ViewGroup host = target.findViewById(android.R.id.content);
            ViewGroup root = (ViewGroup) host.getChildAt(0);
            if (root.getChildAt(0) instanceof WebView) {
              ((WebView) root.getChildAt(0)).evaluateJavascript(script, result::set);
            }
          });
      for (int attempt = 0; attempt < 100 && result.get() == null; attempt++) SystemClock.sleep(50);
      if (result.get() != null) return result.get();
    }
    throw new AssertionError(
        "WebView script did not finish: " + script.substring(0, Math.min(80, script.length())));
  }
}
