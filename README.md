# Plex Downloader

This tool will download specified unseen movies/series from a given [Plex](https://plex.tv/) server. Marks downloaded files as seen to avoid redownload.

Username/Password is stored in ```.netrc``` e.g.:
```
machine plex
  login USERNAME
  password TOPSECRET
```

Install needed python modules:
```
pip3 install --user -r requirements.txt
```
