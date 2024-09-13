import apprise
import json
from datetime import datetime, timedelta
class Notifier:
    def __init__(self, config, entries):
        self.CONFIG = config
        self.apobj = apprise.Apprise()
        self.entries = entries
        self.apobj.add(f"mailto://{self.CONFIG['email_notification']}:{self.CONFIG['email_notification_password']}@{self.CONFIG['email_service']}?to={self.CONFIG['destination_email']}&name=Revolving%20Door%20Watcher")
        print(f"mailto://{self.CONFIG['email_notification']}:{self.CONFIG['email_notification_password']}@{self.CONFIG['email_service']}")#?to={self.CONFIG['destination_email']}")
        bottoken = self.CONFIG['telegram_token']
        ChatID = self.CONFIG['telegram_chatID']
        self.apobj.add(f"tgram://{bottoken}/{ChatID}")
        self.__send_mail()
    def __send_mail(self):
        self.apobj.notify(
            body=self.__build_body(self.entries),
            title='Changes detected by Revolving Door bot',
        )
    def __build_body(self):
        text = ''
        for ent in self.entries:
            text+=  (f'<b>Ex-MEP <a href="x.com/{ent["twitter_name"]}">{ent["name"]}</a> has changed his bio ! <i>Checked @ {ent["timestamp"]}</i></b><br>'
                    '---------------------------------<br>'
                    f'<p style="color:red;"> {ent["old_bio"]}</p>'
                    f'<p style="color:green;">{ent["new_bio"]}</p>'
                    '---------------------------------<br>')
        return text
