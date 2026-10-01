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

登录页已预填 `admin` / `123456`。entrypoint 会建表并写入种子数据（窑场 **乌石岗焖烧坞**，窑号如 **坞东-甲 / 坞东-乙 / 河沿-丙**）。

## 主界面：焖烧时间轴

登录后进入全宽 **焖烧时间轴**（不再使用侧栏 + 双 CRUD 列表）。顶栏可在 **焖烧时间轴** 与 **烟囱测氧簿** 两个入口间切换：

1. **顶部窑剪影行**：每座炭窑以 SVG 剪影展示，带「O₂ n」已测条数角标；点击某窑用 HTMX 局部刷新下方时间轴，并更新地址栏 `?clamp_id=`；「全部窑」取消筛选。
2. **纵向时间轴**：按开始时间倒序列出 `BurnShift`；每条卡片带窑号徽章（再点可开抽屉）、峰值温度、炭品与当前窑态。
3. **侧抽屉（非独立编辑页）**：「登记班次」写入新班次；点窑徽章打开操作抽屉，可标记「已出炭」。抽屉只显示测氧簿摘要并链接到专页，**不放建簿表单**。

## 烟囱测氧簿（专页 `/oxygen/`）

- 专页提供**按窑下拉的簿页**（炭窑、测次（从 1 起）、烟囱氧百分、采集时刻、当班人）与**新增测氧表**。
- 只有**焖烧中**的窑能写簿；已码窑、已出炭禁止建簿。
- 同窑测次不得重复（数据库唯一约束兜底并发）；氧百分必须为正且 ≤ 21。
- 种子数据中焖烧窑「坞东-甲」只备 **2 条**测氧，演示「簿不齐不能出炭」。

## 业务规则：峰值与氧百分并行门槛

炭窑状态不可设为「已出炭」（`drawn`），除非以下**两套门槛同时满足**（抽屉按钮与改窑态接口读同一函数 `can_mark_clamp_drawn`，无另写放行）：

1. **峰值门槛（照旧）**：该窑最近一条 `BurnShift` 的 `peakTempC` 已记录且 **≥ 400℃**；
2. **测氧门槛**：该窑测氧簿测次自 1 起**连续且不少于 4 条**，**最新氧百分 ≤ 8%**，且**最新采集时刻晚于该窑最近一班开始时刻**。

空簿、缺条、测次断号、最新氧偏高、采集时刻过早——任一不满足即拒绝。

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
