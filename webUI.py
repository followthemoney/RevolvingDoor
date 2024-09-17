from flask import Flask, render_template, jsonify, request, redirect, url_for, session, jsonify
from pymongo import MongoClient
from bson import ObjectId
import os, json, signal
from logs import LogsWriter
from waitress import serve

app = Flask(__name__)
config_path = './config.json'
with open(config_path, 'r') as file:
    CONFIG = json.load(file)

app.secret_key = CONFIG["flask_secret_key"]

# Initialize LogsWriter
logger = LogsWriter(CONFIG)
# MongoDB connection
client = MongoClient(CONFIG['db_url'])
db = client[CONFIG['db_name']]
collection = db['twitter_bios']
bios_agg_collection = db['bios_agg']  # New collection for bios_agg
ppfeed = db['rss_feeds']
newsfeed = db['rss_entries']

@app.route('/login', methods=['GET', 'POST'])
def login():
    # Hardcoded username and password (you can store this in a database)
    correct_username = CONFIG['webui_username']
    correct_password = CONFIG['webui_password']

    if request.method == 'POST':
        # Get the username and password from the form
        username = request.form['username']
        password = request.form['password']

        # Check if the credentials are correct
        if username == correct_username and password == correct_password:
            # Set session variable to mark user as logged in
            session['logged_in'] = True
            return redirect(url_for('index'))  # Redirect to the home page
        else:
            return render_template('login.html', error="Invalid credentials. Please try again.")
    
    return render_template('login.html')


@app.route('/')
def index():
    if 'logged_in' in session and session['logged_in']:
        entries = list(collection.find())  # Fetching data from MongoDB collection
        bios_agg_entries = list(bios_agg_collection.find()) 
        return render_template('index.html', entries=entries, bios_agg=bios_agg_entries)
    else:
        return redirect(url_for('login'))  # Redirect to login page if not logged in


@app.route('/stopServer', methods=['GET'])
def stopServer():
    os.kill(os.getpid(), signal.SIGINT)
    return jsonify({ "success": True, "message": "Server is shutting down..." })

@app.route('/toggle_activ/<id>', methods=['POST'])
def toggle_activ(id):
    # Find the document by its ID and toggle the 'activ' field
    entry = collection.find_one({'_id': ObjectId(id)}) or bios_agg_collection.find_one({'_id': ObjectId(id)})
    if entry:
        new_activ = not entry['activ']  # Toggle the activ field
        if 'new_bio' in entry:  # Check if it belongs to bios_agg
            bios_agg_collection.update_one({'_id': ObjectId(id)}, {'$set': {'activ': new_activ}})
        else:  # Otherwise update twitter_bios
            collection.update_one({'_id': ObjectId(id)}, {'$set': {'activ': new_activ}})
        return jsonify({'success': True, 'activ': new_activ})
    return jsonify({'success': False})

@app.route('/get_people_news', methods=['GET'])
def get_people_news():
    people = list(ppfeed.find())
    results = []

    for person in people:
        user_id = person['userID']
        news_entries = list(newsfeed.find({'userID': user_id}))
        person_data = {
            'name': person['full_name'],
            'photo': person['photo'],
            'profile_url': person['meta']['url'],
            'news': []
        }

        for news in news_entries:
            person_data['news'].append({
                'title': news['title'],
                'link': news['link'],
                'summary': news['summary'],
                'published': news['published']
            })
        if len(person_data['news']) > 0:
            results.append(person_data)

    logger.debug("Webserver - People news fetched successfully")
    return jsonify(results)

@app.route('/get_logs', methods=['GET'])
def get_logs():
    # Get the log types to filter from the request parameters
    log_types = request.args.getlist('types[]')

    # If no log types are specified, return all logs
    query = {}
    if log_types:
        query = {'type': {'$in': log_types}}

    logs = list(db['logs'].find(query))
    log_data = []
    for log in logs:
        log_data.append({
            'type': log['type'],
            'msg': log['msg'],
            'date': log['date']
        })
    
    return jsonify(log_data)


if __name__ == '__main__':
    logger.info("Webserver - Starting Flask server")
    serve(app, host='0.0.0.0', port = 5000)
    #app.run(debug=True, port=5000)
    logger.info("Webserver - Flask server started")
