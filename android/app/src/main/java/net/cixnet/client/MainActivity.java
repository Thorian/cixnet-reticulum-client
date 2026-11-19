package net.cixnet.client;

import android.Manifest;
import android.app.Activity;
import android.content.*;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.*;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.webkit.*;
import android.widget.FrameLayout;
import android.widget.TextView;
import android.window.OnBackInvokedDispatcher;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import org.json.JSONObject;

/** Trusted local UI only; remote sites never receive a JavaScript/native bridge. */
public final class MainActivity extends Activity {
  private final Handler handler = new Handler(Looper.getMainLooper());
  private WebView browser;
  private FrameLayout content;
  private String origin;
  private String accessKey;
  private String messageOwner;
  private String messagePeer;
  private ValueCallback<Uri[]> files;
  private PermissionRequest cameraRequest;
  private GeolocationPermissions.Callback locationRequest;
  private String locationOrigin;
  private boolean destroyed;
  private boolean monitoring;

  @Override
  public void onCreate(Bundle state) {
    super.onCreate(state);
    configureContentInsets();
    if (Build.VERSION.SDK_INT >= 33) {
      getOnBackInvokedDispatcher()
          .registerOnBackInvokedCallback(
              OnBackInvokedDispatcher.PRIORITY_DEFAULT, this::handleBack);
    }
    readMessageIntent(getIntent());
    startForegroundService(new Intent(this, ReceiverService.class));
    TextView waiting = new TextView(this);
    waiting.setText("ciXnet · Starting receiver…");
    waiting.setPadding(32, 64, 32, 32);
    showContent(waiting);
    if (Build.VERSION.SDK_INT >= 33
        && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED)
      requestPermissions(new String[] {Manifest.permission.POST_NOTIFICATIONS}, 10);
    awaitReceiver(waiting);
  }

  /** Keep both system bars, display cutouts and the keyboard outside the WebView. */
  private void configureContentInsets() {
    content = new FrameLayout(this);
    content.setBackgroundColor(Color.rgb(12, 19, 16));
    getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
    if (Build.VERSION.SDK_INT >= 30) {
      // Android 15 enforces edge-to-edge; reserve the safe area explicitly.
      getWindow().setDecorFitsSystemWindows(false);
      content.setOnApplyWindowInsetsListener(
          (view, windowInsets) -> {
            android.graphics.Insets safe =
                windowInsets.getInsets(
                    WindowInsets.Type.systemBars()
                        | WindowInsets.Type.displayCutout()
                        | WindowInsets.Type.ime());
            view.setPadding(safe.left, safe.top, safe.right, safe.bottom);
            return WindowInsets.CONSUMED;
          });
    } else {
      content.setFitsSystemWindows(true);
    }
    setContentView(content);
    // The window controller exists only after its decor view has been installed.
    if (Build.VERSION.SDK_INT >= 30) {
      content.post(
          () -> {
            WindowInsetsController controller = getWindow().getInsetsController();
            if (controller != null)
              controller.setSystemBarsAppearance(
                  0,
                  WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS
                      | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS);
          });
    }
    content.requestApplyInsets();
  }

