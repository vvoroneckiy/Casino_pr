import sys
import json
import os
import urllib.request
import urllib.parse
import urllib.error

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
API_BASE = "https://api.github.com"
REPO = "vvoroneckiy/Casino_pr"


def github_request(method, path, data=None):
    url = f"{API_BASE}{path}"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "casino-mcp",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode()}"}
    except Exception as e:
        return {"error": str(e)}


def list_issues(state="open"):
    result = github_request("GET", f"/repos/{REPO}/issues?state={state}&per_page=10")
    if isinstance(result, list):
        return [{"number": i["number"], "title": i["title"], "state": i["state"]} for i in result]
    return result


def create_issue(title, body=""):
    return github_request("POST", f"/repos/{REPO}/issues", {"title": title, "body": body})


def get_repo():
    result = github_request("GET", f"/repos/{REPO}")
    if isinstance(result, dict) and "error" not in result:
        return {
            "name": result["full_name"],
            "stars": result["stargazers_count"],
            "open_issues": result["open_issues_count"],
            "description": result.get("description", ""),
            "url": result["html_url"],
        }
    return result


def search_code(query):
    result = github_request("GET", f"/search/code?q={urllib.parse.quote(query)}+repo:{REPO}&per_page=5")
    if isinstance(result, dict) and "items" in result:
        return [{"file": i["path"], "url": i["html_url"]} for i in result["items"]]
    return result


def list_releases():
    result = github_request("GET", f"/repos/{REPO}/releases?per_page=5")
    if isinstance(result, list):
        return [{"tag": r["tag_name"], "name": r["name"]} for r in result]
    return result


TOOLS = [
    {
        "name": "get_repo",
        "description": "Информация о GitHub репозитории Casino_pr",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_issues",
        "description": "Список открытых issue в репозитории",
        "inputSchema": {
            "type": "object",
            "properties": {
                "state": {"type": "string", "description": "Фильтр: open, closed, all (по умолчанию open)"}
            },
            "required": [],
        },
    },
    {
        "name": "create_issue",
        "description": "Создать новый issue в репозитории",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Заголовок issue"},
                "body": {"type": "string", "description": "Описание issue"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "search_code",
        "description": "Поиск кода в репозитории",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Поисковый запрос"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_releases",
        "description": "Список релизов репозитория",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
]


def handle_tool_call(name, args):
    try:
        if name == "get_repo":
            return get_repo()
        elif name == "list_issues":
            return list_issues(args.get("state", "open"))
        elif name == "create_issue":
            return create_issue(args["title"], args.get("body", ""))
        elif name == "search_code":
            r = search_code(args["query"])
            if isinstance(r, list):
                files = "\n".join(f"- {f['file']}" for f in r) if r else "Ничего не найдено"
                return {"result": f"Найденные файлы:\n{files}"}
            return r
        elif name == "list_releases":
            return list_releases()
        return {"error": f"Неизвестный инструмент: {name}"}
    except Exception as e:
        return {"error": str(e)}


def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            req = json.loads(line.strip())
        except json.JSONDecodeError:
            continue

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method == "initialize":
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "github-mcp", "version": "1.0.0"},
                },
            }, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        elif method == "tools/list":
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": req_id,
                "result": {"tools": TOOLS},
            }, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        elif method == "tools/call":
            result = handle_tool_call(params["name"], params.get("arguments", {}))
            if "error" in result:
                content = [{"type": "text", "text": str(result["error"])}]
            elif "result" in result:
                content = [{"type": "text", "text": result["result"]}]
            else:
                content = [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": req_id,
                "result": {"content": content},
            }, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        elif method == "shutdown":
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": {}}) + "\n")
            sys.stdout.flush()
            break


if __name__ == "__main__":
    main()
