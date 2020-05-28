#!/usr/bin/env python3

import argparse
import logging
import netrc
import os
import sys

import pycurl
from plexapi.exceptions import NotFound
from plexapi.myplex import MyPlexAccount
from tqdm import tqdm


class PlexDownloader:
    def __init__(self, target: str, bw_limit: int, show_progress: bool, assets: bool, force: bool):
        self.logger = logging.getLogger('download')
        self.target = target
        self.bw_limit = bw_limit
        self.show_progress = show_progress
        self.assets = assets
        self.force = force
        self.curl = pycurl.Curl()
        self.progressbar = tqdm(unit='B', unit_scale=True, unit_divisor=1024)
        self.progressbar.clear()

    def process_section(self, section, name: str):
        self.logger.info(f'processing section {section}')
        self.logger.debug(f'searching for {name}')
        try:
            video = section.get(name)
        except NotFound:
            self.logger.error(f'unable to find: {name}')
            sys.exit(os.EX_DATAERR)
        self.logger.debug(f'Found: {name}')
        self.video_episodes(video=video)

    def process_playlist(self, playlist, remove=False):
        self.logger.info(f'processing playlist {playlist}')
        for video in tqdm(playlist.items(), desc='video count', bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}',
                          disable=not self.show_progress):
            self.logger.debug(f'Video {video.title} from playlist {playlist.title}')
            video.reload()
            self.logger.debug(f'viewcount: {video.viewCount}')
            if video.viewCount > 0 and not self.force:
                self.logger.info(f'{video.title} already seen')
                continue
            self.video_episodes(video=video)
            if remove:
                logging.info(f'deleting {video.title} from playlist')
                playlist.removeItem(video)

    def video_episodes(self, video):
        if video.type == 'show':
            self.logger.debug(f'Found Show: {video.title}')
            for episode in tqdm(video.episodes(), desc='video count', bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}',
                                disable=not self.show_progress):
                episode.reload()
                self.logger.debug(f'Found: {episode.season().title} Episode {episode.index} {episode.title}')
                self.logger.debug(f'view count: {episode.viewCount}')
                if episode.viewCount > 0 and not self.force:
                    self.logger.info(f'{episode.season().title} Episode {episode.index} already seen')
                    continue
                self.video_parts(video=episode)
                self.logger.info(f'marking {episode.title} as watched')
                episode.markWatched()
        else:
            self.logger.info(f'Found: {video.title}')
            self.video_parts(video=video)
            self.logger.info(f'marking {video.title} as watched')
            video.markWatched()

    def curl_progress(self, download_total, downloaded, upload_total, uploaded):
        self.progressbar.total = download_total
        self.progressbar.n = downloaded
        self.progressbar.update()

    def video_parts(self, video):
        self.logger.debug(f'finding parts for {video}')
        for part in video.iterParts():
            self.logger.debug(f'Found: {part.id} {part.file}')
            self.logger.info(f'mkdir: {os.path.dirname(os.path.abspath(self.target + part.file))}')
            path = os.path.dirname(os.path.abspath(self.target + part.file))
            filename = os.path.basename(os.path.abspath(self.target + part.file))
            url = video._server.url(f'{part.key}?download=1&X-Plex-Token={video._server._token}')
            self.logger.info(f'downloading {url} to {path + "/." + filename}')
            self.download(url=url, path=path, filename=filename, title=video.title)
            if self.assets:
                self.download_subtitles(video=part, path=path, filename=filename)
                self.download_pics(video=video, path=path, filename=filename)

    def download_subtitles(self, video, path, filename):
        self.logger.debug(f'downloading subtitles for {video}')
        for sub in video.subtitleStreams():
            self.logger.debug(f'Found subtitle {sub}')
            if sub.key is None:
                self.logger.debug('Subtitle is embedded, skipping')
                continue
            filename = f'{".".join(filename.split(".")[0:-1])}.{sub.languageCode}.{sub.codec}'
            url = video._server.url(f'{sub.key}?download=1&X-Plex-Token={video._server._token}')
            self.download(url=url, path=path, filename=filename, title=f'{sub.languageCode} {sub.codec}')

    def download_pics(self, video, path, filename):
        self.logger.debug(f'downloading pics for {video}')
        artfilename = f'{".".join(filename.split(".")[0:-1])}-{"fanart"}.{"jpg"}'
        self.download(url=video.artUrl, path=path, filename=artfilename, title='thumbnail')
        thumbfilename = f'{".".join(filename.split(".")[0:-1])}.{"jpg"}'
        self.download(url=video.thumbUrl, path=path, filename=thumbfilename, title='art')

    def download(self, url, path, filename, title):
        self.logger.debug(f'downloading {url} {path} {filename} {title}')
        try:
            os.makedirs(path)
        except FileExistsError:
            pass
        except Exception as e:
            self.logger.fatal(f'Unexpected error: {repr(e)}')
            sys.exit(os.EX_CANTCREAT)
        self.curl.setopt(self.curl.URL, url)
        if self.bw_limit:
            self.curl.setopt(self.curl.MAX_RECV_SPEED_LARGE, self.bw_limit)
        if os.path.exists(path + "/." + filename):
            file_id = open(path + "/." + filename, "ab")
            self.curl.setopt(self.curl.RESUME_FROM, os.path.getsize(path + "/." + filename))
        else:
            file_id = open(path + "/." + filename, "wb")

        self.curl.setopt(self.curl.WRITEDATA, file_id)
        if self.show_progress:
            self.progressbar.set_description(desc=f'Downloading {title}')
            self.progressbar.reset()
            self.curl.setopt(self.curl.NOPROGRESS, 0)
            self.curl.setopt(self.curl.XFERINFOFUNCTION, self.curl_progress)
        else:
            self.curl.setopt(self.curl.NOPROGRESS, 1)
        self.curl.perform()
        self.progressbar.clear()
        self.logger.info(f'renaming {path + "/." + filename} to {path + "/" + filename}')
        os.rename(path + "/." + filename, path + "/" + filename)


