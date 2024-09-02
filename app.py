import os

from flask import Flask, request, render_template, redirect, url_for, flash, session
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from dash import dcc, html, Input, Output
from datetime import datetime
from decimal import Decimal
import bcrypt
import dash
import plotly.express as px
import pandas as pd

from helpers import login_required

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///manager.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    money = db.Column(db.Numeric(precision=10, scale=2))
    budget = db.Column(db.Numeric(precision=10, scale=2))
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Numeric(precision=10, scale=2), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    transaction_type = db.Column(db.String(10), nullable=False)
    date = db.Column(db.Date, nullable=False)
    description = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# Initialize Dash
dash_app = dash.Dash(
    __name__,
    server=app,
    routes_pathname_prefix='/dash/'
)

# Placeholder layout - will update with data after user is logged in
dash_app.layout = html.Div([
    dcc.Graph(id='bar-chart')
])

@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

@app.route('/')
@login_required
def index():
    user = User.query.filter_by(id=session["user_id"]).first()
    transaction = Transaction.query.filter_by(user_id=session["user_id"]).order_by(Transaction.id.desc()).limit(10).all()
    return render_template('index.html', user=user, transactions=transaction)

@app.route('/graphs')
@login_required
def graphs():
    return redirect('/dash/')

@dash_app.callback(
    Output('bar-chart', 'figure'),
    [Input('bar-chart', 'id')]  # Dummy input just to trigger the callback
)
def update_graph(_):
    user_id = session.get("user_id")
    if user_id:
        # Query the transactions for the logged-in user
        transactions = Transaction.query.filter_by(user_id=user_id).all()

        # Convert to DataFrame
        df = pd.DataFrame([{
            "Category": t.category,
            "Amount": float(t.amount)  # Convert Decimal to float
        } for t in transactions])

        # Create a bar chart using Plotly
        fig = px.bar(df, x="Category", y="Amount", title="Spending by Category")
        return fig

    # Return an empty figure if no data
    return px.bar(title="No data available")

@app.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if request.method == 'POST':
        amount = Decimal(request.form['amount'])
        category = request.form['category']
        transaction_type = request.form['type']
        date = request.form['date']
        description = request.form['description']
        transaction_date = datetime.strptime(date, '%Y-%m-%d').date()
        id = session["user_id"]
        
        new_transaction = Transaction(amount=amount, category=category, transaction_type=transaction_type, date=transaction_date, user_id=id, description=description)

        # Update the user's money from income or expense
        user = User.query.filter_by(id=id).first()
        if transaction_type == 'income':
            user.money += amount
            db.session.add(user)
        else:
            user.money -= amount
            db.session.add(user)


        db.session.add(new_transaction)
        db.session.commit()

        return redirect('/')
    else:        
        return render_template('add.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password'].encode('utf-8')
        confirm = request.form['confirmation'].encode('utf-8')
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'danger')
            return redirect(url_for('register'))
        elif confirm != password:
            flash('Password and Confirmation do not match', 'danger')
            return redirect(url_for('register'))
        
        hashed_password = bcrypt.hashpw(password, bcrypt.gensalt())
        
        new_user = User(username=username, password=hashed_password, money=0)
        
        db.session.add(new_user)
        db.session.commit()

        user = User.query.filter_by(username=username).first()
        session["user_id"] = user.id
        
        return redirect("/")
    else:
        return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():

    session.clear()

    if request.method == 'POST':
        if not request.form.get("username"):
            return render_template('login.html')
        elif not request.form.get("password"):
            return render_template("login.html")

        username = request.form['username']
        password = request.form['password'].encode('utf-8')
        
        user = User.query.filter_by(username=username).first()
        if user and bcrypt.checkpw(password, user.password):
            session["user_id"] = user.id
            return redirect("/")
        else:
            return redirect(url_for("login"))
    else:
        return render_template('login.html')
    
@app.route("/logout")
def logout():
    """Log user out"""
    session.clear()

    return redirect("/")


if __name__ == '__main__':
    app.run(debug=True)