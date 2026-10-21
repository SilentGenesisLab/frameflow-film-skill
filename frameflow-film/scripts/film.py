#!/usr/bin/env python
"""Frameflow Film 出片流水线的命令行入口。

只做四件事：下单、查状态、轮询到终态、拒绝代替人类审批。
凭据从环境变量或 ~/.config/aivideo/credentials 读取，不接受命令行传入。
"""
import argparse
import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

CRED = os.environ.get("AIVIDEO_CREDENTIALS") or os.path.join(
    os.path.expanduser("~"), ".config", "aivideo", "credentials"
)
TERMINAL = {"delivered", "failed", "rejected"}
HINTS = {
    401: "Key 无效或未配置：运行 python scripts/film.py setup",
    402: "积分不足：到平台充值后再提交，任务不会自动重试",
    403: "权限不足：Key 需要 read+write+generate；审批只能由人类登录会话发起",
    409: "任务已处置：先 status 看最新状态",
    422: "参数不合法：最常见是缺少参考图（--ref 或 --product-id）",
    429: "限流：稍后重试",
    503: "流水线未配置：联系平台管理员",
}


def load_creds():
    base = os.environ.get("AIVIDEO_BASE_URL")
    key = os.environ.get("AIVIDEO_API_KEY")
    if base and key:
        return base.rstrip("/"), key
    if os.path.exists(CRED):
        kv = {}
        with open(CRED, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                kv[k.strip()] = v.strip().strip('"').strip("'")
        base = base or kv.get("AIVIDEO_BASE_URL")
        key = key or kv.get("AIVIDEO_API_KEY")
    if not base or not key:
        sys.exit("缺少 AIVIDEO_BASE_URL / AIVIDEO_API_KEY")
    return base.rstrip("/"), key


def opener(no_proxy):
    if no_proxy:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    proxy = os.environ.get("AIVIDEO_PROXY")
    if proxy:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    return urllib.request.build_opener()


def hint(code):
    msg = HINTS.get(code)
    if msg:
        print("提示：" + msg, file=sys.stderr)


def call(method, path, body=None, no_proxy=False, timeout=120, headers=None):
    base, key = load_creds()
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + key)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with opener(no_proxy).open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {"error": raw[:600]}
        return e.code, payload


def cmd_create(a):
    if a.dry_run:
        brief = read_brief(a)
        body = build_body(a, brief)
        print(json.dumps({
            "dry_run": True,
            "headers": {"Idempotency-Key": a.idempotency_key or "<随机生成>"},
            "body": body,
        }, ensure_ascii=False, indent=1))
        return 0
    body = build_body(a, read_brief(a))
    key = a.idempotency_key or str(uuid.uuid4())
    code, out = call("POST", "/api/v1/film-jobs", body, a.no_proxy,
                     headers={"Idempotency-Key": key})
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if code != 201:
        hint(code)
        return 2
    print("\n任务已受理，停在 pending_approval，**尚未产生费用**。", file=sys.stderr)
    print("幂等键：%s（同一请求重试时原样传回 --idempotency-key）" % key, file=sys.stderr)
    print("下一步：把分镜和单元数报给用户，等人到平台界面批准。", file=sys.stderr)
    return 0


def read_brief(a):
    if a.brief_file:
        with open(a.brief_file, encoding="utf-8") as fh:
            return fh.read().strip()
    return (a.brief or "").strip()


def build_body(a, brief):
    body = {"brief": brief}
    if a.title:
        body["title"] = a.title
    if a.product:
        body["product_name"] = a.product
    if a.seconds:
        body["target_seconds"] = a.seconds
    if a.ratio:
        body["aspect_ratio"] = a.ratio
    if a.ref:
        body["reference_image_urls"] = a.ref[:3]
    if a.product_id:
        body["productId"] = a.product_id
    if a.conversation_id:
        body["conversationId"] = a.conversation_id
    return body


def job_id(value):
    if value.upper().startswith("FF-"):
        sys.exit("这是流水线内部的 pipelineJobId；请用下单返回的平台任务 id（UUID）。")
    return value


def cmd_status(a):
    code, out = call("GET", "/api/v1/film-jobs/" + job_id(a.id), None, a.no_proxy, timeout=40)
    if a.quiet and code == 200:
        print(json.dumps({
            "status": out.get("status"),
            "units_done": out.get("units_done"),
            "unit_count": out.get("unit_count"),
            "result_url": out.get("result_url"),
            "passed": (out.get("qc") or {}).get("passed"),
        }, ensure_ascii=False))
    else:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    if code != 200:
        hint(code)
    return 0 if code == 200 else 2


