
import os
from urllib.parse import quote
import re
from time import time

from flask import Flask, render_template, request, redirect, url_for, flash, session
from dotenv import load_dotenv
import requests
import markdown
from markdown.extensions import fenced_code, tables, nl2br, sane_lists
from pygments import highlight
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.formatters import HtmlFormatter
from pygments.util import ClassNotFound
import bleach
from datetime import datetime
import pytz

load_dotenv()

PROJECTS = [p.strip() for p in os.getenv('PROJECTS','').split(',') if p.strip()]
PROJECT_ALIASES = [p.strip() for p in os.getenv('PROJECT_ALIASES','').split(',') if p.strip()]

DEFAULT_GITLAB_URL = os.getenv("GITLAB_URL", "https://gitlab.com").rstrip("/")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-please")

app = Flask(__name__)
app.secret_key = SECRET_KEY

PROJECT_CACHE = {}
CACHE_TTL = 3600

ALLOWED_TAGS = [
    'a', 'abbr', 'acronym', 'b', 'blockquote', 'code', 'em', 'i', 'li', 'ol', 'pre', 'strong', 'ul',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'br', 'span', 'div', 'img', 'table', 'thead', 'tbody',
    'tr', 'th', 'td', 'hr', 'del', 'ins', 'sup', 'sub', 'dl', 'dt', 'dd', 'kbd', 'q', 's', 'strike',
    'details', 'summary', 'input'
]
ALLOWED_ATTRIBUTES = {
    '*': ['class', 'id', 'style'],
    'a': ['href', 'title', 'rel', 'target'],
    'img': ['src', 'alt', 'title', 'width', 'height'],
    'code': ['class'],
    'pre': ['class'],
    'span': ['class'],
    'div': ['class', 'data-*'],
    'input': ['type', 'disabled', 'checked'],
    'details': ['open'],
}

class CodeBlockExtension(markdown.Extension):
    def extendMarkdown(self, md):
        md.preprocessors.register(CodeBlockPreprocessor(md), 'code_block', 25)

class CodeBlockPreprocessor(markdown.preprocessors.Preprocessor):
    def run(self, lines):
        new_lines = []
        in_code_block = False
        code_lines = []
        lang = None
        
        for line in lines:
            if line.strip().startswith('```'):
                if not in_code_block:
                    in_code_block = True
                    lang = line.strip()[3:].strip() or 'text'
                    code_lines = []
                else:
                    in_code_block = False
                    code = '\n'.join(code_lines)
                    highlighted = highlight_code(code, lang)
                    new_lines.append(highlighted)
                    code_lines = []
                    lang = None
            elif in_code_block:
                code_lines.append(line)
            else:
                new_lines.append(line)
        
        return new_lines

def highlight_code(code, lang):
    try:
        lexer = get_lexer_by_name(lang, stripall=True)
    except ClassNotFound:
        try:
            lexer = guess_lexer(code)
        except:
            from pygments.lexers import TextLexer
            lexer = TextLexer()
    
    formatter = HtmlFormatter(cssclass='highlight', style='github-dark')
    return highlight(code, lexer, formatter)

def render_markdown(text):
    if not text:
        return ''
    
    md = markdown.Markdown(
        extensions=[
            'fenced_code',
            'tables',
            'nl2br',
            'sane_lists',
            CodeBlockExtension(),
        ],
        extension_configs={
            'fenced_code': {
                'lang_prefix': 'language-',
            }
        }
    )
    
    html = md.convert(text)
    html = process_gitlab_references(html)
    html = process_task_lists(html)
    
    return bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        strip=False
    )

def process_gitlab_references(html):
    html = re.sub(r'#(\d+)', r'<a href="#\1" class="gfm gfm-issue">#\1</a>', html)
    html = re.sub(r'!(\d+)', r'<a href="!\1" class="gfm gfm-merge_request">!\1</a>', html)
    html = re.sub(r'@([\w\-]+)', r'<a href="@\1" class="gfm gfm-user">@\1</a>', html)
    return html

