#!/usr/bin/env python2

import sys
import re
import argparse
from datetime import datetime

from log_conf import LoggerManager
from common import SubRedditMod

# Configure logging
LOGGER = LoggerManager().getLogger("trade_flair")


class TradeFlairer(object):
    """ Trade flair helper """

    def __init__(self, subreddit, logger):
        self._subreddit = subreddit
        self._config = subreddit.config["trade"]
        self.completed = []
        self.pending = []
        self._trade_count_cache = {}
        self._current_submission = None
        self._logger = logger

    def open_submission(self, submission):
        if submission == "curr":
            submission = self._config["link_id"]
        elif submission == "prev":
            submission = self._config["prevlink_id"]
        self._current_submission = submission

        self._logger.info("Opening trade confirmation submission {id}".format(id=submission))

        with open(submission + "_completed.log", "a+") as completed_file:
            completed_file.seek(0)
            self.completed = completed_file.read().splitlines()

        with open(submission + "_pending.log", "a+") as pending_file:
            pending_file.seek(0)
            self.pending = pending_file.read().splitlines()

    def close_submission(self):
        assert self._current_submission
        if self.pending:
            with open(self._current_submission + "_pending.log", "w") as pending_file:
                pending_file.write("\n".join(self.pending))
        self._current_submission = None

    def add_completed(self, comment):
        assert self._current_submission
        self.completed.append(comment.id)
        with open(self._current_submission + "_completed.log", "a") as completed_file:
            completed_file.write("{id}\n".format(id=comment.id))

    def add_pending(self, comment):
        assert self._current_submission
        self.pending.append(comment.id)

    def remove_pending(self, comment):
        assert self._current_submission
        self.pending.remove(comment.id)

    def get_unhandled_comments(self):
        assert self._current_submission
        comments = self._subreddit.get_top_level_comments(self._current_submission)
        handled = self.completed + self.pending
        unhandled = [comment for comment in comments if comment.id not in handled]
        self._logger.info("Checking {unhandled} out of {total} comments ({pending} pending)"
                          .format(unhandled=len(unhandled), total=len(comments),
                                  pending=len(self.pending)))
        return unhandled

    def check_top_level_comment(self, comment):
        bot_reply = self._subreddit.check_bot_reply(comment)

        explicit_link = re.search(r"\[.*\]\(.*\)", comment.body)
        match = re.findall(r"\/?u(?:ser)?\/([a-zA-Z0-9_-]+)", comment.body)

        if explicit_link or not match:
            if not bot_reply:
                comment.reply("Could not find user mention, "
                              "please edit your comment and make sure the username "
                              "starts with /u/ (no explicit linking!)")
            return None

        match = {user.lower() for user in match}
        if len(match) > 1:
            if not bot_reply:
                comment.reply("Found multiple usernames, "
                              "please only include one user per confirmation comment")
            return None

        if bot_reply:
            bot_reply.mod.remove()

        return match.pop()

    def check_reply(self, comment):
        bot_reply = self._subreddit.check_bot_reply(comment)
        if "confirmed" not in comment.body.lower():
            if not bot_reply:
                comment.reply('Could not find "confirmed" in comment, please edit your comment')
            return False

        if bot_reply:
            bot_reply.mod.remove()

        return True

    def _get_warning(self, comment, warning_type):
        # TODO: Move proof to config
        proofs = ["Screenshot of PM's between the users"]
        modmail_content = ("Comment link: {link}\n\nLink to screenshots of PM's: [REQUIRED]"
                           .format(link=comment.permalink))
        modmail_link = self._subreddit.get_modmail_link(subject="Trade Confirmation Proof",
                                                        content=modmail_content)
        warning = self._config["{type}_warning".format(type=warning_type)] + "\n\n"
        warning += ("To verify this trade send a {modmail_link} including the following: \n\n"
                    .format(modmail_link=modmail_link))
        for proof in proofs:
            warning += "* {proof}\n".format(proof=proof)
        return warning

    def check_requirements(self, parent, reply):
        for comment in [parent, reply]:
            if self._subreddit.check_user_suspended(comment.author):
                return False
            if comment.banned_by:
                comment.report("Flair: Banned user")
                return False

            karma = comment.author.link_karma + comment.author.comment_karma
            age = (datetime.utcnow() - datetime.utcfromtimestamp(comment.author.created_utc)).days
            trade_count = self.get_author_trade_count(comment)

            if trade_count is not None and trade_count < int(self._config["flair_check"]):
                if age < int(self._config["age_check"]):
                    comment.reply(self._get_warning(parent, "age"))
                    return False
                if karma < int(self._config["karma_check"]):
                    comment.reply(self._get_warning(parent, "karma"))
                    return False

        return True

    def get_author_trade_count(self, item):
        if item.author.name in self._trade_count_cache:
            return self._trade_count_cache[item.author.name]
        if not item.author_flair_css_class:
            return 0

        trade_count = item.author_flair_css_class.lstrip("i-")
        try:
            trade_count = int(trade_count)
        except ValueError:
            trade_count = None
        return trade_count

    def flair(self, parent, reply, dock_trade=False):
        for comment in parent, reply:
            trade_count = self.get_author_trade_count(comment)
            if trade_count is not None:
                if dock_trade:
                    trade_count -= 1
                else:
                    trade_count += 1
                new_flair_css_class = "i-{trade_count}".format(trade_count=trade_count)
                self._subreddit.update_comment_user_flair(comment, css_class=new_flair_css_class)
                self._trade_count_cache[comment.author.name] = trade_count

        if not dock_trade:
            try:
                reply.reply(self._config["reply"])
            except Exception:
                LOGGER.info("Failed to reply, probably because of too old comment")

    def process_post(self, post):

        self.open_submission(post)

        for comment in self.get_unhandled_comments():
            if not hasattr(comment.author, 'name'):
                # Deleted comment, ignore comment and move on
                self.add_completed(comment)
                continue

            tagged_user = self.check_top_level_comment(comment)
            if tagged_user is None:
                continue
            elif tagged_user.lower() == comment.author.name.lower():
                comment.report("Flair: Self-tagging")

            for reply in comment.replies:
                if not hasattr(reply.author, 'name'):
                    # Deleted comment, ignore comment and move on
                    continue
                if reply.author.name.lower() == tagged_user.lower():
                    if not self.check_reply(reply):
                        continue

                    if self.check_requirements(comment, reply):
                        self.flair(comment, reply)
                        self.add_completed(comment)
                    else:
                        self.add_pending(comment)
                    break
                else:
                    reply.report("User not tagged in parent")

        self.close_submission()

    def process_mod_messages(self):

        for msg in self._subreddit.get_unread_mod_messages():
            LOGGER.info("Processing PM from mod: " + msg.author.name)
            pattern = r"^https?:\/\/(?:www\.)?reddit\.com\/r\/.*\/comments\/.{6}\/.*\/(.{7})\/$"
            comment_link = re.search(pattern, msg.body)
            if not comment_link:
                msg.reply("You have submitted an invalid URL")
                msg.mark_read()
                continue

            comment_id = comment_link.group(1)
            comment = self._subreddit.praw_h.comment(id=comment_id).refresh()

            # TODO: Restore when stop supporting old confirmation threads
            # tagged_user = self.check_top_level_comment(comment)
            # if tagged_user is None:
            if "u/" not in comment.body.lower():
                msg.reply("Could not find /u/[user] in comment, sure you submitted the top level comment?")
                msg.mark_read()
                continue

            self.open_submission(comment.submission.id)

            if comment_id in self.completed:
                msg.reply("Trade already completed")
                msg.mark_read()
                continue

            # TODO: Restore when stop supporting old confirmation threads
            # if comment_id not in self.pending:
            #     msg.reply("Could not find comment {id} in pending trade confirmations"
            #               .format(id=comment_id))
            #     msg.mark_read()
            #     continue

            if comment.mod_reports:
                comment.mod.approve()
            for reply in comment.replies:
                # TODO: Restore when stop supporting old confirmation threads
                # if reply.author.name.lower() == tagged_user.lower():
                if reply.author.name.lower() in comment.body.lower():
                    if not self.check_reply(reply):
                        continue
                    if reply.mod_reports:
                        reply.mod.approve()
                    self.flair(comment, reply)
                    self.add_completed(comment)
                    if comment.id in self.pending:
                        self.remove_pending(comment)
                    msg.reply("Trade flair added for {comment} and {reply}"
                              .format(comment=comment.author.name, reply=reply.author.name))
                    msg.mark_read()
                    break
            else:
                msg.reply("Could not find confirmation reply on submitted comment")
                msg.mark_read()
            self.close_submission()


def main():

    parser = argparse.ArgumentParser(description="Process flairs")
    parser.add_argument("-m", dest="post", default="curr",
                        help="Which trade post to process (curr, prev or submission id)")
    parser.add_argument("-p", "--pm", dest="pm_only", default=False, action="store_true",
                        help="Only process PMs (from mods)")
    args = parser.parse_args()

    try:
        # Setup SubRedditMod
        subreddit = SubRedditMod(LOGGER)

        # Setup tradeflairer
        trade_flairer = TradeFlairer(subreddit, LOGGER)

        if not args.pm_only:
            trade_flairer.process_post(args.post)

        trade_flairer.process_mod_messages()

    except KeyboardInterrupt:
        print("\nCtrl-C pressed, exiting gracefully")
        sys.exit()

    except Exception as exception:
        LOGGER.error(exception)
        sys.exit()


if __name__ == '__main__':
    main()
