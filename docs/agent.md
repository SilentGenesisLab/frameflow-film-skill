# Frameflow Film — Agent 接入入口

> 这是一份给自动化 Agent 读取的接入说明。人类版说明：https://silentgenesislab.github.io/frameflow-film-skill/
> 平台地址：`https://aivideo.sligenai.cn`
> 机器可读契约：`GET https://aivideo.sligenai.cn/api/v1/openapi.json`

你的目标：把一段产品描述提交为出片任务，拿到用户对分镜和花费的同意后批准，然后跟踪到成片。

**两条硬规则**

1. 审批就是付费。你（Agent Key）可以调审批接口，但必须先向用户报清分镜、`unit_count` 和预计花费，拿到明确同意再批；用户已经整段授权（「直接出片，不用再问我」）时才自行批准。
2. 下单和分镜不产生费用；批准之后才开始调用付费模型。不要为了“推进流程”偷偷批准。

---

## 0. 先向人类要三样东西

| 需要 | 说明 |
|---|---|
| Agent Key | 由团队管理员在平台「团队 → 访问密钥」创建，scopes 必须含 `read`、`write`、`generate` |
| 参考图 | 至少 1 张公网可读的 https 直链（最多 3 张）；或提供 `productId` / `conversationId`（该产品/会话里已有图） |
| 成片信息 | 产品是什么、给谁用、目标时长（8–180 秒）、画幅（`9:16` / `16:9` / `1:1` / `4:3` / `3:4`） |

Key 只放在环境变量或本地凭据文件里。不要写进代码、日志、仓库或聊天记录。

```bash
export AIVIDEO_BASE_URL=https://aivideo.sligenai.cn
export AIVIDEO_API_KEY=...
```

## 1. 验证 Key

```bash
curl -sS https://aivideo.sligenai.cn/api/v1/auth/me \
  -H "Authorization: Bearer $AIVIDEO_API_KEY"
```

返回里确认 `scopes` 含 `write` 和 `generate`。`type: agent` 是正常的。

## 2. 下单

```bash
curl -sS -X POST https://aivideo.sligenai.cn/api/v1/film-jobs \
  -H "Authorization: Bearer $AIVIDEO_API_KEY" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  --data-binary @order.json
```

`order.json`：

```json
{
  "brief": "产品是什么、给谁用、必须出现的画面、一句说结果的卖点。8–4000 字。",
  "title": "片名",
  "product_name": "产品名",
  "target_seconds": 30,
  "aspect_ratio": "9:16",
  "reference_image_urls": ["https://example.com/pack.jpg"]
}
```

- `Idempotency-Key` 必填，8–200 字符。重试同一次提交要复用同一个 Key；换新提交换新 Key。
- 201 响应：

```json
{
  "id": "9f3c…-uuid",
  "pipelineJobId": "FF-20261022-AB12CD",
  "status": "pending_approval",
  "statusUrl": "…"
}
```

**用 `id`（UUID）查询**，不要用 `pipelineJobId` 当查询参数。

## 3. 轮询到待批准

```bash
curl -sS https://aivideo.sligenai.cn/api/v1/film-jobs/<id> \
  -H "Authorization: Bearer $AIVIDEO_API_KEY"
```

| status | 你的动作 |
|---|---|
| `planning` | 继续等，分镜还没出完 |
| `awaiting_approval` 或 `pending_approval` | **停下**，把分镜摘要、`unit_count`、预计费用报给用户；得到同意后批准（见下） |
| `approved` / `generating` | 人类已批准，继续轮询 |
| `assembling` / `posting` | 继续轮询 |
| `delivered` | 完成，读取 `result_url` 和 `qc` |
| `failed` / `rejected` | 停止，把 `error` 报给人类 |

建议 30 秒一次，总超时 90 分钟。

## 3.1 审批（用户同意后）

```bash
curl -sS -X POST https://aivideo.sligenai.cn/api/v1/film-jobs/<id>/approve \
  -H "Authorization: Bearer $AIVIDEO_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{}'
```

- 需要 `write` + `generate`。批准后立刻转入 `generating`，开始计费。
- 只有流水线真的停在 `awaiting_approval` 才能批，否则 `409`，错误信息里带 n8n 返回的实际状态（例如「该任务当前状态是『planning』…」）。看到 409 就回去查状态，不要重试。
- 用户也可以登录平台，在「创作搭档」的待确认卡片上点确认。

## 4. 交付

- `result_url`：成片地址，非空才算完成。
- `qc.passed`：终检是否通过；`qc.checks[]` 要逐条转述。
- `qc.applied: false`：没有配乐，后期被跳过，交付的是拼接片。
- 成片链接有时效，需要长期保存就让人类转存。

## 5. 费用

- 下单、分镜、等待批准：0 元。
- 批准后按生成单元计费，40 秒片约 4 个单元（每段 8~13 秒）。
- `402` 表示积分不足：停下，不要重试，让管理员分配积分后重新提交。

## 6. 错误码

| 码 | 处理 |
|---|---|
| 400 | 缺 `Idempotency-Key` 或 JSON 不合法 |
| 401 | Key 无效，向人类重新索取 |
| 402 | 积分不足，停下等人分配 |
| 403 | scope 不足（下单和审批都需要 `write` + `generate`） |
| 404 | 任务不存在或不属于本团队 |
| 409 | 流水线还没停在 `awaiting_approval`，或任务已处置；重新查状态 |
| 422 | 参数不合法，最常见是缺参考图 |
| 429 | 限流，退避重试 |
| 502 | 流水线受理/读取失败，稍后重试 |
| 503 | 流水线未配置，联系平台管理员 |

## 7. 用现成 CLI（推荐）

```bash
git clone https://github.com/SilentGenesisLab/frameflow-film-skill.git
cd frameflow-film-skill/frameflow-film
python scripts/film.py setup     # 交互写入 Key
python scripts/film.py doctor    # 验证团队和 scopes
```

```bash
python scripts/film.py create --brief-file brief.txt --title "片名" \
  --seconds 30 --ratio 9:16 --ref https://example.com/pack.jpg
python scripts/film.py status <id>
python scripts/film.py watch  <id> --interval 30 --timeout 5400
```

打包下载：https://raw.githubusercontent.com/SilentGenesisLab/frameflow-film-skill/main/dist/frameflow-film-skill.zip

## 8. 文件

- 人类说明：https://silentgenesislab.github.io/frameflow-film-skill/
- 完整接口契约：https://raw.githubusercontent.com/SilentGenesisLab/frameflow-film-skill/main/frameflow-film/references/api.md
- Skill 定义：https://raw.githubusercontent.com/SilentGenesisLab/frameflow-film-skill/main/frameflow-film/SKILL.md
- CLI 源码：https://raw.githubusercontent.com/SilentGenesisLab/frameflow-film-skill/main/frameflow-film/scripts/film.py

本页不含任何密钥。
