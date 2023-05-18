from flask import Flask, request, session, redirect, url_for, render_template, flash, g
from neo4j import (
    GraphDatabase,
    basic_auth,
)
from datetime import datetime
from neo4j.exceptions import ConstraintError
import re

app = Flask(__name__)
app.config['SECRET_KEY'] = 'df0331cefc6c2b9a5d0208a726a5d1c0fd37324feba25506'

uri = "your uri"
user = "your username"
password = "your password"

driver = GraphDatabase.driver(uri, auth=basic_auth(user, password))


def calc_time(time1):
    time2 = datetime.now()
    iso_time = time2.isoformat()
    dt2 = datetime.fromisoformat(iso_time)

    iso_string = str(time1)
    dt1 = datetime.fromisoformat(iso_string[:-9])

    time_diff = dt2 - dt1

    if time_diff.days > 0:
        return (f"{time_diff.days}d")
    elif time_diff.seconds // 3600 > 0:
        return (f"{time_diff.seconds // 3600}h")
    elif time_diff.seconds // 60 > 0:
        return (f"{time_diff.seconds // 60}m")
    else:
        return ("Just now")


def get_db():
    if not hasattr(g, "neo4j_db"):
        g.neo4j_db = driver.session()
    return g.neo4j_db


@app.teardown_appcontext
def close_db(error):
    if hasattr(g, "neo4j_db"):
        g.neo4j_db.close()


@app.route('/', methods=['GET', 'POST'])
def index():

    def work(tx):
        return list(
            tx.run(
                "MATCH (u:User)-[:POSTS]->(t:Tweet) "
                "RETURN u.screen_name as screen_name, u.profile_image_url as image, t.text as text, t.created_at as time "
                "ORDER BY t.created_at DESC LIMIT 10", ))

    def trends_work(tx):
        return list(
            tx.run(
                "MATCH (h:Hashtag)<-[:TAGS]-(t:Tweet) "
                "WITH h, COUNT(h) AS Hashtags "
                "ORDER BY Hashtags DESC "
                "LIMIT 15 "
                "RETURN h.name as name, Hashtags", ))

    if request.method == 'POST':
        username = request.form['username']
        return redirect(url_for('user', username=username))

    db = get_db()
    posts = db.execute_read(work)
    trends = db.execute_read(trends_work)
    records = [dict(record) for record in posts]
    for post in records:
        post['time'] = calc_time(post['time'])

    return render_template('index.html',
                           title='Home',
                           posts=records,
                           trends=trends)


@app.route('/user/<username>', methods=['GET', 'POST'])
def user(username):

    def work(tx, username):
        return (tx.run(
            "MATCH (u:User{screen_name:$username}) "
            "OPTIONAL MATCH (u)-[:POSTS]->(t:Tweet) "
            "with u.screen_name as screen_name, u.name as name, u.followers as followers, u.following as following, u.location as location, u.profile_image_url as image, collect(t.text)[..10] as texts, collect(id(t))[..10] as ids "
            "RETURN screen_name, name, location, followers, following, image, texts, ids",
            username=username)).single()

    def who_work(tx, screen_name):
        return list(
            tx.run(
                "MATCH (ou:User)-[:POSTS]->(t:Tweet)-[mt:MENTIONS]->(me:User{screen_name:$screen_name}) "
                "WITH DISTINCT ou, me "
                "WHERE (ou)-[:FOLLOWS]->(me) AND NOT (me)-[:FOLLOWS]->(ou) "
                "RETURN ou.screen_name as name, ou.profile_image_url as image "
                "LIMIT 6",
                screen_name=screen_name))

    db = get_db()
    posts = db.execute_read(work, username)
    who_to_follow = db.execute_read(who_work, username)
    return render_template('user.html',
                           posts=posts,
                           who_to_follow=who_to_follow)


'''
@app.route('/create', methods=('GET', 'POST'))
def create():
    return render_template('create.html')

@app.route('/register1', methods=['GET', 'POST'])
def register1():

    def work(tx, screen_name, name, location):
        return tx.run(
            "CREATE (u:User) "
            "SET u.screen_name = $screen_name, u.name = $name, u.followers = 0, u.following = 0, u.location = $location "
            "RETURN u ",
            screen_name=screen_name,
            name=name,
            location=location)

    username = request.form['username']
    name = request.form['name']
    location = request.form['location']

    db = get_db()
    db.create_user(username, name, location)

    return render_template('register.html')
'''


