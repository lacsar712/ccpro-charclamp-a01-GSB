# CharClamp-01 · 炭窑焖烧志

窑场炭窑与焖烧班次台账基线项目（Litestar + SQLAlchemy 2 + Jinja2 + HTMX）。

## 技术栈

| 层 | 技术 |
| --- | --- |
| Web | Litestar · Jinja2 · HTMX CDN · Session 认证 |
| 数据 | SQLAlchemy 2（async） · PostgreSQL 15 |
| 部署 | Docker Compose · Uvicorn |
| 结构 | `domain/` · `infra/` · `web/` 分层（非 Django apps） |

## 路径与端口

- **项目路径**：`d:\work\document\bytecode\claudeCodePro\CharClamp\CharClamp-01`
- **Web**：http://localhost:4750
- **PostgreSQL**：localhost:6150

## 演示账号

| 用户名 | 密码 | 角色 |
| --- | --- | --- |
| `admin` | `123456` | 管理员 |
| `worker` | `123456` | 操作工 |

登录页已预填 `admin` / `123456`。entrypoint 会建表并写入种子数据（窑场 **乌石岗焖烧坞**，窑号如 **坞东-甲 / 坞东-乙 / 河沿-丙**；其中坞东-甲焖烧中，测氧簿已记 **2 条**）。

## 主界面：焖烧时间轴

登录后进入全宽 **焖烧时间轴**（不再使用侧栏 + 双 CRUD 列表）：

1. **顶栏导航**：「焖烧时间轴」与「测氧簿」两个入口随时可点开。
2. **顶部窑剪影行**：每座炭窑以 SVG 剪影展示，剪影右上角标出该窑**已测氧条数**角标；点击某窑用 HTMX 局部刷新下方时间轴，并更新地址栏 `?clamp_id=`；「全部窑」取消筛选。
3. **纵向时间轴**：按开始时间倒序列出 `BurnShift`；每条卡片带窑号徽章（再点可开抽屉）、峰值温度、炭品与当前窑态。
4. **侧抽屉（非独立编辑页）**：「登记班次」写入新班次；点窑徽章打开操作抽屉，可标记「已出炭」（受峰值 + 测氧并行规则约束）。测氧登记不在抽屉里，只能去测氧簿专页。

## 测氧簿专页（`/oxygen`）

- **按窑下拉**切换各窑簿页（含已码窑 / 已出炭的只读簿页）；右侧为**新增测氧表**。
- 簿字段：炭窑、测次（从 1 起的正整数）、烟囱氧百分、采集时刻、当班人。
- 约束：
  - 仅 **焖烧中** 的炭窑可登记测氧；已码窑与已出炭禁止建簿。
  - 同窑测次不得重复——数据库对 `(clamp_id, seq)` 设唯一约束；两人同时交同一测次时只落库一笔，第二笔被中文提示挡下。
  - 氧百分必须为正且不超过 21。

## 业务规则

炭窑状态不可设为「已出炭」（`drawn`），除非**两套并行门槛同时满足**：

1. **峰值门槛（照旧）**：该窑**最近一条** `BurnShift` 的 `peakTempC` 已记录且 **≥ 400℃**。
2. **测氧门槛（新增）**：测氧簿测次**从 1 起连续且不少于 4 条**；最新一条氧百分 **≤ 8%**；最新采集时刻**晚于**该窑最近一班开始时刻。

抽屉按钮与改窑态接口（`POST /clamps/{id}/status`）读取同一判定函数，不另写放行逻辑。

规则实现：`src/charclamp/domain/rules.py`

## 快速启动

```bash
cd d:\work\document\bytecode\claudeCodePro\CharClamp\CharClamp-01
docker compose up --build
```

浏览器打开 http://localhost:4750

## 目录结构

```
CharClamp-01/
├── docker-compose.yml
├── Dockerfile
├── entrypoint.sh
└── src/charclamp/
    ├── main.py
    ├── domain/          # models + rules
    ├── infra/           # db + seed + security
    └── web/             # controllers + templates + static
```