if __name__ == "__main__":
    logger = logging.getLogger('download')
    log_handler = logging.StreamHandler()
    log_handler.setFormatter(logging.Formatter('%(asctime)s %(filename)-18s %(levelname)-8s: %(message)s'))
    logger.addHandler(log_handler)

    authentication = netrc.netrc().authenticators('plex')
    if authentication is None:
        logger.error("can't find machine 'plex' in your ~/.netrc")
        sys.exit(os.EX_NOTFOUND)
    user = MyPlexAccount(authentication[0], authentication[2])

    parser = argparse.ArgumentParser()
    group1 = parser.add_mutually_exclusive_group()
    group1.add_argument("-d", "--debug", action="store_true")
    group1.add_argument("-v", "--verbose", action="store_true")
    group1.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument("--server", help="Plex server name to fetch files from", required=True,
                        choices=[x.name for x in user.resources() if x.provides == 'server'])
    parser.add_argument("--target", help="destination folder", required=True)
    parser.add_argument("--section", help="section to fetch")
    parser.add_argument("--name", help="movie or series to fetch")
    parser.add_argument("--bwlimit", help="limit bandwidth in bytes/s", type=int)
    parser.add_argument("--progress", help="show download progress", action="store_true")
    parser.add_argument("--force", help="force download, even if already seen", action="store_true")
    parser.add_argument("--assets", help="also download other assets (subtitles, cover and fanart)", action="store_true")
    group2 = parser.add_argument_group()
    group2.add_argument("--playlist", help="playlist to fetch")
    group2.add_argument("--playlist-remove", action="store_true", help="cleanup playlist after downloading")
    args = parser.parse_args()

    if not (args.playlist or args.section) or (args.playlist and args.section):
        parser.error('either --section or --playlist required')
    elif args.name and not args.section:
        parser.error('--name specified without --section')
    if args.debug:
        loglevel = logging.DEBUG
    elif args.verbose:
        loglevel = logging.INFO
    elif args.quiet:
        loglevel = logging.ERROR
    else:
        loglevel = logging.WARNING
    logger.setLevel(loglevel)

    logger.info(f'connecting to {args.server}')
    plex = user.resource(args.server).connect()
    pd = PlexDownloader(target=args.target, bw_limit=args.bwlimit, show_progress=args.progress, assets=args.assets, force=args.force)
    if args.section:
        logger.info(f'selecting section {args.section}')
        try:
            section = plex.library.section(args.section)
        except NotFound:
            logger.error(f'section {args.section} not found')
            sys.exit(os.EX_DATAERR)
        pd.process_section(section=section, name=args.name)
    elif args.playlist:
        logger.info(f'selecting playlist {args.playlist}')
        try:
            playlist = plex.playlist(args.playlist)
        except NotFound:
            logger.error(f'playlist {args.playlist} not found')
            sys.exit(os.EX_DATAERR)
        pd.process_playlist(playlist=playlist, remove=args.playlist_remove)
