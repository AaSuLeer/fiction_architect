# fiction_architect

面向长期网文生产的作家工作台。项目默认 SQLite 可直接运行，也支持在 `.env` 中切换 MySQL 和智谱 API。

## 快速启动

```powershell
cd D:\fiction_company\fiction_architect
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python app\main.py
```

打开：

```text
http://127.0.0.1:8010
```

VSCode 使用方式：

1. 将 `fiction_architect` 文件夹拖入 VSCode。
2. 复制 `.env.example` 为 `.env`，只在 `.env` 写入数据库密码和 API key。
3. 打开 `app/main.py`，点击 Run Python File。

## 主要入口

- `/books`：正式书库，只显示 active 作品。
- `/archive`：归档作品与演示书，支持恢复和二次确认永久删除。
- `/books/{book_id}`：单本书工作台，维护封面、简介、作者资源、编辑资源、生产入口和导出。
- `/books/{book_id}/outline`：文风、字数、人称、大纲、卷纲、单元细纲、章节细纲。
- `/books/{book_id}/chapters`：生成正文、批量生成三章、拒稿后重写、人工通过。
- `/resources/authors`：作者资源坞，支持 JSON 导入导出。
- `/resources/editors`：编辑资源坞，支持 JSON 导入导出。
- `/books/{book_id}/continuity`：连续性工作室，多级记忆与周期压缩。
- `/debug`：按当前书籍的作者/编辑资源调试正文。
- `/exports`：DOCX 导出记录。

## 配置

`.env.example` 只保留占位。请新建 `.env`：

```env
DB_BACKEND=sqlite
SQLITE_PATH=

MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=
MYSQL_PASSWORD=
MYSQL_DATABASE=fiction_architect

ZHIPUAI_API_KEY=
ZHIPUAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4/chat/completions
ZHIPUAI_MODEL=glm-4.5
ZHIPUAI_TIMEOUT=60
LLM_MODE=
```

填入 `ZHIPUAI_API_KEY` 后默认使用智谱；只有显式设置 `LLM_MODE=mock` 才使用本地 mock writer。

## 测试

```powershell
python -m unittest discover -s tests
```

安全约束：

- `.env`、数据库、上传封面、DOCX 导出不提交 Git。
- MySQL 密码和 API key 只在本地 `.env` 中配置。
- DOCX 导出优先使用 `python-docx`；环境缺失时会用内置兜底生成基础 `.docx`。
