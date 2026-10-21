---
name: frameflow-film
description: 用 Frameflow Film 流水线把一段产品描述做成一条成片——分镜、分段生成、拼接、Suno 配乐、配音、按节拍混剪、调色、终检。当用户说「生成一条产品片」「出片」「把这些素材做成广告片」「一条龙出一版」「调 Frameflow 出片」，或要用 API 下单、查进度、看质检报告时使用。
user-invocable: true
---

# Frameflow Film 出片

一段 `brief` → 分镜 → 3 个左右视频单元 → 拼接 → 配乐 → 配音/混剪/调色/终检 → 成片。

**唯一铁律：审批只能人类做。** 下单不花钱，任务停在待确认；批准之后才调付费模型。
Agent Key 调审批固定 403，不要找绕过方式，也不要把签名算出来自己用。

---

## 第一次使用（新人和新机器）

只需要 Python 3.8+，脚本只用标准库，没有依赖。

1. **有账号**：打开 <https://aivideo.sligenai.cn> 注册或登录。出片任务按团队隔离，看不到别的团队的单。
   想共用你的产品和积分，就让对方走团队邀请加入你的团队；自己注册会新建一个空团队，**默认 0 积分**，需要管理员分配后才能出片。
2. **拿 Key**：在平台的团队/账号页创建「Agent 访问密钥」，勾上 **read + write + generate**。
   Key 只显示一次，别发群里，别写进仓库。
3. **存凭据**（交互输入，不进 shell 历史）：

   ```bash
   python scripts/film.py setup
   ```

   默认地址就是 `https://aivideo.sligenai.cn`；也可以用环境变量
   `AIVIDEO_BASE_URL` / `AIVIDEO_API_KEY` 覆盖，或把凭据文件放到
   `AIVIDEO_CREDENTIALS` 指向的位置。
4. **自检**：

   ```bash
   python scripts/film.py doctor
   ```

   它会打印 team、Key 类型和 scopes。`can_create: true` 才能下单；
   缺 `write` / `generate` 就回平台补权限。
5. **准备参考图**：至少 1 张，最多 3 张，必须是公网可读的 **https 直链**。
   没有直链时，先在平台把图传到产品库或会话里，下单时用 `--product-id` / `--conversation-id`。
   三者都没有图 → `422`，不会开工。

> `doctor` 显示 `type: agent` 是正常的：Agent Key 负责下单和查进度，审批必须由人类登录网页完成。

---

## 命令

```bash
python scripts/film.py create --brief-file brief.txt --title "片名" --product "产品名" --seconds 40 --ratio 16:9 --ref https://.../pack.jpg
python scripts/film.py status <平台任务ID>
python scripts/film.py watch  <平台任务ID> --interval 30 --timeout 5400
python scripts/film.py approve <平台任务ID>   # 只打印为什么不能批
```

`<平台任务ID>` 是 `create` 返回的 `id`（UUID），**不是** `FF-YYYYMMDD-XXXXXX` 那个
`pipelineJobId`；传错脚本会直接提示。
`watch` 每 30 秒打一行状态，到 `delivered` / `failed` / `rejected` 停下并打印最终 JSON。
全部命令输出 JSON；`--dry-run` 只打印将要提交的请求体。
`--ref` 可重复最多 3 次；同一请求重试时用 `--idempotency-key` 复用，不会重复建单。

---

## 标准流程

1. **问清三件事再下单**：产品是什么、给谁用、成片多长。参考图必须有——没有图平台直接 422。
2. `create` → 记下 `id` 和 `pipelineJobId`。**此刻只做分镜，不产生费用。**
3. `status` 轮询：`planning` 表示分镜还没出完；看到 `awaiting_approval`（或兼容写法
   `pending_approval`）就停下来找人批。`create` 响应里的 `pending_approval` 是平台本地状态，
   不能据此认为分镜已完成。
4. **停下来找用户批准**。把分镜、单元数、预计花费讲清楚。不批就不往下走。
   批准入口：登录平台 →「创作搭档」→ 待确认卡片 → 确认。
5. 批准后 `watch` 到终态。`units_done / unit_count` 是唯一可信的进度。
6. 交付时给 `result_url`，并把 `qc` 里 `checks` 逐条念出来——`passed: true` 才算合格。

---

## 费用

- 下单和分镜不扣费；**点确认的瞬间开始调付费模型**。
- 40 秒片约 3 个单元，就是 3 次付费视频请求；费用按单元计。
- 新注册团队/新成员默认 0 积分，先由管理员分配；`402` = 个人积分不足，停下别重试，充值后再提交。

---

## brief 怎么写

写清四件事，别的都是噪音：

- **产品**：是什么、什么形态、给谁用
- **场景**：一个具体的使用现场，不要写「现代生活」这种空话
- **必须出现的画面**：按键、出液、读数、被拿起——这些是分镜模型最容易漏的
- **卖点一句话**：说结果，不说形容词

不要写具体参数、认证、销量、疗效。分镜模型会照抄，抄错了就是虚假宣传。

```text
晨研 Mini 是给通勤族用的便携咖啡机，30 秒出浓缩。
要拍出按键、出液、手表计时、端着走的画面，强调小和快。
```

---

## 读状态

| 字段 | 怎么读 |
|---|---|
| `status` | 见下表的九个状态 |
| `unit_states[]` | 逐段：`status` / `seconds` / `video_ready` / `error` |
| `result_url` | 非空即已成片 |
| `qc` | 终检；`applied: false` 表示没做后期（无配乐），`passed` 才是结论 |

```
planning → awaiting_approval → approved → generating → assembling → posting → delivered
                  ↓                            ↓            ↓
              rejected                       failed       failed
```

`generating` 之后卡住不动超过 40 分钟，先去平台看单元 `error`，不要重复下单。

---

## 已知限制

- **720p**：生成侧写死 `resolution: "720p"`，成片不会更高。
- **24 fps**，配乐由 Suno 自动生成，配音是固定音色。
- 没有配乐就跳过后期重剪，直接交拼接片，此时 `qc.applied = false`。
- 35 秒片的后期四阶段实测约 22 分钟；单元生成随排队波动。
- 只从零生成画面，不复用实拍素材；给已有成片配音/重剪用 `film-post`。

---

## 把这套东西交给别人

整个目录复制过去即可，里面没有任何密钥、机器路径或代理配置：

1. 对方注册账号，由团队管理员给他建一个带 `read + write + generate` 的 Agent Key；
2. 跑 `python scripts/film.py setup`，再跑 `doctor`；
3. 按上面的流程下单，审批仍由人在网页里点。

不需要装依赖，不需要连你的机器，不需要改脚本。
凭据优先级：环境变量 > `AIVIDEO_CREDENTIALS` 指向的文件 > `~/.config/aivideo/credentials`。
脚本默认直连；要走代理时显式设 `AIVIDEO_PROXY`，或统一用系统 HTTPS_PROXY。
完整契约见 [references/api.md](references/api.md)。
