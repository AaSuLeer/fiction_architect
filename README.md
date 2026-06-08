# fiction_architect

长篇网文小说架构工作台。默认使用 SQLite，拖进 VSCode 后打开 `app/main.py` 点击运行即可启动。

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

## VSCode

1. 将 `fiction_architect` 文件夹直接拖入 VSCode。
2. 复制 `.env.example` 为 `.env`。
3. 打开 `app/main.py`，点击 Run Python File。

默认 `DB_BACKEND=sqlite`，无需数据库服务。`SQLITE_PATH` 留空时数据库会放到当前 Python 可写的临时目录，避免 VSCode 运行时因为项目目录权限导致启动失败；需要持久保存时可改成你有权限的绝对路径。切换 MySQL 时在 `.env` 设置：

```env
DB_BACKEND=mysql
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=你的账号
MYSQL_PASSWORD=你的密码
MYSQL_DATABASE=fiction_architect
```

## 智谱 API

在 `.env` 中填写：

```env
ZHIPUAI_API_KEY=你的key
ZHIPUAI_MODEL=glm-4.5
LLM_MODE=zhipu
```

没有 key 时系统使用 mock writer/editor 跑通完整管道。

## 测试

```powershell
python -m unittest discover -s tests
```

MySQL 集成测试只有在 `DB_BACKEND=mysql` 且数据库可连接时运行。
