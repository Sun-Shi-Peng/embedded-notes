#!/usr/bin/env python3
"""
飞书知识库 → GitHub 每日同步脚本（文档 + 表格 + 画板全覆盖）

工作方式：
  1. 用应用身份获取 tenant_access_token
  2. 递归列出知识库全部节点
  3. 按类型分流：
     - docx   → 导出 Markdown 到 dist/docs/，并提取文档内嵌画板下载到 dist/whiteboards/
     - sheet  → 导出 xlsx 到 dist/sheets/
     - whiteboard → 下载画板图片到 dist/whiteboards/
  4. 内容没有变化的文件不会改变，交由 git diff 判断是否提交

环境变量（在 GitHub Actions 中由 Secrets 注入）：
  FEISHU_APP_ID     飞书应用 App ID
  FEISHU_APP_SECRET 飞书应用 App Secret
  FEISHU_SPACE_ID   飞书知识库 space_id
  OUTPUT_DIR        输出目录（可选，默认 dist）
"""
import os
import re
import sys
import time
import json
import urllib.request
import urllib.error
import urllib.parse

APP_ID = os.environ["FEISHU_APP_ID"]
APP_SECRET = os.environ["FEISHU_APP_SECRET"]
SPACE_ID = os.environ["FEISHU_SPACE_ID"]
OUT_DIR = os.environ.get("OUTPUT_DIR", "dist")

BASE = "https://open.feishu.cn/open-apis"
DOC_DIR = os.path.join(OUT_DIR, "docs")
SHEET_DIR = os.path.join(OUT_DIR, "sheets")
BOARD_DIR = os.path.join(OUT_DIR, "whiteboards")


def http_json(method, path, token=None, data=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json; charset=utf-8")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    body = json.dumps(data).encode("utf-8") if data is not None else None
    with urllib.request.urlopen(req, body, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_raw(method, path, token=None):
    req = urllib.request.Request(BASE + path, method=method)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, None, timeout=120) as resp:
        return resp.read(), resp.headers.get("Content-Type", "")


def get_token():
    d = http_json("POST", "/auth/v3/tenant_access_token/internal",
                  data={"app_id": APP_ID, "app_secret": APP_SECRET})
    if d.get("code") != 0:
        raise RuntimeError("获取 tenant_access_token 失败: %s" % d)
    return d["tenant_access_token"]


def list_all_nodes(token):
    """递归列出知识库所有节点（含子节点）"""
    nodes = []

    def walk(space_id, parent_token=None):
        page_token = ""
        while True:
            q = "/wiki/v2/spaces/%s/nodes?page_size=50" % space_id
            if parent_token:
                q += "&parent_node_token=%s" % parent_token
            if page_token:
                q += "&page_token=%s" % page_token
            d = http_json("GET", q, token=token)
            if d.get("code") != 0:
                raise RuntimeError("列知识库节点失败: %s" % d)
            data = d.get("data", {})
            for it in data.get("items", []):
                nodes.append(it)
                if it.get("has_child"):
                    walk(space_id, it["node_token"])
            if data.get("has_more"):
                page_token = data.get("page_token", "")
            else:
                break

    walk(SPACE_ID)
    return nodes


def sanitize(name):
    name = re.sub(r'[\\/:*?"<>|\r\n]', "_", name).strip()
    return name or "untitled"


def export_drive(token, obj_token, obj_type, ext, out_path):
    """创建导出任务并轮询，把 docx/sheet 导出为指定格式保存到本地"""
    d = http_json("POST", "/drive/v1/export_tasks", token=token, data={
        "token": obj_token,
        "type": obj_type,
        "file_extension": ext,
        "file_name": sanitize(os.path.basename(out_path)),
    })
    if d.get("code") != 0:
        raise RuntimeError("创建导出任务失败: %s" % d)
    ticket = d["data"]["ticket"]
    for _ in range(60):
        time.sleep(2)
        # 查询导出任务必须携带源文档 token 参数
        r = http_json("GET",
                      "/drive/v1/export_tasks/%s?token=%s" % (ticket, urllib.parse.quote(obj_token)),
                      token=token)
        if r.get("code") != 0:
            raise RuntimeError("查询导出任务失败: %s" % r)
        res = r["data"]["result"]
        if res["job_status"] == 0:
            content, _ = http_raw(
                "GET", "/drive/v1/export_tasks/file/%s/download" % res["file_token"],
                token=token)
            with open(out_path, "wb") as f:
                f.write(content)
            return
        if res["job_status"] == 1:
            raise RuntimeError("导出任务失败: %s" % res.get("job_error_msg"))
    raise RuntimeError("导出任务超时")


def get_docx_markdown(token, doc_token, out_path):
    """用 raw_content 接口直接获取文档的 Markdown 内容"""
    d = http_json("GET", "/docx/v1/documents/%s/raw_content?lang=0" % doc_token,
                  token=token)
    if d.get("code") != 0:
        raise RuntimeError("读取文档 Markdown 失败: %s" % d)
    content = d["data"].get("content", "")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)


