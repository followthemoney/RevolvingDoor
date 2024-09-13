import requests
import json
from tweeterpy import TweeterPy
from tweeterpy import config
from tinydb import TinyDB, Query
from time import sleep
import random
from datetime import datetime, timedelta
import os
from crontab import CronTab
from notification import Notifier


class TimeKeeper:
    def __init__(self, config_path):
        with open(config_path, 'r') as file:
            CONFIG = json.load(file)
        self.config_path = config_path
        self.CONFIG = CONFIG
        print('[WDB] Opened config json file.') if self.CONFIG['debug'] else None
        self.cron = CronTab(user=True)
        self.__set_cron_scrap()
        self.__start_process()
        

    def __set_cron_scrap(self):
        print('[WDB] Setting cron task for tomorrow.') if self.CONFIG['debug'] else None 
        job = self.cron.new(command=f"python3 {self.CONFIG['script_path']}") if self.CONFIG['debug'] else None
        job.minute.on(0)
        job.hour.on(0)
        self.cron.write()
        print(f"[WDB] Cron job set to run {self.CONFIG['script_path']} every day at midnight.") if self.CONFIG['debug'] else None

    def __start_process(self):
        scraper=Scraper(self.CONFIG)
        scraper.check_updates()
        self.CONFIG = scraper.close_twitter()
        self.__save_config()
        if self.__is_certain_day(self.CONFIG['day_name']):
            print("[WDB] Today is newsletter day, sending it.") if self.CONFIG['debug'] else None
            self.__send_newsletter()
            print("[WDB] Newsletter sent")
    
    def __send_newsletter(self):
        entries = self.agg.get_aggregated_data() if self.CONFIG['debug'] else None
        Notifier(self.CONFIG, entries)

    def __save_config(self):
        print('[WDB] Saving over CONFIG file.') if self.CONFIG['debug'] else None
        with open(self.config_path, 'w') as file:
            json.dump(self.CONFIG, file)

    def __is_certain_day(self, day_name):
        current_day = datetime.today().strftime('%A')
        return current_day.lower() == day_name.lower()


class BioAggregator:
    def __init__(self, db_path):
        self.db = TinyDB(db_path)
        self.User = Query()

    def add_entry(self, user_id, name, old_bio, new_bio, twitter_name):
        entry = {
            'user_id': user_id,
            'name': name,
            'old_bio': old_bio,
            'new_bio': new_bio,
            'twitter_name': twitter_name,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        self.db.insert(entry)

    def get_aggregated_data(self):
        return self.db.all()

    def clear_data(self):
        self.db.truncate()


class Scraper:
    def __init__(self, CONFIG):
        self.CONFIG = CONFIG
        self.agg = BioAggregator(self.CONFIG['agg_db'])
        self.__get_proxy()
        self.db = TinyDB(self.CONFIG['bio_db'])
        self.User = Query()
        print("[WDB] Setting up scrapper") if self.CONFIG['debug'] else None
        config.PROXY = {'http':f"socks5://{self.PROXY['username']}:{self.PROXY['password']}@{self.PROXY['ip']}:{self.PROXY['port']}",
                        'https':f"socks5://{self.PROXY['username']}:{self.PROXY['password']}@{self.PROXY['ip']}:{self.PROXY['port']}"}
        config.TIMEOUT = 10
        config.UPDATE_API = False
        twitter = TweeterPy()
        if CONFIG['session_path'] == 'None': 
            print("[WDB] Logging on Twitter manually.") if self.CONFIG['debug'] else None
            twitter.login(username = CONFIG['username'], password = CONFIG['password'], email = CONFIG['email'])
        else:
            print("[WDB] Logging on Twitter with a session.") if self.CONFIG['debug'] else None
            twitter.load_session(CONFIG['session_path'])
        self.twitter=twitter

    def close_twitter(self):
        print("[WDB] Closing twitter and saving session") if self.CONFIG['debug'] else None
        self.CONFIG['session_path'] = self.twitter.save_session()
        return self.CONFIG
    
    def __get_bio_update(self, username):
        try:
            print(f"[WDB] Attempting to get {username} bio...") if self.CONFIG['debug'] else None
            tt_data = self.twitter.get_user_info(username)
        except:
            print(f"[WDB] Error with user {username}.") if self.CONFIG['debug'] else None
            return ''
        return tt_data['legacy']['description']
    
    def init_bios(self): #Only to be used once when creating database
        for entry in self.db.all():
            sleep(random.randint(self.CONFIG['min_wait'],self.CONFIG['max_wait']))
            bio = self.get_bio_update(self.twitter, entry['twitter_username'])
            self.db.update({'bio': bio}, self.User.userID == entry['userID'])
            pass
        return self.close_twitter()
    
    def check_updates(self):
        User = Query()
        entries = self.db.all()
        random.shuffle(entries)
        TO_PROCESS=self.CONFIG['to_process']
        print(f"[WDB] We have {TO_PROCESS} users to scan.") if self.CONFIG['debug'] else None
        for entry in entries:
            if ((entry['activ']) and (entry['last_check']< (datetime.today() - timedelta(days=2)).strftime('%Y-%m-%d'))):
                sleep(random.randint(self.CONFIG['min_wait'],self.CONFIG['max_wait']))
                new_bio = self.__get_bio_update(self.twitter, entry['twitter_username'])
                old_bio = self.db.search(self.User.userID==entry['userID'])[0]['bio']
                if new_bio!=old_bio:
                    self.agg.add_entry(entry['name'], old_bio, new_bio, entry['twitter_username'])
                    print_notif(entry['name'], old_bio, new_bio, entry['twitter_username'])
                self.db.update({'bio': new_bio, 'last_check': datetime.today().strftime('%Y-%m-%d')}, User.userID == entry['userID'])
                TO_PROCESS=TO_PROCESS-1
            if TO_PROCESS<=0:
                break
        print('Done for now. Going to sleep')
        return self.close_twitter()

    def __get_proxy(self):
        response = requests.get(
            "https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=25",
            headers={"Authorization": f"Token {self.CONFIG['webshare_token']}"}
        )
        print(response.json())
        PROXY = {
            'ip' : response.json()['results'][0]['proxy_address'],
            'port' : response.json()['results'][0]['port'],
            'username' : response.json()['results'][0]['username'],
            'password' : response.json()['results'][0]['password']
        }
        self.PROXY = PROXY

    
def print_notif(Name, old_bio, new_bio, twitter_name):
    print(f"Got a hit with {Name} - {twitter_name}, old bio was : {old_bio}, new bio is : {new_bio}")
    

TimeKeeper("/mnt/2To/jupyter_data/FTM/Revolving_doors/config.json")
