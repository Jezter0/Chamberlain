from flask import Flask, request, render_template, redirect, url_for, flash
import bcrypt

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

users = {}

@app.route('/')
def index():
    return render_template('index.html')

app.run(debug=True)