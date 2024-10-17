import os

from flask import Flask, request, render_template, redirect, url_for, flash, session
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from dash import dcc, html, Input, Output
from datetime import datetime
from decimal import Decimal
from sqlalchemy import Enum
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
    budget = db.Column(db.Numeric(precision=10, scale=2))
    money = db.Column(db.Numeric(precision=10, scale=2), default=0)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

    transactions = db.relationship('Transaction', backref='user', lazy=True)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    type = db.Column(Enum('income', 'expense', name='category_type'), nullable=False)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Numeric(precision=10, scale=2), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    transaction_type = db.Column(Enum('income', 'expense', name='transaction_type'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    description = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    category = db.relationship('Category', backref='transactions')

def seed_categories():
    income_categories = [
        'Salary', 'Freelancing', 'Business Profits', 'Dividends'
    ]
    
    expense_categories = [
        'Groceries', 'Food', 'Rent', 'Transportation', 'Utilities', 
        'Entertainment', 'Health', 'Gifts', 'Investments'
    ]
    
    for name in income_categories:
        if not Category.query.filter_by(name=name).first():
            category = Category(name=name, type='income')  
            db.session.add(category)
    
    for name in expense_categories:
        if not Category.query.filter_by(name=name).first():
            category = Category(name=name, type='expense')
            db.session.add(category)

    db.session.commit()

# Initialize Dash
dash_app = dash.Dash(
    __name__,
    server=app,
    routes_pathname_prefix='/dash/'
)

# Placeholder layout - will update with data after user is logged in
dash_app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    dcc.Store(id='user-id'),
    html.Div([
        dcc.Graph(id='income-pie-chart'),
        dcc.Graph(id='expense-pie-chart'),
    ])
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
    transactions = db.session.query(Transaction).join(Category).filter(
        Transaction.user_id == session["user_id"]
    ).order_by(Transaction.id.desc()).limit(10).all()
    return render_template('index.html', user=user, transactions=transactions)

@app.route('/graphs')
@login_required
def graphs():
    return redirect(f'/dash/?user_id={session["user_id"]}')

@dash_app.callback(
    [Output('income-pie-chart', 'figure'),
     Output('expense-pie-chart', 'figure')],
    [Input('url', 'search')]
)
def update_graph(search):
    user_id = parse_user_id_from_url(search)
    if user_id:
        # Query the transactions for the logged-in user
        transactions = Transaction.query.filter_by(user_id=user_id).all()

        if transactions:
            # Separate income and expense transactions
            income_transactions = [t for t in transactions if t.transaction_type == 'income']
            expense_transactions = [t for t in transactions if t.transaction_type == 'expense']

            # Create pie chart for income transactions
            if income_transactions:
                df_income = pd.DataFrame([{
                    "Category": t.category.name,
                    "Amount": float(t.amount)  
                } for t in income_transactions])

                # Debug: Print DataFrame to check if it has data
                print("Income DataFrame:", df_income)

                fig_income = px.pie(df_income, names="Category", values="Amount", title="Income by Category")
            else:
                fig_income = px.pie(title="No income data available")

            # Create pie chart for expense transactions
            if expense_transactions:
                df_expense = pd.DataFrame([{
                    "Category": t.category.name,
                    "Amount": float(t.amount)
                } for t in expense_transactions])

                # Debug: Print DataFrame to check if it has data
                print("Expense DataFrame:", df_expense)

                fig_expense = px.pie(df_expense, names="Category", values="Amount", title="Expenses by Category")
            else:
                fig_expense = px.pie(title="No expense data available")

            return fig_income, fig_expense

    # Return empty figures if no data
    return px.pie(title="No data available"), px.pie(title="No data available")

def parse_user_id_from_url(search):
    from urllib.parse import parse_qs
    query_params = parse_qs(search[1:])
    return query_params.get('user_id', [None])[0]

@app.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if request.method == 'POST':
        amount = Decimal(request.form['amount'])
        category_id = request.form['category']
        transaction_type = request.form['type']
        date = request.form['date']
        description = request.form['description']
        transaction_date = datetime.strptime(date, '%Y-%m-%d').date()
        id = session["user_id"]

        if transaction_type == 'income' and Category.query.get(category_id).type != 'income':
            flash('Invalid category for income', 'danger')
            return redirect('/add')

        if transaction_type == 'expense' and Category.query.get(category_id).type != 'expense':
            flash('Invalid category for expense', 'danger')
            return redirect('/add')
        
        new_transaction = Transaction(
            amount=amount, 
            category_id=category_id, 
            transaction_type=transaction_type, 
            date=transaction_date, 
            user_id=id, 
            description=description
        )

        # Update the user's money from income or expense
        user = User.query.filter_by(id=id).first()
        if transaction_type == 'income':
            user.money += amount
        else:
            user.money -= amount

        db.session.add(user)
        db.session.add(new_transaction)
        db.session.commit()

        return redirect('/')
    else:        
        income_categories = Category.query.filter_by(type='income').all()
        expense_categories = Category.query.filter_by(type='expense').all()
        return render_template('add.html', income_categories=income_categories, expense_categories=expense_categories)
    
    
@app.route('/edit/<int:transaction_id>', methods=['GET', 'POST'])
@login_required
def edit_transaction(transaction_id):
    transaction = Transaction.query.get(transaction_id)
    if request.method == 'POST':
        transaction.amount = request.form['amount']
        transaction.description = request.form['description']
        transaction.date = request.form['date']
        db.session.commit()
        return redirect('/')
    
    return render_template('edit.html', transaction=transaction)


@app.route('/delete/<int:transaction_id>', methods=['POST'])
@login_required
def delete_transaction(transaction_id):
    transaction = Transaction.query.get(transaction_id)
    
    if transaction and transaction.user_id == session["user_id"]:  
        user = User.query.filter_by(id=session["user_id"]).first()
        
        if transaction.transaction_type == 'income':
            user.money -= transaction.amount
        else:
            user.money += transaction.amount
        
        db.session.delete(transaction)
        db.session.add(user)
        db.session.commit()
        
    return redirect('/')


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
    with app.app_context():
        db.create_all()
        seed_categories()      
    app.run(debug=True)