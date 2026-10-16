from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"message": "AI银行智能体后端已启动"})

@app.route('/api/bill-analysis')
def bill_analysis():
    return jsonify({
        "status": "账单分析模块待实现",
        "owner": "Claire",
        "features": ["消费分类统计", "异常交易识别", "月度/年度账单报告"]
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)