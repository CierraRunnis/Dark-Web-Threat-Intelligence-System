# Tor 稳定连接方案

本文件是 bishe 项目（暗网公开信息收集与威胁情报提取）在 Windows + WSL
混合环境下的 Tor 稳定性方案。目标是让 `.onion` 抓取在日常运行中不因为：

- 单一 SOCKS 端口失效
- 单一 pluggable transport 被干扰
- 桥节点过期或被封
- 上游机场 / 直连切换
- 进程重启后代理配置丢失

而中断 `darkweb_collector` 的采集流水线。

相关已有资产：

- `TOR_BRIDGE_STRATEGY.md`：多桥模式策略说明（snowflake / obfs4 / webtunnel / vanilla / meek）
- `tor-migration-package/`：可迁移到新机器的一整套 Tor 桥脚手架
- `tor-bridge-switch.new` / `wsl-sync-proxy-env`：WSL 侧的切换与代理环境同步脚本
- `torbrowser-socks-env.sh` / `torbrowser-socks-check.sh`：复用 Windows Tor Browser SOCKS 的 shell 辅助
- `darkweb_collector/src/darkweb_collector/tor_fetch.py`：按 `.onion` 主机名自动走 Tor SOCKS，否则走普通代理或直连
- `darkweb_collector/scripts/start_all_services_wsl.sh`：整栈启动脚本，依赖 `TOR_SOCKS_HOST` / `TOR_SOCKS_PORT`

本方案对这些资产做统一约束，不新增新的代理栈。

## 1. 四层冗余架构

抓取 `.onion` 的唯一入口是 SOCKS5。我们准备四层端点，按可靠性由高到低依次回退：

| 层级 | 端点 | 说明 | 典型故障域 |
| --- | --- | --- | --- |
| L1 | `127.0.0.1:9150`（Windows Tor Browser，WSL mirrored 网络直通） | 桌面 Tor Browser 自己维护桥和回路，最稳 | Tor Browser 未启动 / 未连上 |
| L2 | `127.0.0.1:9050`（WSL 系统 `tor@default.service`，桥模式见 §2） | 常驻无人值守，可脚本化 | torrc 桥失效、bootstrap 未完成 |
| L3 | `<gateway>:9150`（从 WSL 访问宿主机 Tor Browser 的显式网关 IP） | 当 mirrored 网络未启用、127.0.0.1 不通时的兜底 | 宿主机防火墙阻断 |
| L4 | `<gateway>:7890/7892/7897`（Clash/Mihomo HTTP/SOCKS，只做明网） | **不用于 `.onion`**，只是明网兜底，保证仓库其它明网抓取不死 | 机场/代理链离线 |

项目里已经隐含了这个优先级：`TOR_SOCKS_HOST=127.0.0.1`、`TOR_SOCKS_PORT=9150`
是 `torbrowser-socks-env.sh` 和 `run_onion_playwright_wsl.sh` 的默认值，
而 WSL 系统 `tor` 仅在 Tor Browser 不在线时顶上。

**口径统一规则**：

- `.onion` → SOCKS5 over L1 → 失败回 L2 → 再失败回 L3。永远不走 L4。
- 明网（`darkforums.su`、`chaos`、`nvd.nist.gov` 等）→ 按 `tor_fetch.py` 现有规则走 L4 或直连，不走任何 Tor 端点。
- `.onion` 主机名判定只看 `urlparse(url).hostname`，不看 `http://` / `https://`，与 `is_onion_hostname` 保持一致。

## 2. 系统 Tor（L2）的桥组合

系统 `tor` 是无人值守时的主力，必须能在 Tor Browser 不在线时自动 bootstrap 成功。
沿用 `tor-migration-package` 的切换框架，但固化以下规则：

1. `bridge-order.conf` 指定尝试顺序：

   ```
   webtunnel
   snowflake
   obfs4
   vanilla
   meek
   ```

   把 `webtunnel` 放第一位而不是 `snowflake`，原因是在本机测试里
   webtunnel 的首次 bootstrap 更快、丢包后恢复更快；snowflake 在 NAT
   环境容易卡在 75% `Connecting to a relay`。`tor-migration-package/etc/tor/bridge-order.conf`
   以及仓库根目录的 `bridge-order.conf.fixed` 都按此顺序。

