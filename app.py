from flask import Flask, render_template, request, jsonify
from core.tools import get_balance, get_transactions, execute_transfer

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

# --- API Endpoints ---

@app.route('/api/balance', methods=['GET'])
def api_balance():
    return jsonify(get_balance())

@app.route('/api/transactions', methods=['GET'])
def api_transactions():
    category = request.args.get('category')
    return jsonify(get_transactions(category))

@app.route('/api/transfer', methods=['POST'])
def api_transfer():
    data = request.json
    amount = float(data.get('amount', 0))
    recipient = data.get('recipient', 'Unknown')
    return jsonify(execute_transfer(amount, recipient))

if __name__ == '__main__':
    app.run(debug=True, port=5000)