def download_board(token, board_token, out_path):
    """下载画板预览图片，扩展名按 Content-Type 决定"""
    try:
        content, ctype = http_raw(
            "GET", "/board/v1/whiteboards/%s/download_as_image" % board_token,
            token=token)
    except urllib.error.HTTPError as e:
        raise RuntimeError("画板下载失败 HTTP %s" % e.code)
    ext = ".png"
    if "jpeg" in ctype or "jpg" in ctype:
        ext = ".jpg"
    elif "webp" in ctype:
        ext = ".webp"
    with open(out_path + ext, "wb") as f:
        f.write(content)


def get_docx_boards(token, doc_token):
    """读取文档块，返回所有内嵌画板的 token（block_type=43）"""
    boards = []
    page_token = ""
    while True:
        q = "/docx/v1/documents/%s/blocks?page_size=500" % doc_token
        if page_token:
            q += "&page_token=%s" % page_token
        d = http_json("GET", q, token=token)
        if d.get("code") != 0:
            raise RuntimeError("读取文档块失败: %s" % d)
        for it in d["data"].get("items", []):
            if it.get("block_type") == 43 and it.get("board", {}).get("token"):
                boards.append(it["board"]["token"])
        if d["data"].get("has_more"):
            page_token = d["data"].get("page_token", "")
        else:
            break
    return boards


def main():
    for d in (DOC_DIR, SHEET_DIR, BOARD_DIR):
        os.makedirs(d, exist_ok=True)

    token = get_token()
    nodes = list_all_nodes(token)
    print("知识库节点数: %d" % len(nodes))

    ok = fail = 0
    for n in nodes:
        title = sanitize(n["title"])
        obj_token = n["obj_token"]
        obj_type = n["obj_type"]
        try:
            if obj_type == "docx":
                get_docx_markdown(token, obj_token,
                                  os.path.join(DOC_DIR, title + ".md"))
                boards = get_docx_boards(token, obj_token)
                board_ok = board_fail = 0
                for i, bt in enumerate(boards, 1):
                    try:
                        download_board(token, bt,
                                       os.path.join(BOARD_DIR, "%s_%02d" % (title, i)))
                        board_ok += 1
                    except Exception as e:
                        board_fail += 1
                        print("  [WARN] %s 画板%d 下载失败: %s" % (title, i, e))
                print("  [OK] %s (docx，画板 x%d，成功%d/失败%d)"
                      % (title, len(boards), board_ok, board_fail))
            elif obj_type == "sheet":
                export_drive(token, obj_token, "sheet", "xlsx",
                             os.path.join(SHEET_DIR, title + ".xlsx"))
                print("  [OK] %s (sheet)" % title)
            elif obj_type == "whiteboard":
                download_board(token, obj_token,
                               os.path.join(BOARD_DIR, title))
                print("  [OK] %s (whiteboard)" % title)
            else:
                print("  [SKIP] %s (类型 %s 不支持)" % (title, obj_type))
            ok += 1
        except Exception as e:
            print("  [FAIL] %s: %s" % (title, e))
            fail += 1

    print("同步完成: 成功 %d 个节点，失败 %d 个" % (ok, fail))
    if fail:
        sys.exit(2)  # 有失败则不提交，方便 workflow 报警


if __name__ == "__main__":
    main()