  private void showContent(View view) {
    content.removeAllViews();
    content.addView(
        view,
        new FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
    content.requestApplyInsets();
  }

  private void awaitReceiver(TextView waiting) {
    if (destroyed) return;
    try {
      File error = new File(getFilesDir(), "receiver-error.txt");
      if (error.exists()) {
        waiting.setText(new String(Files.readAllBytes(error.toPath()), StandardCharsets.UTF_8));
        return;
      }
      JSONObject ready =
          new JSONObject(
              new String(
                  Files.readAllBytes(new File(getFilesDir(), "receiver-ready.json").toPath()),
                  StandardCharsets.UTF_8));
      int port = ready.getInt("port");
      String nextKey = ready.getString("accessKey");
      if (!nextKey.matches("[A-Za-z0-9_-]{43}")) throw new IOException("Invalid access key");
      if (port < 1 || port > 65535) throw new IOException("Invalid receiver port");
      accessKey = nextKey;
      origin = "http://127.0.0.1:" + port;
      openClient();
    } catch (Exception notReady) {
      handler.postDelayed(() -> awaitReceiver(waiting), 500);
    }
  }

  private void openClient() {
    browser = new WebView(this);
    WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);
    browser.getSettings().setJavaScriptEnabled(true);
    browser.getSettings().setDomStorageEnabled(true);
    browser.getSettings().setGeolocationEnabled(true);
    browser.getSettings().setAllowFileAccess(false);
    browser.getSettings().setAllowContentAccess(true);
    browser.getSettings().setSupportMultipleWindows(true);
    browser.setWebViewClient(
        new WebViewClient() {
          @Override
          public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            if (!request.isForMainFrame()) return false;
            if (isOwnOrigin(request.getUrl())) return false;
            openExternal(request.getUrl());
            return true;
          }

          @Override
          public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
            // A crashed renderer is replaced without touching the receiver process.
            view.destroy();
            handler.post(MainActivity.this::openClient);
            return true;
          }
        });
    browser.setWebChromeClient(
        new WebChromeClient() {
          @Override
          public boolean onCreateWindow(
              WebView view, boolean dialog, boolean gesture, android.os.Message result) {
            if (!gesture) return false;
            WebView popup = new WebView(MainActivity.this);
            popup.setWebViewClient(
                new WebViewClient() {
                  @Override
                  public boolean shouldOverrideUrlLoading(
                      WebView unused, WebResourceRequest request) {
                    openExternal(request.getUrl());
                    popup.destroy();
                    return true;
                  }
                });
            ((WebView.WebViewTransport) result.obj).setWebView(popup);
            result.sendToTarget();
            return true;
          }

          @Override
          public boolean onShowFileChooser(
              WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
            if (files != null) files.onReceiveValue(null);
            files = callback;
            try {
              startActivityForResult(params.createIntent(), 20);
            } catch (ActivityNotFoundException unavailable) {
              files.onReceiveValue(null);
              files = null;
            }
            return true;
          }

          @Override
          public void onGeolocationPermissionsShowPrompt(
              String requestedOrigin, GeolocationPermissions.Callback callback) {
            // Remote NomadPL frames must never inherit the client's location access.
            if (!isOwnOrigin(Uri.parse(requestedOrigin))) {
              callback.invoke(requestedOrigin, false, false);
              return;
            }
            finishLocationRequest(false);
            locationOrigin = requestedOrigin;
            locationRequest = callback;
            if (hasLocationPermission()) finishLocationRequest(true);
            else
              requestPermissions(
                  new String[] {
                    Manifest.permission.ACCESS_FINE_LOCATION,
                    Manifest.permission.ACCESS_COARSE_LOCATION
                  },
                  12);
          }

          @Override
          public void onGeolocationPermissionsHidePrompt() {
            finishLocationRequest(false);
          }

          @Override
          public void onPermissionRequest(PermissionRequest request) {
            boolean cameraOnly =
                request.getResources().length == 1
                    && PermissionRequest.RESOURCE_VIDEO_CAPTURE.equals(request.getResources()[0]);
            if (!isOwnOrigin(request.getOrigin()) || !cameraOnly) {
              request.deny();
              return;
            }
            if (checkSelfPermission(Manifest.permission.CAMERA)
                == PackageManager.PERMISSION_GRANTED)
              request.grant(new String[] {PermissionRequest.RESOURCE_VIDEO_CAPTURE});
            else {
              if (cameraRequest != null) cameraRequest.deny();
              cameraRequest = request;
              requestPermissions(new String[] {Manifest.permission.CAMERA}, 11);
            }
          }

          @Override
          public void onPermissionRequestCanceled(PermissionRequest request) {
            if (cameraRequest == request) cameraRequest = null;
          }
        });
    showContent(browser);
    browser.loadUrl(clientUrl());
    if (!monitoring) {
      monitoring = true;
      handler.postDelayed(this::monitorReceiver, 2000);
    }
  }

  private void monitorReceiver() {
    if (destroyed) return;
    try {
      JSONObject ready =
          new JSONObject(
              new String(
                  Files.readAllBytes(new File(getFilesDir(), "receiver-ready.json").toPath()),
                  StandardCharsets.UTF_8));
      int port = ready.getInt("port");
      String nextKey = ready.getString("accessKey");
      if (!nextKey.matches("[A-Za-z0-9_-]{43}")) throw new IOException("Invalid access key");
      String next = "http://127.0.0.1:" + port;
      if (port > 0 && port <= 65535 && (!next.equals(origin) || !nextKey.equals(accessKey))) {
        origin = next;
        accessKey = nextKey;
        if (browser != null) browser.destroy();
        openClient();
      }
    } catch (Exception restarting) {
      /* The UI reports core unavailability until the receiver is ready again. */
    }
    handler.postDelayed(this::monitorReceiver, 2000);
  }

  @Override
  protected void onStart() {
    super.onStart();
    startForegroundService(new Intent(this, ReceiverService.class));
  }

  private boolean isOwnOrigin(Uri uri) {
    if (origin == null) return false;
    Uri own = Uri.parse(origin);
    return "http".equals(uri.getScheme())
        && "127.0.0.1".equals(uri.getHost())
        && uri.getPort() == own.getPort();
  }

  private void openExternal(Uri uri) {
    if (!"http".equals(uri.getScheme()) && !"https".equals(uri.getScheme())) return;
    try {
      startActivity(new Intent(Intent.ACTION_VIEW, uri).addCategory(Intent.CATEGORY_BROWSABLE));
    } catch (ActivityNotFoundException unavailable) {
      /* Keep the working client visible if no browser is installed. */
    }
  }

  private void readMessageIntent(Intent intent) {
    messageOwner = intent.getStringExtra("owner");
    messagePeer = intent.getStringExtra("peer");
  }

  private String clientUrl() {
    if (messageOwner != null
        && messagePeer != null
        && messageOwner.matches("[0-9a-f]{32}")
        && messagePeer.matches("[0-9a-f]{32}"))
      return origin + "/#client=" + accessKey + "&message=" + messageOwner + ":" + messagePeer;
    return origin + "/#client=" + accessKey;
  }

  @Override
  protected void onNewIntent(Intent intent) {
    super.onNewIntent(intent);
    setIntent(intent);
    readMessageIntent(intent);
    if (browser != null) browser.loadUrl(clientUrl());
  }

  @Override
  public void onRequestPermissionsResult(int code, String[] permissions, int[] results) {
    super.onRequestPermissionsResult(code, permissions, results);
    if (code == 11 && cameraRequest != null) {
      if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED)
        cameraRequest.grant(new String[] {PermissionRequest.RESOURCE_VIDEO_CAPTURE});
      else cameraRequest.deny();
      cameraRequest = null;
    }
    if (code == 12) finishLocationRequest(hasLocationPermission());
  }

  private boolean hasLocationPermission() {
    return checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)
            == PackageManager.PERMISSION_GRANTED
        || checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION)
            == PackageManager.PERMISSION_GRANTED;
  }

  private void finishLocationRequest(boolean allow) {
    GeolocationPermissions.Callback callback = locationRequest;
    String requestedOrigin = locationOrigin;
    locationRequest = null;
    locationOrigin = null;
    if (callback != null)
      callback.invoke(
          requestedOrigin, allow && !destroyed && isOwnOrigin(Uri.parse(requestedOrigin)), false);
  }

  @Override
  protected void onActivityResult(int request, int result, Intent data) {
    super.onActivityResult(request, result, data);
    if (request == 20 && files != null) {
      files.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result, data));
      files = null;
    }
  }

  /** Close the top popup before navigating or leaving the activity. */
  private void handleBack() {
    if (browser == null) {
      finish();
      return;
    }
    browser.evaluateJavascript(
        "(() => { const dialogs = [...document.querySelectorAll('dialog[open]')];const top ="
            + " dialogs[dialogs.length - 1];if (top) { if (top.dispatchEvent(new Event('cancel',"
            + " {cancelable:true}))) top.close(); return true; }const menu ="
            + " document.getElementById('attachment-menu');if (menu && !menu.hidden) { menu.hidden"
            + " = true;"
            + " document.getElementById('attach-open')?.setAttribute('aria-expanded','false');"
            + " return true; }return false; })()",
        handled -> {
          if (destroyed || "true".equals(handled)) return;
          if (browser.canGoBack()) browser.goBack();
          else finish();
        });
  }

  @Override
  public void onBackPressed() {
    handleBack();
  }

  @Override
  protected void onDestroy() {
    destroyed = true;
    finishLocationRequest(false);
    handler.removeCallbacksAndMessages(null);
    if (cameraRequest != null) cameraRequest.deny();
    if (files != null) files.onReceiveValue(null);
    if (browser != null) browser.destroy();
    super.onDestroy();
  }
}
