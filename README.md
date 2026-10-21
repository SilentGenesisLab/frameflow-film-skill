# Frameflow Film Skill

把一段产品描述做成一条可直接投放的广告短片：分镜 → 分段生成 → 拼接 → Suno 配乐 → 配音 → 按节拍混剪 → 调色 → 终检，输出 MP4。

这是给外部协作者用的**公开分发版**：只包含命令行客户端和接入说明，**不含任何密钥、内网地址或平台内部实现**。

## 下载

```bash
git clone https://github.com/SilentGenesisLab/frameflow-film-skill.git
```

或者在本页点 **Code → Download ZIP**。仓库里的 `dist/frameflow-film-skill.zip` 是同样内容的打包版。
只需要 Python 3.8+，脚本全部使用标准库，不用装依赖。

## 安装成 Claude Code Skill（可选）

```bash
mkdir -p ~/.claude/skills
cp -r frameflow-film-skill/frameflow-film ~/.claude/skills/
```

之后在 Claude Code 里说「用 Frameflow 出一条产品片」就会触发这个 skill。

## 直接用命令行

```bash
cd frameflow-film
python scripts/film.py setup     # 交互输入平台地址和 Agent Key
python scripts/film.py doctor    # 自检：团队、Key 类型、scopes
```

## 开始出片前

1. **账号**：打开 <https://aivideo.sligenai.cn> 注册或登录。任务按团队隔离。
   想共用产品图和积分，就让管理员用团队邀请把你加进去；自己注册会新建一个空团队，**默认 0 积分**。
2. **Agent Key**：在平台的团队/账号页创建「Agent 访问密钥」，勾选 **read + write + generate**。
   Key 只显示一次，不要提交到仓库。
3. **参考图**：至少 1 张、最多 3 张公网可读的 **https 直链**；没有直链就先传到平台产品库，
   下单时用 `--product-id` 或 `--conversation-id`。三者都没有 → `422`。
4. **审批**：下单和分镜不花钱；分镜完成后任务停在待批准。**审批就是付费**——
   先把分镜、单元数和花费报给用户，同意后调 `approve`，或让用户在「创作搭档」的待确认卡片上点确认。

## 常用命令

```bash
python scripts/film.py create --brief-file brief.txt --title "片名" --product "产品名" \
  --seconds 30 --ratio 9:16 --ref https://example.com/pack.jpg
python scripts/film.py status <平台任务ID>
python scripts/film.py watch  <平台任务ID> --interval 30 --timeout 5400
```

`<平台任务ID>` 是下单返回的 `id`（UUID），不是 `FF-YYYYMMDD-XXXXXX` 形式的 `pipelineJobId`。

完整契约（字段、状态机、错误码、质检报告）见 [frameflow-film/references/api.md](frameflow-film/references/api.md)；
出片流程与 brief 写法见 [frameflow-film/SKILL.md](frameflow-film/SKILL.md)。

## 费用与限制

- 下单、分镜、审批等待：0 元。
- 批准后按生成单元计费；40 秒片约 4 个单元（每段 8~13 秒），即 4 次付费视频请求。
- 分辨率 720p、24 fps，配乐与配音由流水线自动生成。
- `402` = 个人积分不足；`503` = 平台流水线未配置，联系管理员。

## 安全

仓库里没有任何凭据。`setup` 把 Key 写到 `~/.config/aivideo/credentials`（权限 600），
也可以用环境变量 `AIVIDEO_BASE_URL` / `AIVIDEO_API_KEY`。
不要把凭据文件、Key 或带签名的成片链接提交到公开位置。
