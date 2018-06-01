# Common stuff
import sys, os

import praw
from ConfigParser import SafeConfigParser


class DictConfigParser(SafeConfigParser):
    # SafeConfigParser with a getitem returning a dict for that section

    def __getitem__(self, key):
        """ Get section as a dictionary """
        if key not in self.sections():
            raise KeyError, "No section named %s" % key
        else:
            config_dict = {}
            for option, _ in self.items(key):
                try:
                    value = self.getboolean(key, option)
                except ValueError:
                    value = self.get(key, option)
                config_dict[option] = value

            return config_dict


class SubRedditMod(object):
    # Helper class to mod a subreddit

    _mods = None

    def __init__(self, logger):
        self.logger = logger
        self.config = self.load_config()
        self.praw_h = self.login()
        self.subreddit = self.praw_h.subreddit(self.config["subreddit"]["uri"])

    def login(self):
        # Login
        login_info = self.config["login"]
        self.logger.info('Logging in as /u/' + login_info["username"])
        return praw.Reddit(**login_info)

    def load_config(self):
        # Load config
        containing_dir = os.path.abspath(os.path.dirname(sys.argv[0]))
        path_to_cfg = os.path.join(containing_dir, 'config.cfg')
        config = DictConfigParser()
        config.read(path_to_cfg)
        return config

    def get_all_comments(self, link_id):
        # Get all comments on a submission with specified link_id
        submission = self.praw_h.submission(id=link_id)
        submission.comments.replace_more(limit=None, threshold=0)
        flat_comments = submission.comments.list()
        return flat_comments

    def update_comment_user_flair(self, comment, css_class=None, text=None):
        # Update the user flair of an author of a comment
        if css_class is None:
            css_class = comment.author_flair_css_class
        else:
            self.logger.info("Set {}'s flair class to {}".format(comment.author.name, css_class))
        if text is None:
            text = comment.author_flair_text
        else:
            self.logger.info("Set {}'s flair text to {}".format(comment.author.name, text))
        self.subreddit.flair.set(comment.author, text, css_class)

    def get_mods(self):
        # Cache mods
        if self._mods is None:
            self._mods = self.subreddit.moderator()
        return self._mods

    def check_mod_reply(self, comment):
        # Check if mod already has replied
        for reply in comment.replies.list():
            if reply.author in self.get_mods():
                return True
        return False