2. 每种 transport 的桥源来自 `/etc/tor/bridges.<transport>`，由
   `tor-bridge-refresh` 调用 `bridge-fetch.<transport>` hook 刷新。
   hook 内部实际调用 `bridgedb-fetch`，它三路尝试：
   原生 Python `urllib` → Windows `PowerShell` → Windows `curl.exe`，
   适配 WSL 出站策略。

3. **桥池的最小数量约束**：任何时候，`bridges.obfs4` 与
   `bridges.webtunnel` 至少各保留 2 条真实可用的桥。空文件或全是占位
   的文件会让 `tor-bridge-switch <mode>` 直接 `has_lines` 校验失败并
   回退下一个 mode。

4. **占位桥标记**：`tor-migration-package/etc/tor/bridges.webtunnel`
   以及 `tor-migration-package/etc/tor/torrc` 里原本写过一条
   `[2001:db8:1b75:cd28:36c7:1347:3eda:a01e]:443`。`2001:db8::/32` 是
   RFC 3849 文档保留段，不会路由真实流量。本仓库已把这一条整行用 `#`
   注释掉，只保留成样例；`bridges.webtunnel.fixed` 直接剔除了这条。
   这样 `tor-bridge-switch` 的 `render_mode`（它用 `grep '^Bridge '`
   抽行）不会再把占位桥拷进 `/etc/tor/torrc`，避免 `auto` 在它上面
   白白消耗 120 秒 bootstrap 超时。真实部署机器务必在投入使用前
   从 [bridges.torproject.org](https://bridges.torproject.org/bridges?transport=webtunnel)
   或 Telegram `@GetBridgesBot` 取真实桥填入。

5. `tor-bridge-switch <mode>` 在写 torrc 之前会 `tor --verify-config`，
   `restart_service` 后最多等 `TOR_BRIDGE_WAIT_TIMEOUT` 秒等
   `Bootstrapped 100%`。这一步已经内置，禁止在业务代码里重复实现。

## 3. Tor Browser（L1）的使用规范

1. Windows 侧 Tor Browser 自己带 `obfs4` / `snowflake` / `meek-azure`
   内建桥，启动后监听 `127.0.0.1:9150`。它是项目里最稳的 `.onion`
   抓取来源，优先级最高。

2. WSL 2 在 `mirrored` 网络模式下可以直接用 `127.0.0.1:9150`。
   `windows/.wslconfig.sample` 已经给了推荐配置：

   ```
   [wsl2]
   networkingMode=mirrored
   dnsTunneling=true
   autoProxy=true
   ```

   这是 L1 能以 `127.0.0.1` 对 WSL 可达的前提。

3. 不要在 WSL 再起另一个 `tor` 去复用 Windows Tor Browser 的桥。两个
   tor 之间不共享 `DataDirectory`，唯一对接点是 SOCKS5。

4. 所有 shell 进入点都 `source torbrowser-socks-env.sh`，它导出：

   ```
   TOR_BROWSER_SOCKS_HOST=127.0.0.1
   TOR_BROWSER_SOCKS_PORT=9150
   ALL_PROXY=socks5://127.0.0.1:9150
   NO_PROXY=127.0.0.1,localhost,::1
   ```

   但要注意：`ALL_PROXY` 只影响 curl / requests 这类程序，
   **不要**把它透传给 `darkweb_collector` 的明网抓取，
   因为 `tor_fetch.py` 明网路径会读 `PROXY_HOST` / `PROXY_PORT` 或直连。
   `NO_PROXY` 里必须带 `127.0.0.1,localhost`，避免本地 Redis / API 被打爆。

## 4. 端点选择策略（代码侧）

`darkweb_collector/src/darkweb_collector/tor_fetch.py` 是唯一的抓取路由。
它对 `.onion` 主机名调用 `fetch_via_tor_curl`，SOCKS 配置来自
`TOR_SOCKS_HOST` / `TOR_SOCKS_PORT`（默认 `127.0.0.1:9150`）。

要落地 §1 的回退顺序，有两种做法：

- **A. 进程外选择**（推荐，已在本方案里使用）：
  由 `scripts/tor_healthcheck.sh` 在进程启动前选出可用端点，导出
  `TOR_SOCKS_HOST` / `TOR_SOCKS_PORT` 给整个栈（`start_all_services_wsl.sh`
  的 `build_env_exports` 会把这两个变量透传给 API、所有 worker、
  scheduler）。进程运行期间不再切换。

- B. 进程内选择：在 `tor_fetch.py` 里实现 L1 → L2 → L3 的自动降级。
  会让 `fetch_via_tor_curl` 的 retry 语义变复杂，暂不做。

本方案采用 A。脚本位置：`darkweb_collector/scripts/tor_healthcheck.sh`。

## 5. 健康检查与自动切换流程

任何长时间运行的入口都必须在启动前跑一次健康检查，检查失败就尝试修复：

```
tor_healthcheck.sh
  ├─ 探 L1  (127.0.0.1:9150)
  │    └─ curl --socks5-hostname ... https://check.torproject.org/api/ip
  ├─ 探 L2  (127.0.0.1:9050)
  │    ├─ 失败 → 如有 sudo 且有 /usr/local/bin/tor-bridge-switch,
  │    │        执行 `sudo tor-bridge-switch auto`
  │    └─ 再探一次
  ├─ 探 L3  (<default gw>:9150)
  └─ 输出选中的 TOR_SOCKS_HOST / TOR_SOCKS_PORT
```

健康判据是「SOCKS 端口可以完成一次 `check.torproject.org` 查询」，
不只是「端口 TCP 可连接」。仅 TCP 连通不能保证回路建立，
`tor-bridge-switch` 也是这个判据（`tor_api_ready`）。

结果写两处：

1. stdout 导出 shell 变量，供 `eval $(scripts/tor_healthcheck.sh --export)` 使用。
2. `/tmp/bishe-tor-endpoint.env`（或 `${XDG_RUNTIME_DIR}/bishe-tor-endpoint.env`）
   作为副本，便于 systemd / tmux 窗口间读取。

运行时机：

- `start_all_services_wsl.sh` 启动前
- `run_onion_crawler.sh` / `run_onion_playwright_wsl.sh` 启动前
- Celery worker 容器/窗口启动前（可通过 `build_env_exports` 把结果拼进去）

## 6. 配置规范

固定如下：

| 变量 | 推荐值 | 作用 |
| --- | --- | --- |
| `TOR_SOCKS_HOST` | `127.0.0.1` | `.onion` SOCKS5 主机（由 healthcheck 可覆盖） |
| `TOR_SOCKS_PORT` | `9150` | `.onion` SOCKS5 端口（由 healthcheck 可覆盖） |
| `PROXY_HOST` | `127.0.0.1` 或未设置 | 明网 HTTP/HTTPS 代理 |
| `PROXY_PORT` | `7890`/`7892`/`7897` 或未设置 | 明网 HTTP/HTTPS 代理端口 |
| `NO_PROXY` | `127.0.0.1,localhost,::1` | 防止本地 API/Redis 绕路 |
| `TOR_BRIDGE_WAIT_TIMEOUT` | `120` | 系统 tor bootstrap 等待上限（秒） |

强制：

- 所有抓取脚本都必须从上面变量读取，不要硬编码 `9050` 或 `9150`。
- `fetch_onion_playwright.py` 的默认端口必须是 `9150`，和
  `tor_fetch.py`、`torbrowser-socks-env.sh` 对齐，避免在 Tor Browser
  在线时被默认值引到未启动的系统 tor。
- 凡是把 `ALL_PROXY=socks5://...:9150` 导出到 shell 的入口，都必须同时
  导出 `NO_PROXY=127.0.0.1,localhost,::1`。`api_app` 的 `check.torproject.org` 健康
  检测和前端 dev server 代理会因此受影响。

## 7. 应急预案

按故障从轻到重列：

1. **L1 临时失效（Tor Browser 重启窗口）**：`tor_healthcheck.sh` 自动选 L2。
   若 L2 也在 `auto` 切桥，curl fetch 会在 `fetch_via_tor_curl` 的 `retries`
   里重试，单任务失败不阻断整轮（collector 的既有边界）。

2. **L1 / L2 同时不可用（上游大面积干扰）**：
   - 手工运行 `sudo tor-bridge-refresh`，再 `sudo tor-bridge-switch auto`。
   - `bridgedb-fetch` 如果因出站被污染而取不到桥，手工去
     [bridges.torproject.org](https://bridges.torproject.org/) 或
     Telegram `@GetBridgesBot` 领桥，写入
     `/etc/tor/bridges.obfs4` / `/etc/tor/bridges.webtunnel`，再 `tor-bridge-switch <mode>`。

3. **所有桥不可用**：
   - 切到「只跑明网源」模式：把 `.onion` 站点在 `darkweb_collector/sites.yaml`
     里临时 `enabled: false`，让 `darkforums`、`chaos`、公开漏洞源继续跑。
   - `tor-bridge-switch status` 的输出必须截图或粘进 issue，后续复盘。

4. **桥池被污染（obfs4 指纹被封）**：
   - 删除 `/etc/tor/bridges.obfs4`，留空让 `bridge-order.conf` 跳过 obfs4，
     直接让 webtunnel 和 snowflake 顶上。
   - 等 24 小时后再刷新 obfs4。

5. **WSL 网络模式变更（mirrored → NAT）**：
   - `sudo wsl-sync-proxy-env` 会根据 `ip route` 重新探 gateway 并写
     `/etc/tor/proxy.env`，`tor@default.service` 的 drop-in 会重新加载环境。
   - `tor_healthcheck.sh` 的 L3 分支会在 `127.0.0.1:9150` 不通时改用
     gateway IP:9150，保持 Tor Browser 路径可用。

## 8. 变更清单与落地

本次 PR 一起落地：

1. 新增 `TOR_CONNECTION_PLAN.md`（本文件）。
2. 新增 `darkweb_collector/scripts/tor_healthcheck.sh`，实现 §5 的探活与
   `--export` 输出。
3. `darkweb_collector/scripts/fetch_onion_playwright.py` 默认端口
   `9050 → 9150`，与 `tor_fetch.py` 口径一致。
4. `bridges.webtunnel.fixed` 与 `tor-migration-package/etc/tor/bridges.webtunnel`
   中 `2001:db8::` 的占位桥整行注释掉（`# Bridge ...`），确保
   `tor-bridge-switch` 的 `grep '^Bridge '` 不会再把它拷进 torrc。
5. `run_onion_crawler.sh` / `run_onion_playwright_wsl.sh` 改为启动前
   跑 `tor_healthcheck.sh`，自动选端点。
6. `start_all_services_wsl.sh` 在 `ensure_environment` 里新增
   `run_tor_healthcheck`，结果通过 `build_env_exports` 透传给整个 tmux 栈。

后续还需要人工补的：

- 替换 `bridges.webtunnel` 的真实桥（最少 2 条）。
- 替换 `bridges.obfs4` 的真实桥（最少 2 条），当前仓库里的两条是
  示例桥，长期来看不保证可用。
- 在部署机器上执行 `sudo bash tor-migration-package/install/install_wsl_tor_bundle.sh`
  一次，把 `/usr/local/bin/*`、`/etc/tor/*`、`/etc/systemd/system/tor@default.service.d/proxy.conf`
  都装到位。

## 9. 验收标准

部署完成后，下面这些命令必须全部成功：

```bash
# L1
curl --socks5-hostname 127.0.0.1:9150 https://check.torproject.org/api/ip

# L2
curl --socks5-hostname 127.0.0.1:9050 https://check.torproject.org/api/ip

# healthcheck
eval "$(bash darkweb_collector/scripts/tor_healthcheck.sh --export)"
echo "$TOR_SOCKS_HOST:$TOR_SOCKS_PORT"

# 端到端：采集一次 dragonforce（.onion）
python darkweb_collector/scripts/crawl.py run-site --site dragonforce --once
```

长期观察指标（跑一个周末）：

- `crawl_jobs` 里 `.onion` 任务的失败率 < 10%
- `Bootstrapped 100%` 在 `/var/log/tor/notices.log` 出现后，到第一条
  成功抓取之间 < 60 秒
- 没有出现「`fetch_via_tor_curl` 返回 `curl: (7) Failed to connect to 127.0.0.1 port 9150`」
  之类的连接拒绝错误（这说明端点选择失效）
