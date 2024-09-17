from time import sleep
import json
import feedparser
from pymongo import MongoClient
import hashlib
from logs import LogsWriter
import bleach

class NewsChecker:
    def __init__(self, config_path):
        with open(config_path, 'r') as file:
            CONFIG = json.load(file)
        self.client = MongoClient(CONFIG['db_url'])
        self.db = self.client[CONFIG['db_name']]
        self.col_feed = self.db['rss_feeds']
        self.col_entries = self.db['rss_entries']
        self.wait_between_fetch = CONFIG['RSS_wait_betwen_fetch']
        self.logs = LogsWriter(CONFIG)
        self.logs.info("Starting Google Alerts RSS Fetcher...")
        self.__check()
        self.logs.info("Finished with Google Alerts RSS Fetcher.")


    def get_entries(self):
        return list(self.col_entries.find())
    
    def __already_exist(self, userID, hash):
        if self.col_entries.find_one({'userID' : userID, 'md5' : hash}):
            return True
        else :
            return False

    def __check(self):
        for entry in self.col_feed.find():
            feed = feedparser.parse(entry['rss'])
            self.logs.debug(f"Looking for news from {entry['full_name']}.")
            for rss_element in feed.entries:
                if not self.__already_exist(entry['userID'], hashlib.md5(rss_element.link.encode('utf-8')).hexdigest()):
                    self.logs.debug(f"Adding News entry for {entry['full_name']}")
                    new_entry = {
                        'userID' : entry['userID'],
                        'full_name' : entry['full_name'],
                        'title' : bleach.clean(rss_element.title),
                        'link' : rss_element.link,
                        'summary' : bleach.clean(rss_element.summary),
                        'published' : rss_element.published,
                        'md5' : hashlib.md5(rss_element.link.encode('utf-8')).hexdigest()
                    }
                    self.col_entries.insert_one(new_entry)
            sleep(self.wait_between_fetch)


NewsChecker('./config.json')