import os

from flask import Flask, request, render_template, redirect, url_for, flash, session
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from decimal import Decimal
from sqlalchemy import Enum, func, case
import bcrypt

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


@app.route("/graphs")
@login_required
def graphs():
    user_id = session["user_id"]

    # Get all transactions grouped by date
    results = (
    db.session.query(
        Transaction.date,
        func.sum(
            case(
                (Transaction.transaction_type == "income", Transaction.amount),
                else_=0
            )
        ).label("income"),
        func.sum(
            case(
                (Transaction.transaction_type == "expense", Transaction.amount),
                else_=0
            )
        ).label("expense"),
    )
    .filter(Transaction.user_id == user_id)
    .group_by(Transaction.date)
    .order_by(Transaction.date)
    .all()
    )

    # Convert query results to list of dicts for JSON
    chart_data = [
        {
            "date": r.date.strftime("%Y-%m-%d"),
            "income": float(r.income),
            "expense": float(r.expense),
        }
        for r in results
    ]

    return render_template("charts.html", chart_data=chart_data)


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


def seed_database():
    # Check if there's an existing user or create one
    user = User.query.filter_by(username='testuser').first()
    
    if not user:
        # Create a dummy user for the seeding process
        user = User(username='testuser', password=bcrypt.hashpw('password'.encode('utf-8'), bcrypt.gensalt()), money=Decimal('0'))
        db.session.add(user)
        db.session.commit()

    # Get the user ID of the dummy user
    current_user_id = user.id

    # Get income and expense categories
    salary_category = Category.query.filter_by(name='Salary').first()
    freelancing_category = Category.query.filter_by(name='Freelancing').first()
    food_category = Category.query.filter_by(name='Food').first()
    rent_category = Category.query.filter_by(name='Rent').first()
    utilities_category = Category.query.filter_by(name='Utilities').first()
    entertainment_category = Category.query.filter_by(name='Entertainment').first()

    # Generate transactions for two years (2023 and 2024)
    transactions = [
        # Income for 2023
        Transaction(amount=Decimal('3000'), category_id=salary_category.id, transaction_type='income', date=datetime(2023, 1, 1).date(), description='January Salary', user_id=current_user_id),
        Transaction(amount=Decimal('3000'), category_id=salary_category.id, transaction_type='income', date=datetime(2023, 2, 1).date(), description='February Salary', user_id=current_user_id),
        Transaction(amount=Decimal('3200'), category_id=freelancing_category.id, transaction_type='income', date=datetime(2023, 3, 5).date(), description='Freelancing Income', user_id=current_user_id),

        # Expenses for 2023
        Transaction(amount=Decimal('1000'), category_id=rent_category.id, transaction_type='expense', date=datetime(2023, 1, 1).date(), description='January Rent', user_id=current_user_id),
        Transaction(amount=Decimal('200'), category_id=food_category.id, transaction_type='expense', date=datetime(2023, 1, 15).date(), description='Groceries', user_id=current_user_id),
        Transaction(amount=Decimal('150'), category_id=utilities_category.id, transaction_type='expense', date=datetime(2023, 2, 10).date(), description='Electricity Bill', user_id=current_user_id),
        Transaction(amount=Decimal('250'), category_id=entertainment_category.id, transaction_type='expense', date=datetime(2023, 3, 20).date(), description='Concert', user_id=current_user_id),

        # Income for 2024
        Transaction(amount=Decimal('3500'), category_id=salary_category.id, transaction_type='income', date=datetime(2024, 1, 1).date(), description='January Salary', user_id=current_user_id),
        Transaction(amount=Decimal('3500'), category_id=salary_category.id, transaction_type='income', date=datetime(2024, 2, 1).date(), description='February Salary', user_id=current_user_id),
        Transaction(amount=Decimal('3700'), category_id=freelancing_category.id, transaction_type='income', date=datetime(2024, 3, 10).date(), description='Freelancing Income', user_id=current_user_id),

        # Expenses for 2024
        Transaction(amount=Decimal('1100'), category_id=rent_category.id, transaction_type='expense', date=datetime(2024, 1, 1).date(), description='January Rent', user_id=current_user_id),
        Transaction(amount=Decimal('250'), category_id=food_category.id, transaction_type='expense', date=datetime(2024, 1, 15).date(), description='Groceries', user_id=current_user_id),
        Transaction(amount=Decimal('175'), category_id=utilities_category.id, transaction_type='expense', date=datetime(2024, 2, 10).date(), description='Electricity Bill', user_id=current_user_id),
        Transaction(amount=Decimal('300'), category_id=entertainment_category.id, transaction_type='expense', date=datetime(2024, 3, 20).date(), description='Movie Night', user_id=current_user_id)
    ]

    # Add transactions to the database
    db.session.add_all(transactions)
    db.session.commit()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_categories()      
        seed_database()
    app.run(debug=True)