def process_task_lists(html):
    html = re.sub(
        r'<li>\s*\[ \]\s*',
        r'<li class="task-list-item"><input type="checkbox" class="task-list-item-checkbox" disabled> ',
        html
    )
    html = re.sub(
        r'<li>\s*\[x\]\s*',
        r'<li class="task-list-item"><input type="checkbox" class="task-list-item-checkbox" disabled checked> ',
        html,
        flags=re.IGNORECASE
    )
    return html

def format_datetime_jst(dt_str):
    if not dt_str:
        return None
    try:
        if 'T' in dt_str:
            dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        else:
            dt = datetime.strptime(dt_str, '%Y-%m-%d')
            dt = dt.replace(tzinfo=pytz.UTC)
        
        jst = pytz.timezone('Asia/Tokyo')
        dt_jst = dt.astimezone(jst)
        
        return dt_jst.strftime('%Y年%m月%d日 %H:%M')
    except Exception:
        return dt_str

def format_date_jst(date_str):
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        return dt.strftime('%Y年%m月%d日')
    except Exception:
        return date_str

app.jinja_env.filters['format_datetime_jst'] = format_datetime_jst
app.jinja_env.filters['format_date_jst'] = format_date_jst

def current_gl():
    return session.get("gl") or {}

def gl_headers():
    gl = current_gl()
    token = gl.get("token")
    return {"PRIVATE-TOKEN": token} if token else {}

def gl_url():
    gl = current_gl()
    return (gl.get("url") or DEFAULT_GITLAB_URL).rstrip("/")

def gl_get(path, params=None):
    url = f"{gl_url()}/api/v4{path}"
    r = requests.get(url, headers=gl_headers(), params=params or {}, timeout=30)
    r.raise_for_status()
    return r

def gl_get_all(path, params=None):
    params = dict(params or {})
    page = 1
    per_page = int(params.get("per_page", 100))
    params["per_page"] = per_page
    results = []
    while True:
        params["page"] = page
        resp = gl_get(path, params=params)
        chunk = resp.json()
        if isinstance(chunk, list):
            results.extend(chunk)
        else:
            return chunk
        nxt = resp.headers.get("X-Next-Page")
        if not nxt:
            break
        try:
            page = int(nxt)
        except Exception:
            page += 1
    return results

def gl_post(path, data=None, json_data=None):
    url = f"{gl_url()}/api/v4{path}"
    r = requests.post(url, headers=gl_headers(), data=(None if json_data else (data or {})), json=(json_data or None), timeout=30)
    r.raise_for_status()
    return r

def gl_graphql(query, variables=None):
    url = f"{gl_url()}/api/graphql"
    payload = {'query': query}
    if variables:
        payload['variables'] = variables
    r = requests.post(url, headers=gl_headers(), json=payload, timeout=30)
    r.raise_for_status()
    return r.json()

def resolve_project_id(project):
    if project.isdigit():
        return project
    encoded = quote(project, safe="")
    r = gl_get(f"/projects/{encoded}")
    return str(r.json()["id"])

def login_required():
    gl = current_gl()
    return bool(gl.get("token"))

