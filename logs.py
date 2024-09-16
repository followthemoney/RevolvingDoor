from pymongo import MongoClient
from datetime import datetime
ERRORS = ['DEBUG', 'INFO', 'ERROR', 'CRITICAL']

class LogsWriter:
    def __init__(self, CONFIG):
        self.client = MongoClient(CONFIG['db_url'])
        self.db = self.client[CONFIG['db_name']]
        self.col_logs = self.db['logs'] #4 DEBUG, INFO, ERROR, CRITICAL [Type, MSG, datetime]
    def debug(self, msg):
        self.__addlog(msg, ERRORS[0])
    def info(self, msg):
        self.__addlog(msg, ERRORS[1])
    def error(self, msg):
        self.__addlog(msg, ERRORS[2]) 
    def critical(self, msg):
        self.__addlog(msg, ERRORS[3])
    def __addlog(self, msg, type):
        self.col_logs.insert_one({
            'type': type, 
            'msg': msg, 
            'date': datetime.today().strftime('%Y-%m-%d %H:%M:%S')
        })