def cmd_watch(a):
    jid = job_id(a.id)
    start = time.time()
    last = None
    while True:
        code, out = call("GET", "/api/v1/film-jobs/" + jid, None, a.no_proxy, timeout=40)
        if code != 200:
            print(json.dumps(out, ensure_ascii=False))
            hint(code)
            return 2
        now = (out.get("status"), out.get("units_done"), out.get("unit_count"))
        if now != last:
            print("[%s] %s units=%s/%s" % (
                time.strftime("%H:%M:%S"), now[0], now[1], now[2]), flush=True)
            last = now
        if now[0] in TERMINAL:
            print(json.dumps({
                "status": out.get("status"),
                "unit_count": out.get("unit_count"),
                "unit_states": out.get("unit_states"),
                "result_url": out.get("result_url"),
                "qc": out.get("qc"),
                "error": out.get("error"),
            }, ensure_ascii=False, indent=1))
            return 0 if now[0] == "delivered" else 1
        if time.time() - start > a.timeout:
            print("轮询超时，任务仍在 %s" % now[0], file=sys.stderr)
            return 3
        time.sleep(a.interval)


def cmd_setup(a):
    if not sys.stdin.isatty():
        sys.exit("setup 需要在交互终端运行；非交互环境请改用 AIVIDEO_BASE_URL / AIVIDEO_API_KEY")
    default_base = "https://aivideo.sligenai.cn"
    base = a.base_url or input("平台地址 [%s]: " % default_base).strip() or default_base
    key = getpass.getpass("Agent Key（输入不显示）: ").strip()
    if not key:
        sys.exit("未输入 Key，未写入")
    os.makedirs(os.path.dirname(CRED), exist_ok=True)
    with open(CRED, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# Frameflow Film 凭据，勿提交到仓库或发给他人\n")
        fh.write("AIVIDEO_BASE_URL=%s\n" % base.rstrip("/"))
        fh.write("AIVIDEO_API_KEY=%s\n" % key)
    try:
        os.chmod(CRED, 0o600)
    except OSError:
        pass
    print("已写入 %s" % CRED, file=sys.stderr)
    print("下一步：python scripts/film.py doctor", file=sys.stderr)
    return 0


def cmd_doctor(a):
    base, _ = load_creds()
    code, out = call("GET", "/api/v1/auth/me", None, a.no_proxy, timeout=30)
    if code != 200:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        hint(code)
        return 2
    scopes = out.get("scopes") or []
    missing = [s for s in ("write", "generate") if s not in scopes]
    print(json.dumps({
        "base_url": base,
        "type": out.get("type"),
        "name": out.get("name"),
        "team": out.get("teamName"),
        "scopes": scopes,
        "can_create": not missing,
    }, ensure_ascii=False, indent=1))
    if missing:
        print("缺少 scope：%s" % "、".join(missing), file=sys.stderr)
        return 3
    if out.get("type") != "human":
        print("这是 Agent Key：可以下单，不能审批。", file=sys.stderr)
    print("就绪。审批请由人类登录网页，在「创作搭档」里确认待批任务。", file=sys.stderr)
    return 0


def cmd_approve(a):
    print("审批只能由人类会话发起：平台对 Agent Key 返回 403，这是设计。", file=sys.stderr)
    print("请让用户到平台界面确认任务 %s。" % a.id, file=sys.stderr)
    return 4


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Frameflow Film 出片接口客户端")
    p.add_argument("--no-proxy", action="store_true", help="直连，不走代理")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create", help="下单")
    c.add_argument("--brief-file")
    c.add_argument("--brief")
    c.add_argument("--title")
    c.add_argument("--product", help="产品名")
    c.add_argument("--seconds", type=int)
    c.add_argument("--ratio", choices=["9:16", "16:9", "1:1", "4:3", "3:4"])
    c.add_argument("--ref", action="append", help="产品参考图 https 直链，可重复，最多 3 个")
    c.add_argument("--product-id")
    c.add_argument("--conversation-id", help="从该会话已上传的图里取参考图")
    c.add_argument("--idempotency-key", help="重试同一请求时复用；不传则每次生成")
    c.add_argument("--dry-run", action="store_true")
    c.set_defaults(func=cmd_create)

    st = sub.add_parser("setup", help="交互写入凭据文件")
    st.add_argument("--base-url", default="")
    st.set_defaults(func=cmd_setup)

    dr = sub.add_parser("doctor", help="验证 Key 与 scopes")
    dr.set_defaults(func=cmd_doctor)

    s = sub.add_parser("status", help="查一次状态")
    s.add_argument("id")
    s.add_argument("--quiet", action="store_true")
    s.set_defaults(func=cmd_status)

    w = sub.add_parser("watch", help="轮询到终态")
    w.add_argument("id")
    w.add_argument("--interval", type=int, default=30)
    w.add_argument("--timeout", type=int, default=5400)
    w.set_defaults(func=cmd_watch)

    ap = sub.add_parser("approve", help="说明为什么这里不能审批")
    ap.add_argument("id")
    ap.set_defaults(func=cmd_approve)

    a = p.parse_args()
    sys.exit(a.func(a))


if __name__ == "__main__":
    main()