@app.route("/")
def root():
    if login_required():
        return redirect(url_for("list_issues"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        url = (request.form.get("url") or DEFAULT_GITLAB_URL).rstrip("/")
        token = (request.form.get("token") or "").strip()
        default_project = (request.form.get("project") or "").strip()

        if not token:
            flash("トークンを入力してください。")
            return redirect(url_for("login"))

        try:
            r = requests.get(f"{url}/api/v4/user", headers={"PRIVATE-TOKEN": token}, timeout=20)
            r.raise_for_status()
            user = r.json()
        except Exception as e:
            flash(f"ログイン失敗: トークン検証に失敗しました（{e}）")
            return redirect(url_for("login"))

        session["gl"] = {
            "url": url,
            "token": token,
            "default_project": default_project,
            "username": user.get("username", "?"),
            "user_id": user.get("id"),
        }
        flash(f"ログイン成功: @{user.get('username')}")
        
        next_url = session.pop('next_url', None)
        if next_url:
            return redirect(next_url)
        return redirect(url_for("list_issues"))

    return render_template("login.html", default_url=DEFAULT_GITLAB_URL)

@app.route("/logout")
def logout():
    session.pop("gl", None)
    flash("ログアウトしました。")
    return redirect(url_for("login"))

@app.route("/select")
def index():
    if not login_required():
        session['next_url'] = request.url
        return redirect(url_for("login"))
    gl = current_gl()
    return render_template("index.html", default_project=gl.get("default_project",""), base_url=gl_url(), projects=get_project_list())

@app.route("/clear_cache")
def clear_project_cache():
    if not login_required():
        return redirect(url_for("login"))
    
    gl = current_gl()
    user_id = gl.get('user_id')
    cache_key = f'projects_{user_id}'
    
    if cache_key in PROJECT_CACHE:
        del PROJECT_CACHE[cache_key]
    
    flash('プロジェクトリストのキャッシュをクリアしました。')
    return redirect(url_for('index'))

@app.route("/projects/roadmap")
def roadmap():
    if not login_required():
        session['next_url'] = request.url
        return redirect(url_for("login"))

    group_path = 'minma-tech'
    
    try:
        query = '''
        query {
          group(fullPath: "minma-tech") {
            id
            epics(first: 50, state: opened) {
              nodes {
                id
                iid
                title
                state
                webUrl
                description
                startDate
                dueDate
                descendantCounts {
                  openedIssues
                  closedIssues
                }
                issues {
                  nodes {
                    id
                    iid
                    title
                    state
                    webUrl
                    createdAt
                    updatedAt
                    dueDate
                    projectId
                    assignees {
                      nodes {
                        name
                        username
                        avatarUrl
                      }
                    }
                    labels {
                      nodes {
                        title
                        color
                      }
                    }
                  }
                }
              }
            }
          }
        }
        '''
        
        result = gl_graphql(query)
        
        if 'errors' in result:
            error_msg = ', '.join([e.get('message', str(e)) for e in result['errors']])
            flash(f'GraphQLエラー: {error_msg}')
            return redirect(url_for('index'))
        
        epics = result.get('data', {}).get('group', {}).get('epics', {}).get('nodes', [])
        
        roadmap_data = []
        for epic in epics:
            children = epic.get('issues', {}).get('nodes', [])
            counts = epic.get('descendantCounts', {})
            
            opened_count = counts.get('openedIssues', 0)
            closed_count = counts.get('closedIssues', 0)
            total_count = opened_count + closed_count
            progress = int((closed_count / total_count * 100)) if total_count > 0 else 0
            
            roadmap_data.append({
                'epic': epic,
                'start_date': epic.get('startDate'),
                'due_date': epic.get('dueDate'),
                'children': children,
                'opened_count': opened_count,
                'closed_count': closed_count,
                'total_count': total_count,
                'progress': progress
            })
        
    except requests.HTTPError as e:
        flash(f'HTTPエラー: {e.response.status_code} - {e.response.text[:200]}')
        return redirect(url_for('index'))
    except Exception as e:
        flash(f'ロードマップの取得に失敗しました: {e}')
        return redirect(url_for('index'))

    return render_template('roadmap.html', roadmap_data=roadmap_data, group_path=group_path)

@app.route("/projects/issues")
def list_issues():
    if not login_required():
        session['next_url'] = request.url
        return redirect(url_for("login"))

    gl = current_gl()
    project = request.args.get("project") or gl.get("default_project","")
    if not project:
        flash("プロジェクトのパスまたはIDを入力してください (e.g., group/subgroup/repo or 12345).")
        return redirect(url_for("index"))

    try:
        project_id = resolve_project_id(project)
    except Exception as e:
        flash(f"プロジェクト解決に失敗しました: {e}")
        return redirect(url_for("index"))

    page = request.args.get("page", "1")
    try:
        resp = gl_get(f"/projects/{project_id}/issues", params={"page": page, "per_page": 20, "order_by": "created_at", "sort": "desc", "issue_type": "issue", "search": request.args.get("q") or "", "in": "title,description"})
        issues = resp.json()
        next_page = resp.headers.get("X-Next-Page") or None
        prev_page = resp.headers.get("X-Prev-Page") or None
    except Exception as e:
        flash(f"課題一覧の取得に失敗しました: {e}")
        return redirect(url_for("index"))

    label_map = get_label_color_map(project_id)
    return render_template("issues.html", issues=issues, project_id=project_id, page=page, next_page=next_page, prev_page=prev_page, label_map=label_map)

@app.route("/projects/<project_id>/issues/<int:iid>")
def view_issue(project_id, iid: int):
    if not login_required():
        session['next_url'] = request.url
        return redirect(url_for("login"))
    try:
        issue_resp = gl_get(f"/projects/{project_id}/issues/{iid}")
        issue = issue_resp.json()
        
        if issue.get('description'):
            issue['description_html'] = render_markdown(issue['description'])
        
        notes = gl_get_all(
            f"/projects/{project_id}/issues/{iid}/notes",
            params={"sort": "asc", "per_page": 100}
        )
        
        for note in notes:
            if note.get('body'):
                note['body_html'] = render_markdown(note['body'])
        
        try:
            links = gl_get_all(f"/projects/{project_id}/issues/{iid}/links", params={"per_page": 100})
        except Exception:
            links = []
        label_map = get_label_color_map(project_id)
    except Exception as e:
        flash(f"課題詳細の取得に失敗しました: {e}")
        return redirect(url_for("list_issues"))

    return render_template(
        "issue.html",
        issue=issue,
        notes=notes,
        links=links,
        label_map=label_map,
        project_id=project_id,
    )


@app.route("/projects/<project_id>/issues/<int:iid>/comment", methods=["POST"])
def comment_issue(project_id, iid: int):
    if not login_required():
        session['next_url'] = request.url
        return redirect(url_for("login"))

    body = (request.form.get("body") or "").strip()
    if not body:
        flash("コメント本文を入力してください。")
        return redirect(url_for("view_issue", project_id=project_id, iid=iid))

    try:
        resp = gl_post(f"/projects/{project_id}/issues/{iid}/notes", json_data={"body": body})
        flash("コメントを投稿しました。")
    except requests.HTTPError as he:
        err = he.response
        try:
            detail = err.json()
        except Exception:
            detail = err.text
        flash(f"コメント投稿に失敗しました: HTTP {err.status_code} — {detail}")
    except Exception as e:
        flash(f"コメント投稿に失敗しました: {e}")

    return redirect(url_for("view_issue", project_id=project_id, iid=iid))

if __name__ == "__main__":
    host = os.getenv("FLASK_RUN_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_RUN_PORT", "5000"))
    app.run(host=host, port=port, debug=True)


def _ideal_text_color(hex_color: str) -> str:
    try:
        h = hex_color.lstrip('#')
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        l = 0.299*r + 0.587*g + 0.114*b
        return "#000" if l > 186 else "#fff"
    except Exception:
        return "#000"

def get_label_color_map(project_id: str):
    labels = gl_get_all(f"/projects/{project_id}/labels", params={"per_page": 100})
    mapping = {}
    for lb in labels:
        name = lb.get("name")
        color = lb.get("color") or "#f1f5f9"
        mapping[name] = {"color": color, "text": _ideal_text_color(color)}
    return mapping


def get_project_list():
    if not login_required():
        items = []
        for idx, p in enumerate(PROJECTS):
            name = PROJECT_ALIASES[idx] if idx < len(PROJECT_ALIASES) else p
            items.append({'key': p, 'name': name})
        return items
    
    gl = current_gl()
    user_id = gl.get('user_id')
    cache_key = f'projects_{user_id}'
    
    now = time()
    if cache_key in PROJECT_CACHE:
        cached_data, cached_time = PROJECT_CACHE[cache_key]
        if now - cached_time < CACHE_TTL:
            return cached_data
    
    try:
        projects = gl_get('/projects', params={
            'membership': True,
            'order_by': 'last_activity_at',
            'sort': 'desc',
            'per_page': 10,
            'page': 1
        }).json()
        
        items = []
        for p in projects:
            items.append({
                'key': p.get('path_with_namespace'),
                'name': p.get('name'),
                'name_with_namespace': p.get('name_with_namespace'),
                'last_activity_at': p.get('last_activity_at')
            })
        
        PROJECT_CACHE[cache_key] = (items, now)
        return items
    except Exception:
        items = []
        for idx, p in enumerate(PROJECTS):
            name = PROJECT_ALIASES[idx] if idx < len(PROJECT_ALIASES) else p
            items.append({'key': p, 'name': name})
        return items
