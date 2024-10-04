from flask import Flask, render_template, jsonify, request, redirect, url_for, session, jsonify
from pymongo import MongoClient
from bson import ObjectId
import os, json, signal
from logs import LogsWriter
from waitress import serve
from datetime import datetime, timedelta
app = Flask(__name__)
config_path = './config_beta.json'
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
newsfeed = db['rss_entries_2']

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
    start_date = request.args.get('start_date')
    country = request.args.get('country')
    party = request.args.get('party')
    groupe = request.args.get('groupe')
    is_news = request.args.get('is_news')
    subject = request.args.get('subject')
    results = []
    query = {}
    if start_date:
        query['published'] = {'$gte': datetime.strptime(start_date, '%Y-%m-%d')}
    if country:
        query['constituencies_country'] = country
    if party:
        query['constituencies_party'] = party
    if groupe:
        query['groups_organization'] = groupe
    if is_news:
        query['is_news'] = is_news.lower() == 'true'
    post_query = {}
    if subject:
        post_query['subject'] = subject
    pipeline = [
        # Matchingg
        {
            "$match": query
        },
        # Groupingggg
        {
            "$group": {
            "_id": "$userID",
            "news": {
                "$push": {
                "title": "$title",
                "link": "$link",
                "summary": "$summary",
                "published": "$published",
                "in_transparency" : "$in_transparency",
                }
            },
            "name": {"$first": "$full_name"},
            }
        },
        {
            "$sort": {
            "news.published": -1  # Sort by the date 
            }
        },
        {
            "$lookup": {
                "from": "rss_feeds",  # The name of the collection to join
                "localField": "_id",  # Field from newsfeed (grouped by userID)
                "foreignField": "userID",  # Field from ppfeed to match
                "as": "pp_data"  # Output array with matching documents from ppfeed
            }
        },
        # Add photo and meta.url 
        {
            "$addFields": {
                "photo": {
                    "$arrayElemAt": ["$pp_data.photo", 0]  # get first no list
                },
                "profile_url": {
                    "$arrayElemAt": ["$pp_data.meta.url", 0]  # get first no list
                },
                "subject": {
                    "$arrayElemAt": ["$pp_data.subject", 0]  # get first no list
                },
            }
        },
        {
            "$project": {
                "pp_data": 0  # remove raw ppdata
            }
        },
        {
            "$match": post_query
        }
    ]
    results = list(newsfeed.aggregate(pipeline))

    logger.debug("WEB - People news fetched successfully")
    return jsonify(results)

@app.route('/get_logs', methods=['GET'])
def get_logs():
    # Get the log types to filter from the request parameters
    log_types = request.args.getlist('types[]')

    # If no log types are specified, return all logs
    query = {}
    if log_types:
        query = {'type': {'$in': log_types}}

    logs = list(db['logs'].find(query).sort('date', -1))  # Sort logs by date in descending order
    log_data = []
    for log in logs:
        log_data.append({
            'type': log['type'],
            'msg': log['msg'],
            'date': log['date']
        })
    
    return jsonify(log_data)

@app.route('/clear_logs', methods=['POST'])
def clear_logs():
    col_logs = db['logs']
    col_logs.delete_many({})
    return jsonify({'success': True, 'message': 'All logs have been cleared.'})

@app.route('/clear_agg', methods=['POST'])
def clear_agg():
    bios_agg_collection.delete_many({})
    return jsonify({'success': True, 'message': 'All differences have been cleared.'})