@app.route('/register', methods=['GET', 'POST'])
def register():

    def work(tx, screen_name, name, location):
        return tx.run(
            "CREATE (u:User) "
            "SET u.screen_name = $screen_name, u.name = $name, u.followers = 0, u.following = 0, u.location = $location "
            "RETURN u ",
            screen_name=screen_name,
            name=name,
            location=location)

    if request.method == 'POST':
        screen_name = request.form['screen_name']
        name = request.form['name']
        location = request.form['location']
        db = get_db()
        try:
            db.execute_write(work, screen_name, name, location)
            return redirect(url_for('index'))
        except ConstraintError:
            flash(
                f"{screen_name} already taken. Please choose a different username."
            )
            return render_template('register.html')

    return render_template('register.html')


@app.route('/delete', methods=['GET', 'POST'])
def delete():

    def work(tx, screen_name):
        result = tx.run(
            "MATCH (u:User{screen_name:$screen_name}) "
            "DETACH DELETE u ",
            screen_name=screen_name,
        )
        return bool(result.consume().counters.nodes_deleted)

    if request.method == 'POST':
        screen_name = request.form['screen_name']
        db = get_db()
        deleted = db.execute_write(work, screen_name)
        if deleted:
            return redirect(url_for('index'))
        else:
            flash(f"User {screen_name} was not found.")
            return redirect(url_for('delete'))

    return render_template('delete.html')


@app.route('/follow', methods=['GET', 'POST'])
def follow():

    def work(tx, screen_name1, screen_name2):
        result = tx.run(
            "OPTIONAL MATCH (u:User{screen_name:$screen_name1}) "
            "OPTIONAL MATCH (f:User{screen_name:$screen_name2}) "
            "OPTIONAL MATCH (u) -[r:FOLLOWS]-> (f) "
            "RETURN u IS NOT NULL as user1_found,f IS NOT NULL as user2_found, r IS NOT NULL as already_follow ",
            screen_name1=screen_name1,
            screen_name2=screen_name2)
        record = result.single()

        return record.value("user1_found"), record.value(
            "user2_found"), record.value("already_follow")

    def follow_work(tx, screen_name1, screen_name2):
        return tx.run(
            "MATCH (u:User{screen_name:$screen_name1}) "
            "MATCH (f:User{screen_name:$screen_name2}) "
            "CREATE (u) -[:FOLLOWS]-> (f)",
            screen_name1=screen_name1,
            screen_name2=screen_name2)

    if request.method == 'POST':
        screen_name1 = request.form['screen_name1']
        screen_name2 = request.form['screen_name2']
        db = get_db()
        user1, user2, already_follow = db.execute_write(
            work, screen_name1, screen_name2)
        if not user1 and not user2:
            flash('Both users doesnt exist')
            return redirect(url_for('follow'))
        elif not user1 and user2:
            flash(f"User {screen_name1} was not found.")
            return redirect(url_for('follow'))
        elif user1 and not user2:
            flash(f"User {screen_name2} was not found.")
            return redirect(url_for('follow'))
        elif user1 and user2 and already_follow:
            flash(f"User {screen_name1} already follows User {screen_name2}.")
            return redirect(url_for('follow'))
        else:
            db.execute_write(follow_work, screen_name1, screen_name2)
            return redirect(url_for('index'))

    return render_template('follow.html')


