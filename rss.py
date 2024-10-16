from time import sleep
import json
import feedparser
from urllib.request import ProxyHandler
from pymongo import MongoClient
import hashlib
from logs import LogsWriter
import bleach
import requests
from datetime import datetime
import random
from urllib.parse import urlparse

class NewsChecker:
    def __init__(self, config_path):
        with open(config_path, 'r') as file:
            CONFIG = json.load(file)
        self.CONFIG = CONFIG
        self.client = MongoClient(CONFIG['db_url'])
        self.db = self.client[CONFIG['db_name']]
        self.col_feed = self.db['rss_feeds']
        self.col_entries = self.db['rss_entries_2']
        self.col_transparency = self.db['transparency']
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
        
    def __check_website(self, url):
        url = url.replace('https://www.google.com/url?rct=j&sa=t&url=', '')
        domain = urlparse(url).netloc.replace('www.','')
        ignore_list = ['twitter.com', 'x.com', 'google.com', 'youtube.com', 'facebook.com', 'instagram.com', 'dailymotion.com', 'bbc.co.uk']
        finding = self.col_transparency.find_one({'webSiteURL': {'$regex': f".*{domain}.*"}})
        if domain in ignore_list:
            return False
        elif finding:
            return True
        return False

    def __check(self):
        for entry in self.col_feed.find():
            for entry in self.col_feed.find():
                if 'constituencies_country' not in entry:
                    entry['constituencies_country'] == '' 
                if 'constituencies_party' not in entry:
                    entry['constituencies_party'] == '' 
                if 'groups_organization' not in entry:
                    entry['groups_organization'] == '' 
            PROXY_DATA = random.choice(self.url_proxies)
            proxy_handler = ProxyHandler(PROXY_DATA) #ADD PROXY
            ##NEWS
            feed = feedparser.parse(entry['news_rss'], handlers=[proxy_handler])
            for rss_element in feed.entries:
                if not self.__already_exist(entry['userID'], hashlib.md5(rss_element.link.encode('utf-8')).hexdigest()):
                    self.logs.debug(f"RSS - Adding news entry for {entry['full_name']}")
                    new_entry = {
                        'userID' : entry['userID'],
                        'full_name' : entry['full_name'],
                        'title' : bleach.clean(rss_element.title),
                        'link' : rss_element.link,
                        'summary' : bleach.clean(rss_element.summary),
                        'published' : datetime.strptime(rss_element.published, '%Y-%m-%dT%H:%M:%SZ'),
                        'md5' : hashlib.md5(rss_element.link.encode('utf-8')).hexdigest(),
                        'constituencies_country' : entry['constituencies_country'],
                        'constituencies_party' : entry['constituencies_party'],
                        'groups_organization' : entry['groups_organization'],
                        'is_news' : True,
                        'in_transparency' : False #Set news item as false as some news are in transparency register
                    }
                    self.col_entries.insert_one(new_entry)
            sleep(self.wait_between_fetch)
            ##ALL
            feed = feedparser.parse(entry['rss'], handlers=[proxy_handler])
            for rss_element in feed.entries:
                if not self.__already_exist(entry['userID'], hashlib.md5(rss_element.link.encode('utf-8')).hexdigest()):
                    self.logs.debug(f"RSS - Adding News entry for {entry['full_name']}")
                    new_entry = {
                        'userID' : entry['userID'],
                        'full_name' : entry['full_name'],
                        'title' : bleach.clean(rss_element.title),
                        'link' : rss_element.link,
                        'summary' : bleach.clean(rss_element.summary),
                        'published' : datetime.strptime(rss_element.published, '%Y-%m-%dT%H:%M:%SZ'),
                        'md5' : hashlib.md5(rss_element.link.encode('utf-8')).hexdigest(),
                        'constituencies_country' : entry['constituencies_country'],
                        'constituencies_party' : entry['constituencies_party'],
                        'groups_organization' : entry['groups_organization'],
                        'is_news' : False,
                        'in_transparency' : self.__check_website(rss_element.link),
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