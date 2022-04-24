# Plex Downloader
This tool will download specified unseen movies/series from a given [Plex](https://plex.tv/) server. Marks downloaded files as seen to avoid redownload.
Now with resume, progressbar and Bandwidth limit.

Username/Password is stored in ```.netrc``` e.g.:
```
machine plex
  login USERNAME
  password TOPSECRET
```

Install needed python modules:
```commandline
$ pip3 install --user -r requirements.txt
```

see `./downloader.py --help` for usage.
