#!/usr/bin/env python2
""" New post checker """

import sys
import re
import sqlite3
import unicodedata
from datetime import datetime
from time import sleep

from log_conf import LoggerManager
from common import SubRedditMod


# configure logging
LOGGER = LoggerManager().getLogger("post_check")


PERSONAL_RE = re.compile(r"^\[[A-Z]{2}-?[A-Z]{,2}\] ?\[H\].*\[W\].*")


def check_post(post, config, db_cursor):
    """
    Check post for rule violations
    Currently only checks repost violations
    """

    db_cursor.execute(
        '''SELECT username, last_id, last_created as "last_created [timestamp]" FROM user WHERE username=?''',
        (post.author.name,))
    db_row = db_cursor.fetchone()

    post_created = datetime.utcfromtimestamp(post.created_utc)

    if db_row is not None:
        last_id = db_row["last_id"]
        last_created = db_row["last_created"]
        if post.id != last_id:
            LOGGER.info("Checking post {} for repost violation".format(post.id))
            seconds_between_posts = (post_created - last_created).total_seconds()
            if seconds_between_posts < config["upper_hour"] * 3600:
                LOGGER.info("Reported because time between posts: {}".format(post_created - last_created))
                LOGGER.info("Last created {}".format(last_created))
                LOGGER.info("Post created {}".format(post_created))
                post.report("Possible repost: https://redd.it/{}".format(last_id))
        db_cursor.execute('''UPDATE OR IGNORE user SET last_created=?, last_id=? WHERE username=?''',
                          (post_created, post.id, post.author.name, ))
    else:
        db_cursor.execute('''INSERT OR IGNORE INTO user (username, last_created, last_id) VALUES (?, ?, ?)''',
                          (post.author.name, post_created, post.id, ))


def main():
    """ Main function, setups stuff and checks posts"""

    try:
        subreddit = SubRedditMod(LOGGER)

        user_db = subreddit.config["trade"]["user_db"]
        db_conn = sqlite3.connect(user_db, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
        db_conn.row_factory = sqlite3.Row
        db_cursor = db_conn.cursor()
    except Exception as e:
        LOGGER.error(e)
        sys.exit()

    while True:
        try:
            already_done = []
            while True:
                new_posts = subreddit.get_new(20)
                for post in new_posts:
                    clean_title = unicodedata.normalize('NFKD', post.title).encode('ascii', 'ignore')
                    if post.id in already_done:
                        continue
                    if not subreddit.check_mod_reply(post):
                        # Only check posts which the old script (or another mod) have already handled
                        continue
                    if not PERSONAL_RE.match(clean_title):
                        # Only check personal posts for now
                        continue
                    check_post(post, subreddit.config["post_check"], db_cursor)
                    db_conn.commit()
                    already_done.append(post.id)
                LOGGER.debug('Sleeping for 5 minutes')
                sleep(360)
        except Exception as e:
            LOGGER.error(e)
            sleep(360)


if __name__ == '__main__':
    main()
