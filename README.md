# Boring, simple threaded server

```sh
pip install requests
echo server.py | entr -r python server.py
# http://localhost:8000/v/<gdrive_file_id>
```

# Shiny (read: weird) async server

```sh
pip install starlette aiohttp uvicorn
uvicorn asyncserver:app --reload
# http://localhost:8000/v/<gdrive_file_id>
```
