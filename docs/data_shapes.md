# Data Shapes Contract (数据结构规范)

All backend tools in `core/tools.py` MUST return exactly this dictionary format. 
(所有后端工具必须返回这个固定格式)

## Standard Return Format
```json
{
  "status": "success", 
  "data": { ... }, 
  "txn_id": "TXN-12345", 
  "error": null
}

Field Definitions:
status (string): Must be "success" or "failed".

data (dict): The actual payload.

For queries (like checking balance), put the data here.

For actions (like transferring), put the receipt details here.

txn_id (string or null): Only used for money-moving actions (like transfers). Set to null for queries.

error (string or null): If status is "failed", put the error message here (e.g., "余额不足"). Otherwise, set to null.

