#!/usr/bin/env python2

import re
from log_conf import LoggerManager
from common import SubRedditMod, DictConfigParser

# Configure logging
logger = LoggerManager().getLogger("heatware")


def process_comment(subreddit, cfg, comment):
    """ Process a heatware thread comment"""
    logger.debug("Processing comment: " + comment.id)
    if subreddit.check_mod_reply(comment):
        # If a mod has already replied, case closed
        return

    heatware = re.search(cfg["regex"], comment.body)
    if not heatware:
        # If no match, notify user
        comment.reply("No heatware link found, please double check your link and make a new comment")
        return

    new_flair = heatware.group(0)
    if comment.author_flair_text:
        # If user already have flair text set
        if cfg["overwrite_flair"]:
            subreddit.update_comment_user_flair(comment, text=new_flair)
            if cfg["report_overwrite"]:
                comment.report("Overwritten flair: %s" % comment.author_flair_text)
        else:
            if cfg["report_overwrite"]:
                comment.report("User already has flair")
        if cfg["overwrite_msg"]:
            comment.reply(cfg["overwrite_msg"])
    else:
        subreddit.update_comment_user_flair(comment, text=new_flair)
        if cfg["add_msg"]:
            comment.reply(cfg["add_msg"])


def process_thread(subreddit):
    """ Get and process heatware thread comments """
    cfg = subreddit.config["heatware"]
    comments = subreddit.get_all_comments(cfg["link_id"])
    for comment in comments:
        if not hasattr(comment, 'author'):
            continue
        if comment.is_root is True:
            process_comment(subreddit, cfg, comment)


def main():
    try:
        subreddit = SubRedditMod(logger)
        process_thread(subreddit)
    except Exception as e:
        logger.error(e)

if __name__ == '__main__':
    main()
