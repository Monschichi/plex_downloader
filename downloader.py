#!/usr/bin/env python3

from plexapi.myplex import MyPlexAccount
import netrc
import argparse
import logging
import os
import urllib3
import certifi
import shutil

http = urllib3.PoolManager(cert_reqs='CERT_REQUIRED', ca_certs=certifi.where())

def process_section(section, target, name, plex):
    logger = logging.getLogger('download')
    logger.info('processing section %s' % section)
    logger.debug('searching for %s' % name)
    try:
        video = section.get(name)
    except:
        logger.error('unable to find: %s' % name)
        os._exit(os.EX_DATAERR)
    logger.debug('Found: %s' % name)
    video_episodes(video, target, plex)

def video_episodes(video, target, plex):
    logger = logging.getLogger('download')
    if video.type == 'show':
        logger.debug('Found: %s' % video.title)
        for episode in video.episodes():
            episode.reload()
            logger.debug('Found: %s episode %s %s' % (episode.season().title, episode.index, episode.title))
            logger.debug('viewcount: %s' % episode.viewCount)
            if episode.viewCount > 0:
                logger.info('%s %s already seen' % (episode.season().title, episode.index))
                continue
            for part in episode.iterParts():
                logger.debug('Found: %s %s' % (part.id, part.file))
                download(part, target, plex)
            logger.info('marking %s as watched' % episode.title)
            episode.markWatched()
    else:
        logger.info('Found: %s' % video.title)
        for part in video.iterParts():
            logger.debug('Found: %s %s' % (part.id, part.file))
            download(part, target, plex)
        logger.info('marking %s as watched' % video.title)
        video.markWatched()

def download(part, target, plex):
    logger = logging.getLogger('download')
    logger.info('mkdir: %s' % os.path.dirname(os.path.abspath(target + part.file)))
    path = os.path.dirname(os.path.abspath(target + part.file))
    filename = os.path.basename(os.path.abspath(target + part.file))
    try:
        os.makedirs(path)
    except FileExistsError:
        pass
    except:
        logger.fatal('Unexpected error: %s' % sys.exc_info()[0])
        os._exit(os.EX_CANTCREAT)
    url = plex.url('/library/parts/' + str(part.id) + '/file.mkv')
    logger.info('downloading %s to %s' % (url, path + "/." + filename))
    with http.request('GET', url, preload_content=False) as r, open(path + "/." + filename, 'wb') as out_file:
        shutil.copyfileobj(r, out_file)
    logger.info('renaming %s to %s' % (path + "/." + filename, path + "/" + filename))
    os.rename(path + "/." + filename, path + "/" + filename)

def main():
    logformat = '%(asctime)s %(filename)-18s %(levelname)-8s: %(message)s'
    logger = logging.getLogger('download')
    loghandler = logging.StreamHandler()
    loghandler.setFormatter(logging.Formatter(logformat))
    logger.addHandler(loghandler)
    authentication = netrc.netrc().authenticators('plex')
    if authentication is None:
        logger.error("can't find Machine 'plex' in your ~/.netrc")
    else:
        user = MyPlexAccount(authentication[0], authentication[2])

        parser = argparse.ArgumentParser()
        group1 = parser.add_mutually_exclusive_group()
        group1.add_argument("-d", "--debug", action = "store_true")
        group1.add_argument("-v", "--verbose", action = "store_true")
        group1.add_argument("-q", "--quiet", action = "store_true")
        parser.add_argument("--server", help = "Plex server name to fetch files from", required = True, choices = [x.name for x in user.resources() if x.provides == 'server'])
        parser.add_argument("--target", help = "destination folder", required = True)
        parser.add_argument("--section", help = "section to fetch", required = True)
        parser.add_argument("--name", help = "movie or serie to fetch", required = True)
        args = parser.parse_args()

        if args.name and not args.section:
            parser.error('--name specified without --section')
        if args.debug:
            loglevel=logging.DEBUG
        elif args.verbose:
            loglevel=logging.INFO
        elif args.quiet:
            loglevel=logging.ERROR
        else:
            loglevel=logging.WARNING
        logger.setLevel(loglevel)

        logger.info('connecting to %s' % args.server)
        plex = user.resource(args.server).connect()
        logger.info('selecting section %s' % args.section)
        try:
            section = plex.library.section(args.section)
        except:
            logger.error('section %s not found' % args.section)
            os._exit(os.EX_DATAERR)
        process_section(section, args.target, args.name, plex)

if __name__ == "__main__":
    main()
