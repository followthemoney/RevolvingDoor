import requests
import json
from tweeterpy import TweeterPy
from time import sleep
import random
from datetime import datetime, timedelta
import os
from crontab import CronTab
#from notification import Notifier
from pymongo import MongoClient
import bleach
from logs import LogsWriter
from tweeterpy import config


class TimeKeeper:
    def __init__(self, config_path):
        with open(config_path, 'r') as file:
            CONFIG = json.load(file)
        self.config_path = config_path
        self.CONFIG = CONFIG
        self.logs = LogsWriter(self.CONFIG)
        self.logs.debug('TWITTER - Opened config json file.')
        self.cron = CronTab(user=True)
        self.logs.info("TWITTER - Starting Twitter bio fetcher...")
        self.__start_process()
        self.logs.info("TWITTER - Finished Twitter bio fetcher.")

    def __start_process(self):
        scraper=Scraper(self.CONFIG)
        scraper.check_updates()
        self.CONFIG = scraper.close_twitter()
        self.__save_config()

    def __save_config(self):
        self.logs.debug("Saving over CONFIG file.")
        with open(self.config_path, 'w') as file:
            json.dump(self.CONFIG, file)

class BioAggregator:
    def __init__(self, db_url, db_name):
        self.client = MongoClient(db_url)
        self.db = self.client[db_name]
        self.agg_collection = self.db['bios_agg']

    def add_entry(self, entry):
        self.agg_collection.insert_one(entry)

    def get_aggregated_data(self):
        return list(self.agg_collection.find())

    def clear_data(self):
        self.agg_collection.delete_many({})

class Scraper:
    def __init__(self, CONFIG):
        self.CONFIG = CONFIG
        self.logs = LogsWriter(self.CONFIG)
        self.agg = BioAggregator(self.CONFIG['db_url'], self.CONFIG['db_name'])
        self.__get_proxy()
        self.client = MongoClient(self.CONFIG['db_url'])
        self.db = self.client[self.CONFIG['db_name']]
        self.logs.debug(f"TWITTER - Connecting to MongoDB {self.CONFIG['db_url']}.")
        self.collection = self.db['twitter_bios']
        self.logs.debug("TWITTER - Setting up scrapper")
        config.PROXY = {'http':f"socks5://{self.PROXY['username']}:{self.PROXY['password']}@{self.PROXY['ip']}:{self.PROXY['port']}",
                        'https':f"socks5://{self.PROXY['username']}:{self.PROXY['password']}@{self.PROXY['ip']}:{self.PROXY['port']}"}
        config.TIMEOUT = 10
        config.UPDATE_API = False
        twitter = TweeterPy()
        if CONFIG['session_path'] == 'None': 
            self.logs.debug("TWITTER - Logging on Twitter manually.")
            twitter.login(username = CONFIG['username'], password = CONFIG['password'], email = CONFIG['email'])
        else:
            self.logs.debug("TWITTER - Logging on Twitter with a session.")
            twitter.load_session(CONFIG['session_path'])
        self.twitter=twitter

    def close_twitter(self):
        self.logs.debug("TWITTER - Closing twitter and saving session")
        self.CONFIG['session_path'] = self.twitter.save_session()
        self.client.close()
        return self.CONFIG
    
    def __get_bio_update(self, username):
        try:
            self.logs.debug(f"TWITTER - Attempting to get {username} bio...")
            tt_data = self.twitter.get_user_info(username)
        except:
            self.logs.debug(f"TWITTER - Error with user {username}.")
            return ''
        return bleach.clean(tt_data['legacy']['description'])
    
    def init_bios(self): #Only to be used once when creating database
        for entry in self.collection.find():
            sleep(random.randint(self.CONFIG['min_wait'],self.CONFIG['max_wait']))
            bio = self.__get_bio_update(entry['twitter_username'])
            self.collection.update_one({'userID': entry['userID']}, {'$set': {'bio': bleach.clean(bio)}})
        return self.close_twitter()
    
    def check_updates(self):
        entries = list(self.collection.find())
        TO_PROCESS=self.CONFIG['to_process']
        self.logs.info(f"TWITTER - Scanning {TO_PROCESS} users.") 
        for entry in entries:
            self.logs.debug(f"TWITTER - Checking {entry['name']}, last checked {entry['last_check']} and active {entry['activ']}")
            if ((entry['activ']) and (entry['last_check']< (datetime.today() - timedelta(days=3)).strftime('%Y-%m-%d'))):
                sleep(random.randint(self.CONFIG['min_wait'],self.CONFIG['max_wait']))
                try:
                    new_bio = self.__get_bio_update(entry['twitter_username'])
                    old_bio = bleach.clean(self.collection.find_one({'userID': entry['userID']})['bio'])
                    if new_bio!=old_bio:
                        entry['new_bio'] = new_bio
                        entry['last_check'] = datetime.today().strftime('%Y-%m-%d')
                        self.agg.add_entry(entry)
                        self.__print_notif(entry['name'], old_bio, new_bio, entry['twitter_username'])
                    self.collection.update_one({'userID': entry['userID']}, {'$set': {'bio': new_bio, 'last_check': datetime.today().strftime('%Y-%m-%d')}})
                    TO_PROCESS=TO_PROCESS-1
                except Exception as e:
                    self.logs.error(f"TWITTER - Failed to get bio update for {entry['twitter_username']}: {e}")
                    continue
            if TO_PROCESS<=0:
                break
        self.logs.info('TWITTER - Done with scrapping !')
        return self.close_twitter()

    def __get_proxy(self):
        try:
            response = requests.get(
                "https://proxy.webshare.io/api/v2/proxy/list/?mode=backbone&page=1&page_size=25&country_code__in=NL",
                headers={"Authorization": f"Token {self.CONFIG['webshare_token']}"}
            )
            response.raise_for_status()  # Raise an HTTPError for bad responses
        except requests.RequestException as e:
            self.logs.critical(f"TWITTER - Failed to get proxy: {e}")
            return
        random_index = random.randint(0, 24)
        print(response)
        PROXY = {
            'ip' : self.CONFIG['webshare_proxy_ip'],#response.json()['results'][random_index]['proxy_address'],
            'port' : response.json()['results'][random_index]['port'],
            'username' : response.json()['results'][random_index]['username'],
            'password' : response.json()['results'][random_index]['password']
        }
        print(PROXY)
        self.PROXY = PROXY

    def __print_notif(self, Name, old_bio, new_bio, twitter_name):
        self.logs.info(f"TWITTER - Got a hit with {Name} - {twitter_name}, old bio was : {old_bio}, new bio is : {new_bio}")
    
TimeKeeper("./config.json")