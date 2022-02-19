Defines a set of private/public keys used to sign live builds:
- the public key is added to the live build image (in the /opt/share/build-sign-key.pub file),
  and it is used to verify the signature of any new live build before applying the update
- the private key is used to sign a live build image when it is added to the build repository

# Build configuration attributes

- **build-skey-pub-file**: public key file name, relative to the configuration file itself
- **build-skey-priv-file**: private key file name, relative to the configuration file itself

# USERDATA attributes

none