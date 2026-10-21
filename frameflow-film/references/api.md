# Frameflow Film 接口契约

> 平台侧以 `GET /api/v1/openapi.json` 为准；本文只补业务语义。
> 本文与 `scripts/film.py` 一起分发，不含任何密钥或本机路径。

> 一段产品描述 → 分镜 → 分段生成 → 拼接 → 配乐 → 配音/混剪/调色/终检 → 一条成片 MP4。
> 本文是调用方唯一的契约。**提交不花钱，人工批准后才调付费模型。**

## 0. 上手与自检

1. 平台地址 <https://aivideo.sligenai.cn>，注册/登录后按团队隔离任务。
   外部协作者优先用团队邀请加入，共享产品图与积分；自建团队默认 0 积分。
2. 在团队/账号页创建 Agent Key，scopes 至少 `read` + `write` + `generate`。
3. `python scripts/film.py setup` 写入凭据，`python scripts/film.py doctor` 自检。
4. `GET /api/v1/auth/me` 返回当前身份、团队与 scopes，`doctor` 就是调它。
5. 批准入口在平台网页的「创作搭档」待确认卡片，不在本 CLI。

- 平台地址：`https://aivideo.sligenai.cn`
- 机器可读契约：`GET /api/v1/openapi.json`（平台随时更新，本文只补业务语义）
- 最后核对：2026-10-22，对照平台源码 `src/lib/film-pipeline.ts` 与线上响应

---

## 1. 三个端点

| 方法 | 路径 | 谁调 | 作用 |
|---|---|---|---|
| `POST` | `/api/v1/film-jobs` | API Key / 人类会话 | 下单，返回平台任务 ID 与流水线 ID |
| `GET` | `/api/v1/film-jobs/{id}` | API Key / 人类会话 | 查进度、逐段状态、成片地址、质检报告 |
| `POST` | `/api/v1/film-jobs/{id}/approve` | **仅人类会话** | 批准，立刻开始付费生成 |

`{id}` 是**平台任务 ID**（UUID），不是流水线内部的 `FF-YYYYMMDD-XXXXXX`。响应里的 `pipelineJobId` 才是后者。

---

## 2. 鉴权

```
Authorization: Bearer <AIVIDEO_API_KEY>
```

- 下单需要 `write` + `generate` 两个 scope。
- 审批走 `requireHuman`，**Agent Key 一律 403**，这是设计而非缺陷；没有绕过方式。
- Key 绑定团队，创建的任务只在该团队可见。

### 客户端配置

- 凭据：`AIVIDEO_BASE_URL` + `AIVIDEO_API_KEY`，或 `AIVIDEO_CREDENTIALS` 指向的文件，默认 `~/.config/aivideo/credentials`。
- 网络：默认直连；需要代理时设 `AIVIDEO_PROXY`，或沿用系统 `HTTPS_PROXY`；`--no-proxy` 强制直连。
- 自检：`GET /api/v1/auth/me` 可验证 Key、团队与 scopes，不需要额外权限。

### 写操作要带 `Idempotency-Key`

所有创建类请求必须带请求头 `Idempotency-Key`，8–200 字符，缺了直接 `400`。

- 同一个 Key + 同一个请求体 → 重放上次的结果，**不会重复建任务**。
- 同一个 Key + 不同的请求体 → `409 相同幂等键对应不同请求`。
- 重试同一次提交时原样复用；换一次新提交就换新 Key。

错误统一是这个形状：

```json
{"error": {"code": "INVALID_REQUEST", "message": "找不到该出片任务", "requestId": "…"}}
```

---

## 3. 下单

`POST /api/v1/film-jobs`

