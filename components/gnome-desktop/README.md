Base GNOME installation.

# Build configuration attributes

- **display-type**: define the session which will be used: 'x11' or 'wayland'
- **dconf-file**: file which defines the initial UI settings (can be obtained from a running system using `dconf dump /`)
- **desktop-apps**: directory which can contain one or more .desktop files for end user applications (those files will be
  copied to /usr/share/applications, potentially overwriting existing files)

# USERDATA attributes

none

## Proxy PAC handling

To cope with all the weird possible configurations or HTTP proxy servers, the base installation includes a simple HTTP web server (listening on http://127.0.0.1:8088) which can be configured to suit any need:

- by default no proxy will be used (the server returns "DIRECT")
- if a "pac-url" USERDATA value is provided at install time (by the **proxy-pac-url** component):
  - if the URL can be fetched, then the proxy.pac is downloaded from that URL and returned
  - otherwise the server does not answer
- if the `/opt/share/proxy.pac` file exists (installed at build time by the **proxy-pac-file** component), then it
  is downloaded and returned

So, any program needing to find a proxy can be told to use this simple server, at the `http://127.0.0.1:8088/proxy.pac` URL.

NB: the associated inseca-proxy-pac service is not started at boot time because the proxy PAC data (either a file as PRIVDATA or a distant URL as USERDATA) is only available when the device is unlocked.

## References

- https://wiki.debian.org/fr/plymouth