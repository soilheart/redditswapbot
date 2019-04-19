""" Common stuff """

import sys
import os
import urllib

from ConfigParser import SafeConfigParser

import praw


class DictConfigParser(SafeConfigParser):
    """ SafeConfigParser with a getitem returning a dict for that section """

    def __getitem__(self, key):
        """ Get section as a dictionary """
        if key not in self.sections():
            raise KeyError("No section named %s" % key)
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
    """ Helper class to mod a subreddit """

    _mods = None
    _suspended = {}

    def __init__(self, logger):
        self.logger = logger
        self.config = self._load_config()
        self.praw_h = self.login()
        self.subreddit = self.praw_h.subreddit(self.config["subreddit"]["uri"])
        self.username = self.config["login"]["username"]

    @staticmethod
    def _load_config():
        """ Load config from config.cfg """
        containing_dir = os.path.abspath(os.path.dirname(sys.argv[0]))
        path_to_cfg = os.path.join(containing_dir, 'config.cfg')
        config = DictConfigParser()
        config.read(path_to_cfg)
        return config

    def login(self):
        """ Login in praw """
        login_info = self.config["login"]
        self.logger.info('Logging in as /u/' + login_info["username"])
        return praw.Reddit(**login_info)

    def get_modmail_link(self, title="modmail", subject=None, content=None):
        """ Get link to modmail """
        link = ("https://www.reddit.com/message/compose?to=/r/{subreddit}"
                .format(subreddit=self.config["subreddit"]["uri"]))
        if subject:
            link += "&subject=" + urllib.quote_plus(subject)
        if content:
            link += "&message=" + urllib.quote_plus(content)
        return "[{title}]({link})".format(title=title, link=link)

    def get_unread_messages(self):
        """ Get unread messages (not comment replies) """
        return [msg for msg in self.praw_h.inbox.unread(limit=100) if not msg.was_comment]

    def get_unread_mod_messages(self):
        """ Get undread messages from mods """
        return [msg for msg in self.get_unread_messages() if msg.author in self.get_mods()]

    def get_top_level_comments(self, link_id):
        """ Get all top level comments on a submission with specified link_id """
        submission = self.praw_h.submission(id=link_id)
        submission.comments.replace_more(limit=None, threshold=0)
        return submission.comments

    def get_all_comments(self, link_id):
        """ Get all comments on a submission with specified link_id """
        return self.get_top_level_comments(link_id).list()

    def update_comment_user_flair(self, comment, css_class=None, text=None):
        """ Update the user flair of an author of a comment """
        if css_class is None:
            css_class = comment.author_flair_css_class
        else:
            self.logger.info("Set {}'s flair class to {}".format(comment.author.name, css_class))
        if text is None:
            text = comment.author_flair_text
        else:
            self.logger.info("Set {}'s flair text to {}".format(comment.author.name, text))
        self.subreddit.flair.set(comment.author, text, css_class)

    def get_new(self, limit=20):
        """ Get new posts """
        return self.subreddit.new(limit=limit)

    def _get_replies(self, item):
        """ Get replies to submission or comment """
        if isinstance(item, praw.models.reddit.submission.Submission):
            comments = item.comments
        elif isinstance(item, praw.models.reddit.comment.Comment):
            comments = item.replies
        else:
            raise TypeError, "Unknown item type %s" % type(item)
        return comments

    def get_mods(self):
        """ Cache mods """
        if self._mods is None:
            self._mods = self.subreddit.moderator()
        return self._mods

    def check_mod_reply(self, item):
        """ Check if mod already has replied """
        comments = self._get_replies(item)

        for comment in comments.list():
            if comment.author in self.get_mods():
                return True
        return False

    def check_bot_reply(self, item):
        """ Check if bot has replied, if so return comment """
        comments = self._get_replies(item)

        for comment in comments.list():
            if comment.author == self.username:
                return comment
        return None

    def check_user_suspended(self, user):
        """ Check if user is suspended/shadowbanned """
        if user.name in self._suspended:
            return self._suspended[user.name]

        if hasattr(user, 'fullname'):
            self._suspended[user.name] = False
            return False

        self._suspended[user.name] = True
        return True