### 请求体

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `brief` | string | 是 | 8–4000 字 | 产品描述。写清：是什么、给谁用、解决什么问题、必须出现的画面 |
| `title` | string | 否 | ≤80 字 | 片名 |
| `product_name` | string | 否 | ≤80 字 | 产品名，用于分镜提示 |
| `target_seconds` | int | 否 | 8–180，默认 40 | 成片时长。分镜时长会按比例归一到这个值 |
| `aspect_ratio` | string | 否 | `9:16` `16:9` `1:1` `4:3` `3:4`，默认 `16:9` | 画幅 |
| `reference_image_urls` | string[] | 否* | ≤3 个 https 直链 | 产品参考图，保证外观一致 |
| `productId` | uuid | 否 | 本团队产品 | 不给参考图时，自动取该产品已上传的图 |
| `conversationId` | uuid | 否 | 本团队会话 | 不给参考图时，取该会话上传的图 |

\* **参考图最终必需**。三者都拿不到图 → `422`，不会生成。
参考图会签成 7 天可读的链接（要撑过人工审批的等待时间）。

### 响应 `201`

```json
{
  "id": "9f3c…-uuid",
  "pipelineJobId": "FF-20261022-AB12CD",
  "status": "pending_approval",
  "statusUrl": "…"
}
```

下单只做分镜规划，**此刻不产生任何费用**。分镜跑完后任务停在 `awaiting_approval`，等人批准。

> 注意：`create` 响应里的 `status` 是平台本地状态，固定为 `pending_approval`；分镜是否跑完，
> 以 `GET /film-jobs/{id}` 透传的流水线状态为准。流水线正式写法是 `planning → awaiting_approval`，
> 部分版本/节点也会返回 `pending_approval`；两者都表示“在等人批”，不要把它当成“分镜未完成”。

---

## 4. 查状态

`GET /api/v1/film-jobs/{id}`

返回流水线状态原样透传，外加 `id`、`pipelineJobId`。

```json
{
  "found": true,
  "job_id": "FF-20261022-AB12CD",
  "status": "generating",
  "title": "晨研 Mini 产品片",
  "unit_count": 3,
  "units_done": 1,
  "unit_states": [
    {"index": 1, "status": "succeeded", "shots": 6, "seconds": 14, "video_ready": true, "error": ""},
    {"index": 2, "status": "running",   "shots": 7, "seconds": 13, "video_ready": false, "error": ""},
    {"index": 3, "status": "pending",   "shots": 6, "seconds": 13, "video_ready": false, "error": ""}
  ],
  "result_url": "",
  "qc": null,
  "error": "",
  "updated_at": "2026-10-22T02:14:07.512Z",
  "id": "9f3c…-uuid",
  "pipelineJobId": "FF-20261022-AB12CD"
}
```

`result_url` 非空即已成片；`qc` 见第 6 节。

---

## 5. 审批

`POST /api/v1/film-jobs/{id}/approve`，请求体 `{}`。

- 只有 `status === "pending_approval"` 能批，否则 `409 该任务已处置`。
- 平台内部完成审批签名，调用方不接触任何签名密钥。
- 批准瞬间转入 `generating`，开始调用付费视频模型。

**调用方必须把审批交给人**：Agent 拿到 `status: pending_approval` 就停下来，把 `pipelineJobId`、分镜摘要、预计单元数报给用户，由人在平台界面确认。入口是登录后的「创作搭档」里那张待确认卡片；也可以用人类登录会话直接调本端点。Agent Key 一律 403。

---

## 6. 状态与质检

### 状态机

```
planning ──► awaiting_approval ──► approved ──► generating ──► assembling ──► posting ──► delivered
                    │                                              │            │
                    └──► rejected（人工驳回）                       └────────────┴──► failed
```

| 状态 | 含义 |
|---|---|
| `planning` | 正在出分镜、切单元 |
| `awaiting_approval` | 分镜就绪，**等人工批准，未产生费用**；个别版本返回 `pending_approval`，含义相同 |
| `approved` | 已批准，即将派发 |
| `generating` | 逐单元生成视频，看 `units_done / unit_count` |
| `assembling` | 拼接成片 |
| `posting` | 配音、按节拍重剪、调色、终检 |
| `delivered` | 完成，`result_url` 可用 |
| `failed` | 失败，看 `error` |
| `rejected` | 人工驳回 |

### 单元切分

分镜单镜 2–6 秒，总时长归一到 `target_seconds`，再贪心并成 **每段 10–15 秒**的生成单元。
40 秒片 ≈ 3 个单元 → **3 次付费视频请求**。费用按单元计，批准后才产生。

