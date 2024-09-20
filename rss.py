from time import sleep
import json
import feedparser
from urllib.request import ProxyHandler
from pymongo import MongoClient
import hashlib
from logs import LogsWriter
import bleach
import requests
import random

class NewsChecker:
    def __init__(self, config_path):
        with open(config_path, 'r') as file:
            CONFIG = json.load(file)
        self.CONFIG = CONFIG
        self.client = MongoClient(CONFIG['db_url'])
        self.db = self.client[CONFIG['db_name']]
        self.col_feed = self.db['rss_feeds']
        self.col_entries = self.db['rss_entries']
        self.wait_between_fetch = CONFIG['RSS_wait_betwen_fetch']
        self.logs = LogsWriter(CONFIG)
        self.logs.info("RSS - Starting Google Alerts RSS Fetcher...")
        self.url_proxies = []
        for prox in self.__get_proxies():
            self.url_proxies.append({'http':f"socks5://{prox['username']}:{prox['password']}@{prox['ip']}:{prox['port']}",
                    'https':f"socks5://{prox['username']}:{prox['password']}@{prox['ip']}:{prox['port']}"})

        self.__check()
        self.logs.info("RSS - Finished with Google Alerts RSS Fetcher.")

    def get_entries(self):
        return list(self.col_entries.find())
    
    def __already_exist(self, userID, hash):
        if self.col_entries.find_one({'userID' : userID, 'md5' : hash}):
            return True
        else :
            return False

    def __check(self):
        for entry in self.col_feed.find():
            PROXY_DATA = random.choice(self.url_proxies)
            proxy_handler = ProxyHandler(PROXY_DATA) #ADD PROXY
            feed = feedparser.parse(entry['rss'], handlers=[proxy_handler])
            self.logs.debug(f"RSS - Looking for news from {entry['full_name']}.")
            for rss_element in feed.entries:
                if not self.__already_exist(entry['userID'], hashlib.md5(rss_element.link.encode('utf-8')).hexdigest()):
                    self.logs.debug(f"RSS - Adding News entry for {entry['full_name']}")
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

    def __get_proxies(self):
        try:
            response = requests.get(
                "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=100",
                headers={"Authorization": f"Token {self.CONFIG['webshare_token']}"}
            )
            response.raise_for_status()  # Raise an HTTPError for bad responses
        except requests.RequestException as e:
            print(f"Failed to get proxy: {e}")
            return
        PROXIES = []
        for res in response.json()['results']:
            PROXIES.append({
                    'ip' : res['proxy_address'],
                    'port' : res['port'],
                    'username' : res['username'],
                    'password' : res['password']
                })
        return PROXIES


NewsChecker('./config.json')