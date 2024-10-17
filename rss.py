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
import LLM
import requests
from bs4 import BeautifulSoup
import uuid
from youtube_transcript_api import YouTubeTranscriptApi


class NewsChecker:
    def __init__(self, config_path):
        with open(config_path, 'r') as file:
            CONFIG = json.load(file)
        self.CONFIG = CONFIG
        self.client = MongoClient(CONFIG['db_url'])
        self.db = self.client[CONFIG['db_name']]
        self.col_feed = self.db['rss_feeds']
        self.col_entries = self.db['rss_entries_3']
        self.col_transparency = self.db['transparency']
        self.wait_between_fetch = CONFIG['RSS_wait_betwen_fetch']
        self.logs = LogsWriter(CONFIG)
        self.logs.info("RSS - Starting Google Alerts RSS Fetcher...")
        self.url_proxies = []
        prox = self.__get_proxies()
        self.llm_requests = []
        self.url_proxies = {'http':f"http://{prox['username']}:{prox['password']}@{prox['ip']}:{prox['port']}",
                'https':f"http://{prox['username']}:{prox['password']}@{prox['ip']}:{prox['port']}"}
        self.solver_proxy = {"url": "http://{prox['ip']}:{prox['port']}", "username": prox['username'], "password": prox['password']}
        self.LLM = LLM.LLMBatchProcessor(config_path)
        self.fetch_llm_results()
        self.__check()
        self.LLM.upload_batch()
        self.logs.info("RSS - Finished with Google Alerts RSS Fetcher.")

    def __get_page_content(self, url):
        self.logs.debug(f"RSS - Fetching URL {url}")
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0"}
        PROXY_DATA = self.url_proxies
        solvedwflaresolver = False
        if 'youtube.com' in url or 'youtu.be' in url:
            self.logs.debug(f"RSS - Youtube Subtitle download {url}")
            subtitles = ""
            try:
                video_id = url.split('%3Fv%3D')[-1].split('v%3D')[-1].split('&')[0]
                lang = [transcript.language_code for transcript in YouTubeTranscriptApi.list_transcripts(video_id)]
                transcript = YouTubeTranscriptApi.get_transcript(video_id, lang, proxies = PROXY_DATA)
                subtitles = "\n".join([entry['text'] for entry in transcript])
                return subtitles
            except Exception as e:
                self.logs.error(f"RSS - Error fetching subtitles for YouTube URL {url}: {e}")
                return ""
        try:
            response = requests.get(url, headers=headers, proxies=PROXY_DATA, timeout=(5, 10), verify=True)
            response.raise_for_status()  # Handle HTTP errors
            if 'text/html' not in response.headers.get('Content-Type', ''):
                self.logs.error(f"RSS - Unexpected content type for URL {url}")
                return ""
            if len(response.content) > 10**6:  # Limit the maximum response size to 1MB
                self.logs.error(f"RSS - Response too large for URL {url}")
                return ""
        except requests.exceptions.Timeout:
            self.logs.error(f"RSS - Timeout error fetching URL {url}")
            return ""
        except requests.exceptions.TooManyRedirects:
            self.logs.error(f"RSS - Too many redirects for URL {url}")
            return ""
        except requests.exceptions.RequestException as e:
            self.logs.info(f"RSS - Error fetching URL {url}: {e}")
            try:
                #Try to solve with FlareSolverr
                url_fs = self.CONFIG['FlareSolverr']
                headers = {"Content-Type": "application/json"}
                data = {
                    "cmd": "request.get",
                    "url": url,
                    "maxTimeout": 6000,
                    "proxy" : self.solver_proxy
                }
                response = requests.post(url_fs, headers=headers, json=data)
                solvedwflaresolver = True
            except Exception as e:
                self.logs.error(f"RSS - Solve Error with FlareSolverr failed for {url} with error: {e}")
            return ""
        except Exception as e:
            self.logs.error(f"RSS - Unexpected error fetching URL {url}: {e}")
            return ""
        html_content = response.json()['solution']['response'] if solvedwflaresolver else response.content #different key for both method ;(
        soup = BeautifulSoup(html_content, 'html.parser')
        page_title = soup.title.string if soup.title else 'No Title'
        page_contents = soup.get_text()
        page_contents = ' '.join(page_contents.split())
        self.logs.debug(f"RSS - Done fetching URL {url}")

        return page_title + "\n\n" + page_contents
 

    def fetch_llm_results(self):
        results = self.LLM.return_ready_batches()
        for sub_result in results:
            for res in sub_result:
                uuid = res['custom_id'].replace('request-', '')
                if res['score'] == -1:
                    self.col_entries.update_one(
                        {'uuid': uuid},
                        {'$set': {'llm_score': -1, 'llm_run': True, 'llm_state': 'error'}}
                    )
                if res['score'] != -1:
                    self.col_entries.update_one(
                        {'uuid': uuid},
                        {'$set': {'llm_score': res['score'], 'llm_run': True, 'llm_state': 'completed'}}
                    )

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
        ignore_list = ['twitter.com', 'x.com', 'google.com', 'youtube.com', 'facebook.com', 'instagram.com', 'dailymotion.com', 'bbc.co.uk', 'tiktok.com']
        finding = self.col_transparency.find_one({'webSiteURL': {'$regex': f".*{domain}.*"}})
        if domain in ignore_list:
            return False
        elif finding:
            return True
        return False

    def __check(self):
        self.logs.debug(f"RSS - Fetching News labeled entries")
        for entry in self.col_feed.find():
            if 'constituencies_country' not in entry.keys():
                entry['constituencies_country'] = '' 
            if 'constituencies_party' not in entry.keys():
                entry['constituencies_party'] = '' 
            if 'groups_organization' not in entry.keys():
                entry['groups_organization'] = '' 
            #PROXY_DATA = random.choice(self.url_proxies)
            PROXY_DATA = self.url_proxies
            proxy_handler = ProxyHandler(PROXY_DATA) #ADD PROXY
            ##NEWSf
            try:
                feed = feedparser.parse(entry['news_rss'], handlers=[proxy_handler])
            except:
                continue
            for rss_element in feed.entries:
                if not self.__already_exist(entry['userID'], hashlib.md5(rss_element.link.encode('utf-8')).hexdigest()):
                    self.logs.debug(f"RSS - Adding news entry for {entry['full_name']}")
                    new_uuid = str(uuid.uuid4())
                    new_entry = {
                        'uuid' : new_uuid,
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
                        'in_transparency' : self.__check_website(rss_element.link), #Set news item as false as some news are in transparency register,
                        'llm_run' : False,
                        'llm_state' : 'pending',
                        'llm_score' : 0,
                        'read' : False,
                        'pinned' : False
                    }
                    self.col_entries.insert_one(new_entry)
                    try:
                        page_content = self.__get_page_content(rss_element.link.replace('https://www.google.com/url?rct=j&sa=t&url=', '').split('&ct=')[0])
                        page_content = page_content + "\n\n" + new_entry['summary']
                        self.llm_requests.append({'name':entry['full_name'], 'page_text': page_content, 'uuid': new_uuid})
                    except Exception as e:
                        self.logs.error(f"RSS - Error Fetching URL {rss_element.link.replace('https://www.google.com/url?rct=j&sa=t&url=', '').split('&ct=')[0]}")
            if feed.entries:
                self.logs.debug(f"RSS - Sleeping for {self.wait_between_fetch} seconds...")
                sleep(self.wait_between_fetch)
            ##ALL
            try:
                feed = feedparser.parse(entry['rss'], handlers=[proxy_handler])
            except:
                continue
            for rss_element in feed.entries:
                if not self.__already_exist(entry['userID'], hashlib.md5(rss_element.link.encode('utf-8')).hexdigest()):
                    self.logs.debug(f"RSS - Adding News entry for {entry['full_name']}")
                    new_uuid = str(uuid.uuid4())
                    new_entry = {
                        'uuid' : new_uuid,
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
                        'llm_run' : False,
                        'llm_state' : 'pending',
                        'llm_score' : 0,
                        'read' : False,
                        'pinned' : False
                    }
                    self.col_entries.insert_one(new_entry)
                    try:
                        page_content = self.__get_page_content(rss_element.link.replace('https://www.google.com/url?rct=j&sa=t&url=', '').split('&ct=')[0])
                        page_content = page_content + "\n\n" + new_entry['summary']
                        self.llm_requests.append({'name':entry['full_name'], 'page_text': page_content, 'uuid': new_uuid})
                    except Exception as e:
                        self.logs.error(f"RSS - Error Fetching URL {rss_element.link.replace('https://www.google.com/url?rct=j&sa=t&url=', '').split('&ct=')[0]}")
            if feed.entries:
                self.logs.debug(f"RSS - Sleeping for {self.wait_between_fetch} seconds...")
                sleep(self.wait_between_fetch)

        # Step 1: Create the JSONL batch file
        if self.llm_requests != []:
            self.LLM.create_batch_jsonl(self.llm_requests)
            
    def __get_proxies(self):
            return {
                    'ip' : 'p.webshare.io',
                    'port' : '80',
                    'username' : self.CONFIG['webshare_usr'],
                    'password' : self.CONFIG['webshare_pwd']
                }
NewsChecker('./config.json')