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
    def __init__(self, target: str, bw_limit: int, show_progress: bool):
        self.logger = logging.getLogger('download')
        self.target = target
        self.bw_limit = bw_limit
        self.show_progress = show_progress
        self.curl = pycurl.Curl()
        self.progressbar = tqdm(unit='B', unit_scale=True, unit_divisor=1024)
        self.progressbar.clear()

    def process_section(self, section, name: str):
        self.logger.info('processing section %s' % section)
        self.logger.debug('searching for %s' % name)
        try:
            video = section.get(name)
        except NotFound:
            self.logger.error('unable to find: %s' % name)
            sys.exit(os.EX_DATAERR)
        self.logger.debug('Found: %s' % name)
        self.video_episodes(video=video)

    def process_playlist(self, playlist, remove=False):
        self.logger.info('processing playlist %s' % playlist)
        for video in tqdm(playlist.items(), desc='video count', bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}',
                          disable=not self.show_progress):
            self.logger.debug('Video %s from playlist %s' % (video.title, playlist.title))
            video.reload()
            self.logger.debug('viewcount: %s' % video.viewCount)
            if video.viewCount > 0:
                self.logger.info('%s already seen' % video.title)
                continue
            self.video_episodes(video=video)
            if remove:
                logging.info('deleting %s from playlist' % video.title)
                playlist.removeItem(video)

    def video_episodes(self, video):
        if video.type == 'show':
            self.logger.debug('Found Show: %s' % video.title)
            for episode in tqdm(video.episodes(), desc='video count', bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}',
                                disable=not self.show_progress):
                episode.reload()
                self.logger.debug('Found: %s Episode %s %s' % (episode.season().title, episode.index, episode.title))
                self.logger.debug('view count: %s' % episode.viewCount)
                if episode.viewCount > 0:
                    self.logger.info('%s Episode %s already seen' % (episode.season().title, episode.index))
                    continue
                self.download(video=episode)
                self.logger.info('marking %s as watched' % episode.title)
                episode.markWatched()
        else:
            self.logger.info('Found: %s' % video.title)
            self.download(video=video)
            self.logger.info('marking %s as watched' % video.title)
            video.markWatched()

    def curl_progress(self, download_total, downloaded, upload_total, uploaded):
        self.progressbar.total = download_total
        self.progressbar.n = downloaded
        self.progressbar.update()

    def download(self, video):
        self.logger.debug('downloading %s' % video)
        for part in video.iterParts():
            self.logger.debug('Found: %s %s' % (part.id, part.file))
            self.logger.info('mkdir: %s' % os.path.dirname(os.path.abspath(self.target + part.file)))
            path = os.path.dirname(os.path.abspath(self.target + part.file))
            filename = os.path.basename(os.path.abspath(self.target + part.file))
            try:
                os.makedirs(path)
            except FileExistsError:
                pass
            except Exception as e:
                self.logger.fatal('Unexpected error: %s' % repr(e))
                sys.exit(os.EX_CANTCREAT)
            url = video._server.url('%s?download=1&X-Plex-Token=%s' % (part.key, video._server._token))
            self.logger.info('downloading %s to %s' % (url, path + "/." + filename))
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
                self.progressbar.set_description(desc='Downloading %s' % video.title)
                self.progressbar.reset()
                self.curl.setopt(self.curl.NOPROGRESS, 0)
                self.curl.setopt(self.curl.XFERINFOFUNCTION, self.curl_progress)
            else:
                self.curl.setopt(self.curl.NOPROGRESS, 1)
            self.curl.perform()
            self.progressbar.clear()
            self.logger.info('renaming %s to %s' % (path + "/." + filename, path + "/" + filename))
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

    logger.info('connecting to %s' % args.server)
    plex = user.resource(args.server).connect()
    pd = PlexDownloader(target=args.target, bw_limit=args.bwlimit, show_progress=args.progress)
    if args.section:
        logger.info('selecting section %s' % args.section)
        try:
            section = plex.library.section(args.section)
        except NotFound:
            logger.error('section %s not found' % args.section)
            sys.exit(os.EX_DATAERR)
        pd.process_section(section=section, name=args.name)
    elif args.playlist:
        logger.info('selecting playlist %s' % args.playlist)
        try:
            playlist = plex.playlist(args.playlist)
        except NotFound:
            logger.error('playlist %s not found' % args.playlist)
            sys.exit(os.EX_DATAERR)
        pd.process_playlist(playlist=playlist, remove=args.playlist_remove)