@app.route('/unfollow', methods=['GET', 'POST'])
def unfollow():

    def work(tx, screen_name1, screen_name2):
        result = tx.run(
            "OPTIONAL MATCH (u:User {screen_name: $screen_name1}) "
            "OPTIONAL MATCH (o:User {screen_name: $screen_name2}) "
            "OPTIONAL MATCH (u) -[r:FOLLOWS]-> (o)"
            "DELETE r "
            "RETURN u.screen_name AS name1, o.screen_name AS name2",
            screen_name1=screen_name1,
            screen_name2=screen_name2)
        return result.single(), result.consume()

    if request.method == 'POST':
        screen_name1 = request.form['screen_name1']
        screen_name2 = request.form['screen_name2']
        db = get_db()
        result, summary = db.execute_write(work, screen_name1, screen_name2)

        if result.get('name1') is None and result.get('name2') is None:
            flash("\nIncorrect usernames !!")
            return redirect(url_for('unfollow'))
        elif result.get('name1') is None:
            flash(f"User {screen_name1} doesn't exists.")
            return redirect(url_for('unfollow'))
        elif result.get('name2') is None:
            flash(f"User {screen_name2} doesn't exists.")
            return redirect(url_for('unfollow'))
        elif summary.counters.relationships_deleted == 0:
            flash(f"User {screen_name1} didn't follow User {screen_name2}.")
        else:
            return redirect(url_for('index'))

    return render_template('unfollow.html')


@app.route('/tweet', methods=['GET', 'POST'])
def tweet():

    def work(tx, screen_name, text):
        mentions = re.findall(r'(?<=@)\w+', text)
        hashtags = re.findall(r'(?<=#)\w+', text)
        created_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        query = (
            "MATCH(u:User{screen_name:$screen_name}) "
            "CREATE (u)-[:POSTS]->(t:Tweet) "
            "SET t.text = $text, t.favorites = 0, t.created_at = DateTime($created_at) "
            "WITH t "
            "UNWIND $hashtags AS tag "
            "MERGE (h:Hashtag{name:tag}) CREATE (t)-[:TAGS]->(h) "
            "WITH t "
            "UNWIND $mentions AS mention "
            "MATCH (m:User{screen_name:mention}) CREATE (t)-[:MENTIONS]->(m) "
            "RETURN t")
        result = tx.run(query,
                        screen_name=screen_name,
                        text=text,
                        created_at=created_at,
                        mentions=mentions,
                        hashtags=hashtags)
        return bool(result.consume().counters.relationships_created)

    if request.method == 'POST':
        screen_name = request.form['screen_name']
        text = request.form['tweet-text']
        db = get_db()
        success = db.execute_write(work, screen_name, text)
        if not success:
            flash(f"User {screen_name} doesn't exists.")
            return redirect(url_for('tweet'))
        return redirect(url_for('index'))

    return render_template('tweet.html')


@app.post('/<id>/delete_tweet/')
def delete_tweet(id):

    def work(tx, t_id):
        return tx.run(
            "MATCH (t:Tweet) "
            "where id(t) = $t_id_int "
            "DETACH DELETE t",
            t_id_int=int(t_id))

    db = get_db()
    db.execute_write(work, id)
    return redirect(url_for('index'))


@app.route('/<id>/<text>/edit_tweet/', methods=['GET', 'POST'])
def edit_tweet(id, text):

    def work(tx, t_id):
        return tx.run(
            "MATCH (t:Tweet) "
            "WHERE id(t) = $t_id_int "
            "SET t.text = $text "
            "RETURN t",
            t_id_int=int(t_id),
            text=text)

    if request.method == 'POST':
        text = request.form['tweet-text']
        db = get_db()
        db.execute_write(work, id)
        return redirect(url_for('index'))

    return render_template('edit_tweet.html', id=id, text=text)


@app.route('/edit/<oldname>', methods=['GET', 'POST'])
def edit_user(oldname):

    def work(tx, name):
        return tx.run(
            "MATCH (u:User{screen_name:$name}) "
            "RETURN u.name as name , u.location as location, u.screen_name as screen_name",
            name=name).single()

    def edit_work(tx, oldname, screen_name, name, location):
        return tx.run(
            "MATCH (u:User{screen_name:$oldname}) "
            "SET u.screen_name = $screen_name, u.name = $name, u.location = $location "
            "RETURN u",
            oldname=oldname,
            screen_name=screen_name,
            name=name,
            location=location)

    db = get_db()
    user_info = db.execute_write(work, oldname)

    if request.method == 'POST':
        screen_name = request.form['screen_name']
        name = request.form['name']
        location = request.form['location']
        user_info = db.execute_write(edit_work, oldname, screen_name, name,
                                     location)

        return redirect(url_for('index'))

    return render_template('edit_user.html', user_info=user_info)


if __name__ == "__main__":
    app.run(host='0.0.0.0', debug=True)