@app.route('/add_user', methods=['POST'])
def add_user():
    data = request.get_json()
    # Ensure Name is provided
    if not data.get('name'):
        return jsonify({'success': False, 'message': 'Name is required'})

    # Ensure either Twitter Username or Google Alert Feed is provided
    if not data.get('twitterUsername') and not data.get('googleAlertFeed'):
        return jsonify({'success': False, 'message': 'At least one of Twitter Username and/or Google Alert Feed is required'})

    # Get the latest userID from the twitter_bios collection
    last_user = collection.find_one({"userID": {"$regex": "^EXTRA"}}, sort=[("userID", -1)])
    if last_user:
        last_user_id = last_user['userID']
        new_user_id = f"EXTRA{int(last_user_id.replace('EXTRA', '')) + 1:04}"
    else:
        new_user_id = 'EXTRA0000'
    if data['photoUrl'] == '':
        data['photoUrl'] = 'https://cdn.pixabay.com/photo/2015/10/05/22/37/blank-profile-picture-973460_960_720.png'
    if data['profileUrl'] == '':
        data['profileUrl'] = 'ftm.eu'
    
    if data.get('twitterUsername'):
        # Prepare data for the twitter_bios collection
        twitter_bio_data = {
            'userID': new_user_id,
            'name': data['name'],
            'meta': {'url':data['profileUrl']},
            'photo': data['photoUrl'],
            'twitter_username': data['twitterUsername'],
            'last_check': (datetime.now() - timedelta(weeks=1)).strftime('%Y-%m-%d'),
            'subject' : data['subject'],
            'activ' : True,
            'bio' : ''
        }
        logger.info(f'WEB - Adding user {twitter_bio_data["name"]} to Twitter database')
        # Insert into the twitter_bios collection
        collection.insert_one(twitter_bio_data)
    if data.get('googleAlertFeed'):
        # Prepare data for the rss_feeds collection
        rss_feed_data = {
            'userID': new_user_id,
            'full_name': data['name'],
            'meta' : {'url' : data['photoUrl']},
            'photo': data['photoUrl'],
            'rss': data['googleAlertFeed'],
            'news_rss' : data['NewsgoogleAlertFeed'],
            'subject' : data['subject'],
            'activ' : True
        }
        print(rss_feed_data)
        logger.info(f'WEB - Adding user {rss_feed_data["full_name"]} to Google Alerts database')

        # Insert into the rss_feeds collection
        ppfeed.insert_one(rss_feed_data)

    return jsonify({'success': True})

# Fetch all users from twitter_bios collection with userID starting with EXTRA
@app.route('/get_twitter_bios_extra', methods=['GET'])
def get_twitter_bios_extra():
    users = list(collection.find({'userID': {'$regex': '^EXTRA'}}))
    return jsonify([{
        'userID': user['userID'],
        'name': user['name'],# + ' ' + user['userID'],
        'photo': user.get('photo', ''),
        'twitter_username': user.get('twitter_username', ''),
        'subject' : user.get('subject')
    } for user in users])

# Fetch all users from rss_feeds (ppfeed) collection with userID starting with EXTRA
@app.route('/get_rss_feeds_extra', methods=['GET'])
def get_rss_feeds_extra():
    users = list(ppfeed.find({'userID': {'$regex': '^EXTRA'}}))
    return jsonify([{
        'userID': user['userID'],
        'name': user['full_name'],# + ' ' + user['userID'],
        'photo': user.get('photo', ''),
        'subject' : user.get('subject')
    } for user in users])

# Delete user from the appropriate collection
@app.route('/delete_user/<col>/<userID>', methods=['DELETE'])
def delete_user(col, userID):
    if col == 'twitter':
        result = collection.delete_one({'userID': userID})
    elif col == 'rss':
        result = ppfeed.delete_one({'userID': userID})
    else:
        return jsonify({'success': False, 'message': 'Invalid collection'}), 400
    
    if result.deleted_count > 0:
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'message': 'User not found'}), 404
    
@app.route('/get_unique_subjects_twitter', methods=['GET'])
def get_unique_subjects_twitter():
    subjects = collection.distinct('subject')
    return jsonify(subjects)

@app.route('/get_unique_subjects_bios_agg', methods=['GET'])
def get_unique_subjects_bios_agg():
    subjects = bios_agg_collection.distinct('subject')
    return jsonify(subjects)

@app.route('/get_unique_subjects_rss', methods=['GET'])
def get_unique_subjects_rss():
    subjects = ppfeed.distinct('subject')
    return jsonify(subjects)

@app.route('/get_people_news_filters', methods = ['GET'])
def get_people_news_filters():
    results = {'constituencies_party' : ppfeed.distinct('constituencies_party'),
               'constituencies_country' : ppfeed.distinct('constituencies_country'),
               'groups_organization' : ppfeed.distinct('groups_organization'),
               'subject' : ppfeed.distinct('subject')}
    return jsonify(results)

if __name__ == '__main__':
    logger.info("WEB - Starting Flask server")
    try:
        #serve(app, host='0.0.0.0', port = 8080, url_scheme='https')
        app.run(debug=True, port=5000)
    except Exception as e:
        logger.critical(f"WEB - Webserver died due to: {e}")
