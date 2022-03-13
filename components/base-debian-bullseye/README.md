Base installation.

# Build configuration attributes

none

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