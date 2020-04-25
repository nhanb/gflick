# Boring threaded server

```sh
pip install urllib3
python server.py
# http://localhost:8000/v/<gdrive_file_id>
```

# Shiny (crazy) async server

```sh
pip install starlette aiohttp uvicorn
uvicorn asyncserver:app --reload
# http://localhost:8000/v/<gdrive_file_id>
```