### `qc`（终检报告）

```json
{
  "applied": true,
  "passed": true,
  "fails": [],
  "frames": 839,
  "loudness": {"integrated": -16.5, "truePeak": -1.7, "lra": 7},
  "voice": {"lines": 3, "mix": {"lines": 3, "tiltDb": [0.65, 0, -1.3]}, "error": "", "skipped": ""},
  "checks": [
    {"name": "frame_count",    "ok": true, "detail": "839 / 839"},
    {"name": "loudness",       "ok": true, "detail": "-16.5 LUFS (目标 -16)"},
    {"name": "true_peak",      "ok": true, "detail": "-1.7 dBTP (上限 -1.5)"},
    {"name": "cut_landing",    "ok": true, "detail": "2 刀全部落帧"},
    {"name": "white_balance",  "ok": true, "detail": "3/3 段可判，最大偏 1.4（目标 -12）"}
  ]
}
```

- `applied: false` 表示没做后期（没有配乐），`skipped` 里写原因。
- `passed` 只有在全部 `checks.ok` 且后期确实执行时才为 `true`。
- 交付规格：x265 CRF 12、AAC 256k / 48 kHz、−16 LUFS、真峰 ≤ −1.5 dBTP。

---

## 7. 规格与已知限制

| 项 | 现状 |
|---|---|
| 分辨率 | **720p**。单元生成侧写死 `resolution: "720p"`（seedance-2.0），后期照原尺寸出片 |
| 帧率 | 24 fps（后期阶段固定） |
| 配乐 | Suno 自动生成；没有配乐就跳过后期重剪，直接交拼接片 |
| 配音 | 固定音色参考 `ref-voxcpm2-zh-01.wav`，文案来自分镜的 `voiceover` |
| 时长 | 分镜模型可能偏离目标时超过 5%，超过就按比例缩放归一到 `target_seconds` |
| 实测耗时 | 35 秒、3 段、3 句口播的后期四阶段约 22 分钟；单元生成随模型排队波动 |

1080p 需要改生成侧的分辨率参数，属于花钱参数的变更，目前保持 720p。

---

## 8. 错误码

| 码 | 场景 | 处理 |
|---|---|---|
| `400` | 缺 `Idempotency-Key`，或请求体不是合法 JSON | 补请求头 |
| `401` | 未带 Key / Key 失效 | 检查 `AIVIDEO_API_KEY` |
| `402` | 个人积分不足（新账号默认 0 分） | 停下保留进度，由管理员分配/充值后重新提交 |
| `403` | scope 不足；或用 Agent Key 调审批 | 审批必须人类会话 |
| `404` | 任务不存在或不属于本团队 | 核对 `id` |
| `409` | 任务已处置 | 重新查状态 |
| `422` | 参数不合法 | 看 `error`；常见是缺参考图 |
| `429` | 限流 | 退避重试 |
| `502` | 流水线受理或读取失败 | 稍后重试；持续失败查 `statusUrl` |
| `503` | 出片流水线未配置（服务端缺环境变量） | 联系管理员 |

---

## 9. 调用示例

```bash
curl -sS -X POST https://aivideo.sligenai.cn/api/v1/film-jobs \
  -H "Authorization: Bearer $AIVIDEO_API_KEY" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  --data-binary @order.json
```

```json
{
  "brief": "晨研 Mini 是给通勤族用的便携咖啡机，30 秒出浓缩。要拍出按键、出液、手表计时、端着走的画面，强调小和快。",
  "title": "晨研 Mini 产品片",
  "product_name": "晨研 Mini",
  "target_seconds": 40,
  "aspect_ratio": "16:9",
  "reference_image_urls": ["https://.../pack.jpg"]
}
```

```bash
curl -sS https://aivideo.sligenai.cn/api/v1/film-jobs/<id> \
  -H "Authorization: Bearer $AIVIDEO_API_KEY"
```

Windows 下发送中文请求体**必须**用 `--data-binary @file`，不要内联 `-d`。
