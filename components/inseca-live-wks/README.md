Main component to manage a running INSECA system.

# Build configuration attributes

- **userdata-skey-pub-file**: public key used to verify the signature of USERDATA resources,
  relative to the build's config file
- **network-connections-allowed**: boolean indicating if the network stack (managed by NetworkManager) is enabled
  (which allows the user to connect to wired or wireless networks) or disabled
- NOT YET **network-allow-list**: if defined, the network access is denied by default and restricted only to the
  provided list of system names and/or IP address ranges.

# USERDATA attributes

none