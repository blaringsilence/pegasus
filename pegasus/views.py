from pegasus import app
import sqlite3
import uuid
import string
import random
from flask import request, session, g, redirect, url_for, abort, render_template, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta



# all the definitions
def get_random_string(length=32):
     return ''.join(random.choice(string.ascii_letters + string.digits) for i in range(length))

def generate_csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = get_random_string()
    return session['_csrf_token']

app.jinja_env.globals['csrf_token'] = generate_csrf_token

def login_user(username):
    session['logged_in'] = True
    session['username'] = username
    cur = g.db.execute('select id from users where username=?', [username]).fetchone()
    uid = cur[0]
    session['userid'] = uid # to register any info in another table where userid is a FK instead of querying every time


def is_owner(boardID, userID):
    cur = g.db.execute('select creatorID from boards where id=?', [boardID]).fetchone()[0]
    if cur == userID:
        return True
    else:
        return False

def is_authorized(boardID):
    access = False
    isOwner = False
    if session.get('logged_in'):
        # not counting in the invitation link logic here
        uid = session['userid']
        # are they the owner?
        if is_owner(boardID, uid):
            access = True
            isOwner = True
        else:
            uemail = g.db.execute('select email from users where id=?', [uid]).fetchone()[0]
            cur2 = g.db.execute('select id from invites where boardID=? and userEmail=?', [boardID, uemail]).fetchone()
            if cur2 is not None:
                access = True
    return {'access':access, 'isOwner':isOwner}




    
# routing (views)
@app.route('/')
def index():
    if session.get('logged_in'):
        email = g.db.execute('select email from users where id=?', [session['userid']]).fetchone()[0].lower()
        cur2 = g.db.execute('select id, title from boards where id in (select boardID from invites where userEmail=?)', [email]).fetchall()
        invitedLi = [dict(id=row[0], title=row[1]) for row in cur2]
        return render_template('show_list.html', invitedBoards=invitedLi)
    else:
        cur = g.db.execute('select username, join_date from users order by id')
        li = [dict(username=row[0], jdate=row[1]) for row in cur.fetchall()]
        return render_template('show_list.html', li=li)

@app.route('/register', methods=['GET', 'POST'])
def register_user():
    if session.get('logged_in'):
        abort(401)
    error = None
    if request.method == 'POST':
        try:
            pw = generate_password_hash(request.form['password'])
            un = request.form['username'].lower()
            em = request.form['email'].lower()
            g.db.execute('insert into users (username, password, email, name) values (?, ?, ?, ?)', [un, pw, em, request.form['name']])
            g.db.commit()
            login_user(un)
            return redirect(url_for('index'))
        except sqlite3.IntegrityError as e:
            if e.args[0][32:] == 'email':
                error = 'Email'
            elif e.args[0][32:] == 'username':
                error = 'Username'
            error = error + ' already in use.'
    return render_template('register.html', error=error)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        abort(401)
    error = None
    if request.method == 'POST':
        cur = g.db.execute('select username, password from users where username=?', [request.form['username'].lower()])
        cur_res = cur.fetchone()
        if cur_res is None:
            error = 'Invalid username'
        else:
            username = cur_res[0]
            pw = cur_res[1]
            if check_password_hash(pw, request.form['password']) == False: # ouch
                error = 'Invalid password'
            else:
                login_user(username)
                flash('Hey there!', 'info')
                return redirect(url_for('index'))
    return render_template('login.html', error=error)

@app.route('/profile')
def show_profile():
    if not session.get('logged_in'):
        abort(401)
    uid = session.get('userid')
    cur = g.db.execute('select name, email from users where id=?', [uid]).fetchone()
    cur2 = g.db.execute('select id, title from boards where creatorID=?', [uid]).fetchall()
    boards = [dict(id=row[0], title=row[1]) for row in cur2]
    return render_template('profile.html', name=cur[0], email=cur[1], boards=boards)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    session.pop('userid', None)
    flash('You go bye bye :(', 'warning')
    return redirect(url_for('index')) # always going there..

@app.route('/new-board', methods=['GET', 'POST'])
def create_board():
    if not session.get('logged_in'):
        abort(401)
    error = None
    if request.method == 'POST':
        try:
            uid = session.get('userid')
            title = request.form['title']
            done_at = datetime.utcnow() + timedelta(days=1)
            g.db.execute('insert into boards (creatorID, title, done_at) values (?, ?, ?)', [uid, title, done_at])
            g.db.commit()
            return redirect(url_for('show_profile'))
        except sqlite3.Error as e:
            error = 'An error occured: ' + e.args[0]
    return render_template('new-board.html', error=error)

@app.route('/board/<boardID>')
def show_board(boardID):
    # first, check if there's even a board
    curB = g.db.execute('select title, created_at, done_at from boards where id=?', [boardID]).fetchone()
    if curB is None:
        abort(404)
    else:
        invite = request.args.get('invite') # ?invite=INVITE_ID
        auth = is_authorized(boardID)
        if invite is None and auth['access']:
            return render_template('show-board.html', title=curB[0], created_at=curB[1], done_at=curB[2], isOwner=auth['isOwner'], boardID=boardID)
        elif invite is not None:
            cur = g.db.execute('select userEmail from invites where id=? and boardID=?', [invite, boardID]).fetchone()
            if cur is None:
                abort(401)
            else:
                return render_template('show-board.html', title=curB[0], created_at=curB[1], done_at=curB[2], email=cur[0], boardID=boardID)
        else:
            abort(401)


# AJAX functions
@app.route('/_validateUsername')
def valUsername():
    un = request.args.get('username', 0, type=str)
    cur = g.db.execute('select id from users where username=?', [un.lower()]).fetchone()
    if cur is None:
        return jsonify(available='true')
    else:
        return jsonify(available='false')

@app.route('/_validateEmail')
def valEmail():
    em = request.args.get('email', 0, type=str)
    cur = g.db.execute('select id from users where email=?', [em.lower()]).fetchone()
    if cur==None:
        return jsonify(available='true')
    else:
        return jsonify(available='false')

@app.route('/_editBoard', methods=['POST'])
def edit_board():
    if not session.get('logged_in'):
        abort(401)
    else: # is logged in
        error = 'None'
        new_token = generate_csrf_token()
        try:
            g.db.execute('update boards set title=? where id=? and creatorID=?', [request.form['title'], int(request.form['boardID']), session['userid']])
            g.db.commit()
        except sqlite3.Error as e:
            error = e.args[0]
        return jsonify(error=error, token=new_token) # and new CSRF token to be used again


@app.route('/_inviteUser', methods=['POST'])
def invite_user():
    em = request.form['email'].lower()
    ty = request.form['type'] # view or edit
    b_id = int(request.form['boardID'])
    user = session['userid']
    inviteID = uuid.uuid4().hex
    error = 'none'
    successful='false'
    if is_owner(b_id, user):
        try:
            g.db.execute('insert into invites (id, userEmail, boardID, type) values (?, ?, ?, ?)', [inviteID, em, b_id, ty])
            g.db.commit()
            successful = 'true'
        except sqlite3.IntegrityError as e:
            error = 'This email has already been invited to this board.'
        except sqlite3.Error as e: # for debugging
            error = e.args[0]
        finally:
            new_token = generate_csrf_token()
    return jsonify(successful=successful, error=error, token=new_token)