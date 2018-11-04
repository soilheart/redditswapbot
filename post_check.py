#!/usr/bin/env python2
""" New post checker """

import sys
import re
import sqlite3
import unicodedata
import json
from datetime import datetime
from time import sleep

from log_conf import LoggerManager
from common import SubRedditMod


# configure logging
LOGGER = LoggerManager().getLogger("post_check")


class PostChecker(object):

    def __init__(self, config, db_con, post_categories, locations):
        self._config = config
        self._user_db_con = db_con
        self._user_db_cursor = self._user_db_con.cursor()
        self._post_categories = post_categories
        self._locations = locations

    def _get_user_db_entry(self, post):
        self._user_db_cursor.execute('SELECT username, last_id, last_created as "last_created [timestamp]" '
                               'FROM user WHERE username=?', (post.author.name,))

        return self._user_db_cursor.fetchone()

    def _update_user_db(self, post):
        post_created = datetime.utcfromtimestamp(post.created_utc)
        self._user_db_cursor.execute('UPDATE OR IGNORE user SET last_created=?, last_id=? WHERE username=?',
                               (post_created, post.id, post.author.name))

    def _add_to_user_db(self, post):
        post_created = datetime.utcfromtimestamp(post.created_utc)
        self._user_db_cursor.execute('INSERT OR IGNORE INTO user (username, last_created, last_id) VALUES (?, ?, ?)',
                               (post.author.name, post_created, post.id))

    def _is_personal_post(self, title):
        return bool(re.search(self._config["trade_post_format"], title))

    def _is_nonpersonal_post(self, title):
        return bool(re.search(self._config["informational_post_format"], title))

    def check_and_flair_personal_post(self, post, clean_title):

        location, have, want = re.search(self._config["trade_post_format"], clean_title).groups()

        if "-" in location:
            primary, secondary = location.split("-")
        else:
            primary = "OTHER"
            secondary = location

        if primary not in self._locations:
            print(primary, " not in ", self._locations)
            return False

        if secondary not in self._locations[primary]:
            print(secondary, " not in ", primary)
            return False

        timestamp_check = False
        flair_class = self._config["default_flair_class"]
        for category in self._post_categories["personal"]:
            if "want" in category:
                assert "have" not in category, "Limitation of script"
                regex = category["want"].replace("\\\\", "\\")
                if re.search(regex, want, re.IGNORECASE):
                    print(want, "matches", category["name"])
                    flair_class = category["class"]
                    timestamp_check = category["timestamp_check"]
            if "have" in category:
                assert "want" not in category, "Limitation of script"
                regex = category["have"].replace("\\\\", "\\")
                if re.search(regex, have, re.IGNORECASE):
                    print(have, "matches", category["name"])
                    flair_class = category["class"]
                    timestamp_check = category["timestamp_check"]
        print(clean_title, " flaired as ", flair_class)

        self.check_repost(post)

        if timestamp_check:
            print("Checking for timestamps")
            if not re.search(self._config["timestamp_regex"], post.selftext, re.IGNORECASE):
                post.report("Could not find timestamp...")

        return True

    def check_and_flair_nonpersonal_post(self, post, clean_title):
        tag = re.search(self._config["informational_post_format"], clean_title).group(1)

        for category in self._post_categories["nonpersonal"]:
            if tag == category["tag"]:
                print(tag, " matches ", category["name"])
                if "required_flair" in category:
                    if category["required_flair"] != post.author_flair_css_class:
                        print("User not having the expected flair ", category["required_flair"])
                        return False
                return True
        else:
            print("Bad tag ", tag)
            return False

    def check_post(self, post):
        """
        Check post for rule violations
        """

        clean_title = unicodedata.normalize('NFKD', post.title).encode('ascii', 'ignore')

        print("#"*20 + clean_title)

        if self._is_personal_post(clean_title):
            if "trade_post_format_strict" in self._config:
                if not bool(re.match(self._config["trade_post_format_strict"], clean_title)):
                    print("!*80")
                    print(clean_title, " failed strict check")
                    return

            if not self.check_and_flair_personal_post(post, clean_title):
                print("!*80")
                return

        elif self._is_nonpersonal_post(clean_title):
            # TODO: Add strict format check (not necessary at the moment)

            if not self.check_and_flair_nonpersonal_post(post, clean_title):
                print("!*80")
                return

        else:
            print(clean_title, " did not match any format")
            print("!*80")
            return


        print("Post looks fine! Commenting")

    def check_repost(self, post):
        """
        Check post for repost rule violations
        """

        db_row = self._get_user_db_entry(post)
        if db_row is not None:
            last_id = db_row["last_id"]
            last_created = db_row["last_created"]
            if post.id != last_id:
                LOGGER.info("Checking post {} for repost violation".format(post.id))
                post_created = datetime.utcfromtimestamp(post.created_utc)
                seconds_between_posts = (post_created - last_created).total_seconds()
                if (seconds_between_posts < int(self._config["upper_hour"]) * 3600 and
                    seconds_between_posts > int(self._config["lower_min"]) * 60):
                    LOGGER.info("Reported because seconds between posts: {}".format(seconds_between_posts))
                    post.report("Possible repost: https://redd.it/{}".format(last_id))
                    return
            self._update_user_db(post)
        else:
            self._add_to_user_db(post)

        self._user_db_con.commit()


def main():
    """ Main function, setups stuff and checks posts"""

    try:
        # Setup SubRedditMod
        subreddit = SubRedditMod(LOGGER)
        with open("submission_categories.json") as category_file:
            post_categories = json.load(category_file)
        with open("locations.json") as locations_file:
            locations = json.load(locations_file)

        # Setup PostChecker
        user_db = subreddit.config["trade"]["user_db"]
        db_con = sqlite3.connect(user_db, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
        db_con.row_factory = sqlite3.Row
        post_checker = PostChecker(subreddit.config["post_check"], db_con, post_categories, locations)
    except Exception as e:
        LOGGER.error(e)
        sys.exit()

    while True:
        try:
            first_pass = True
            processed = []
            while True:
                new_posts = subreddit.get_new(20)
                for post in new_posts:
                    if first_pass and subreddit.check_mod_reply(post):
                        processed.append(post.id)
                    if post.id in processed:
                        continue
                    post_checker.check_post(post)
                    processed.append(post.id)
                first_pass = False
                LOGGER.debug('Sleeping for 5 minutes')
                sleep(360)
        except Exception as e:
            LOGGER.error(e)
            sleep(360)


if __name__ == '__main__':
    main()
