"""
Cấu hình chung cho test: dùng DB lịch sử tạm thời để không đụng tới history.db thật.
Phải set biến môi trường TRƯỚC khi app.main / app.storage được import.
"""
import os
import tempfile

_tmp_db = os.path.join(tempfile.gettempdir(), "chatbot_test_history.db")
os.environ["HISTORY_DB"] = _tmp_db
