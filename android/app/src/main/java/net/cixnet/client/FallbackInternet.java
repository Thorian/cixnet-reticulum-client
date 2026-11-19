package net.cixnet.client;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.NetworkRequest;

/** Keep LAN Wi-Fi intact while requesting cellular only for a needed fallback. */
public final class FallbackInternet {
  private final ConnectivityManager manager;
  private volatile Network cellular;
  private ConnectivityManager.NetworkCallback callback;
  private volatile String state = "offline";

  public FallbackInternet(Context context) {
    manager = context.getSystemService(ConnectivityManager.class);
  }

  public synchronized String prepare(boolean needed) {
    if (!needed) {
      release();
      return state = "idle";
    }
    Network current = manager.getActiveNetwork();
    NetworkCapabilities caps = current == null ? null : manager.getNetworkCapabilities(current);
    // A VPN remains authoritative. Do not silently bypass it with cellular.
    if (caps != null && caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) {
      release();
      return state =
          caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
              ? "default:" + current.getNetworkHandle()
              : "vpn_waiting";
    }
    if (caps != null && caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)) {
      release();
      return state = "default:" + current.getNetworkHandle();
    }
    if (callback == null) {
      callback =
          new ConnectivityManager.NetworkCallback() {
            @Override
            public void onCapabilitiesChanged(Network network, NetworkCapabilities capabilities) {
              if (capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED))
                cellular = network;
            }

            @Override
            public void onLost(Network network) {
              if (network.equals(cellular)) cellular = null;
            }

            @Override
            public void onUnavailable() {
              cellular = null;
            }
          };
      try {
        manager.requestNetwork(
            new NetworkRequest.Builder()
                .addTransportType(NetworkCapabilities.TRANSPORT_CELLULAR)
                .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                .build(),
            callback);
      } catch (SecurityException error) {
        callback = null;
        return state = "offline";
      }
    }
    Network network = cellular;
    return state = network == null ? "waiting" : "cellular:" + network.getNetworkHandle();
  }

  public Network cellularNetwork() {
    return state.startsWith("cellular:") ? cellular : null;
  }

  public synchronized void release() {
    if (callback != null) {
      try {
        manager.unregisterNetworkCallback(callback);
      } catch (IllegalArgumentException ignored) {
      }
      callback = null;
    }
    cellular = null;
  }
}
